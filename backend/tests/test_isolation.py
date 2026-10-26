"""Tenant isolation: scoped sessions, stamping, and a route walker that fails when a new
ID-bearing route is added without being covered."""
import pytest

from app.db import TenantViolation, new_session
from app.main import app
from app.models.core import BackgroundTask
from app.tasks import enqueue
from tests import synth_resumes as sr


def _uid(api):
    return api.get("/api/auth/me").json()["id"]


def test_scoped_session_hides_other_users_rows(env, mk):
    a, b = mk("a@example.com"), mk("b@example.com")
    ua, ub = _uid(a), _uid(b)
    s = new_session(ua)
    enqueue(s, "noop")
    s.close()
    assert new_session(ub).query(BackgroundTask).count() == 0
    assert new_session(ua).query(BackgroundTask).count() == 1
    assert new_session().query(BackgroundTask).count() == 1  # unscoped (system) sees all


def test_insert_for_other_user_is_rejected(env, mk):
    a, b = mk("a@example.com"), mk("b@example.com")
    s = new_session(_uid(a))
    s.add(BackgroundTask(user_id=_uid(b), kind="noop"))
    with pytest.raises(TenantViolation):
        s.flush()


def test_every_id_route_is_isolated(env, mk):
    a, b = mk("a@example.com"), mk("b@example.com")
    up = a.upload(sr.pdf_single()).json()
    prof = a.get("/api/profile").json()
    item = prof["items"]["experience"][0]["id"]
    version = a.get("/api/profile/versions").json()[0]["id"]
    known = {"task_id": up["task_id"], "resume_id": up["resume_id"], "item_id": item, "version_id": version}
    walked = []
    for r in app.routes:
        params = list(getattr(r, "param_convertors", {}))
        if not params or not r.path.startswith("/api/") or r.path.startswith("/api/auth"):
            continue
        if params == ["name"]:  # consent names, not object ids: see test_consents_are_per_user
            continue
        assert all(p in known for p in params), f"route {r.path} has uncovered param: add it to `known`"
        url = r.path
        for p in params:
            url = url.replace("{%s}" % p, known[p])
        for m in r.methods - {"HEAD", "OPTIONS"}:
            resp = b.request(m, url, {} if m != "GET" else None)
            assert resp.status_code in (404, 405, 422), f"{m} {url} as other user -> {resp.status_code}"
            walked.append((m, r.path))
        assert a.get(url).status_code in (200, 405) if "GET" in r.methods else True
    assert len(walked) >= 7  # tasks, resume x2, item patch/delete/confirm, version
    # B's attempts (including DELETE/PATCH) must not have damaged A's data
    assert a.get("/api/profile").json()["items"]["experience"][0]["id"] == item


def test_consents_are_per_user(env, mk):
    a, b = mk("a@example.com"), mk("b@example.com")
    assert b.put("/api/consents/github", {"granted": True}).status_code == 200
    assert a.get("/api/consents").json()["github"]["granted"] is False
    assert a.post("/api/profile/github", {"username": "demo-user"}).status_code == 403


def test_list_endpoints_never_include_other_users(env, mk):
    a, b = mk("a@example.com"), mk("b@example.com")
    a.upload(sr.pdf_single())
    assert len(a.get("/api/tasks").json()) == 1 and len(a.get("/api/resumes").json()) == 1
    assert b.get("/api/tasks").json() == [] and b.get("/api/resumes").json() == []
    assert b.get("/api/profile").json()["items"] == {}
    assert b.get("/api/profile/versions").json() == []


def test_export_contains_only_own_data(env, mk):
    a, b = mk("a@example.com"), mk("b@example.com")
    a.upload(sr.pdf_single())
    data = b.get("/api/me/export").json()
    assert data["background_tasks"] == [] and data["profile_items"] == [] and data["resumes"] == []
    assert [u["email"] for u in data["users"]] == ["b@example.com"]
    assert "password_hash" not in str(data) and "token_hash" not in str(data)
    assert "Acme Test Co" in str(a.get("/api/me/export").json())
