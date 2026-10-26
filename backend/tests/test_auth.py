from app.db import new_session
from app.models.core import User
from tests.conftest import Api, last_token


def test_signup_policy_and_duplicates(env):
    a = Api()
    assert a.post("/api/auth/signup", {"email": "x@example.com", "password": "short1"}).status_code == 422
    assert a.post("/api/auth/signup", {"email": "x@example.com", "password": "alllettersnodigit"}).status_code == 422
    assert a.post("/api/auth/signup", {"email": "not-an-email", "password": "correct-horse-9"}).status_code == 422
    assert a.post("/api/auth/signup", {"email": "x@example.com", "password": "correct-horse-9"}).status_code == 201
    assert a.post("/api/auth/signup", {"email": "X@example.com", "password": "correct-horse-9"}).status_code == 409


def test_password_is_argon2id(env, mk):
    mk("a@example.com")
    db = new_session()
    h = db.query(User).one().password_hash
    db.close()
    assert h.startswith("$argon2id$")


def test_login_flow_and_logout(env, mk):
    a = mk("a@example.com")
    assert a.get("/api/auth/me").json()["email"] == "a@example.com"
    assert a.get("/api/auth/me").json()["email_verified"] is True
    assert a.post("/api/auth/logout").status_code == 200
    assert a.get("/api/auth/me").status_code == 401


def test_cookie_flags(env):
    a = Api()
    a.post("/api/auth/signup", {"email": "a@example.com", "password": "correct-horse-9"})
    r = a.post("/api/auth/login", {"email": "a@example.com", "password": "correct-horse-9"})
    sid = [h for h in r.headers.get_list("set-cookie") if h.startswith("sid=")][0].lower()
    assert "httponly" in sid and "samesite=lax" in sid


def test_csrf_required_on_unsafe_methods(env, mk):
    a = mk("a@example.com")
    r = a.c.post("/api/me/delete", json={"password": "correct-horse-9"})  # no header
    assert r.status_code == 403
    r = a.c.post("/api/me/delete", json={"password": "x"}, headers={"X-CSRF-Token": "wrong"})
    assert r.status_code == 403
    assert a.get("/api/auth/me").status_code == 200  # GET needs no csrf


def test_login_rate_limit(env, mk):
    mk("a@example.com")
    b = Api()
    codes = [b.post("/api/auth/login", {"email": "a@example.com", "password": "bad-password-1"}).status_code
             for _ in range(7)]
    # the setup login already used 1 of the 5 attempts/5min for this account
    assert codes[:4] == [401] * 4 and set(codes[4:]) == {429}


def test_wrong_password_and_unknown_user_same_error(env, mk):
    mk("a@example.com")
    b = Api()
    r1 = b.post("/api/auth/login", {"email": "a@example.com", "password": "bad-password-1"})
    r2 = b.post("/api/auth/login", {"email": "nobody@example.com", "password": "bad-password-1"})
    assert r1.status_code == r2.status_code == 401 and r1.json() == r2.json()


def test_password_reset_invalidates_sessions_and_token_single_use(env, mk):
    a = mk("a@example.com")
    b = Api()
    assert b.post("/api/auth/forgot", {"email": "a@example.com"}).status_code == 202
    assert b.post("/api/auth/forgot", {"email": "ghost@example.com"}).status_code == 202  # no enumeration
    tok = last_token(env, "a@example.com")
    assert b.post("/api/auth/reset", {"token": tok, "password": "new-password-77"}).status_code == 200
    assert b.post("/api/auth/reset", {"token": tok, "password": "another-pass-88"}).status_code == 400
    assert a.get("/api/auth/me").status_code == 401  # old session gone
    assert b.post("/api/auth/login", {"email": "a@example.com", "password": "new-password-77"}).status_code == 200


def test_verify_token_single_use_and_garbage(env):
    a = Api()
    a.post("/api/auth/signup", {"email": "a@example.com", "password": "correct-horse-9"})
    tok = last_token(env, "a@example.com")
    assert a.post("/api/auth/verify", {"token": "garbage"}).status_code == 400
    assert a.post("/api/auth/verify", {"token": tok}).status_code == 200
    assert a.post("/api/auth/verify", {"token": tok}).status_code == 400


def test_admin_endpoint_forbidden_for_users(env, mk):
    a = mk("a@example.com")
    assert a.get("/api/admin/health").status_code == 403
    db = new_session()
    db.query(User).update({"role": "admin"})
    db.commit()
    db.close()
    r = a.get("/api/admin/health")
    assert r.status_code == 200 and "users" in r.json() and "email" not in str(r.json())
