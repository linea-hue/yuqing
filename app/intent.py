from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from time import perf_counter
from typing import Callable
from uuid import uuid4

from .store import now, store


INTENT_RULES: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("售后退款", ("退款", "退货", "换货", "破损", "质量", "少件", "漏发"), "after_sales"),
    ("物流查询", ("物流", "快递", "发货", "签收", "到哪", "催件"), "logistics"),
    ("订单操作", ("下单", "支付", "取消订单", "确认收货", "订单状态"), "order"),
    ("商品咨询", ("规格", "尺寸", "材质", "参数", "库存", "怎么用", "适配"), "product"),
    ("优惠咨询", ("优惠券", "满减", "活动", "折扣", "积分"), "promotion"),
    ("投诉升级", ("投诉", "生气", "差评", "欺骗", "曝光", "媒体"), "complaint"),
    ("人工咨询", ("人工", "客服", "转人工"), "human"),
)


@dataclass(frozen=True)
class IntentResult:
    intent: str
    confidence: float
    route: str
    method: str
    latency_ms: float
    fallback_reason: str | None = None
    trace_id: str | None = None


class IntentCircuitBreaker:
    """轻量本地熔断器；生产部署可由 Redis 共享窗口替换。"""

    def __init__(self, threshold: int = 3) -> None:
        self.threshold = threshold
        self.failures = 0
        self.open = False

    def success(self) -> None:
        self.failures = 0
        self.open = False

    def failure(self) -> None:
        self.failures += 1
        self.open = self.failures >= self.threshold


breaker = IntentCircuitBreaker()


def _rule_match(text: str) -> tuple[str, float, str] | None:
    normalized = text.lower().strip()
    candidates: list[tuple[int, str, str]] = []
    for intent, words, route in INTENT_RULES:
        hits = sum(word in normalized for word in words)
        if hits:
            candidates.append((hits, intent, route))
    if not candidates:
        return None
    hits, intent, route = max(candidates, key=lambda item: item[0])
    return intent, min(0.98, 0.88 + hits * 0.03), route


def _parse_model_result(raw: str) -> tuple[str, float, str]:
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("intent response must be an object")
    intent = str(data["intent"])
    confidence = float(data["confidence"])
    route = str(data["route"])
    allowed_intents = {item[0] for item in INTENT_RULES}
    allowed_routes = {item[2] for item in INTENT_RULES}
    if intent not in allowed_intents or route not in allowed_routes or not 0 <= confidence <= 1:
        raise ValueError("intent response is outside schema")
    return intent, confidence, route


def classify_intent(
    text: str,
    *,
    trace_id: str | None = None,
    model_call: Callable[[str], str] | None = None,
    record: bool = True,
) -> IntentResult:
    """规则优先、模型补充、异常兜底的两级意图路由。

    默认零配置环境不伪装调用大模型：规则未命中时直接进入 Fallback。
    注入 model_call 后会校验严格 JSON，解析失败写入死信队列。
    """
    started = perf_counter()
    trace_id = trace_id or str(uuid4())
    match = _rule_match(text)
    if match:
        intent, confidence, route = match
        result = IntentResult(intent, confidence, route, "rule", round((perf_counter() - started) * 1000, 2), trace_id=trace_id)
    elif model_call is not None and not breaker.open:
        try:
            intent, confidence, route = _parse_model_result(model_call(text))
            breaker.success()
            result = IntentResult(intent, confidence, route, "model", round((perf_counter() - started) * 1000, 2), trace_id=trace_id)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError, TimeoutError) as exc:
            breaker.failure()
            dead = {"id": "dlq-" + uuid4().hex[:10], "trace_id": trace_id, "stage": "intent_model", "input": text[:500], "error": type(exc).__name__, "created_at": now(), "retry_count": breaker.failures}
            store.dead_letters.append(dead)
            result = IntentResult("人工咨询", 0.35, "human", "fallback", round((perf_counter() - started) * 1000, 2), f"model_{type(exc).__name__.lower()}", trace_id)
    else:
        reason = "circuit_open" if breaker.open else "no_rule_match"
        result = IntentResult("人工咨询", 0.35, "human", "fallback", round((perf_counter() - started) * 1000, 2), reason, trace_id)

    audit_record = {"time": now(), "input": text[:300], **asdict(result)}
    store.intent_records.append(audit_record)
    if record:
        store.add_event({"node": "IntentRouter", "status": "fallback" if result.method == "fallback" else "completed", **audit_record})
    return result


def intent_metrics() -> dict:
    rows = store.intent_records
    totals: dict[str, dict] = {}
    for row in rows:
        item = totals.setdefault(row["intent"], {"intent": row["intent"], "count": 0, "fallback": 0, "avg_confidence": 0.0})
        item["count"] += 1
        item["fallback"] += int(row["method"] == "fallback")
        item["avg_confidence"] += row["confidence"]
    items = []
    for item in totals.values():
        count = item["count"]
        items.append({"intent": item["intent"], "count": count, "fallback_rate": round(item["fallback"] / count, 4), "avg_confidence": round(item["avg_confidence"] / count, 4)})
    return {"items": sorted(items, key=lambda item: item["count"], reverse=True), "total": len(rows), "fallback_total": sum(row["method"] == "fallback" for row in rows), "circuit_open": breaker.open}
