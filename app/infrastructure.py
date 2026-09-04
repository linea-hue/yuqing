from __future__ import annotations

import json
import os
from threading import RLock


class WorkflowInfrastructure:
    """Redis Checkpoint/Stream 适配器，连接不可用时自动降级到进程内实现。"""

    def __init__(self) -> None:
        self.url = os.getenv("REDIS_URL", "")
        self._client = None
        self._memory_checkpoints: dict[str, dict] = {}
        self._memory_stream: list[dict] = []
        self._lock = RLock()
        self.mode = "memory"
        self.last_error: str | None = None
        if self.url:
            try:
                import redis

                client = redis.Redis.from_url(self.url, decode_responses=True, socket_connect_timeout=0.25, socket_timeout=0.5)
                client.ping()
                self._client = client
                self.mode = "redis"
            except Exception as exc:  # Redis 是可选生产依赖，本地必须可零配置启动。
                self.last_error = type(exc).__name__

    def checkpoint(self, workflow_id: str, state: dict) -> None:
        payload = json.dumps(state, ensure_ascii=False, default=str)
        if self._client is not None:
            try:
                self._client.set(f"ecom:workflow:{workflow_id}", payload, ex=7 * 24 * 3600)
                return
            except Exception as exc:
                self.last_error = type(exc).__name__
                self.mode = "memory_fallback"
        with self._lock:
            self._memory_checkpoints[workflow_id] = json.loads(payload)

    def load_checkpoint(self, workflow_id: str) -> dict | None:
        if self._client is not None:
            try:
                raw = self._client.get(f"ecom:workflow:{workflow_id}")
                return json.loads(raw) if raw else None
            except Exception as exc:
                self.last_error = type(exc).__name__
                self.mode = "memory_fallback"
        with self._lock:
            return self._memory_checkpoints.get(workflow_id)

    def publish(self, event: dict) -> str:
        payload = json.dumps(event, ensure_ascii=False, default=str)
        if self._client is not None:
            try:
                return str(self._client.xadd("ecom:workflow-events", {"payload": payload}, maxlen=10000, approximate=True))
            except Exception as exc:
                self.last_error = type(exc).__name__
                self.mode = "memory_fallback"
        with self._lock:
            self._memory_stream.append(json.loads(payload))
            return f"memory-{len(self._memory_stream)}"

    def status(self) -> dict:
        return {
            "mode": self.mode,
            "redis_configured": bool(self.url),
            "redis_connected": self._client is not None and self.mode == "redis",
            "last_error": self.last_error,
            "memory_checkpoint_count": len(self._memory_checkpoints),
            "memory_stream_depth": len(self._memory_stream),
            "stream": "ecom:workflow-events",
        }


workflow_infra = WorkflowInfrastructure()
