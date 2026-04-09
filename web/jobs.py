"""
Background job manager using threading + in-memory dict.

Single-user local tool — no persistence or cleanup needed.
"""

import threading
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class Job:
    id: str
    state: str = "pending"      # pending -> running -> done | failed
    progress: str = ""          # Human-readable, updated by worker thread
    result: Any = None          # Stored output (EvaluatedMeme list, image list, etc.)
    error: str | None = None


_jobs: dict[str, Job] = {}
_lock = threading.Lock()


def submit(target_fn: Callable, *args, **kwargs) -> str:
    """
    Run target_fn(job, *args, **kwargs) in a daemon thread.

    The worker function receives the Job object as its first argument so it can
    update job.progress and job.result in real time.

    Returns:
        job_id string
    """
    job_id = uuid.uuid4().hex[:12]
    job = Job(id=job_id)

    with _lock:
        _jobs[job_id] = job

    def _worker():
        job.state = "running"
        try:
            target_fn(job, *args, **kwargs)
            job.state = "done"
        except Exception as e:
            job.state = "failed"
            job.error = f"{type(e).__name__}: {e}"
            traceback.print_exc()

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    return job_id


def get(job_id: str) -> Job | None:
    """Look up a job by ID."""
    with _lock:
        return _jobs.get(job_id)
