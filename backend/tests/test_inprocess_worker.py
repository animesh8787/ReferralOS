import threading
import time

from fastapi.testclient import TestClient

from app.config import get_settings


def test_worker_thread_runs_tasks_when_enabled(env, monkeypatch):
    monkeypatch.setenv("RUN_WORKER", "1")
    monkeypatch.setenv("TASKS_INLINE", "0")
    get_settings.cache_clear()
    from app.main import app
    from tests.conftest import last_token  # noqa: F401
    with TestClient(app) as c:
        assert any(t.name == "task-worker" for t in threading.enumerate())
        time.sleep(0.2)
    time.sleep(1.5)  # the loop polls every second, then sees the stop flag
    assert not any(t.name == "task-worker" and t.is_alive() for t in threading.enumerate())


def test_no_worker_thread_by_default(env):
    from app.main import app
    with TestClient(app):
        assert not any(t.name == "task-worker" for t in threading.enumerate())
