"""Background job tracking for dashboard-triggered runs.

A full-year comparison takes minutes and Monte Carlo takes longer, so runs are
executed on worker threads while the browser polls for status. This registry is
in-memory only: restarting the dashboard forgets running jobs, but the run
directories they produced stay on disk and reappear in the runs list.
"""

from __future__ import annotations

import threading
import traceback
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

# Job kinds the launch form can request. Each maps 1:1 onto an existing
# application use case -- the dashboard adds no run logic of its own.
JOB_KINDS = (
    "compare",
    "monte-carlo",
    "sensitivity-oneway",
    "winner-map",
    "break-even",
)


@dataclass
class Job:
    job_id: str
    kind: str
    config_name: str
    status: str = "queued"  # queued -> running -> done | failed
    detail: str = ""
    output_directory: Path | None = None
    error: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None

    def to_record(self) -> dict[str, object]:
        return {
            "job_id": self.job_id,
            "kind": self.kind,
            "config_name": self.config_name,
            "status": self.status,
            "detail": self.detail,
            "output_directory": str(self.output_directory) if self.output_directory else None,
            "run_id": self.output_directory.name if self.output_directory else None,
            "error": self.error,
            "created_at": self.created_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }


class JobRegistry:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def submit(
        self,
        kind: str,
        config_name: str,
        work: Callable[[Job], Path],
    ) -> Job:
        job = Job(job_id=uuid.uuid4().hex[:12], kind=kind, config_name=config_name)
        with self._lock:
            self._jobs[job.job_id] = job

        def _run() -> None:
            job.status = "running"
            try:
                job.output_directory = work(job)
                job.status = "done"
            except Exception as exc:  # surfaced to the UI, never swallowed silently
                job.status = "failed"
                job.error = f"{type(exc).__name__}: {exc}"
                job.detail = traceback.format_exc(limit=8)
            finally:
                job.finished_at = datetime.now(UTC)

        threading.Thread(target=_run, name=f"dashboard-{kind}-{job.job_id}", daemon=True).start()
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def all(self) -> list[Job]:
        with self._lock:
            return sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)
