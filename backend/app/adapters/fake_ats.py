"""Offline ATS fixtures (ADAPTER_MODE=mock and tests). Companies and jobs are invented.

Payload shapes follow the vendors' public job-board documentation as I understand it; they are hand-built, NOT
recordings from live services. STATE is mutable so tests can close jobs, remove boards or break pages.
"""
import copy
import json

import httpx

CLOSED_HTML = "<html><body><h1>Backend Engineer</h1><p>This job is no longer accepting applications.</p></body></html>"


def _default() -> dict:
    return {
        "greenhouse": {"acme-test": [
            {"id": 1001, "title": "Backend Engineer", "location": {"name": "Remote - US"}, "updated_at": "2026-05-01T00:00:00Z",
             "absolute_url": "https://boards.greenhouse.io/acme-test/jobs/1001",
             "content": "&lt;p&gt;Build APIs with Python and PostgreSQL. Requirements: 2+ years Python. Nice to have: Kubernetes.&lt;/p&gt;"},
            {"id": 1002, "title": "Software Engineering Intern", "location": {"name": "San Francisco, CA"}, "updated_at": "2026-05-02T00:00:00Z",
             "absolute_url": "https://boards.greenhouse.io/acme-test/jobs/1002", "content": "&lt;p&gt;Internship for students graduating in 2027.&lt;/p&gt;"}]},
        "lever": {"globex-test": [
            {"id": "lv-1", "text": "Platform Engineer", "categories": {"location": "Austin, TX", "commitment": "Full-time"}, "workplaceType": "hybrid",
             "descriptionPlain": "Run Kubernetes clusters on AWS.", "hostedUrl": "https://jobs.lever.co/globex-test/lv-1",
             "applyUrl": "https://jobs.lever.co/globex-test/lv-1/apply", "createdAt": 1714521600000}]},
        "ashby": {"northwind-test": [
            {"id": "ab-1", "title": "Machine Learning Engineer", "location": "Remote", "isRemote": True, "employmentType": "FullTime", "isListed": True,
             "descriptionPlain": "Train and serve models with PyTorch.", "jobUrl": "https://jobs.ashbyhq.com/northwind-test/ab-1",
             "applyUrl": "https://jobs.ashbyhq.com/northwind-test/ab-1/application", "publishedAt": "2026-04-20T00:00:00Z"}]},
        "workable": {"initech-test": [
            {"shortcode": "WK1", "title": "Data Engineer", "city": "Pune", "state": "MH", "country": "India", "telecommuting": False,
             "employment_type": "Full-time", "description": "<p>Build pipelines with Spark and Airflow.</p>", "url": "https://apply.workable.com/initech-test/j/WK1/",
             "application_url": "https://apply.workable.com/initech-test/j/WK1/apply/", "published_on": "2026-04-01"}]},
        "smartrecruiters": {"umbrella-test": [
            {"id": "sr-1", "name": "DevOps Engineer", "location": {"city": "Berlin", "country": "de", "remote": False},
             "typeOfEmployment": {"label": "Full-time"}, "ref": "https://jobs.smartrecruiters.com/umbrella-test/sr-1-devops-engineer",
             "releasedDate": "2026-04-05T00:00:00Z"}]},
        "closed_text_urls": [], "broken_urls": [], "pages": {}, "robots": {},
    }


STATE: dict = _default()


def reset() -> None:
    STATE.clear()
    STATE.update(_default())


def _j(data, status=200):
    return httpx.Response(status, content=json.dumps(data), headers={"content-type": "application/json"})


def _job_pages() -> dict[str, bool]:
    """job page url -> is the job still listed on its board"""
    pages = {}
    for token, jobs in STATE["greenhouse"].items():
        for j in jobs:
            pages[f"/{token}/jobs/{j['id']}"] = True
    for token, jobs in STATE["lever"].items():
        for j in jobs:
            pages[f"/{token}/{j['id']}"] = True
    for token, jobs in STATE["ashby"].items():
        for j in jobs:
            pages[f"/{token}/{j['id']}"] = True
    for token, jobs in STATE["workable"].items():
        for j in jobs:
            pages[f"/{token}/j/{j['shortcode']}/"] = True
    for token, jobs in STATE["smartrecruiters"].items():
        for j in jobs:
            pages[f"/{token}/{j['id']}-devops-engineer"] = True
    return pages


def handler(request: httpx.Request) -> httpx.Response | None:
    host, path, url = request.url.host, request.url.path, str(request.url).split("?")[0]
    st = STATE
    ats_hosts = ("boards-api.greenhouse.io", "boards.greenhouse.io", "api.lever.co", "jobs.lever.co", "api.ashbyhq.com", "jobs.ashbyhq.com",
                 "apply.workable.com", "api.smartrecruiters.com", "jobs.smartrecruiters.com")
    if path == "/robots.txt":
        txt = st["robots"].get(host)
        if txt:
            return httpx.Response(200, text=txt)
        return httpx.Response(404) if host in ats_hosts or host.endswith(".example.com") else None
    parts = path.strip("/").split("/")
    if host == "boards-api.greenhouse.io" and path.startswith("/v1/boards/") and path.endswith("/jobs"):
        b = st["greenhouse"].get(parts[2])
        return _j({"jobs": b}) if b is not None else _j({"error": "not found"}, 404)
    if host == "api.lever.co" and parts[:2] == ["v0", "postings"] and len(parts) == 3:
        b = st["lever"].get(parts[2])
        return _j(b) if b is not None else _j({"ok": False}, 404)
    if host == "api.ashbyhq.com" and parts[:2] == ["posting-api", "job-board"]:
        b = st["ashby"].get(parts[2])
        return _j({"jobs": b}) if b is not None else _j({}, 404)
    if host == "apply.workable.com" and parts[:4] == ["api", "v1", "widget", "accounts"]:
        b = st["workable"].get(parts[4])
        return _j({"name": parts[4], "jobs": b}) if b is not None else _j({}, 404)
    if host == "api.smartrecruiters.com" and parts[:2] == ["v1", "companies"] and parts[-1] == "postings":
        b = st["smartrecruiters"].get(parts[2])
        return _j({"totalFound": len(b), "content": b}) if b is not None else _j({}, 404)
    # job pages on ATS hosts and arbitrary pages
    if url in st["broken_urls"]:
        return httpx.Response(503)
    if url in st["pages"]:
        code, body = st["pages"][url]
        return httpx.Response(code, text=body, headers={"content-type": "text/html"})
    if host in ("boards.greenhouse.io", "jobs.lever.co", "jobs.ashbyhq.com", "apply.workable.com", "jobs.smartrecruiters.com"):
        if url in st["closed_text_urls"]:
            return httpx.Response(200, text=CLOSED_HTML, headers={"content-type": "text/html"})
        listed = path in _job_pages() or path.rstrip("/") + "/" in _job_pages()
        return httpx.Response(200, text="<html><body><h1>Job</h1><p>Apply now.</p></body></html>", headers={"content-type": "text/html"}) if listed else httpx.Response(404)
    return None


def snapshot() -> dict:
    return copy.deepcopy(STATE)
