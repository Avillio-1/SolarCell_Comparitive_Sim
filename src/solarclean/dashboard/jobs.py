"""Background job tracking for dashboard-triggered runs.

A full-year comparison takes minutes and Monte Carlo takes longer, so runs are
executed on worker threads while the browser polls for status. This registry is
in-memory only: restarting the dashboard forgets running jobs, but the run
directories they produced stay on disk and reappear in the runs list.

Progress here is bookkeeping, not science: use cases report how many work units
(scenarios, trials) they have completed, and this module only stores those
counts and measures wall-clock time. The ETA is elapsed-time-per-completed-unit
times remaining units — when no unit has finished yet, or the use case reports
no unit counts at all, no percentage or ETA is shown rather than a made-up one.
"""

from __future__ import annotations

import json
import threading
import traceback
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

# Cap for the persisted session history; oldest terminal records drop first.
HISTORY_LIMIT = 100

# Job kinds the launch form can request. Each maps 1:1 onto an existing
# application use case -- the dashboard adds no run logic of its own.
JOB_KINDS = (
    "compare",
    "monte-carlo",
    "sensitivity-oneway",
    "winner-map",
    "break-even",
)


class JobCancelled(Exception):
    """Raised inside a worker thread when the user deleted a running job."""


class ActiveJobError(Exception):
    """Raised when an atomic idle-only submission finds an active job."""

    def __init__(self, job: Job) -> None:
        self.job = job
        super().__init__(f"job {job.job_id} is already {job.status}")


@dataclass
class Job:
    job_id: str
    kind: str
    config_name: str
    status: str = "queued"  # queued -> running -> done | failed | cancelled
    detail: str = ""
    output_directory: Path | None = None
    error: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    finished_at: datetime | None = None
    progress_done: int | None = None
    progress_total: int | None = None
    hidden: bool = False
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)

    @property
    def cancel_requested(self) -> bool:
        return self.cancel_event.is_set()

    def report_progress(self, done: int, total: int, stage: str) -> None:
        """Progress callback handed to use cases; also a cancellation checkpoint."""
        if self.cancel_event.is_set():
            raise JobCancelled(f"job {self.job_id} cancelled by user")
        self.progress_done = done
        self.progress_total = total
        if stage:
            self.detail = stage

    def _elapsed_seconds(self, now: datetime) -> float | None:
        start = self.started_at
        if start is None:
            return None
        end = self.finished_at or now
        return max((end - start).total_seconds(), 0.0)

    def _progress_percent(self) -> float | None:
        if self.status == "done":
            return 100.0
        if self.progress_done is None or not self.progress_total:
            return None
        return min(100.0 * self.progress_done / self.progress_total, 100.0)

    def _eta_seconds(self, elapsed: float | None) -> float | None:
        """Honest ETA only: measured pace over completed units, else nothing."""
        if (
            self.status != "running"
            or elapsed is None
            or self.progress_done is None
            or not self.progress_total
            or self.progress_done <= 0
        ):
            return None
        remaining = self.progress_total - self.progress_done
        if remaining <= 0:
            return None
        return elapsed / self.progress_done * remaining

    def to_record(self) -> dict[str, object]:
        now = datetime.now(UTC)
        elapsed = self._elapsed_seconds(now)
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
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "progress_done": self.progress_done,
            "progress_total": self.progress_total,
            "progress_percent": self._progress_percent(),
            "elapsed_seconds": elapsed,
            "eta_seconds": self._eta_seconds(elapsed),
        }


class JobRegistry:
    """Tracks live jobs and, optionally, a persisted history of finished ones.

    With a ``history_path``, terminal jobs (done/failed/cancelled) are appended
    to a JSON file so the sessions table survives server restarts. Only
    finished jobs are persisted — a job lost to a crash mid-run simply leaves
    no session record (its run directory, if any, still appears in the runs
    list). Persistence failures are ignored: history is a convenience and must
    never break a run.
    """

    def __init__(self, history_path: Path | None = None) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._pending: deque[tuple[Job, Callable[[Job], Path]]] = deque()
        self._worker: threading.Thread | None = None
        self._history_path = history_path
        self._history: list[dict[str, object]] = self._load_history()

    def _load_history(self) -> list[dict[str, object]]:
        if self._history_path is None or not self._history_path.is_file():
            return []
        try:
            payload = json.loads(self._history_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        records = payload.get("jobs") if isinstance(payload, dict) else None
        if not isinstance(records, list):
            return []
        return [record for record in records if isinstance(record, dict)][-HISTORY_LIMIT:]

    def _save_history(self) -> None:
        if self._history_path is None:
            return
        try:
            self._history_path.parent.mkdir(parents=True, exist_ok=True)
            self._history_path.write_text(
                json.dumps({"version": 1, "jobs": self._history[-HISTORY_LIMIT:]}, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass

    def _record_finished(self, job: Job) -> None:
        with self._lock:
            if job.hidden:
                self._jobs.pop(job.job_id, None)
                return
            if self._jobs.get(job.job_id) is not job:
                return
            self._history.append(job.to_record())
            self._history = self._history[-HISTORY_LIMIT:]
            self._save_history()

    def submit(
        self,
        kind: str,
        config_name: str,
        work: Callable[[Job], Path],
        *,
        require_idle: bool = False,
    ) -> Job:
        job = Job(job_id=uuid.uuid4().hex[:12], kind=kind, config_name=config_name)
        with self._lock:
            if require_idle:
                active = next(
                    (
                        existing
                        for existing in self._jobs.values()
                        if not existing.hidden and existing.status in ("queued", "running")
                    ),
                    None,
                )
                if active is not None:
                    raise ActiveJobError(active)
            self._jobs[job.job_id] = job
            self._pending.append((job, work))
            if self._worker is None:
                self._worker = threading.Thread(
                    target=self._drain_queue,
                    name="dashboard-job-worker",
                    daemon=True,
                )
                worker_to_start = self._worker
            else:
                worker_to_start = None

        if worker_to_start is not None:
            worker_to_start.start()
        return job

    def _drain_queue(self) -> None:
        """Run submitted analyses serially in FIFO order."""
        while True:
            with self._lock:
                if not self._pending:
                    self._worker = None
                    return
                job, work = self._pending.popleft()
                if job.cancel_requested:
                    job.status = "cancelled"
                    job.detail = "Cancelled by user before starting."
                    job.finished_at = datetime.now(UTC)
                    cancelled_before_start = True
                else:
                    job.status = "running"
                    job.started_at = datetime.now(UTC)
                    cancelled_before_start = False

            if cancelled_before_start:
                self._record_finished(job)
                continue

            try:
                if job.cancel_requested:
                    raise JobCancelled(f"job {job.job_id} cancelled before start")
                output_directory = work(job)
                with self._lock:
                    job.output_directory = output_directory
                    job.status = "done"
            except JobCancelled:
                with self._lock:
                    job.status = "cancelled"
                    job.detail = "Cancelled by user before completion."
            except Exception as exc:  # surfaced to the UI, never swallowed silently
                error = f"{type(exc).__name__}: {exc}"
                detail = traceback.format_exc(limit=8)
                with self._lock:
                    job.status = "failed"
                    job.error = error
                    job.detail = detail
            finally:
                with self._lock:
                    job.finished_at = datetime.now(UTC)
                self._record_finished(job)

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None or job.hidden:
            return None
        return job

    def get_record(self, job_id: str) -> dict[str, object] | None:
        """Live job record, or the persisted record of a finished session."""
        job = self.get(job_id)
        if job is not None:
            return job.to_record()
        with self._lock:
            for record in self._history:
                if record.get("job_id") == job_id:
                    return dict(record)
        return None

    def delete(self, job_id: str) -> Job | dict[str, object] | None:
        """Remove a job from the visible list, cancelling it first if still active.

        Worker threads cannot be killed mid-computation safely, so a running job
        is asked to stop (it exits at its next progress checkpoint) and hidden
        immediately. Finished jobs are dropped from the registry and the
        persisted history. Run directories already written to outputs/ are
        never touched — deleting a session only affects the session list.
        """
        with self._lock:
            job = self._jobs.get(job_id)
            found: Job | dict[str, object] | None = None
            if job is not None and not job.hidden:
                if job.status in ("queued", "running"):
                    job.cancel_event.set()
                    job.hidden = True
                else:
                    del self._jobs[job_id]
                found = job
            history_match = [r for r in self._history if r.get("job_id") == job_id]
            if history_match:
                self._history = [r for r in self._history if r.get("job_id") != job_id]
                self._save_history()
                found = found or dict(history_match[0])
        return found

    def all(self) -> list[Job]:
        with self._lock:
            visible = [job for job in self._jobs.values() if not job.hidden]
        return sorted(visible, key=lambda j: j.created_at, reverse=True)

    def records(self) -> list[dict[str, object]]:
        """Live jobs first, then persisted history, newest first, deduplicated."""
        live = [job.to_record() for job in self.all()]
        live_ids = {record["job_id"] for record in live}
        with self._lock:
            historical = [dict(r) for r in self._history if r.get("job_id") not in live_ids]
        merged = live + historical
        merged.sort(key=lambda record: str(record.get("created_at", "")), reverse=True)
        return merged
