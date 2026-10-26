"""DB-backed task queue: progress, checkpoint, retries with a limit, failure report, resume after crash.

Claiming is optimistic (UPDATE ... WHERE status='queued'), which is atomic on SQLite and Postgres.
Handlers are registered by kind and get a TaskContext; tests set TASKS_INLINE=1 to run synchronously.
"""
import logging
import time
import traceback
from datetime import timedelta
from typing import Callable

from sqlalchemy import update

from .config import get_settings
from .crypto import redact
from .db import new_session
from .models.core import BackgroundTask
from .util import utcnow

log = logging.getLogger("tasks")
HANDLERS: dict[str, Callable] = {}
STALE_AFTER = timedelta(minutes=5)


def handler(kind: str):
    def deco(fn):
        HANDLERS[kind] = fn
        return fn
    return deco


class TaskContext:
    def __init__(self, db, task):
        self.db, self.task = db, task

    @property
    def payload(self) -> dict:
        return self.task.payload

    @property
    def checkpoint(self) -> dict:
        return dict(self.task.checkpoint or {})

    def update(self, progress: float | None = None, checkpoint: dict | None = None) -> None:
        if progress is not None:
            self.task.progress = progress
        if checkpoint is not None:
            self.task.checkpoint = checkpoint
        self.task.heartbeat_at = utcnow()
        self.db.commit()


def enqueue(db, kind: str, payload: dict | None = None, max_attempts: int = 3) -> BackgroundTask:
    """db must be a tenant-scoped session (user_id stamped automatically)."""
    t = BackgroundTask(kind=kind, payload=payload or {}, max_attempts=max_attempts)
    db.add(t)
    db.commit()
    if get_settings().tasks_inline:
        drain(t.id)
        db.refresh(t)
    return t


def enqueue_nowait(db, kind: str, payload: dict | None = None) -> BackgroundTask:
    """Queue a follow-up task from inside a handler. The worker (or the inline drain) picks it up after the caller finishes."""
    t = BackgroundTask(kind=kind, payload=payload or {})
    db.add(t)
    return t


def drain(task_id: str | None = None, limit: int = 50) -> None:
    """Inline mode only: run the given task (with retries), then any follow-ups it queued."""
    while task_id and run_task(task_id):
        pass
    for _ in range(limit):
        if not run_task():
            break


def requeue_stale() -> int:
    """Tasks left 'running' by a crashed worker go back to the queue (attempts still count)."""
    db = new_session()
    try:
        cutoff = utcnow() - STALE_AFTER
        stale = db.query(BackgroundTask).filter(BackgroundTask.status == "running",
                                                BackgroundTask.heartbeat_at < cutoff).all()
        for t in stale:
            t.status = "queued" if t.attempts < t.max_attempts else "failed"
            t.error = t.error or "worker lost"
        db.commit()
        return len(stale)
    finally:
        db.close()


def claim_next(kind_filter: str | None = None) -> str | None:
    db = new_session()
    try:
        q = db.query(BackgroundTask.id).filter(BackgroundTask.status == "queued")
        if kind_filter:
            q = q.filter(BackgroundTask.kind == kind_filter)
        row = q.order_by(BackgroundTask.created_at).first()
        if not row:
            return None
        res = db.execute(update(BackgroundTask).where(BackgroundTask.id == row[0], BackgroundTask.status == "queued")
                         .values(status="running", attempts=BackgroundTask.attempts + 1, heartbeat_at=utcnow()))
        db.commit()
        return row[0] if res.rowcount == 1 else None
    finally:
        db.close()


def run_task(task_id: str | None = None) -> bool:
    """Run one task (given or next queued). Returns True if a task was processed."""
    if task_id:
        db = new_session()
        res = db.execute(update(BackgroundTask).where(BackgroundTask.id == task_id, BackgroundTask.status == "queued")
                         .values(status="running", attempts=BackgroundTask.attempts + 1, heartbeat_at=utcnow()))
        db.commit()
        db.close()
        if res.rowcount != 1:
            return False
    else:
        task_id = claim_next()
        if not task_id:
            return False
    boot = new_session()
    uid = boot.query(BackgroundTask.user_id).filter(BackgroundTask.id == task_id).scalar()
    boot.close()
    db = new_session(uid)  # handler runs scoped to the task owner
    try:
        task = db.query(BackgroundTask).filter(BackgroundTask.id == task_id).one()
        try:
            result = HANDLERS[task.kind](TaskContext(db, task))
            task.status, task.progress, task.result, task.finished_at = "done", 1.0, result or {}, utcnow()
        except Exception as e:  # failure report, retry if attempts remain
            db.rollback()
            task = db.query(BackgroundTask).filter(BackgroundTask.id == task_id).one()
            task.error = redact(f"{type(e).__name__}: {e}")[:2000]
            log.warning("task %s failed: %s", task.kind, redact(traceback.format_exc()[-500:]))
            task.status = "queued" if task.attempts < task.max_attempts else "failed"
            if task.status == "failed":
                task.finished_at = utcnow()
        db.commit()
        return True
    finally:
        db.close()


def worker_loop(poll_s: float = 1.0, stop=lambda: False) -> None:
    requeue_stale()
    while not stop():
        if not run_task():
            time.sleep(poll_s)
