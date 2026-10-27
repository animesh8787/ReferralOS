"""Cross-cutting security properties, checked over EVERY route rather than a hand-picked few."""
import json
import logging

import pytest

from app.main import app
from tests.outreach_helpers import *  # noqa: F401,F403
from tests.outreach_helpers import _reset_world  # noqa: F401
from tests.conftest import Api
from tests.test_isolation import _uid  # noqa: F401

PUBLIC = {("GET", "/api/health"), ("POST", "/api/auth/signup"), ("POST", "/api/auth/login"), ("POST", "/api/auth/verify"), ("POST", "/api/auth/forgot"), ("POST", "/api/auth/reset"),
          ("GET", "/api/outreach/guidance")}  # guidance text is static legal-style information; the others are the sign-in flow itself
FILLERS = {"task_id": "0" * 32, "resume_id": "0" * 32, "item_id": "0" * 32, "version_id": "0" * 32, "import_id": "0" * 32, "contact_id": "0" * 32, "review_id": "0" * 32,
           "entry_id": "0" * 32, "company_id": "0" * 32, "job_id": "0" * 32, "board_id": "0" * 32, "tailored_id": "0" * 32, "other_id": "0" * 32, "message_id": "0" * 32,
           "batch_id": "0" * 32, "event_id": "0" * 32, "pair_id": "0" * 32, "campaign_id": "0" * 32, "name": "github"}
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


def api_routes():
    for r in app.routes:
        if getattr(r, "path", "").startswith("/api/") and getattr(r, "methods", None):
            for m in sorted(r.methods - {"HEAD", "OPTIONS"}):
                yield m, r.path, r


def url_of(path):
    for k, v in FILLERS.items():
        path = path.replace("{%s}" % k, v)
    assert "{" not in path, f"add filler for {path}"
    return path


def test_every_route_requires_a_session_except_the_sign_in_flow(env):
    anon = Api()
    n = 0
    for m, path, _ in api_routes():
        if (m, path) in PUBLIC:
            continue
        r = anon.c.request(m, url_of(path), json={})
        assert r.status_code == 401, f"{m} {path} answered {r.status_code} without a session"
        n += 1
    assert n > 100


def test_every_state_changing_route_rejects_a_missing_or_wrong_csrf_token(env, mk):
    a = mk("a@example.com")
    checked = 0
    for m, path, _ in api_routes():
        if m not in UNSAFE or path.startswith("/api/auth/") or (m, path) in PUBLIC:
            continue
        for hdr in ({}, {"X-CSRF-Token": "not-the-token"}):
            r = a.c.request(m, url_of(path), json={}, headers=hdr)
            assert r.status_code == 403, f"{m} {path} accepted a request with csrf={hdr or 'missing'} -> {r.status_code}"
        checked += 1
    assert checked > 60
    assert a.get("/api/auth/me").status_code == 200  # nothing above logged us out or changed the session


def _table_counts():
    from sqlalchemy import text
    from app.db import Base, new_session
    db = new_session()
    try:  # audit_logs is excluded on purpose: reading sensitive data (an export) is itself audited
        return {t.name: db.execute(text(f"select count(*) from {t.name}")).scalar() for t in Base.metadata.sorted_tables if t.name != "audit_logs"}
    finally:
        db.close()


def test_safe_methods_never_change_stored_data(env, mk):
    a = mk("a@example.com")
    prep(a)  # noqa: F405
    gen(a)  # noqa: F405
    before = _table_counts()
    n = 0
    for m, path, _ in api_routes():
        if m == "GET" and "{" not in path and path not in ("/api/me/export", "/api/me/audit"):
            assert a.get(path).status_code < 500, path
            n += 1
    assert n > 30 and _table_counts() == before


@pytest.mark.parametrize("payload", ["' OR '1'='1", "'; DROP TABLE users; --", "%' UNION SELECT password_hash FROM users --", "\" OR 1=1 --", "<script>alert(1)</script>", "../../etc/passwd", "\x00", "A" * 5000])
def test_hostile_search_and_filter_input_is_treated_as_plain_text(env, mk, payload):
    a = mk("a@example.com")
    prep(a)  # noqa: F405
    for url in ("/api/contacts?q=", "/api/email-contacts?q=", "/api/prospects?q=", "/api/jobs?q=", "/api/outreach/messages?q=", "/api/companies?q="):
        r = a.get(url + payload.replace("#", "%23").replace("&", "%26").replace("+", "%2B").replace("\x00", "%00"))
        assert r.status_code in (200, 422), (url, r.status_code)
        if r.status_code == 200:
            assert "password_hash" not in r.text and "argon2" not in r.text
    assert a.get("/api/contacts").json()["total"] == 6  # nothing was dropped or changed


def test_hostile_text_in_stored_fields_stays_inert_in_json_and_exports(env, mk):
    a = mk("a@example.com")
    xss = "<img src=x onerror=alert(1)>"
    a.post("/api/contacts", {"first_name": "=cmd|' /C calc'!A0", "last_name": xss, "company": "<script>x</script> Corp"})
    r = a.get("/api/contacts")
    assert r.headers["content-type"].startswith("application/json") and xss in r.text  # returned as data, escaped by JSON; React escapes on render
    a.post("/api/scoring/recompute", {})
    csv_text = a.get("/api/exports/prospects.csv").text
    assert "'=cmd" in csv_text and ",=cmd" not in csv_text


def test_downloads_cannot_be_sniffed_or_traversed(env, mk):
    a = mk("a@example.com")
    jobs = prep(a)  # noqa: F405
    t = a.post("/api/tailoring", {"job_id": jobs["Backend Engineer"]["id"]}).json()
    r = a.get(f"/api/tailoring/{t['id']}/files/resume.pdf")
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["content-disposition"].startswith("attachment")
    for bad in ("../../../.kek", "..%2f..%2f.kek", "resume.pdf%00.txt", "%2e%2e/%2e%2e/.kek"):
        assert a.get(f"/api/tailoring/{t['id']}/files/{bad}").status_code == 404
    assert a.get(f"/api/resumes/{'../' * 5}etc/file").status_code in (404, 422)


def test_uploads_are_validated_by_content_and_size(env, mk):
    a = mk("a@example.com")
    assert a.upload(b"MZ\x90\x00 fake exe", "resume.pdf").json()["status"] == "failed"  # wrong content under a pdf name: rejected by the parser, never executed
    assert a.upload(b"<html><script>alert(1)</script>", "resume.docx").json()["status"] == "failed"
    r = a.c.post("/api/imports", data={"kind": "linkedin"}, files={"file": ("x.csv", b"a,b\n" + b"1,2\n" * 10)}, headers=a._h())
    assert r.status_code == 201


def test_logs_never_contain_personal_data_or_secrets_even_through_failures(env, mk, caplog):
    caplog.set_level(logging.DEBUG)
    logging.getLogger("worker.noise").warning("could not email jane.doe@corp.example.com (token=ya29.SECRETVALUE123456)")  # any logger, any module
    a = mk("a@example.com")
    prep(a)  # noqa: F405
    gen(a)  # noqa: F405
    approve_emails(a)  # noqa: F405
    a.post("/api/outreach/send", {})
    a.post("/api/email/test-send", {})
    a.post("/api/auth/login", {"email": "a@example.com", "password": "wrong-password-1"})
    text = caplog.text
    assert "[email]" in text and "jane.doe" not in text
    for needle in ("alex.example@example.com", "pat@acme-test.example.com", "lee@acme-test.example.com", "mock-access-token", "correct-horse-9", "wrong-password-1", "ya29.SECRETVALUE", "a@example.com"):
        assert needle not in text, needle


def test_failure_reports_in_the_task_queue_are_redacted(env, mk):
    from app import tasks
    from app.db import new_session

    @tasks.handler("leaky")
    def _boom(ctx):
        raise RuntimeError("smtp login failed for alex@corp.example.com password=hunter2hunter2 token=abc123abc123")

    a = mk("a@example.com")
    t = tasks.enqueue(new_session(_uid(a)), "leaky", max_attempts=1)
    assert t.status == "failed" and "alex@corp" not in t.error and "hunter2" not in t.error and "abc123abc" not in t.error


def test_rate_limits_cover_the_sensitive_endpoints(env, mk):
    a = mk("a@example.com")
    statuses = {"export": [a.get("/api/me/export").status_code for _ in range(7)], "csv": [a.get("/api/exports/prospects.csv").status_code for _ in range(7)]}
    assert 429 in statuses["export"] and 429 in statuses["csv"]
    b = Api()
    codes = [b.post("/api/auth/signup", {"email": f"x{i}@example.com", "password": "correct-horse-9"}).status_code for i in range(12)]
    assert 429 in codes and codes[:9] == [201] * 9  # the 10-per-hour signup budget already covered the user created above
    assert 429 in [b.post("/api/auth/forgot", {"email": "x@example.com"}).status_code for _ in range(7)]
