from __future__ import annotations

from statistics import mean
from time import perf_counter
from uuid import uuid4

from .intent import classify_intent
from .rag import grounded_answer
from .security import inspect_input, security_snapshot
from .store import now, store


def create_session(channel: str = "websocket") -> dict:
    session_id = "voice-" + uuid4().hex[:12]
    session = {
        "session_id": session_id,
        "channel": channel,
        "state": "LISTENING",
        "turns": [],
        "interrupt_count": 0,
        "created_at": now(),
        "last_active_at": now(),
        "adapters": {"vad": "browser", "asr": "browser_or_external", "tts": "browser_speech_synthesis"},
    }
    store.voice_sessions[session_id] = session
    return session


def interrupt_session(session_id: str) -> dict:
    session = store.voice_sessions.get(session_id)
    if not session:
        raise KeyError(session_id)
    started = perf_counter()
    previous = session["state"]
    session["state"] = "LISTENING"
    session["tts_queue"] = []
    session["interrupt_count"] += 1
    session["last_active_at"] = now()
    latency = round((perf_counter() - started) * 1000, 2)
    store.add_event({"node": "VoiceBargeIn", "status": "completed", "session_id": session_id, "duration_ms": latency, "previous_state": previous})
    return {"session_id": session_id, "interrupted": previous in {"THINKING", "SPEAKING"}, "state": session["state"], "tts_queue_cleared": True, "latency_ms": latency}


def process_turn(transcript: str, *, session_id: str | None = None, duration_ms: int = 0) -> dict:
    session = store.voice_sessions.get(session_id or "") or create_session("http_turn")
    session_id = session["session_id"]
    trace_id = str(uuid4())
    total_started = perf_counter()
    session["state"] = "THINKING"
    session["last_active_at"] = now()

    security_started = perf_counter()
    security = inspect_input(transcript)
    security_ms = round((perf_counter() - security_started) * 1000, 2)
    if security.blocked:
        answer = "检测到不安全或越权指令，本次自动处理已停止，并已转交人工客服。"
        turn = {
            "trace_id": trace_id,
            "transcript": security.text,
            "blocked": True,
            "intent": "安全事件",
            "confidence": 1.0,
            "answer": answer,
            "references": [],
            "next_action": "human_review",
            "latency": {"security_ms": security_ms, "intent_ms": 0, "rag_ms": 0, "llm_ttft_ms": 0, "total_ms": round((perf_counter() - total_started) * 1000, 2)},
            "security": security_snapshot(security),
            "created_at": now(),
        }
    else:
        intent_started = perf_counter()
        intent = classify_intent(security.text, trace_id=trace_id)
        intent_ms = round((perf_counter() - intent_started) * 1000, 2)
        rag_started = perf_counter()
        grounded = grounded_answer(security.text, role="buyer")
        rag_ms = round((perf_counter() - rag_started) * 1000, 2)
        if intent.intent == "物流查询":
            answer = "普通地区通常在下单后 48 小时内发货；物流停滞超过 72 小时可以登记催件。"
        else:
            answer = grounded["answer"]
        turn = {
            "trace_id": trace_id,
            "transcript": security.text,
            "blocked": False,
            "intent": intent.intent,
            "confidence": intent.confidence,
            "intent_method": intent.method,
            "answer": answer,
            "references": grounded["references"],
            "retrieval": {"rewritten_query": grounded["retrieval"]["rewritten_query"], "latency_ms": grounded["retrieval"]["latency_ms"], "grounded": grounded["grounded"]},
            "next_action": "answer" if grounded["grounded"] or intent.intent == "物流查询" else "human_review",
            "latency": {"security_ms": security_ms, "intent_ms": intent_ms, "rag_ms": rag_ms, "llm_ttft_ms": 0, "total_ms": round((perf_counter() - total_started) * 1000, 2)},
            "created_at": now(),
        }
    session["turns"].append(turn)
    session["state"] = "SPEAKING"
    session["tts_queue"] = [turn["answer"]]
    store.add_event({"node": "VoicePipeline", "status": "blocked" if turn["blocked"] else "completed", "session_id": session_id, "trace_id": trace_id, "duration_ms": turn["latency"]["total_ms"], "intent": turn["intent"], "source_duration_ms": duration_ms})
    return {"session_id": session_id, **turn, "state": session["state"], "transport": session["channel"], "tts": {"mode": "browser_speech_synthesis", "queue_size": len(session["tts_queue"]), "interruptible": True}}


def voice_metrics() -> dict:
    turns = [turn for session in store.voice_sessions.values() for turn in session["turns"]]
    totals = sorted(turn["latency"]["total_ms"] for turn in turns)
    p95 = totals[min(len(totals) - 1, int(len(totals) * 0.95))] if totals else 0
    return {
        "active_sessions": sum(session["state"] != "CLOSED" for session in store.voice_sessions.values()),
        "session_count": len(store.voice_sessions),
        "turn_count": len(turns),
        "interrupt_count": sum(session["interrupt_count"] for session in store.voice_sessions.values()),
        "avg_pipeline_ms": round(mean(totals), 2) if totals else 0,
        "p95_pipeline_ms": round(p95, 2),
        "target_p95_ms": 800,
        "transport": ["HTTP turn", "WebSocket JSON"],
        "production_gap": "真实音频帧 VAD/STT/TTS 与 35 路 WebRTC 压测需配置外部媒体服务",
    }
