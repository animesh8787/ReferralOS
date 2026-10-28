import io
import zipfile

import docx
import fitz
import pytest

from app import storage
from app.adapters import fake_ats
from app.db import new_session
from app.models.tailoring import TailoredResume
from tests import synth_contacts as sc
from tests.test_imports import do_import

FILES = {"resume.pdf", "resume.docx", "resume.txt", "requirement_matrix.json", "validation_report.json", "tailoring_summary.md", "diff.json"}


@pytest.fixture(autouse=True)
def _fresh_fake_ats():
    fake_ats.reset()
    yield
    fake_ats.reset()


def profile(a):
    P = lambda sec, d: a.post("/api/profile/items", {"section": sec, "data": d}).json()  # noqa: E731
    ids = {}
    ids["per"] = P("personal", {"name": "Alex Example", "email": "alex.example@example.com", "phone": "+1 415 555 0134", "links": ["github.com/alex-example"]})["id"]
    ids["exp"] = P("experience", {"title": "Backend Engineer", "organization": "Initech Sample", "start": "2021-01", "end": "present",
                                  "bullets": ["Built REST APIs in Python backed by PostgreSQL for an internal tools service.", "Wrote pytest suites and Docker based CI checks."], "metrics": []})["id"]
    ids["proj"] = P("project", {"name": "Job Tracker", "stack": ["Flask", "Redis", "Docker"], "repo_url": "https://github.com/alex-example/job-tracker", "demo_url": None,
                                "description": ["Built a Flask and Redis service that tracks job applications."], "outcomes": []})["id"]
    ids["edu"] = P("education", {"institution": "Example State University", "degree": "B.Tech", "end": "2020-05", "expected": False, "coursework": []})["id"]
    for n in ("Python", "PostgreSQL", "Docker"):
        P("skill", {"name": n, "category": "other"})
    a.put("/api/profile/preferences", {"target_roles": ["Backend Engineer"], "locations": ["Remote"], "graduation_date": None})
    return ids


def setup(a):
    ids = profile(a)
    a.post("/api/boards", {"company": "Acme Test Co", "ats": "greenhouse", "token": "acme-test"})
    a.post("/api/jobs/discover", {})
    jobs = {j["title"]: j for j in a.get("/api/jobs?page_size=50").json()["items"]}
    return ids, jobs


def tailor(a, job, **o):
    r = a.post("/api/tailoring", {"job_id": job["id"], **o})
    assert r.status_code == 201, r.text
    return r.json()


def master(a):
    return a.get("/api/profile").json()["items"], len(a.get("/api/profile/versions").json())


def test_create_produces_validated_versioned_bundle_and_never_touches_the_master(env, mk):
    a = mk("a@example.com")
    _, jobs = setup(a)
    before = master(a)
    r = tailor(a, jobs["Backend Engineer"])
    assert r["version"] == 1 and r["status"] == "draft" and set(r["files"]) == FILES
    assert r["validation"]["ok_to_approve"] and r["validation"]["render_check"]["ok"] and r["validation"]["claims_total"] == r["validation"]["validated"] > 5
    assert 0 < r["score"] <= 100 and "not an ATS score" in r["score_detail"]["label"]
    assert r["changes"]["master_unchanged"] is True and r["changes"]["unsupported_requirements"]
    assert master(a) == before  # items, versions: identical
    r2 = tailor(a, jobs["Backend Engineer"])
    assert r2["version"] == 2 and master(a) == before
    assert [v["version"] for v in a.get(f"/api/tailoring?job_id={jobs['Backend Engineer']['id']}").json()] == [2, 1]


def test_downloads_open_and_contain_the_resume(env, mk):
    a = mk("a@example.com")
    _, jobs = setup(a)
    r = tailor(a, jobs["Backend Engineer"])
    pdf = a.get(f"/api/tailoring/{r['id']}/files/resume.pdf")
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf"
    assert "Alex Example" in fitz.open(stream=pdf.content, filetype="pdf")[0].get_text()
    d = docx.Document(io.BytesIO(a.get(f"/api/tailoring/{r['id']}/files/resume.docx").content))
    assert any("Alex Example" in p.text for p in d.paragraphs)
    assert "BACKEND" not in a.get(f"/api/tailoring/{r['id']}/files/resume.txt").text and "Alex Example" in a.get(f"/api/tailoring/{r['id']}/files/resume.txt").text
    assert a.get(f"/api/tailoring/{r['id']}/files/validation_report.json").json()["ledger"]
    z = zipfile.ZipFile(io.BytesIO(a.get(f"/api/tailoring/{r['id']}/bundle.zip").content))
    assert set(z.namelist()) == FILES
    for bad in ("..%2f..%2fdata%2f.kek", "passwd", "resume.exe", "../resume.pdf"):
        assert a.get(f"/api/tailoring/{r['id']}/files/{bad}").status_code == 404


def test_validation_of_requests(env, mk):
    a = mk("a@example.com")
    _, jobs = setup(a)
    jid = jobs["Backend Engineer"]["id"]
    assert a.post("/api/tailoring", {"job_id": "0" * 32}).status_code == 404
    assert a.post("/api/tailoring", {"job_id": jid, "max_projects": 9}).status_code == 422
    assert a.post("/api/tailoring", {"job_id": jid, "max_bullets": 0}).status_code == 422
    assert a.post("/api/tailoring", {"job_id": jid, "section_order": ["summary"]}).status_code == 422
    fake_ats.STATE["greenhouse"]["acme-test"] = [j for j in fake_ats.STATE["greenhouse"]["acme-test"] if j["id"] != 1001]
    a.post(f"/api/jobs/{jid}/verify", {})
    assert a.post("/api/tailoring", {"job_id": jid}).status_code == 409  # closed job: nothing to tailor for


def test_edits_create_new_versions_and_approved_versions_are_immutable(env, mk):
    a = mk("a@example.com")
    _, jobs = setup(a)
    v1 = tailor(a, jobs["Backend Engineer"])
    assert a.post(f"/api/tailoring/{v1['id']}/approve", {}).json()["status"] == "approved"
    snapshot = a.get(f"/api/tailoring/{v1['id']}").json()
    claim = [c for c in v1["ledger"] if c["kind"] == "bullet"][0]
    v2 = a.patch(f"/api/tailoring/{v1['id']}", {"exclude_claims": [claim["id"]]}).json()
    assert v2["version"] == 2 and v2["parent_id"] == v1["id"] and v2["status"] == "draft"
    assert claim["text"] not in str(v2["content"]) and a.get(f"/api/tailoring/{v1['id']}").json() == snapshot  # approved v1 is byte-for-byte unchanged
    v3 = a.patch(f"/api/tailoring/{v2['id']}", {"bullet_edits": [{"claim_id": [c for c in v2["ledger"] if c["kind"] == "bullet" and c["id"] != claim["id"]][0]["id"], "text": "Built internal REST APIs in Python backed by PostgreSQL."}]}).json()
    still = [c for c in v3["ledger"] if c["id"] == claim["id"]][0]
    assert still["status"] == "excluded" and claim["text"] not in str(v3["content"])  # a removed claim never silently comes back
    assert a.patch(f"/api/tailoring/{v1['id']}", {"exclude_claims": ["nope"]}).status_code == 422


def test_edit_that_adds_unsupported_text_blocks_approval_until_explicitly_confirmed(env, mk):
    a = mk("a@example.com")
    _, jobs = setup(a)
    v1 = tailor(a, jobs["Backend Engineer"])
    bullet = [c for c in v1["ledger"] if c["kind"] == "bullet" and c["section"] == "experience"][0]
    v2 = a.patch(f"/api/tailoring/{v1['id']}", {"bullet_edits": [{"claim_id": bullet["id"], "text": "Built REST APIs in Python on Kubernetes serving 5000 users."}]}).json()
    c = [x for x in v2["ledger"] if x["id"] == bullet["id"]][0]
    assert c["status"] == "needs_confirmation" and "Kubernetes" in c["reasons"][0] and "5000" in c["reasons"][1]
    assert not v2["validation"]["ok_to_approve"] and v2["needs_confirmation"] == 1
    r = a.post(f"/api/tailoring/{v2['id']}/approve", {})
    assert r.status_code == 409 and "need your confirmation" in r.json()["detail"]
    items_before, versions_before = master(a)
    assert "Kubernetes" not in str(items_before)  # the master was NOT changed by merely editing the resume
    v3 = a.post(f"/api/tailoring/{v2['id']}/confirm-claim", {"claim_id": bullet["id"]}).json()  # the user explicitly says: this is true
    assert v3["validation"]["ok_to_approve"] and v3["version"] == 3
    items_after, versions_after = master(a)
    assert "Kubernetes serving 5000 users" in str(items_after) and versions_after == versions_before + 1
    assert a.post(f"/api/tailoring/{v3['id']}/approve", {}).status_code == 200
    assert a.post(f"/api/tailoring/{v1['id']}/confirm-claim", {"claim_id": bullet["id"]}).status_code == 422  # nothing to confirm on a clean claim


def test_regenerate_compare_and_options(env, mk):
    a = mk("a@example.com")
    ids, jobs = setup(a)
    v1 = tailor(a, jobs["Backend Engineer"])
    assert [p["name"] for p in v1["content"]["projects"]] == ["Job Tracker"]
    v2 = a.post(f"/api/tailoring/{v1['id']}/regenerate", {"excluded_item_ids": [ids["proj"]], "section_order": ["summary", "skills", "projects", "experience", "education", "certifications", "awards"]}).json()
    assert v2["content"]["projects"] == [] and v2["content"]["section_order"][2] == "projects" and v2["parent_id"] == v1["id"]
    assert a.post(f"/api/tailoring/{v1['id']}/regenerate", {"section_order": ["x"]}).status_code == 422
    cmp = a.get(f"/api/tailoring/{v1['id']}/compare/{v2['id']}").json()
    assert "Job Tracker" in cmp["text_diff"] and isinstance(cmp["score_delta"], float)


def test_approved_resume_is_linked_to_the_job_and_updates_the_opportunity(env, mk):
    a = mk("a@example.com")
    _, jobs = setup(a)
    jid = jobs["Backend Engineer"]["id"]
    assert a.get(f"/api/jobs/{jid}/resume").json()["status"] == "not_started"
    a.post("/api/matching/run", {})
    assert a.get(f"/api/opportunities/{jid}").json()["next_action"] == "Tailor your resume for this role."
    v1 = tailor(a, jobs["Backend Engineer"])
    a.post("/api/matching/run", {})
    assert a.get(f"/api/jobs/{jid}/resume").json()["status"] == "draft" and a.get(f"/api/opportunities/{jid}").json()["next_action"] == "Review and approve your tailored resume."
    a.post(f"/api/tailoring/{v1['id']}/approve", {})
    a.post("/api/matching/run", {})
    link = a.get(f"/api/jobs/{jid}/resume").json()
    assert link["status"] == "approved" and link["approved"]["id"] == v1["id"]
    card = a.get(f"/api/opportunities/{jid}").json()
    assert card["resume"]["status"] == "approved" and "Tailor" not in card["next_action"]


def test_scenario_master_untouched_after_tailoring_several_jobs_and_unsupported_tech_never_appears(env, mk):
    a = mk("a@example.com")
    _, jobs = setup(a)
    manual = a.post("/api/jobs/manual", {"title": "Infra Engineer", "company": "Stealth Co", "location": "Remote",
                                         "description": "Requirements:\n- Strong Terraform experience required\n- Experience with Python\n- Experience with Go\n" + "x" * 100}).json()
    before = master(a)
    out = [tailor(a, j) for j in (jobs["Backend Engineer"], jobs["Software Engineering Intern"], manual)]
    assert master(a) == before
    infra = out[2]
    blob = str(infra["content"]) + storage.get_bundle(a.get("/api/auth/me").json()["id"], infra["id"], "resume.txt").decode("utf-8")
    assert "Terraform" not in blob and "Go" not in [i["name"] for g in infra["content"]["skills"] for i in g["items"]]
    tips = {t["term"]: t["type"] for t in infra["score_detail"]["improvements"] if t["term"]}
    assert tips["Terraform"] == "no_support" and tips["Go"] == "no_support"
    assert any(q["type"] == "missing_metric" and "Do you have a number" in q["text"] for q in infra["questions"])  # prompts, not invented numbers
    assert len({o["id"] for o in out}) == 3
    assert out[0]["content"]["section_order"] != out[1]["content"]["section_order"]  # the internship gets an early-career layout; nothing leaks between jobs
    snap = a.get(f"/api/tailoring/{out[0]['id']}").json()
    a.post(f"/api/tailoring/{out[0]['id']}/approve", {})
    a.post(f"/api/tailoring/{out[0]['id']}/regenerate", {"max_projects": 0})
    after = a.get(f"/api/tailoring/{out[0]['id']}").json()
    assert after["content"] == snap["content"] and after["ledger"] == snap["ledger"] and after["status"] == "approved"


def test_empty_profile_cannot_produce_an_approvable_resume(env, mk):
    a = mk("a@example.com")
    a.post("/api/boards", {"company": "Acme Test Co", "ats": "greenhouse", "token": "acme-test"})
    a.post("/api/jobs/discover", {})
    job = a.get("/api/jobs").json()["items"][0]
    r = tailor(a, job)
    assert r["content"]["summary"] is None and r["content"]["experience"] == []
    assert a.post(f"/api/tailoring/{r['id']}/approve", {}).status_code == 409  # render check fails: there is nothing to render


def test_tailoring_is_isolated_between_users(env, mk):
    a, b = mk("a@example.com"), mk("b@example.com")
    _, jobs = setup(a)
    v1 = tailor(a, jobs["Backend Engineer"])
    v2 = tailor(a, jobs["Backend Engineer"])
    tid, jid = v1["id"], jobs["Backend Engineer"]["id"]
    for call in (b.get(f"/api/tailoring/{tid}"), b.get(f"/api/tailoring/{tid}/files/resume.pdf"), b.get(f"/api/tailoring/{tid}/bundle.zip"),
                 b.post(f"/api/tailoring/{tid}/approve", {}), b.patch(f"/api/tailoring/{tid}", {}), b.get(f"/api/tailoring/{tid}/compare/{v2['id']}"),
                 b.post(f"/api/tailoring/{tid}/regenerate", {}), b.post(f"/api/tailoring/{tid}/confirm-claim", {"claim_id": "c001"}),
                 b.get(f"/api/tailoring?job_id={jid}"), b.post("/api/tailoring", {"job_id": jid}), b.get(f"/api/jobs/{jid}/resume")):
        assert call.status_code == 404, call.request.url
    assert new_session().query(TailoredResume).count() == 2


def test_deleting_the_account_removes_generated_files_and_rows(env, mk):
    a = mk("a@example.com")
    _, jobs = setup(a)
    r = tailor(a, jobs["Backend Engineer"])
    uid = a.get("/api/auth/me").json()["id"]
    assert storage.get_bundle(uid, r["id"], "resume.pdf")
    assert a.post("/api/me/delete", {"password": "correct-horse-9"}).status_code == 200
    with pytest.raises(FileNotFoundError):
        storage.get_bundle(uid, r["id"], "resume.pdf")
    assert new_session().query(TailoredResume).count() == 0
