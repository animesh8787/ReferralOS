"""Firebase sign-in: the token verifier is replaced so no network is used; what is tested is our handling of the claims."""
import time

import pytest
from fastapi import HTTPException

from app.api import auth
from app.config import get_settings
from tests.conftest import Api

PID = "demo-project"


@pytest.fixture
def fb(env, monkeypatch):
    monkeypatch.setenv("FIREBASE_PROJECT_ID", PID)
    get_settings.cache_clear()
    claims = {}

    def fake(token):
        if token == "bad":
            raise ValueError("invalid")
        return {"iss": f"https://securetoken.google.com/{PID}", "auth_time": int(time.time()), **claims.get(token, {})}

    monkeypatch.setattr(auth, "_verify_firebase", fake)
    return claims


def tok(fb, key, uid="uid-1", email="a@example.com", verified=True, **extra):
    fb[key] = {"user_id": uid, "email": email, "email_verified": verified, **extra}
    return key


def test_valid_token_creates_account_and_session(fb):
    a = Api()
    r = a.post("/api/auth/firebase", {"id_token": tok(fb, "t1", name="Alex")})
    assert r.status_code == 200 and r.json()["email"] == "a@example.com" and r.json()["email_verified"] is True
    assert a.get("/api/auth/me").json()["email"] == "a@example.com"
    assert a.post("/api/auth/firebase", {"id_token": "t1"}).json()["id"] == r.json()["id"]  # same uid -> same account


def test_bad_token_is_rejected_without_detail(fb):
    r = Api().post("/api/auth/firebase", {"id_token": "bad"})
    assert r.status_code == 401 and r.json()["detail"] == "Sign-in could not be verified"


def test_unverified_email_cannot_take_over_an_existing_account(fb):
    a = Api()
    a.post("/api/auth/firebase", {"id_token": tok(fb, "owner", uid="uid-owner")})
    r = Api().post("/api/auth/firebase", {"id_token": tok(fb, "thief", uid="uid-thief", verified=False)})
    assert r.status_code == 403


def test_verified_firebase_user_links_to_an_existing_local_account(env, monkeypatch):
    local = Api()
    local.post("/api/auth/signup", {"email": "a@example.com", "password": "correct-horse-9"})
    monkeypatch.setenv("FIREBASE_PROJECT_ID", PID)
    get_settings.cache_clear()
    monkeypatch.setattr(auth, "_verify_firebase", lambda t: {"iss": f"https://securetoken.google.com/{PID}", "user_id": "u9", "email": "a@example.com", "email_verified": True})
    r = Api().post("/api/auth/firebase", {"id_token": "x"})
    assert r.status_code == 200 and r.json()["email_verified"] is True


def test_password_routes_are_off_when_firebase_is_configured(fb):
    a = Api()
    for path, body in (("/api/auth/signup", {"email": "x@example.com", "password": "correct-horse-9"}), ("/api/auth/login", {"email": "x@example.com", "password": "correct-horse-9"}),
                       ("/api/auth/forgot", {"email": "x@example.com"})):
        assert a.post(path, body).status_code == 404


def test_firebase_endpoint_is_off_without_configuration(env):
    assert Api().post("/api/auth/firebase", {"id_token": "x"}).status_code == 404


def test_deleting_the_account_needs_a_fresh_token_for_that_user(fb):
    a = Api()
    a.post("/api/auth/firebase", {"id_token": tok(fb, "t1")})
    assert a.post("/api/me/delete", {}).status_code == 403
    assert a.post("/api/me/delete", {"id_token": tok(fb, "other", uid="someone-else")}).status_code == 403
    assert a.post("/api/me/delete", {"id_token": tok(fb, "old", auth_time=int(time.time()) - 3600)}).status_code == 403
    assert a.post("/api/me/delete", {"id_token": "t1"}).status_code == 200
    assert Api().post("/api/auth/firebase", {"id_token": "t1"}).status_code == 200  # the Firebase identity itself is untouched; signing in again makes a fresh empty account
