import httpx
import pytest

from app.adapters.http import FetchError, PoliteFetcher, RobotsDisallowed, UnsafeUrl, USER_AGENT, check_public_url


def fetcher(handler, **kw):
    sleeps = []
    f = PoliteFetcher(httpx.Client(transport=httpx.MockTransport(handler)), sleep=sleeps.append, **kw)
    return f, sleeps


def test_retries_5xx_then_succeeds_with_backoff():
    calls = []

    def h(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        calls.append(1)
        return httpx.Response(503) if len(calls) < 3 else httpx.Response(200, text="ok")

    f, sleeps = fetcher(h)
    assert f.get("https://site.test/p").text == "ok" and sleeps == [1, 2]


def test_429_honours_retry_after_capped():
    n = []

    def h(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        n.append(1)
        return httpx.Response(429, headers={"retry-after": "999"}) if len(n) == 1 else httpx.Response(200, text="ok")

    f, sleeps = fetcher(h)
    f.get("https://site.test/p")
    assert sleeps == [10]


def test_gives_up_after_three_attempts():
    f, _ = fetcher(lambda r: httpx.Response(404) if r.url.path == "/robots.txt" else httpx.Response(500))
    assert f.get("https://site.test/p").status_code == 500


def test_robots_disallow_and_unreachable_robots_both_block():
    f, _ = fetcher(lambda r: httpx.Response(200, text="User-agent: *\nDisallow: /") if r.url.path == "/robots.txt" else httpx.Response(200))
    with pytest.raises(RobotsDisallowed):
        f.get("https://site.test/x")
    f2, _ = fetcher(lambda r: httpx.Response(500) if r.url.path == "/robots.txt" else httpx.Response(200))
    with pytest.raises(RobotsDisallowed):
        f2.get("https://site.test/x")


def test_missing_robots_allows_and_user_agent_is_honest():
    seen = {}

    def h(req):
        if req.url.path != "/robots.txt":
            seen["ua"] = req.headers["user-agent"]
        return httpx.Response(404 if req.url.path == "/robots.txt" else 200, text="ok")

    f = PoliteFetcher(httpx.Client(transport=httpx.MockTransport(h), headers={"User-Agent": USER_AGENT}))
    f.get("https://site.test/x")
    assert seen["ua"].startswith("ReferralOS/")


def test_redirect_to_private_address_is_blocked():
    def h(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data"})

    f, _ = fetcher(h)
    with pytest.raises(UnsafeUrl):
        f.get("https://site.test/x")


def test_dns_resolving_to_private_ip_is_blocked():
    with pytest.raises(UnsafeUrl):
        check_public_url("https://innocent.test/", resolver=lambda h: ["10.1.2.3"])
    assert check_public_url("https://innocent.test/", resolver=lambda h: ["93.184.216.34"])


def test_oversized_response_and_redirect_loop():
    f, _ = fetcher(lambda r: httpx.Response(404) if r.url.path == "/robots.txt" else httpx.Response(200, content=b"x" * (3 * 1024 * 1024)))
    with pytest.raises(FetchError):
        f.get("https://site.test/big")
    f2, _ = fetcher(lambda r: httpx.Response(404) if r.url.path == "/robots.txt" else httpx.Response(302, headers={"location": "/again"}))
    with pytest.raises(FetchError):
        f2.get("https://site.test/loop")


def test_responses_are_cached():
    n = []

    def h(req):
        if req.url.path != "/robots.txt":
            n.append(1)
        return httpx.Response(404 if req.url.path == "/robots.txt" else 200, text="ok")

    f, _ = fetcher(h)
    f.get("https://site.test/a")
    f.get("https://site.test/a")
    assert len(n) == 1


def test_worker_registers_every_task_kind():
    """The worker process imports only app.handlers; every enqueue()d kind must be registered through it."""
    import re
    import subprocess
    import sys
    code = "import app.handlers, app.tasks as t; print(sorted(t.HANDLERS))"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout
    from pathlib import Path
    used = set()
    for p in Path("app").rglob("*.py"):
        used |= set(re.findall(r'enqueue(?:_nowait)?\(\w+, "(\w+)"', p.read_text(encoding="utf-8")))
    missing = [k for k in used if f"'{k}'" not in out]
    assert not missing, missing
