import hashlib

import pytest

from app import storage
from tests import synth_resumes as sr


def grant(a, *names):
    for n in names:
        assert a.put(f"/api/consents/{n}", {"granted": True}).status_code == 200


def items(a, section):
    return a.get("/api/profile").json()["items"].get(section, [])


# ---------------------------------------------------------------- resume upload
def test_upload_parses_into_profile_with_provenance(env, mk):
    a = mk("a@example.com")
    r = a.upload(sr.pdf_single())
    assert r.status_code == 201 and r.json()["status"] == "parsed" and r.json()["result"]["added"] > 8
    exp = items(a, "experience")[0]
    assert exp["data"]["organization"] == "Acme Test Co" and exp["source"] == "resume" and exp["verified"] is False
    assert exp["source_ref"] == r.json()["resume_id"] and 0 < exp["confidence"] < 1
    detail = a.get(f"/api/resumes/{r.json()['resume_id']}").json()
    assert "Backend Engineering Intern" in detail["raw_text"] and detail["items"][0]["span"]  # extracted vs original view


def test_original_file_is_stored_immutably(env, mk):
    a = mk("a@example.com")
    data = sr.pdf_single()
    rid = a.upload(data).json()["resume_id"]
    assert a.get(f"/api/resumes/{rid}/file").content == data
    exp = items(a, "experience")[0]
    a.patch(f"/api/profile/items/{exp['id']}", {"data": {**exp["data"], "title": "Staff Engineer"}})
    assert a.get(f"/api/resumes/{rid}/file").content == data  # edits never touch the upload
    assert hashlib.sha256(data).hexdigest() == a.get(f"/api/resumes/{rid}").json().get("sha256", hashlib.sha256(data).hexdigest())


def test_reupload_same_resume_adds_nothing(env, mk):
    a = mk("a@example.com")
    a.upload(sr.pdf_single())
    n = {s: len(v) for s, v in a.get("/api/profile").json()["items"].items()}
    r2 = a.upload(sr.pdf_single()).json()
    assert r2["result"]["added"] == 0
    assert {s: len(v) for s, v in a.get("/api/profile").json()["items"].items()} == n


def test_changed_resume_flags_conflict_instead_of_overwriting(env, mk):
    a = mk("a@example.com")
    a.upload(sr.pdf_single())
    changed = [l.replace("Jun 2024 - Aug 2024", "Jun 2024 - Dec 2024") for l in sr.LINES]
    a.upload(sr.pdf_single(changed))
    prof = a.get("/api/profile").json()
    active = [i for i in prof["items"]["experience"] if i["status"] == "active"]
    sug = [i for i in prof["items"]["experience"] if i["status"] == "suggested"]
    assert active[0]["data"]["end"] == "2024-08"  # original untouched
    assert sug and sug[0]["flags"][0]["type"] == "conflict" and sug[0]["data"]["end"] == "2024-12"
    assert any(q["type"] == "conflict" for q in prof["questions"])


def test_image_only_pdf_is_reported_not_guessed(env, mk):
    a = mk("a@example.com")
    r = a.upload(sr.pdf_image_only()).json()
    assert r["status"] == "image_only" and "OCR" in r["result"]["warning"]
    assert a.get("/api/profile").json()["items"] == {}


@pytest.mark.parametrize("data,name,code", [(b"", "a.pdf", 422), (b"x", "a.exe", 422), (b"x" * (5 * 1024 * 1024 + 5), "a.pdf", 413)],
                         ids=["empty", "wrong-ext", "too-big"])
def test_upload_validation(env, mk, data, name, code):
    assert mk("a@example.com").upload(data, name).status_code == code


def test_corrupt_pdf_marks_resume_failed_with_reason(env, mk):
    a = mk("a@example.com")
    r = a.upload(b"%PDF-1.4 not really", "bad.pdf").json()
    assert r["status"] == "failed" and r["result"]["error"]
    assert a.get(f"/api/resumes/{r['resume_id']}").json()["parse_info"]["error"]


# ---------------------------------------------------------------- profile editing, versions, questions
def test_edit_confirm_delete_create_versions(env, mk):
    a = mk("a@example.com")
    a.upload(sr.pdf_single())
    v0 = len(a.get("/api/profile/versions").json())
    sk = next(i for i in items(a, "skill") if i["data"]["name"] == "Rust")
    assert a.patch(f"/api/profile/items/{sk['id']}", {"verified": True}).json()["verified"] is True
    new = a.post("/api/profile/items", {"section": "award", "data": {"name": "Dean's list"}}).json()
    assert new["source"] == "manual" and new["verified"] is True
    assert a.delete(f"/api/profile/items/{new['id']}").status_code == 200
    vs = a.get("/api/profile/versions").json()
    assert len(vs) == v0 + 3
    old = a.get(f"/api/profile/versions/{vs[-1]['id']}").json()  # first version is a frozen snapshot
    assert all(i["section"] != "award" for i in old["snapshot"])
    assert a.post("/api/profile/items", {"section": "bogus", "data": {}}).status_code == 422


def test_questions_ask_instead_of_fabricating(env, mk):
    a = mk("a@example.com")
    a.upload(sr.pdf_single())
    qs = a.get("/api/profile").json()["questions"]
    kinds = {q["type"] for q in qs}
    assert {"missing_metric", "unsupported_skill", "missing_section"} <= kinds
    assert any("Job Tracker" in q["text"] for q in qs if q["type"] == "missing_metric")
    assert any("Rust" in q["text"] for q in qs if q["type"] == "unsupported_skill")
    # no metric was invented anywhere
    proj = items(a, "project")[0]["data"]
    assert proj["outcomes"] == [] and not any(ch.isdigit() for ch in " ".join(proj["description"]))


def test_completeness_and_preferences(env, mk):
    a = mk("a@example.com")
    assert a.get("/api/profile").json()["completeness"]["score"] == 0
    a.upload(sr.pdf_single())
    c0 = a.get("/api/profile").json()["completeness"]
    assert "preferences" in c0["missing"]
    a.put("/api/profile/preferences", {"target_roles": ["Backend Engineer"], "graduation_date": "2026-05"})
    assert a.get("/api/profile").json()["completeness"]["score"] == c0["score"] + 10


# ---------------------------------------------------------------- GitHub / portfolio (fake servers)
def test_consent_required_before_any_fetch(env, mk):
    a = mk("a@example.com")
    assert a.post("/api/profile/github", {"username": "demo-user"}).status_code == 403
    assert a.post("/api/profile/portfolio", {"url": "https://portfolio.example.test/"}).status_code == 403
    grant(a, "github")
    assert a.post("/api/profile/github", {"username": "demo-user"}).status_code == 202
    assert a.put("/api/consents/nonsense", {"granted": True}).status_code == 404


def test_github_import_suggests_and_flags_not_original(env, mk):
    a = mk("a@example.com")
    grant(a, "github")
    r = a.post("/api/profile/github", {"username": "https://github.com/demo-user"}).json()
    assert r["result"]["repos"] == 3
    projs = {p["data"]["name"]: p for p in items(a, "project")}
    assert all(p["status"] == "suggested" and not p["verified"] and p["source"] == "github" for p in projs.values())
    assert [f["type"] for f in projs["linux-fork"]["flags"]] == ["possibly_not_original"]
    assert projs["react-tutorial-followalong"]["flags"]
    assert not projs["job-tracker"]["flags"] and {"Python", "FastAPI", "PostgreSQL"} <= set(projs["job-tracker"]["data"]["stack"])
    sk = [s for s in items(a, "skill") if s["source"] == "github"]
    assert sk and all(s["evidence_level"] == "USED_IN_PROJECT" and s["status"] == "suggested" for s in sk)
    assert "120 requests/sec" not in str(a.get("/api/profile").json()["items"]["project"][0]["data"]["description"])  # README numbers are not adopted as metrics
    # confirming makes it a real, verified fact
    conf = a.post(f"/api/profile/items/{projs['job-tracker']['id']}/confirm").json()
    assert conf["status"] == "active" and conf["verified"] is True


@pytest.mark.parametrize("user,expect", [("ghost", "not found"), ("ratelimited", "rate limit")])
def test_github_errors_are_reported_gracefully(env, mk, user, expect):
    a = mk("a@example.com")
    grant(a, "github")
    r = a.post("/api/profile/github", {"username": user}).json()
    assert r["status"] == "done" and expect in r["result"]["error"].lower()
    assert a.get("/api/profile").json()["items"] == {}


def test_github_username_validation(env, mk):
    a = mk("a@example.com")
    grant(a, "github")
    assert a.post("/api/profile/github", {"username": "../etc/passwd"}).status_code == 422


def test_portfolio_import_low_confidence_and_robots(env, mk):
    a = mk("a@example.com")
    grant(a, "portfolio")
    ok = a.post("/api/profile/portfolio", {"url": "https://portfolio.example.test/"}).json()
    assert ok["result"]["added"] >= 2
    p = [i for i in items(a, "project") if i["source"] == "portfolio"][0]
    assert p["confidence"] <= 0.4 and p["status"] == "suggested"
    assert "secret" not in str(a.get("/api/profile").json())  # <script> content is ignored
    blocked = a.post("/api/profile/portfolio", {"url": "https://portfolio.example.test/private"}).json()
    assert "robots" in blocked["result"]["error"]


@pytest.mark.parametrize("url", ["http://127.0.0.1/", "http://localhost:8000/x", "http://169.254.169.254/latest", "ftp://x.test/",
                                 "http://10.0.0.5/", "http://[::1]/", "https://user:pw@portfolio.example.test/"])
def test_ssrf_urls_are_rejected(env, mk, url):
    a = mk("a@example.com")
    grant(a, "portfolio")
    assert a.post("/api/profile/portfolio", {"url": url}).status_code == 422


def test_github_repo_without_language_or_topics_does_not_crash():
    # found by the real-service smoke check: the public API returns language=null and may omit topics
    from app.adapters import github_api
    items = github_api.to_items([{"name": "notes", "full_name": "u/notes", "html_url": "https://github.com/u/notes", "language": None,
                                  "topics": None, "description": None, "fork": False}], {"u/notes": None})
    assert [i.section for i in items] == ["project"]
