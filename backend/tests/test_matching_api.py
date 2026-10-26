import pytest

from app.adapters import fake_ats
from tests import synth_contacts as sc
from tests.test_imports import do_import

U = "https://www.linkedin.com/in/synthetic-"


@pytest.fixture(autouse=True)
def _fresh_fake_ats():
    fake_ats.reset()
    yield
    fake_ats.reset()


def build_profile(a, start="2021-01", degree_end="2020-05", grad=None, with_degree=True, locations=("Remote", "Austin")):
    P = lambda sec, d: a.post("/api/profile/items", {"section": sec, "data": d})  # noqa: E731
    P("experience", {"title": "Backend Engineer", "organization": "Initech Sample", "start": start, "end": "present",
                     "bullets": ["Built REST APIs in Python with PostgreSQL and Docker."], "metrics": []})
    if with_degree:
        P("education", {"institution": "Example State University", "degree": "B.Tech", "end": degree_end, "expected": False, "coursework": []})
    for n in ("Python", "PostgreSQL", "Docker"):
        P("skill", {"name": n, "category": "other"})
    a.put("/api/profile/preferences", {"target_roles": ["Backend Engineer"], "locations": list(locations), "graduation_date": grad})


def li(rows):
    return sc.to_csv(sc.LI_HEADER, rows, preamble="")


ACME_CONTACTS = [
    ["Alex", "Banson", U + "1", "", "Acme Test Co", "Senior Backend Engineer", "01 Jun 2026"],
    ["Sam", "Koson", U + "2", "", "Acme Test Co", "Technical Recruiter", "01 Mar 2026"],
    ["Jordan", "Renson", U + "3", "", "Acme Test Co", "Engineering Manager", "01 Feb 2026"],
    ["Taylor", "Talson", U + "4", "", "Acme Test Co", "Product Manager", "01 Feb 2026"],
    ["Quinn", "Vason", U + "5", "", "Acme Test Co", "Frontend Engineer", "01 Jan 2020"],
    ["Robin", "Mason", U + "6", "", "Acme Test Co", "Staff Engineer", ""],
]


def setup(a, contacts=ACME_CONTACTS, **profile):
    build_profile(a, **profile)
    a.post("/api/boards", {"company": "Acme Test Co", "ats": "greenhouse", "token": "acme-test"})
    if contacts:
        do_import(a, li(contacts))
    a.post("/api/jobs/discover", {})
    return {j["title"]: j for j in a.get("/api/jobs?page_size=100").json()["items"]}


def match(a, job):
    return a.get(f"/api/jobs/{job['id']}/match").json()


# ---------------------------------------------------------------- acceptance 1: open job + verified current employee
def test_scenario_verified_job_with_verified_employee_is_ranked_first(env, mk):
    a = mk("a@example.com")
    jobs = setup(a)
    be = jobs["Backend Engineer"]
    cid = [c for c in a.get("/api/contacts?q=alex").json()["items"]][0]["id"]
    assert a.post(f"/api/contacts/{cid}/verify-employment", {}).json()["employment_status"] == "verified"
    a.post("/api/scoring/recompute", {})
    assert a.post("/api/matching/run", {}).status_code == 202
    m = match(a, be)
    assert m["computed"] and m["status"] == "ACTIVE_VERIFIED" and m["outreach_eligible"] and 0 < m["match_score"] <= 100
    assert m["readiness_group"] == 0 and m["eligibility_summary"]["VIOLATED"] == 0 and m["prioritize_applying"] in ("yes", "maybe")
    first = m["contact_first"]
    assert first["name"] == "Alex Banson" and first["employment"] == "verified" and first["recommended"] and "not proof" in first["note"]
    assert len(m["best_contacts"]) <= 3
    assert m["message"]["status"] == "not_drafted" and m["next_action"] == "Tailor your resume for this role."
    assert any("Python" in w for w in m["why_pursue"])


# ---------------------------------------------------------------- acceptance 3: uncertain employment
def test_scenario_uncertain_employment_is_retained_and_never_called_verified(env, mk):
    a = mk("a@example.com")
    jobs = setup(a)
    m = match(a, jobs["Backend Engineer"])
    by = {c["name"]: c for c in m["contacts"]}
    assert by["Quinn Vason"]["employment"] == "possibly_outdated"      # connected 2020: retained, flagged, not hidden
    assert by["Robin Mason"]["employment"] == "unknown"                # no date: unknown, not negative
    assert by["Alex Banson"]["employment"] == "likely_current"         # inferred, never 'verified' without the user
    assert all(c["employment"] != "verified" for c in m["contacts"])
    assert all("not proof" in c["note"] for c in m["contacts"])
    c = by["Robin Mason"]["components"]["employment"]
    assert c["known"] is False and "unknown" in c["explanation"].lower()
    ps = a.get(f"/api/prospects/{a.get('/api/contacts?q=robin').json()['items'][0]['id']}").json()
    assert ps["confidence"] < a.get(f"/api/prospects/{a.get('/api/contacts?q=alex').json()['items'][0]['id']}").json()["confidence"]  # shown as lower confidence


def test_employment_verification_is_user_only_and_survives_rescoring(env, mk):
    a, b = mk("a@example.com"), mk("b@example.com")
    setup(a)
    cid = a.get("/api/contacts?q=alex").json()["items"][0]["id"]
    assert b.post(f"/api/contacts/{cid}/verify-employment", {}).status_code == 404
    a.post(f"/api/contacts/{cid}/verify-employment", {})
    a.post("/api/scoring/recompute", {})
    assert a.get(f"/api/contacts/{cid}").json()["employment_status"] == "verified"
    a.post(f"/api/contacts/{cid}/verify-employment", {"still_works_there": False})
    a.post("/api/scoring/recompute", {})
    assert a.get(f"/api/contacts/{cid}").json()["employment_status"] != "verified"


# ---------------------------------------------------------------- acceptance 6: several jobs, several connections, one strategy per person
def test_scenario_multiple_jobs_one_company_per_job_ranking_and_consolidation(env, mk):
    a = mk("a@example.com")
    jobs = setup(a, grad="2027-05")
    be, intern = match(a, jobs["Backend Engineer"]), match(a, jobs["Software Engineering Intern"])
    rec_be = [c["contact_id"] for c in be["best_contacts"]]
    rec_in = [c["contact_id"] for c in intern["best_contacts"]]
    assert 1 <= len(rec_be) <= 3 and 1 <= len(rec_in) <= 3
    shared = set(rec_be) & set(rec_in)
    assert shared, "the strongest people fit both roles"
    for c in be["best_contacts"]:
        if c["contact_id"] in shared:
            assert intern["job_id"] in c["also_fits_jobs"]  # one consolidated strategy, not two cold messages
    assert {c["rank_in_job"] for c in be["contacts"]} == set(range(1, len(be["contacts"]) + 1))
    assert a.put("/api/matching/config", {"contacts_per_job": 1}).status_code == 200
    a.post("/api/matching/run", {})
    assert [len(match(a, j)["best_contacts"]) for j in jobs.values() if j["company"].startswith("Acme")] == [1, 1]
    assert a.put("/api/matching/config", {"contacts_per_job": 6}).status_code == 422  # never "message everyone"


# ---------------------------------------------------------------- acceptance 7: missing eligibility data
def test_scenario_missing_graduation_year_is_uncertain_with_review_action(env, mk):
    a = mk("a@example.com")
    jobs = setup(a, grad=None, with_degree=False, locations=("Remote", "San Francisco"))  # no graduation date, no education entry
    before = a.get("/api/profile").json()["items"]
    intern = match(a, jobs["Software Engineering Intern"])
    g = [e for e in intern["eligibility"] if e["key"] == "graduation_year"][0]
    assert g["status"] == "UNCERTAIN" and "Add your graduation date" in g["action"] and "2027" in g["reason"]
    assert intern["next_action"] == g["action"] and intern["readiness_group"] == 1 and intern["prioritize_applying"] == "review"
    assert not any("graduat" in w.lower() for w in intern["why_pursue"])  # no unsupported claim
    wa = [e for e in intern["eligibility"] if e["key"] == "work_authorization"][0]
    assert wa["status"] == "UNCERTAIN"  # "no sponsorship" in the posting + nothing stated by the user
    assert a.get("/api/profile").json()["items"] == before  # the profile was not edited to satisfy anything
    opps = a.get("/api/opportunities").json()["items"]
    assert [o["title"] for o in opps][:2] == ["Backend Engineer", "Software Engineering Intern"] or opps[0]["readiness_group"] <= opps[1]["readiness_group"]


def test_wrong_graduation_year_is_violated_not_assumed(env, mk):
    a = mk("a@example.com")
    jobs = setup(a, grad="2025-05")
    intern = match(a, jobs["Software Engineering Intern"])
    g = [e for e in intern["eligibility"] if e["key"] == "graduation_year"][0]
    assert g["status"] == "VIOLATED" and intern["readiness_group"] == 3 and intern["prioritize_applying"] == "no"


# ---------------------------------------------------------------- ranking, trade-offs, closed jobs
def test_unverified_job_never_outranks_verified_eligible_job_and_shows_tradeoff(env, mk):
    a = mk("a@example.com")
    jobs = setup(a, grad="2027-05")
    r = a.post("/api/jobs/manual", {"title": "Backend Engineer", "company": "Stealth Co", "location": "Remote",
                                    "description": "Requirements:\n- Experience with Python\n- Experience with PostgreSQL\n- Experience with Docker\n" + "x" * 100})
    a.put("/api/profile/preferences", {"target_roles": ["Backend Engineer"], "locations": ["Remote"], "graduation_date": "2027-05"})
    a.post("/api/matching/run", {})
    items = a.get("/api/opportunities?page_size=50").json()["items"]
    pasted = [o for o in items if o["company"] == "Stealth Co"][0]
    assert pasted["status"] == "UNKNOWN" and pasted["readiness_group"] == 2
    ranks = {o["title"] + o["company"]: o["rank"] for o in items}
    verified = [o for o in items if o["readiness_group"] == 0]
    assert verified and all(v["rank"] < pasted["rank"] for v in verified)
    if pasted["score_only_rank"] < max(v["score_only_rank"] for v in verified):
        assert pasted["trade_off"] and "Ranked below" in pasted["trade_off"]
    assert "Verify the job" in pasted["next_action"] or "Verify" in pasted["next_action"]
    assert ranks and [o["rank"] for o in items] == list(range(1, len(items) + 1))


def test_closed_job_is_filtered_to_the_bottom_and_marked_skip(env, mk):
    a = mk("a@example.com")
    jobs = setup(a, grad="2027-05")
    fake_ats.STATE["greenhouse"]["acme-test"] = [j for j in fake_ats.STATE["greenhouse"]["acme-test"] if j["id"] != 1001]
    a.post(f"/api/jobs/{jobs['Backend Engineer']['id']}/verify", {})
    m = match(a, jobs["Backend Engineer"])
    assert m["status"] == "CLOSED" and m["readiness_group"] == 4 and "closed" in m["next_action"].lower() and not m["outreach_eligible"]
    items = a.get("/api/opportunities").json()["items"]
    assert items[-1]["job_id"] == jobs["Backend Engineer"]["id"], [(o["title"], o["status"], o["readiness_group"], o["rank"], o["priority_score"]) for o in items]
    assert a.get("/api/opportunities?group=4").json()["total"] == 1 and a.get("/api/opportunities?status=CLOSED").json()["total"] == 1


def test_missing_description_is_reported_not_invented(env, mk):
    a = mk("a@example.com")
    build_profile(a)
    a.post("/api/boards", {"company": "Globex Example", "ats": "lever", "token": "globex-test"})
    a.post("/api/jobs/discover", {})
    m = match(a, a.get("/api/jobs").json()["items"][0])
    assert m["analysis"]["description_ok"] is False and m["matrix"] == [] and "too short" in m["analysis"]["note"]
    assert m["match_components"]["technical_skills"]["known"] is False


def test_manual_job_needs_matching_run_and_profile_edits_mark_matches_stale(env, mk):
    a = mk("a@example.com")
    build_profile(a)
    j = a.post("/api/jobs/manual", {"title": "Platform Engineer", "company": "Stealth Co", "location": "Remote",
                                    "description": "Requirements:\n- Experience with Kubernetes\n- Strong Python\n" + "x" * 100}).json()
    assert a.get(f"/api/jobs/{j['id']}/match").json() == {"computed": False, "note": "Run matching to analyse this job."}
    a.post("/api/matching/run", {})
    m = match(a, j)
    assert m["computed"] and {r["term"]: r["status"] for r in m["matrix"]}["Kubernetes"] == "NO_EVIDENCE" and not m["stale"]
    a.post("/api/profile/items", {"section": "award", "data": {"name": "x"}})  # any profile change creates a new version
    assert match(a, j)["stale"] is True
    a.post("/api/matching/run", {})
    assert match(a, j)["stale"] is False


def test_matching_config_validation_and_effect(env, mk):
    a = mk("a@example.com")
    jobs = setup(a, grad="2027-05")
    assert a.put("/api/matching/config", {"match_weights": {"technical_skills": 1}}).status_code == 422
    r = a.put("/api/matching/config", {"match_weights": {"technical_skills": 0, "required_qualifications": 0, "role_career": 0, "experience_projects": 0, "location": 1}})
    assert r.json()["match_weights"]["location"] == 100
    a.post("/api/matching/run", {})
    assert match(a, jobs["Backend Engineer"])["match_score"] == 100.0  # remote job, location satisfied, nothing else counts
    assert a.get("/api/matching/config").json()["missing_policy"] in ("neutral", "exclude")


def test_matching_is_isolated_between_users(env, mk):
    a, b = mk("a@example.com"), mk("b@example.com")
    jobs = setup(a, grad="2027-05")
    jid = jobs["Backend Engineer"]["id"]
    assert b.get(f"/api/jobs/{jid}/match").status_code == 404 and b.get(f"/api/opportunities/{jid}").status_code == 404
    assert b.get("/api/opportunities").json()["total"] == 0
    assert b.post("/api/matching/run", {}).json()["result"] == {"matched": 0, "total_opportunities": 0}
    assert a.get("/api/opportunities").json()["total"] == 3 or a.get("/api/opportunities").json()["total"] == 2
