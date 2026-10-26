"""Tenant isolation: scoped sessions, stamping, and a route walker that fails when a new
ID-bearing route is added without being covered."""
import pytest

from app.db import TenantViolation, new_session
from app.main import app
from app.models.core import BackgroundTask, User
from app.tasks import enqueue


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
    s = new_session(_uid(a))
    task = enqueue(s, "noop")
    s.close()
    known = {"task_id": task.id}  # extend when a new resource type gets by-id routes
    walked = 0
    for r in app.routes:
        params = [p for p in getattr(r, "param_convertors", {})]
        if not params or not r.path.startswith("/api/") or r.path.startswith("/api/auth"):
            continue
        assert all(p in known for p in params), f"route {r.path} has uncovered param: add it to `known`"
        url = r.path
        for p in params:
            url = url.replace("{%s}" % p, known[p])
        for m in r.methods - {"HEAD", "OPTIONS"}:
            resp = b.get(url) if m == "GET" else b.post(url, {})
            assert resp.status_code in (404, 405, 422), f"{m} {url} -> {resp.status_code}"
            owner = a.get(url) if m == "GET" else None
            if owner is not None:
                assert owner.status_code == 200
        walked += 1
    assert walked >= 1


def test_list_endpoints_never_include_other_users(env, mk):
    a, b = mk("a@example.com"), mk("b@example.com")
    s = new_session(_uid(a))
    enqueue(s, "noop")
    s.close()
    assert len(a.get("/api/tasks").json()) == 1
    assert b.get("/api/tasks").json() == []


def test_export_contains_only_own_data(env, mk):
    a, b = mk("a@example.com"), mk("b@example.com")
    s = new_session(_uid(a))
    enqueue(s, "noop")
    s.close()
    data = b.get("/api/me/export").json()
    assert data["background_tasks"] == [] and [u["email"] for u in data["users"]] == ["b@example.com"]
    assert "password_hash" not in str(data) and "token_hash" not in str(data)
