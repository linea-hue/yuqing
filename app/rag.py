from __future__ import annotations

import math
import re
from collections import Counter
from datetime import datetime, timezone
from time import perf_counter

from .store import now, store


QUERY_EXPANSIONS = {
    "能退吗": "退货 退款 售后政策",
    "怎么退": "退货退款 流程 售后",
    "还没到": "物流 停滞 配送 时效",
    "快递": "物流 运单 发货",
    "坏了": "破损 质量问题 凭证",
    "不想要": "无理由退货",
    "优惠": "优惠券 满减 活动规则",
    "怎么用": "商品 使用说明 参数",
}


def _tokens(text: str) -> list[str]:
    """英文按词、中文按单字和双字切分，避免中文整句只有零散单字命中。"""
    latin = [value.lower() for value in re.findall(r"[a-zA-Z0-9]+", text)]
    chinese_runs = re.findall(r"[\u4e00-\u9fff]+", text)
    chinese: list[str] = []
    for run in chinese_runs:
        chinese.extend(run)
        chinese.extend(run[index:index + 2] for index in range(len(run) - 1))
    return latin + chinese


def rewrite_query(query: str) -> str:
    rewritten = re.sub(r"\s+", " ", query.strip())
    for source, target in QUERY_EXPANSIONS.items():
        if source in rewritten:
            rewritten += " " + target
    return rewritten


def _is_effective(doc: dict) -> bool:
    effective = doc.get("effective_at")
    expires = doc.get("expires_at")
    current = datetime.now(timezone.utc)
    try:
        if effective and datetime.fromisoformat(effective.replace("Z", "+00:00")) > current:
            return False
        if expires and datetime.fromisoformat(expires.replace("Z", "+00:00")) <= current:
            return False
    except ValueError:
        return False
    return True


def _score(query_counter: Counter, query_norm: float, doc: dict) -> tuple[float, dict]:
    title_tokens = _tokens(doc.get("title", ""))
    body_tokens = _tokens(doc.get("text", ""))
    keyword_tokens = _tokens(" ".join(doc.get("keywords", [])))
    body = Counter(body_tokens)
    title = Counter(title_tokens)
    keywords = Counter(keyword_tokens)
    lexical = sum(min(query_counter[token], body[token]) for token in query_counter) / query_norm
    title_score = sum(min(query_counter[token], title[token]) for token in query_counter) / query_norm
    keyword_score = sum(min(query_counter[token], keywords[token]) for token in query_counter) / query_norm
    exact_bonus = 0.18 if any(keyword and keyword in doc.get("text", "") for keyword in doc.get("keywords", [])) else 0
    raw = lexical * 0.56 + title_score * 0.26 + keyword_score * 0.18 + exact_bonus
    return min(1.0, raw), {"lexical": round(lexical, 4), "title": round(title_score, 4), "keyword": round(keyword_score, 4), "exact_bonus": exact_bonus}


def search_with_diagnostics(query: str, top_k: int = 4, shop_id: str = "all", role: str = "buyer") -> dict:
    started = perf_counter()
    original = query.strip()
    rewritten = rewrite_query(original)
    query_counter = Counter(_tokens(rewritten))
    query_norm = max(1.0, math.sqrt(sum(value * value for value in query_counter.values())))
    candidates = []
    filtered = {"draft": 0, "tenant": 0, "acl": 0, "expired": 0}
    for doc in store.knowledge:
        if doc.get("status", "published") != "published":
            filtered["draft"] += 1
            continue
        if doc.get("shop_id", "all") not in {"all", shop_id}:
            filtered["tenant"] += 1
            continue
        if role not in set(doc.get("acl", ["buyer", "agent", "manager", "admin"])):
            filtered["acl"] += 1
            continue
        if not _is_effective(doc):
            filtered["expired"] += 1
            continue
        score, channels = _score(query_counter, query_norm, doc)
        if score > 0:
            candidates.append({
                "score": round(score, 4),
                "source": {key: doc.get(key) for key in ("id", "title", "type", "version", "status")},
                "text": doc.get("text", ""),
                "metadata": {"shop_id": doc.get("shop_id", "all"), "effective_at": doc.get("effective_at"), "keywords": doc.get("keywords", []), "score_channels": channels},
            })
    candidates.sort(key=lambda item: item["score"], reverse=True)

    # 简单多样性约束：同一知识类型最多返回 2 条，减少重复政策占满上下文。
    results: list[dict] = []
    type_counts: Counter = Counter()
    for item in candidates:
        doc_type = item["source"].get("type") or "unknown"
        if type_counts[doc_type] >= 2:
            continue
        results.append(item)
        type_counts[doc_type] += 1
        if len(results) >= max(1, min(top_k, 10)):
            break

    latency_ms = round((perf_counter() - started) * 1000, 2)
    threshold = 0.08
    grounded = bool(results and results[0]["score"] >= threshold)
    if not grounded:
        gap = {"query": original, "rewritten_query": rewritten, "created_at": now(), "status": "open", "top_score": results[0]["score"] if results else 0}
        if not any(item["query"] == original and item["status"] == "open" for item in store.rag_gaps):
            store.rag_gaps.append(gap)
    store.add_event({"node": "RAG", "status": "grounded" if grounded else "fallback", "query": original[:200], "latency_ms": latency_ms, "result_count": len(results), "top_score": results[0]["score"] if results else 0})
    return {
        "query": original,
        "rewritten_query": rewritten,
        "items": results,
        "latency_ms": latency_ms,
        "citation_required": True,
        "evidence_threshold": threshold,
        "grounded": grounded,
        "filtered": filtered,
        "retrieval_mode": "hybrid_lexical_keyword_rerank",
    }


def grounded_answer(query: str, *, shop_id: str = "all", role: str = "buyer", top_k: int = 4) -> dict:
    retrieval = search_with_diagnostics(query, top_k, shop_id, role)
    if not retrieval["grounded"]:
        return {"answer": "当前知识库没有足够可靠的依据，已转交人工客服核实。", "references": [], "grounded": False, "retrieval": retrieval}
    best = retrieval["items"][0]
    source = best["source"]
    answer = f"根据《{source.get('title')}》：{best['text']}"
    return {"answer": answer, "references": [item["source"] for item in retrieval["items"]], "grounded": True, "retrieval": retrieval}


def search(query: str, top_k: int = 4, shop_id: str = "all", role: str = "buyer") -> list[dict]:
    return search_with_diagnostics(query, top_k, shop_id, role)["items"]
