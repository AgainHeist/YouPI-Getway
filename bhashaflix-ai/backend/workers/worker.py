"""Background worker: a small in-process queue over SQLite-backed jobs.

₹0 constraint: no Redis, no Celery, no external broker.  One process, N
threads, and a persistent job table — restarting the container requeues
anything that was interrupted (and says so honestly in the event log).
Heavy model stages are serialised by default (BFLIX_WORKER_THREADS=1).
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass

from ..config import settings
from ..db import get_conn
from ..services import pipeline, repo
from ..services.repo import storage_usage_bytes

log = logging.getLogger("bhashaflix.worker")


@dataclass
class Task:
    job_id: str
    stages: list[str] | None
    final_status: str | None = None
    force: bool = False


class JobQueue:
    def __init__(self, threads: int | None = None):
        self._queue: "queue.Queue[Task]" = queue.Queue()
        self._pending: set[tuple[str, tuple[str, ...] | None]] = set()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._n = max(1, threads or settings.worker_threads)
        self._active: dict[str, float] = {}

    # ------------------------------------------------------------------ api --
    def start(self) -> None:
        if self._threads:
            return
        # A previous stop() set this event; clear it so restarted workers live.
        self._stop.clear()
        self._requeue_interrupted()
        for i in range(self._n):
            thread = threading.Thread(target=self._loop, name=f"bhashaflix-worker-{i}", daemon=True)
            thread.start()
            self._threads.append(thread)
        log.info("worker queue started with %s thread(s)", self._n)

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        for thread in self._threads:
            thread.join(timeout=timeout)
        self._threads.clear()

    def enqueue(
        self,
        job_id: str,
        stages: list[str] | None = None,
        final_status: str | None = None,
        force: bool = False,
    ) -> bool:
        key = (job_id, tuple(stages) if stages else None)
        with self._lock:
            if key in self._pending:
                return False
            self._pending.add(key)
        self._queue.put(Task(job_id=job_id, stages=stages, final_status=final_status, force=force))
        return True

    def stats(self) -> dict:
        return {
            "queued": self._queue.qsize(),
            "active": len(self._active),
            "threads": self._n,
            "storage_bytes": storage_usage_bytes(),
        }

    # -------------------------------------------------------------- internals --
    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                task = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            key = (task.job_id, tuple(task.stages) if task.stages else None)
            self._active[task.job_id] = time.time()
            try:
                self._run(task)
            except Exception:  # pragma: no cover - never kill the worker
                log.exception("worker task failed: %s", task.job_id)
            finally:
                self._active.pop(task.job_id, None)
                with self._lock:
                    self._pending.discard(key)
                self._queue.task_done()

    def _run(self, task: Task) -> None:
        job = repo.get_job(task.job_id)
        if not job:
            log.info("skipping deleted job %s", task.job_id)
            return
        try:
            pipeline.run_full_job(task.job_id, stages=task.stages, force=task.force)
            job = repo.get_job(task.job_id)
            if job and job["status"] == "running":
                # A granular stage finished: the job is no longer executing.
                status = task.final_status or "awaiting_input"
                repo.update_job(task.job_id, status=status)
                repo.add_event(
                    task.job_id,
                    job.get("stage", "queued"),
                    "Stage finished — paused. Run the next step when you are ready."
                    if status == "awaiting_input" else "Paused for your review in the studio.",
                )
        except pipeline.StageFailure as exc:
            log.warning("job %s failed: %s (%s)", task.job_id, exc.message, exc.code)
        except Exception:  # pragma: no cover
            log.exception("job %s crashed", task.job_id)

    def _requeue_interrupted(self) -> None:
        rows = get_conn().execute(
            "SELECT id, status FROM jobs WHERE status IN ('queued','running') AND deleted=0"
        ).fetchall()
        for row in rows:
            job = repo.get_job(row["id"])
            if not job:
                continue
            repo.update_job(row["id"], status="queued")
            repo.add_event(
                row["id"], job.get("stage", "queued"),
                "The previous worker stopped. This project was requeued and will restart from the first incomplete stage.",
                level="warning",
            )
            self.enqueue(row["id"])


queue_service = JobQueue()


def start_queue() -> None:
    queue_service.start()


def stop_queue() -> None:
    queue_service.stop()
