from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from time import perf_counter
from uuid import uuid4

from .infrastructure import workflow_infra
from .intent import classify_intent
from .rag import search_with_diagnostics
from .security import evaluate_tool, inspect_input, security_snapshot
from .store import now, store


AUTO_REFUND_LIMIT = 300.0
HIGH_RISK_THRESHOLD = 70
MIN_EVIDENCE_CONFIDENCE = 0.75


def _evidence_consistency(case: dict) -> dict:
    """本地证据适配器：把申请声明、订单商品和附件 OCR 文本放进同一判定。"""
    files = case.get("evidence_files") or []
    order = next((item for item in store.orders if item["id"] == case.get("order_id")), None)
    item_names = [item.get("name", "") for item in (order or {}).get("items", [])]
    reason = str(case.get("reason", ""))
    declared = " ".join([reason, str(case.get("service_type", "")), " ".join(item_names), str(case.get("evidence_description") or "")]).lower()
    issue_terms = ("退货", "退款", "换货", "质量", "破损", "损坏", "少件", "漏发", "无声", "断连", "物流", "包装")
    expected_terms = [term for term in issue_terms if term in declared]
    product_terms = [name for name in item_names if len(name) >= 2]

    if not files:
        return {"status": "missing", "matched": False, "confidence": 0.0, "reason": "未上传附件，无法核验申请内容与证据的一致性", "checked_files": 0, "matched_files": 0}

    results = []
    for artifact in files:
        ocr_text = str(artifact.get("ocr_text") or "").strip().lower()
        if not ocr_text:
            results.append({"artifact_id": artifact.get("id"), "status": "unverified", "reason": "附件尚未获得 OCR 文本，不能仅凭文件名认定内容一致"})
            continue
        issue_hits = [term for term in expected_terms if term in ocr_text]
        product_hits = [term for term in product_terms if term.lower() in ocr_text]
        order_hit = str(case.get("order_id", "")).lower() in ocr_text
        specific_issue_hits = [term for term in issue_hits if term != "包装"]
        matched = bool(product_hits or specific_issue_hits) and (not product_terms or bool(product_hits or order_hit))
        results.append({
            "artifact_id": artifact.get("id"),
            "status": "matched" if matched else "mismatch",
            "reason": "附件文本与申请原因/订单商品存在可解释匹配" if matched else "附件文本未能匹配申请原因或订单商品",
            "issue_hits": issue_hits,
            "specific_issue_hits": specific_issue_hits,
            "product_hits": product_hits,
            "order_id_matched": order_hit,
        })

    matched_files = [item for item in results if item["status"] == "matched"]
    mismatch_files = [item for item in results if item["status"] == "mismatch"]
    if mismatch_files:
        status, reason = "mismatch", "附件内容与退货申请或订单商品不一致，需要人工核验"
    elif matched_files:
        status, reason = "matched", "附件内容与退货申请及订单上下文一致"
    else:
        status, reason = "unverified", "附件已上传但尚未完成 OCR，暂不能确认一致性"
    return {
        "status": status,
        "matched": status == "matched",
        "confidence": round(len(matched_files) / max(1, len(results)), 2),
        "reason": reason,
        "checked_files": len(results),
        "matched_files": len(matched_files),
        "details": results,
    }


def classify(text: str) -> tuple[str, float]:
    """兼容旧接口，实际由统一双层意图路由器完成。"""
    result = classify_intent(text)
    return result.intent, result.confidence


def _evidence_agent(case: dict) -> dict:
    confidence = float(case.get("evidence_confidence", 0.95))
    reason = case.get("reason", "")
    evidence_type = "image_ocr" if any(word in reason for word in ("图片", "照片", "凭证", "截图")) else "buyer_statement"
    consistency = _evidence_consistency(case)
    return {
        "agent": "EvidenceOCRAgent",
        "confidence": confidence,
        "evidence_type": evidence_type,
        "quality": "sufficient" if confidence >= MIN_EVIDENCE_CONFIDENCE else "insufficient",
        "production_adapter": "OCRProvider" if evidence_type == "image_ocr" else None,
        "consistency": consistency,
    }


def _fraud_agent(case: dict) -> dict:
    reason = case.get("reason", "")
    signals: list[str] = []
    risk = 12
    keywords = {"多次": 24, "薅羊毛": 55, "异常": 28, "伪造": 60, "代下单": 25, "空包": 45}
    for word, score in keywords.items():
        if word in reason:
            signals.append(word)
            risk += score
    previous = sum(item.get("buyer_id") == case.get("buyer_id") for item in store.after_sales.values())
    if previous >= 4:
        signals.append("frequent_claims")
        risk += 18
    amount = float(case.get("amount", 0))
    if amount >= 1000:
        signals.append("high_amount")
        risk += 15
    return {"agent": "FraudAgent", "risk_score": min(risk, 100), "signals": signals, "previous_claims": previous}


def _sentiment_agent(case: dict) -> dict:
    reason = case.get("reason", "")
    negative = sum(word in reason for word in ("生气", "欺骗", "投诉", "差评", "曝光", "垃圾", "失望"))
    urgent = sum(word in reason for word in ("马上", "立刻", "媒体", "监管", "报警"))
    score = min(100, 20 + negative * 18 + urgent * 15)
    level = "crisis" if score >= 75 else "negative" if score >= 45 else "normal"
    return {"agent": "SentimentAgent", "score": score, "level": level, "needs_priority": level == "crisis"}


def _execute_refund(case: dict, *, role: str, approved: bool) -> dict:
    tool = evaluate_tool("execute_refund", role, float(case["amount"]), approved=approved)
    if not tool.allowed:
        return {"executed": False, "tool_policy": asdict(tool), "reason": tool.reason}
    existing = store.refunds.get(case["id"])
    if existing:
        return {**existing, "idempotent": True, "tool_policy": asdict(tool)}
    refund = {
        "id": "rf-" + uuid4().hex[:12],
        "case_id": case["id"],
        "order_id": case["order_id"],
        "amount": round(float(case["amount"]), 2),
        "status": "succeeded",
        "executed": True,
        "created_at": now(),
        "provider": "local_refund_adapter",
        "tool_policy": asdict(tool),
    }
    store.refunds[case["id"]] = refund
    order = next((item for item in store.orders if item["id"] == case["order_id"]), None)
    if order:
        order["refund_amount"] = round(float(order.get("refund_amount", 0)) + refund["amount"], 2)
        order["status"] = "退款完成" if order["refund_amount"] >= float(order["total"]) else "部分退款完成"
    return refund


def run_after_sales(case: dict) -> dict:
    """工单 1 主链：安全→意图→并行分析→RAG→确定性策略→退款/人工。

    运行态只使用 RUNNING、SUSPENDED_HUMAN、COMPLETED，审批结果放在 outcome，
    消除过去 APPROVED 既表示流程状态又表示业务结果的重复含义。
    """
    trace_id = str(uuid4())
    events: list[dict] = []
    history = [{"state": "RUNNING", "at": now(), "reason": "case_created"}]
    workflow_infra.checkpoint(case["id"], {"status": "RUNNING", "trace_id": trace_id, "state_history": history})

    def node(name: str, status: str, output: dict, started: float) -> None:
        event = {
            "trace_id": trace_id,
            "case_id": case["id"],
            "node": name,
            "status": status,
            "duration_ms": round((perf_counter() - started) * 1000, 2),
            "output": output,
        }
        events.append(event)
        store.add_event(event)

    started = perf_counter()
    security = inspect_input(case.get("reason", ""))
    node("CriticDLP", "blocked" if security.blocked else "completed", security_snapshot(security), started)
    if security.blocked:
        assignee = store.least_active_agent()
        history.append({"state": "SUSPENDED_HUMAN", "at": now(), "reason": "security_gate"})
        result = {
            "status": "SUSPENDED_HUMAN",
            "outcome": "PENDING",
            "decision": "SECURITY_REVIEW_REQUIRED",
            "decision_reason": "安全网关检测到提示词注入或越权指令，退款工具未被调用",
            "assigned_to": assignee,
            "security": security_snapshot(security),
        }
        node("SecurityGate", "blocked", result, perf_counter())
        payload = {**result, "trace_id": trace_id, "events": events, "state_history": history, "updated_at": now()}
        workflow_infra.checkpoint(case["id"], payload)
        workflow_infra.publish({"type": "after_sales.suspended", "case_id": case["id"], "trace_id": trace_id, "reason": result["decision"]})
        return payload

    started = perf_counter()
    intent = classify_intent(security.text, trace_id=trace_id, record=False)
    node("IntentRouter", "fallback" if intent.method == "fallback" else "completed", asdict(intent), started)

    # 三个不相互依赖的 Agent 并行运行，结果在决策节点统一汇合。
    parallel_started = perf_counter()
    with ThreadPoolExecutor(max_workers=3, thread_name_prefix="case-agent") as pool:
        evidence_future = pool.submit(_evidence_agent, case)
        fraud_future = pool.submit(_fraud_agent, case)
        sentiment_future = pool.submit(_sentiment_agent, case)
        evidence = evidence_future.result()
        fraud = fraud_future.result()
        sentiment = sentiment_future.result()
    node("ParallelAnalysis", "completed", {"evidence": evidence, "fraud": fraud, "sentiment": sentiment}, parallel_started)
    consistency = evidence["consistency"]
    node("EvidenceConsistency", "completed" if consistency["status"] == "matched" else "blocked", consistency, perf_counter())

    retrieval_started = perf_counter()
    retrieval = search_with_diagnostics(security.text + " 售后政策 退货退款", role="agent")
    node("PolicyRAG", "completed" if retrieval["grounded"] else "fallback", {"grounded": retrieval["grounded"], "references": [item["source"] for item in retrieval["items"]], "latency_ms": retrieval["latency_ms"]}, retrieval_started)

    amount = round(float(case.get("amount", 0)), 2)
    risk_score = fraud["risk_score"]
    confidence = evidence["confidence"]
    policy_started = perf_counter()
    if consistency["status"] == "mismatch":
        status, outcome, decision, reason = "SUSPENDED_HUMAN", "PENDING", "EVIDENCE_MISMATCH_REVIEW", consistency["reason"]
    elif case.get("evidence_required") and consistency["status"] != "matched":
        status, outcome, decision, reason = "SUSPENDED_HUMAN", "PENDING", "EVIDENCE_VERIFICATION_REQUIRED", consistency["reason"]
    elif confidence < MIN_EVIDENCE_CONFIDENCE:
        status, outcome, decision, reason = "SUSPENDED_HUMAN", "PENDING", "REQUEST_MORE_EVIDENCE", "凭证识别置信度低于 0.75，需要补充或人工核验"
    elif risk_score >= HIGH_RISK_THRESHOLD:
        status, outcome, decision, reason = "SUSPENDED_HUMAN", "PENDING", "FRAUD_REVIEW_REQUIRED", "风险评分达到人工复核阈值"
    elif case.get("service_type") in {"退货退款", "换货"}:
        status, outcome, decision, reason = "SUSPENDED_HUMAN", "PENDING", "RETURN_SHIPMENT_REQUIRED", "退货或换货已通过规则预审，等待买家寄回并由仓库验收"
    elif amount > AUTO_REFUND_LIMIT:
        status, outcome, decision, reason = "SUSPENDED_HUMAN", "PENDING", "AMOUNT_REVIEW_REQUIRED", "申请金额超过 300 元自动审批额度"
    elif not retrieval["grounded"]:
        status, outcome, decision, reason = "SUSPENDED_HUMAN", "PENDING", "POLICY_REVIEW_REQUIRED", "知识库未检索到足够可靠的有效政策"
    else:
        status, outcome, decision, reason = "COMPLETED", "APPROVED", "AUTO_REFUND", "低金额、低风险、凭证充分且政策依据有效"
    node("PolicyDecision", "completed", {"status": status, "outcome": outcome, "decision": decision, "amount": amount, "risk_score": risk_score}, policy_started)

    assignee = None
    refund = None
    if status == "COMPLETED":
        refund_started = perf_counter()
        refund = _execute_refund({**case, "amount": amount}, role="workflow", approved=True)
        if not refund.get("executed"):
            status, outcome, decision, reason = "SUSPENDED_HUMAN", "PENDING", "TOOL_POLICY_REVIEW", refund["reason"]
        node("RefundTool", "completed" if refund.get("executed") else "blocked", refund, refund_started)
    if status == "SUSPENDED_HUMAN":
        assignee = store.least_active_agent()
    history.append({"state": status, "at": now(), "reason": decision})
    payload = {
        "status": status,
        "outcome": outcome,
        "decision": decision,
        "decision_reason": reason,
        "amount": amount,
        "risk_score": risk_score,
        "evidence": evidence,
        "evidence_consistency": consistency,
        "sentiment": sentiment,
        "intent": asdict(intent),
        "references": [item["source"] for item in retrieval["items"]],
        "rag_grounded": retrieval["grounded"],
        "assigned_to": assignee,
        "refund": refund,
        "trace_id": trace_id,
        "events": events,
        "state_history": history,
        "updated_at": now(),
    }
    workflow_infra.checkpoint(case["id"], payload)
    workflow_infra.publish({"type": "after_sales.completed" if status == "COMPLETED" else "after_sales.suspended", "case_id": case["id"], "trace_id": trace_id, "decision": decision})
    return payload


def review_after_sales(case_id: str, *, action: str, comment: str, role: str, idempotency_key: str) -> dict:
    """原子恢复挂起流程；同一个幂等键不会重复执行退款。"""
    with store.lock:
        case = store.after_sales.get(case_id)
        if not case:
            raise KeyError(case_id)
        remembered = store.recall_idempotency(f"case-review:{case_id}", idempotency_key)
        if remembered:
            return {"idempotent": True, **remembered}
        if case.get("status") != "SUSPENDED_HUMAN":
            raise RuntimeError("invalid_state")
        if role.lower() not in {"supervisor", "admin", "manager"}:
            raise PermissionError("insufficient_role")
        approved = action == "approve"
        refund = None
        if approved:
            if case.get("service_type") in {"退货退款", "换货"}:
                shipment = store.return_shipments.get(case_id)
                if not shipment or shipment.get("status") != "仓库已验收":
                    raise RuntimeError("return_not_received")
            refund = _execute_refund(case, role="admin" if role.lower() == "manager" else role.lower(), approved=True)
            if not refund.get("executed"):
                raise PermissionError(refund["reason"])
        case.update({
            "status": "COMPLETED",
            "outcome": "APPROVED" if approved else "REJECTED",
            "decision": "MANUAL_APPROVE" if approved else "MANUAL_REJECT",
            "review_comment": comment,
            "reviewed_by_role": role.upper(),
            "reviewed_at": now(),
            "refund": refund,
        })
        case.setdefault("state_history", []).append({"state": "COMPLETED", "at": now(), "reason": case["decision"]})
        store.add_event({"case_id": case_id, "node": "HumanReview", "status": "completed", "action": action, "role": role, "trace_id": case.get("trace_id")})
        workflow_infra.checkpoint(case_id, case)
        workflow_infra.publish({"type": "after_sales.resumed", "case_id": case_id, "trace_id": case.get("trace_id"), "outcome": case["outcome"]})
        store.remember_idempotency(f"case-review:{case_id}", idempotency_key, dict(case))
        return case
