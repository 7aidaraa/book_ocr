"""Disk-backed job records.

A job outlives the process that started it: state lives in data/jobs/<id>.json,
written atomically, so restarting the server never loses a book's history.
No Redis, no Celery, no database — one small JSON file per job.

A job that was mid-flight when the process died is reopened as `failed` with
`interrupted: true` on the next start. It is never silently resurrected and
never silently lost: the user sees it and can run it again, and the OCR
pipeline's own resume skips the pages that already succeeded.
"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

JOBS_DIR = Path("data/jobs")

QUEUED = "queued"
DOWNLOADING = "downloading"
PROCESSING = "processing"
COMPLETED = "completed"
FAILED = "failed"
CANCELLED = "cancelled"

STATES = (QUEUED, DOWNLOADING, PROCESSING, COMPLETED, FAILED, CANCELLED)
ACTIVE_STATES = (QUEUED, DOWNLOADING, PROCESSING)
TERMINAL_STATES = (COMPLETED, FAILED, CANCELLED)

_SAFE_ID = set("0123456789abcdef")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobStore:
    """Thread-safe store of job dicts, persisted one file per job."""

    def __init__(self, directory: str | Path = JOBS_DIR, recover: bool = True) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._jobs: dict[str, dict] = {}
        self._cancelled: set[str] = set()
        self._load(recover=recover)

    # ---- persistence ---------------------------------------------------

    def _path(self, job_id: str) -> Path:
        if not job_id or not set(job_id) <= _SAFE_ID:
            raise ValueError(f"unsafe job id: {job_id!r}")   # no path traversal
        return self.directory / f"{job_id}.json"

    def _write(self, job: dict) -> None:
        path = self._path(job["id"])
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)                                    # atomic on POSIX and NTFS

    def _load(self, recover: bool) -> None:
        for path in sorted(self.directory.glob("*.json")):
            try:
                job = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(job, dict) or "id" not in job:
                continue
            if recover and job.get("state") in ACTIVE_STATES:
                job["state"] = FAILED
                job["interrupted"] = True
                job["error"] = "interrupted: the server restarted mid-run"
                job["message"] = "توقفت المهمة بإعادة تشغيل الخادم — يمكن إعادة تشغيلها"
                job["updated_at"] = _now()
                self._write(job)
            self._jobs[job["id"]] = job

    # ---- lifecycle -----------------------------------------------------

    def create(self, kind: str, **fields) -> dict:
        job_id = uuid.uuid4().hex[:12]
        job = {
            "id": job_id,
            "kind": kind,                 # "upload" | "acquire"
            "state": QUEUED,
            "message": "في الانتظار",
            "error": None,
            "interrupted": False,
            "created_at": _now(),
            "updated_at": _now(),
            "progress": {"stage": QUEUED, "current": 0, "total": None},
            **fields,
        }
        with self._lock:
            self._jobs[job_id] = job
            self._write(job)
        return dict(job)

    def update(self, job_id: str, **fields) -> dict:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise KeyError(job_id)
            state = fields.get("state")
            if state is not None and state not in STATES:
                raise ValueError(f"unknown state: {state}")
            job.update(fields)
            job["updated_at"] = _now()
            self._write(job)
            return dict(job)

    def set_progress(self, job_id: str, stage: str, current: int,
                     total: Optional[int] = None, message: str = "") -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise KeyError(job_id)
            job["progress"] = {"stage": stage, "current": current, "total": total}
            if message:
                job["message"] = message
            job["updated_at"] = _now()
            self._write(job)

    def get(self, job_id: str) -> Optional[dict]:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    def list(self, kinds: Optional[Iterable[str]] = None) -> list[dict]:
        with self._lock:
            jobs = [dict(j) for j in self._jobs.values()]
        if kinds is not None:
            kinds = set(kinds)
            jobs = [j for j in jobs if j.get("kind") in kinds]
        return sorted(jobs, key=lambda j: j.get("created_at", ""), reverse=True)

    def delete(self, job_id: str) -> None:
        with self._lock:
            self._jobs.pop(job_id, None)
            self._cancelled.discard(job_id)
            self._path(job_id).unlink(missing_ok=True)

    # ---- cancellation --------------------------------------------------

    def request_cancel(self, job_id: str) -> dict:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise KeyError(job_id)
            if job["state"] in TERMINAL_STATES:
                return dict(job)
            self._cancelled.add(job_id)
            job["message"] = "طُلب الإلغاء..."
            job["updated_at"] = _now()
            self._write(job)
            return dict(job)

    def cancel_requested(self, job_id: str) -> bool:
        with self._lock:
            return job_id in self._cancelled

    def mark_cancelled(self, job_id: str) -> dict:
        self._cancelled.discard(job_id)
        return self.update(job_id, state=CANCELLED, message="أُلغيت المهمة")
