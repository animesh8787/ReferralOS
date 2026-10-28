import json
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import close_all_sessions

from app import ratelimit


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    from app.config import get_settings
    from app.db import Base, get_engine, reset_engine
    url = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{(tmp_path / 't.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TASKS_INLINE", "1")
    monkeypatch.setenv("ADAPTER_MODE", "mock")  # tests never touch the network
    monkeypatch.setenv("RESEND_API_KEY", "")
    get_settings.cache_clear()
    reset_engine()
    ratelimit.reset()
    import app.models  # noqa: F401
    close_all_sessions()  # tests open sessions they never close; on PostgreSQL an open transaction would block DROP TABLE forever
    eng = get_engine()
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    yield tmp_path
    close_all_sessions()
    reset_engine()
    get_settings.cache_clear()


class Api:
    """TestClient wrapper that adds the CSRF header like the browser app does."""

    def __init__(self):
        from app.main import app
        self.c = TestClient(app)

    def _h(self):
        t = self.c.cookies.get("csrf")
        return {"X-CSRF-Token": t} if t else {}

    def get(self, url, **kw):
        return self.c.get(url, **kw)

    def post(self, url, json=None, **kw):
        return self.c.post(url, json=json, headers=self._h(), **kw)

    def request(self, method, url, json=None):
        return self.c.request(method, url, json=json, headers=self._h())

    def put(self, url, json=None):
        return self.request("PUT", url, json)

    def patch(self, url, json=None):
        return self.request("PATCH", url, json)

    def delete(self, url):
        return self.request("DELETE", url)

    def upload(self, data, name="resume.pdf"):
        return self.c.post("/api/resumes", files={"file": (name, data, "application/octet-stream")}, headers=self._h())


def last_token(tmp_path, to):
    files = sorted((tmp_path / "outbox").glob("*.json"))
    for f in reversed(files):
        d = json.loads(f.read_text())
        if d["to"] == to:
            return d["body"].rsplit(": ", 1)[1]
    raise AssertionError("no mail")


def make_user(tmp_path, email, pw="correct-horse-9"):
    api = Api()
    assert api.post("/api/auth/signup", {"email": email, "password": pw}).status_code == 201
    assert api.post("/api/auth/verify", {"token": last_token(tmp_path, email)}).status_code == 200
    assert api.post("/api/auth/login", {"email": email, "password": pw}).status_code == 200
    return api


@pytest.fixture
def mk(env):
    return lambda email, pw="correct-horse-9": make_user(env, email, pw)
