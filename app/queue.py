from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional


@dataclass
class JobInfo:
    job_id: str
    project_id: str
    step: str
    status: str = "queued"  # queued | running | done | failed
    error: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    started_at: Optional[str] = None
    finished_at: Optional[str] = None


class BusyError(Exception):
    """Raised when a second job tries to start while one is running."""

    def __init__(self, current: JobInfo):
        self.current = current
        super().__init__(
            f"全局队列忙碌：当前任务 {current.step} (project={current.project_id}, job={current.job_id})"
        )


class SingleTaskQueue:
    """Process-wide single GPU-safe job slot. Concurrent submit → BusyError (HTTP 409)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._current: Optional[JobInfo] = None
        self._history: list[JobInfo] = []

    @property
    def current(self) -> Optional[JobInfo]:
        return self._current

    def is_busy(self) -> bool:
        cur = self._current
        return cur is not None and cur.status in ("queued", "running")

    def snapshot(self) -> dict[str, Any]:
        cur = self._current
        return {
            "busy": self.is_busy(),
            "current": cur.__dict__ if cur else None,
            "recent": [j.__dict__ for j in self._history[-10:]],
        }

    async def run(
        self,
        project_id: str,
        step: str,
        coro_factory: Callable[[], Awaitable[Any]],
        *,
        allow_queue: bool = False,
    ) -> JobInfo:
        """
        Run a single job. If busy and allow_queue=False, raise BusyError immediately (HTTP 409).
        """
        job = JobInfo(job_id=str(uuid.uuid4())[:8], project_id=project_id, step=step)

        with self._lock:
            if self.is_busy() and not allow_queue:
                assert self._current is not None
                raise BusyError(self._current)
            self._current = job
            job.status = "running"
            job.started_at = datetime.now(timezone.utc).isoformat()

        try:
            await coro_factory()
            job.status = "done"
        except Exception as e:  # noqa: BLE001
            job.status = "failed"
            job.error = str(e)
            raise
        finally:
            job.finished_at = datetime.now(timezone.utc).isoformat()
            with self._lock:
                self._history.append(job)
                if self._current is job:
                    self._current = None
        return job


# Singleton
task_queue = SingleTaskQueue()
