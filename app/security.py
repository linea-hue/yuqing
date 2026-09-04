from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from hashlib import sha256
from typing import Any


INJECTION_PATTERNS: tuple[tuple[str, str], ...] = (
    ("instruction_override", r"忽略(?:之前|上面|所有|系统).{0,20}(?:指令|规则|限制)"),
    ("approval_bypass", r"(?:跳过|绕过|不要).{0,16}(?:审批|风控|权限|审核)"),
    ("tool_coercion", r"(?:调用|执行|使用).{0,24}(?:退款|删除|改价|转账).{0,12}(?:api|工具|函数)"),
    ("prompt_exfiltration", r"(?:system\s*prompt|developer\s*message|系统提示词|开发者消息|泄露提示词)"),
    ("jailbreak", r"(?:jailbreak|越狱模式|dan\s+mode|无视安全策略)"),
    ("role_impersonation", r"(?:你现在是|假装你是).{0,16}(?:管理员|系统|开发者|超级用户)"),
)

DLP_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("mobile", re.compile(r"(?<!\d)(1[3-9]\d)\d{4}(\d{4})(?!\d)"), r"\1****\2"),
    ("national_id", re.compile(r"(?<!\d)(\d{6})\d{8}(\d{3}[0-9Xx])(?!\d)"), r"\g<1>********\g<2>"),
    ("email", re.compile(r"(?i)([a-z0-9._%+-]{1,3})[a-z0-9._%+-]*(@[a-z0-9.-]+\.[a-z]{2,})"), r"\1***\2"),
    ("api_key", re.compile(r"(?i)(sk-[a-z0-9_-]{12,}|AKIA[A-Z0-9]{12,}|bearer\s+[a-z0-9._-]{16,})"), "[API_KEY_MASKED]"),
    ("bank_card", re.compile(r"(?<!\d)(\d{4})\d{8,11}(\d{4})(?!\d)"), r"\1********\2"),
)


@dataclass(frozen=True)
class SecurityResult:
    text: str
    blocked: bool
    reasons: list[str]
    risk_level: str = "low"
    dlp_types: list[str] = field(default_factory=list)
    content_fingerprint: str = ""


@dataclass(frozen=True)
class ToolDecision:
    allowed: bool
    reason: str
    requires_approval: bool
    policy_id: str


def mask_pii(text: str) -> str:
    masked = text
    for _, pattern, replacement in DLP_PATTERNS:
        masked = pattern.sub(replacement, masked)
    return masked


def inspect_input(text: str) -> SecurityResult:
    reasons = [rule_id for rule_id, pattern in INJECTION_PATTERNS if re.search(pattern, text, re.I)]
    masked = text
    dlp_types: list[str] = []
    for kind, pattern, replacement in DLP_PATTERNS:
        if pattern.search(masked):
            dlp_types.append(kind)
            masked = pattern.sub(replacement, masked)
    if dlp_types:
        reasons.append("pii_detected")
    blocked = any(reason != "pii_detected" for reason in reasons)
    risk_level = "critical" if blocked else "medium" if dlp_types else "low"
    fingerprint = sha256(text.encode("utf-8")).hexdigest()[:16]
    return SecurityResult(masked, blocked, reasons, risk_level, dlp_types, fingerprint)


def inspect_output(payload: Any) -> SecurityResult:
    """输出 DLP：所有返回给前端的自然语言都可经过同一脱敏器。"""
    return inspect_input(str(payload))


def evaluate_tool(tool: str, role: str, amount: float = 0, *, approved: bool = False) -> ToolDecision:
    normalized_role = role.lower()
    if tool in {"get_order", "get_logistics", "search_knowledge", "create_ticket"}:
        return ToolDecision(True, "read_or_low_risk_action", False, "tool-policy-v2")
    if tool == "execute_refund":
        if amount <= 300 and approved and normalized_role in {"workflow", "supervisor", "admin"}:
            return ToolDecision(True, "approved_low_amount_refund", True, "tool-policy-v2")
        if amount <= 3000 and approved and normalized_role in {"supervisor", "admin"}:
            return ToolDecision(True, "human_approved_refund", True, "tool-policy-v2")
        return ToolDecision(False, "refund_requires_approved_workflow_and_authorized_role", True, "tool-policy-v2")
    if tool in {"update_catalog", "adjust_stock"}:
        allowed = normalized_role in {"manager", "admin"}
        return ToolDecision(allowed, "authorized" if allowed else "insufficient_role", not allowed, "tool-policy-v2")
    return ToolDecision(False, "tool_not_allowlisted", True, "tool-policy-v2")


def allow_tool(tool: str, role: str, amount: float = 0) -> bool:
    """兼容旧调用；退款仍需通过正式工作流传入 approved=True。"""
    mapped = "execute_refund" if tool == "approve_refund" else tool
    return evaluate_tool(mapped, role, amount, approved=False).allowed


def security_snapshot(result: SecurityResult) -> dict:
    return asdict(result)
