from __future__ import annotations

import asyncio
import os

from .evaluation import run_offline_eval
from .store import now


class EvaluationScheduler:
    def __init__(self) -> None:
        self.enabled = os.getenv("ENABLE_PERIODIC_EVALS", "false").lower() == "true"
        self.interval_seconds = max(300, int(os.getenv("EVAL_INTERVAL_SECONDS", "86400")))
        self.last_run_at: str | None = None
        self.last_run_id: str | None = None
        self.task: asyncio.Task | None = None

    async def run(self) -> None:
        while True:
            result = await asyncio.to_thread(run_offline_eval)
            self.last_run_at = now()
            self.last_run_id = result["run_id"]
            await asyncio.sleep(self.interval_seconds)

    def status(self) -> dict:
        return {"enabled": self.enabled, "interval_seconds": self.interval_seconds, "last_run_at": self.last_run_at, "last_run_id": self.last_run_id, "runner": "asyncio_local", "production_adapter": "Kubernetes CronJob/Celery Beat"}


evaluation_scheduler = EvaluationScheduler()
