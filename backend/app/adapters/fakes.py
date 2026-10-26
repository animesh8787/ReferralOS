"""Offline stand-ins for external services (ADAPTER_MODE=mock). All data here is invented.

Each fake is an httpx handler so the real adapter code runs unchanged against it.
"""
import json

import httpx

_REPOS = [
    {"name": "job-tracker", "full_name": "demo-user/job-tracker", "description": "Track job applications", "fork": False,
     "language": "Python", "topics": ["fastapi", "postgres"], "stargazers_count": 12, "pushed_at": "2025-05-01T00:00:00Z",
     "html_url": "https://github.com/demo-user/job-tracker", "private": False, "archived": False},
    {"name": "react-tutorial-followalong", "full_name": "demo-user/react-tutorial-followalong", "description": "Following a course",
     "fork": False, "language": "JavaScript", "topics": ["tutorial", "react"], "stargazers_count": 0,
     "pushed_at": "2024-01-01T00:00:00Z", "html_url": "https://github.com/demo-user/react-tutorial-followalong", "private": False, "archived": False},
    {"name": "linux-fork", "full_name": "demo-user/linux-fork", "description": None, "fork": True, "language": "C",
     "topics": [], "stargazers_count": 0, "pushed_at": "2023-01-01T00:00:00Z",
     "html_url": "https://github.com/demo-user/linux-fork", "private": False, "archived": False},
]
_PORTFOLIO = """<html><head><title>Alex Example - Portfolio</title><style>.x{}</style></head><body>
<h1>Alex Example</h1><p>I build backend services with Python and Docker.</p>
<a href="https://github.com/demo-user/job-tracker">Job Tracker</a> <a href="/about">About</a>
<a href="https://blog.example.test/post">Blog</a><script>var secret = 1;</script></body></html>"""


def _json(data, status=200, headers=None):
    return httpx.Response(status, content=json.dumps(data), headers={"content-type": "application/json", **(headers or {})})


def handler(request: httpx.Request) -> httpx.Response:
    host, path = request.url.host, request.url.path
    if host == "api.github.com":
        if path == "/users/ratelimited" or path.startswith("/users/ratelimited/"):
            return _json({"message": "rate limit"}, 403, {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1999999999"})
        if path == "/users/demo-user":
            return _json({"login": "demo-user", "public_repos": 3})
        if path == "/users/demo-user/repos":
            return _json(_REPOS if request.url.params.get("page", "1") == "1" else [])
        if path.startswith("/repos/demo-user/") and path.endswith("/readme"):
            return httpx.Response(200, text="# Demo\nBuilt with FastAPI and PostgreSQL. 120 requests/sec in local tests.")
        return _json({"message": "Not Found"}, 404)
    if host == "portfolio.example.test":
        if path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /private\n")
        if path in ("/", ""):
            return httpx.Response(200, text=_PORTFOLIO, headers={"content-type": "text/html"})
        return httpx.Response(200, text="<html><body>private</body></html>", headers={"content-type": "text/html"})
    return httpx.Response(404, text="not found")
