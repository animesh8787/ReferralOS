from datetime import timedelta

import pytest

from app import crypto, storage, tasks
from app.db import new_session
from app.models.core import AuditLog, BackgroundTask, User
from app.util import utcnow


def _uid(api):
    return api.get("/api/auth/me").json()["id"]


# ---- task queue ----
def test_task_runs_and_reports_progress(env, mk):
    a = mk("a@example.com")
    s = new_session(_uid(a))
    t = tasks.enqueue(s, "noop")
    assert (t.status, t.progress, t.result) == ("done", 1.0, {"ok": True})


def test_task_retries_then_fails_with_report(env, mk):
    calls = []

    @tasks.handler("flaky")
    def _f(ctx):
        calls.append(1)
        raise RuntimeError("boom for jane@example.com")

    a = mk("a@example.com")
    s = new_session(_uid(a))
    t = tasks.enqueue(s, "flaky", max_attempts=3)
    assert len(calls) == 3 and t.status == "failed" and t.attempts == 3
    assert "boom" in t.error and "jane@example.com" not in t.error  # redacted failure report


def test_task_succeeds_on_retry_and_resumes_from_checkpoint(env, mk):
    seen = []

    @tasks.handler("resumable")
    def _r(ctx):
        start = ctx.checkpoint.get("i", 0)
        for i in range(start, 5):
            seen.append(i)
            ctx.update(progress=i / 5, checkpoint={"i": i + 1})
            if i == 2 and len(seen) == 3:
                raise RuntimeError("crash mid-way")

    a = mk("a@example.com")
    s = new_session(_uid(a))
    t = tasks.enqueue(s, "resumable")
    assert t.status == "done" and seen == [0, 1, 2, 3, 4]  # 2nd attempt resumed at checkpoint 3


def test_stale_running_task_is_requeued(env, mk):
    a = mk("a@example.com")
    s = new_session(_uid(a))
    t = BackgroundTask(kind="noop", status="running", attempts=1, heartbeat_at=utcnow() - timedelta(hours=1))
    s.add(t)
    s.commit()
    assert tasks.requeue_stale() == 1
    s.refresh(t)
    assert t.status == "queued"
    assert tasks.run_task() and s.refresh(t) is None and t.status == "done"


def test_two_workers_cannot_claim_same_task(env, mk):
    a = mk("a@example.com")
    s = new_session(_uid(a))
    s.add(BackgroundTask(kind="noop"))
    s.commit()
    assert tasks.claim_next() is not None
    assert tasks.claim_next() is None


# ---- privacy ----
def test_delete_account_is_complete(env, mk):
    a, b = mk("a@example.com"), mk("b@example.com")
    ua = _uid(a)
    s = new_session(ua)
    tasks.enqueue(s, "noop")
    s.close()
    storage.put(ua, "resumes", "a" * 32, b"pdfbytes", ".pdf")
    assert a.post("/api/me/delete", {"password": "wrong-pass-123"}).status_code == 403
    assert a.post("/api/me/delete", {"password": "correct-horse-9"}).status_code == 200
    db = new_session()
    from app.db import Base
    from sqlalchemy import func, select
    for t in Base.metadata.sorted_tables:
        if "user_id" in t.c:
            assert db.execute(select(func.count()).select_from(t).where(t.c.user_id == ua)).scalar() == 0, t.name
    assert db.query(User).filter(User.id == ua).count() == 0
    assert db.query(User).count() == 1  # the other user survives
    assert not storage.user_dir(ua).exists()
    assert a.get("/api/auth/me").status_code == 401


def test_audit_log_records_sensitive_actions(env, mk):
    a = mk("a@example.com")
    a.get("/api/me/export")
    db = new_session()
    actions = {r.action for r in db.query(AuditLog).all()}
    assert {"signup", "email_verified", "login", "data_exported"} <= actions


# ---- crypto / storage / redaction ----
def test_encrypt_roundtrip_and_tamper(env):
    blob = crypto.encrypt("ya29.secret-oauth-token")
    assert "secret" not in blob and crypto.decrypt(blob) == "ya29.secret-oauth-token"
    assert crypto.encrypt("x") != crypto.encrypt("x")  # fresh DEK/nonce each time
    with pytest.raises(Exception):
        crypto.decrypt(blob[:-4] + "AAAA")


def test_redaction():
    t = crypto.redact("mail jane.doe@corp.com token=abcdef123456 call +91 98765 43210")
    assert "jane.doe" not in t and "abcdef123456" not in t and "98765" not in t


def test_storage_blocks_traversal(env):
    uid = "a" * 32
    for bad in ("../x", "a" * 31, "A" * 32):
        with pytest.raises(ValueError):
            storage.path_for(uid, "resumes", bad)
    with pytest.raises(ValueError):
        storage.path_for(uid, "../etc", "a" * 32)
    with pytest.raises(ValueError):
        storage.path_for("../evil", "resumes", "a" * 32)
    with pytest.raises(ValueError):
        storage.path_for(uid, "resumes", "a" * 32, "/../x")
