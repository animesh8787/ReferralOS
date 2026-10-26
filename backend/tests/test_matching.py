import copy
from datetime import date, datetime, timedelta

import pytest

from app.services import contact_job as cj, jd_analysis, matching as mt, opportunity as op

TODAY = date(2026, 6, 1)
JD = """About Acme
We build developer tools.

Requirements:
- 3+ years of experience with Python
- Experience with Postgres or MySQL
- Bachelor's degree in Computer Science or equivalent experience
- Must be authorized to work in the US; we are unable to sponsor visas.

Nice to have:
- Kubernetes experience
- Familiarity with Kafka

Responsibilities:
- Build REST APIs and collaborate with cross-functional teams
- Own services end to end
"""


def reqs(a, kind=None, imp=None):
    return {(r["term"] if r["type"] == "skill" else r["type"]): r for r in a["requirements"] if (kind is None or r["type"] == kind) and (imp is None or r["importance"] == imp)}


# ---------------------------------------------------------------- JD analysis
def test_mandatory_vs_preferred_and_synonyms():
    a = jd_analysis.analyse(JD)
    assert a["description_ok"]
    mand, pref = reqs(a, "skill", "mandatory"), reqs(a, "skill", "preferred")
    assert set(mand) == {"Python", "PostgreSQL", "MySQL"} and set(pref) == {"Kubernetes", "Kafka"}  # "Postgres" -> PostgreSQL
    assert reqs(a, "experience_years")["experience_years"]["years"] == 3 and a["hints"]["min_years"] == 3
    edu = reqs(a, "education")["education"]
    assert edu["level"] == "bachelors" and edu["or_equivalent"] and edu["importance"] == "mandatory"
    assert a["hints"]["sponsorship"] == "none" and any("sponsorship" in f for f in a["disqualifier_flags"])
    assert a["responsibilities"] and a["collaboration"] and "REST APIs" in a["concepts"]


def test_every_requirement_text_is_a_span_of_the_posting():
    a = jd_analysis.analyse(JD)
    for r in a["requirements"]:
        assert r["text"] in " ".join(JD.split()) or r["text"] in JD
    assert all(k in JD or k in ("PostgreSQL", "REST APIs", "Postgres") or k.lower() in JD.lower() for k in a["keywords"])


def test_flat_paragraph_posting_uses_cues():
    text = ("We are hiring a backend engineer. You must have strong experience with Go and Docker. "
            "Experience with Terraform is a plus. You will design and ship services with the platform team. "
            "Candidates graduating in 2026 or 2027 are encouraged to apply. This role requires a security clearance.")
    a = jd_analysis.analyse(text)
    assert reqs(a, "skill", "mandatory").keys() >= {"Go", "Docker"} and "Terraform" in reqs(a, "skill", "preferred")
    assert a["hints"]["graduation_years"] == [2026, 2027] and a["hints"]["clearance"]


def test_short_or_missing_description_is_not_invented():
    for d in (None, "", "Great job, apply now!"):
        a = jd_analysis.analyse(d)
        assert a["description_ok"] is False and a["requirements"] == [] and "too short" in a["note"]


def test_mandatory_beats_preferred_when_both_mentioned():
    a = jd_analysis.analyse("Requirements:\n- Strong Python skills required\n\nNice to have:\n- Python type hints and mypy\n" + "x" * 100)
    assert reqs(a, "skill")["Python"]["importance"] == "mandatory"


# ---------------------------------------------------------------- profile + matrix
def item(i, section, data, status="active", verified=False, evidence=None, flags=None, source="resume"):
    return {"id": i, "section": section, "data": data, "status": status, "verified": verified, "evidence_level": evidence, "flags": flags or [], "source": source}


def profile_items(**o):
    items = [
        item("e1", "experience", {"title": "Backend Intern", "organization": "Acme Test Co", "start": "2024-06", "end": "2024-08",
                                  "bullets": ["Built REST APIs in Python with PostgreSQL and Docker."]}),
        item("p1", "project", {"name": "Job Tracker", "stack": ["Flask", "Redis"], "description": []}),
        item("s1", "skill", {"name": "Python"}, evidence="USED_PROFESSIONALLY"), item("s2", "skill", {"name": "Kubernetes"}, evidence="CLAIMED_ONLY"),
        item("s3", "skill", {"name": "Rust"}, evidence="CLAIMED_ONLY"),
        item("s4", "skill", {"name": "Kafka"}, status="suggested", source="github", evidence="USED_IN_PROJECT"),
        item("d1", "education", {"institution": "Example State University", "degree": "B.Tech", "end": "2026-05", "expected": True, "coursework": ["Data Structures"]}),
        item("pref", "preference", {"target_roles": ["Backend Engineer"], "locations": ["Remote", "Austin"], "work_arrangement": ["remote", "hybrid"], "graduation_date": "2026-05"}),
    ]
    return items + o.get("extra", [])


@pytest.fixture
def prof():
    return mt.summarize_profile(profile_items(), TODAY)


def test_matrix_statuses_and_honest_explanations(prof):
    a = jd_analysis.analyse(JD)
    m = {(r["term"], r["type"]): r for r in mt.build_matrix(a, prof)}
    assert m[("Python", "skill")]["status"] == "STRONG_EVIDENCE" and "e1" in m[("Python", "skill")]["fact_ids"]
    assert m[("PostgreSQL", "skill")]["status"] == "STRONG_EVIDENCE"            # via the synonym "Postgres" and experience bullet
    assert m[("MySQL", "skill")]["status"] == "PARTIAL_EVIDENCE" and "PostgreSQL" in m[("MySQL", "skill")]["explanation"]  # related, not the same
    assert m[("Kubernetes", "skill")]["status"] == "NEEDS_VERIFICATION" and "nothing in your jobs or projects" in m[("Kubernetes", "skill")]["explanation"]
    assert m[("Kafka", "skill")]["status"] == "NEEDS_VERIFICATION" and "suggest" in m[("Kafka", "skill")]["explanation"].lower()
    yrs = m[("Python", "experience_years")]
    assert yrs["status"] == "NO_EVIDENCE" and "0.2 years using Python" in yrs["explanation"] and "3+ asked" in yrs["explanation"]
    assert m[("bachelors", "education")]["status"] == "PARTIAL_EVIDENCE" and "in progress" in m[("bachelors", "education")]["explanation"]


def test_unsupported_jd_technology_never_enters_the_profile(prof):
    before = copy.deepcopy(prof)
    a = jd_analysis.analyse("Requirements:\n- Strong Rust and Terraform experience required\n- 2+ years of experience with Go\n" + "x" * 100)
    m = {r["term"]: r for r in mt.build_matrix(a, prof)}
    assert m["Terraform"]["status"] == "NO_EVIDENCE" and "not proof you lack" in m["Terraform"]["explanation"]
    assert m["Rust"]["status"] == "NEEDS_VERIFICATION"       # only CLAIMED_ONLY: never promoted to strong
    assert prof == before and "Terraform" not in prof["skills"] and "Go" not in prof["skills"]


def test_conflicting_evidence_is_surfaced():
    items = profile_items(extra=[item("s9", "skill", {"name": "Go"}, evidence="USED_PROFESSIONALLY", flags=[{"type": "conflict", "note": "x"}])])
    p = mt.summarize_profile(items, TODAY)
    m = {r["term"]: r for r in mt.build_matrix(jd_analysis.analyse("Requirements:\n- Experience with Go required\n" + "x" * 100), p)}
    assert m["Go"]["status"] == "CONFLICTING_EVIDENCE"


def test_experience_months_merge_overlaps_and_skip_bad_dates():
    items = [item("a", "experience", {"title": "A", "organization": "X", "start": "2022-01", "end": "2022-12", "bullets": []}),
             item("b", "experience", {"title": "B", "organization": "Y", "start": "2022-06", "end": "2023-05", "bullets": []}),
             item("c", "experience", {"title": "C", "organization": "Z", "start": "2024-06", "end": "2023-01", "bullets": []}, flags=[{"type": "date_order", "note": ""}]),
             item("d", "experience", {"title": "D", "organization": "W", "start": "2025-01", "end": "present", "bullets": []})]
    p = mt.summarize_profile(items, date(2025, 12, 15))
    assert p["experience_months"] == 17 + 12  # Jan22-May23 merged (overlap not double-counted) + Jan25-Dec25; the bad-date entry is ignored


# ---------------------------------------------------------------- eligibility (hard constraints, separate from the score)
def elig(jd, prof, job=None, matrix=None):
    a = jd_analysis.analyse(jd + "\n" + "x" * 120)
    m = matrix if matrix is not None else mt.build_matrix(a, prof)
    return {e["key"]: e for e in mt.eligibility(a, prof, job or {"work_arrangement": "onsite", "location": "Austin, TX"}, m)}


def test_graduation_year_rules(prof):
    assert elig("Requirements:\n- Graduating in 2027", prof)["graduation_year"]["status"] == "VIOLATED"
    assert "double-check" in elig("Requirements:\n- Graduating in 2027", prof)["graduation_year"]["reason"]
    assert elig("Requirements:\n- Graduating in 2026 or 2027", prof)["graduation_year"]["status"] == "SATISFIED"
    no_grad = mt.summarize_profile([i for i in profile_items() if i["id"] not in ("d1", "pref")], TODAY)  # scenario 7: missing data
    e = elig("Requirements:\n- Graduating in 2027", no_grad)["graduation_year"]
    assert e["status"] == "UNCERTAIN" and "Add your graduation date" in e["action"]
    assert "graduation_year" not in elig("Requirements:\n- Python", prof)  # no constraint stated -> none invented


def test_work_authorization_never_assumed(prof):
    jd = "Requirements:\n- Python\nWe are unable to sponsor visas."
    assert elig(jd, prof)["work_authorization"]["status"] == "UNCERTAIN"
    need = mt.summarize_profile(profile_items(extra=[item("pref2", "preference", {"work_authorization": "I need sponsorship"})]), TODAY)
    need["prefs"]["work_authorization"] = "I need sponsorship"
    assert elig(jd, need)["work_authorization"]["status"] == "VIOLATED"
    ok = copy.deepcopy(prof)
    ok["prefs"]["work_authorization"] = "US citizen"
    assert elig(jd, ok)["work_authorization"]["status"] == "SATISFIED"
    assert elig("Requirements:\n- Python\nMust be a U.S. citizen.", ok)["work_authorization"]["status"] == "UNCERTAIN"
    assert elig("Requirements:\n- Python\nSecurity clearance required.", prof)["security_clearance"]["status"] == "UNCERTAIN"


def test_location_rules(prof):
    f = lambda job, p=prof: elig("Requirements:\n- Python", p, job)["location"]  # noqa: E731
    assert f({"work_arrangement": "remote", "location": "Remote - US"})["status"] == "SATISFIED"
    assert f({"work_arrangement": "onsite", "location": "Austin, TX"})["status"] == "SATISFIED"
    assert f({"work_arrangement": "onsite", "location": "Berlin"})["status"] == "VIOLATED"
    assert f({"work_arrangement": "onsite", "location": None})["status"] == "UNCERTAIN"
    nop = copy.deepcopy(prof)
    nop["prefs"] = {}
    assert f({"work_arrangement": "onsite", "location": "Berlin"}, nop)["status"] == "UNCERTAIN"


def test_eligibility_never_changes_the_profile(prof):
    before = copy.deepcopy(prof)
    elig("Requirements:\n- Graduating in 2031\n- 10+ years of Python experience", prof)
    assert prof == before


# ---------------------------------------------------------------- Job Match Score
def run_match(jd, prof, job=None, cfg=None):
    a = jd_analysis.analyse(jd)
    job = job or {"title": "Backend Engineer", "work_arrangement": "remote", "location": "Remote", "employment_type": "full_time", "status": "ACTIVE_VERIFIED"}
    m = mt.build_matrix(a, prof)
    e = mt.eligibility(a, prof, job, m)
    return mt.match_score(a, m, e, prof, job, cfg), m, e


def test_match_score_range_reproducible_and_explained(prof):
    r1, _, _ = run_match(JD, prof)
    r2, _, _ = run_match(JD, copy.deepcopy(prof))
    assert r1 == r2 and 0 <= r1["total"] <= 100
    assert abs(sum(c["points"] for c in r1["components"].values()) - r1["total"]) < 0.05
    assert set(r1["components"]) == set(mt.MATCH_COMPONENTS) and all(c["explanation"] for c in r1["components"].values())
    assert r1["aligned_skills"] == ["Python", "PostgreSQL"] or set(r1["aligned_skills"]) == {"Python", "PostgreSQL"}
    assert "Kubernetes" in r1["to_verify"] and r1["missing_qualifications"]


def test_weights_move_the_score_and_policy_marks_unknown(prof):
    only_loc = {"technical_skills": 0, "required_qualifications": 0, "role_career": 0, "experience_projects": 0, "location": 1}
    only_skills = {**only_loc, "technical_skills": 1, "location": 0}
    a, _, _ = run_match(JD, prof, cfg={"weights": only_loc})
    b, _, _ = run_match(JD, prof, cfg={"weights": only_skills})
    assert a["total"] == 100.0 and b["total"] < 100
    bare = mt.summarize_profile([], TODAY)
    n, _, _ = run_match(JD, bare, cfg={"missing_policy": "neutral"})
    x, _, _ = run_match(JD, bare, cfg={"missing_policy": "exclude"})
    assert n["components"]["role_career"]["known"] is False and n["components"]["role_career"]["points"] == 7.5  # half of 15
    assert x["components"]["role_career"]["points"] == 0
    for bad in ({}, {**mt.DEFAULT_MATCH_WEIGHTS, "location": -1}, {k: 0 for k in mt.MATCH_COMPONENTS}):
        with pytest.raises(ValueError):
            mt.normalize_match_weights(bad)


def test_prioritize_verdict_respects_eligibility_and_verification(prof):
    good = "Requirements:\n- Python\n- Experience with PostgreSQL\n" + "x" * 100
    r, _, _ = run_match(good, prof)
    assert r["prioritize_applying"] in ("yes", "maybe") and r["eligibility_summary"]["VIOLATED"] == 0
    r2, _, _ = run_match(good + "\nGraduating in 2030", prof)
    assert r2["prioritize_applying"] == "no"
    unv, _, _ = run_match(good, prof, job={"title": "Backend Engineer", "work_arrangement": "remote", "location": "Remote", "employment_type": "full_time", "status": "ACTIVE_UNCONFIRMED"})
    assert unv["prioritize_applying"] == "review"


def test_role_career_penalises_unwanted_employment_type(prof):
    p = copy.deepcopy(prof)
    p["prefs"]["employment_type"] = ["internship"]
    full, _, _ = run_match(JD, p, job={"title": "Backend Engineer", "work_arrangement": "remote", "location": "Remote", "employment_type": "full_time", "status": "ACTIVE_VERIFIED"})
    intern, _, _ = run_match(JD, p, job={"title": "Backend Engineer", "work_arrangement": "remote", "location": "Remote", "employment_type": "internship", "status": "ACTIVE_VERIFIED"})
    assert full["components"]["role_career"]["value"] < intern["components"]["role_career"]["value"]


# ---------------------------------------------------------------- job-specific contact score
def ct(**o):
    base = {"role_category": "engineer", "role_position": "Senior Backend Engineer", "seniority": "senior", "domains": ["backend"], "connected_on": date(2025, 9, 1),
            "employment_status": "likely_current", "employment_verified": False, "general_confidence": 70.0, "prior_employer": False}
    return {**base, **o}


JOB = {"title": "Backend Engineer", "domains": ["backend", "platform_cloud"]}


def test_contact_score_components_and_honesty():
    r = cj.score(JOB, ct(), TODAY)
    assert 0 <= r["total"] <= 100 and set(r["components"]) == set(cj.COMPONENTS)
    assert "Not proof they still work there" in r["components"]["employment"]["explanation"] and "not referral ability" in r["components"]["seniority"]["explanation"]
    assert r["employment_label"] == "likely_current" and "does not predict" in r["note"]
    ver = cj.score(JOB, ct(employment_verified=True), TODAY)
    assert ver["employment_label"] == "verified" and ver["total"] > r["total"]
    old = cj.score(JOB, ct(employment_status="possibly_outdated"), TODAY)
    assert old["total"] < r["total"] and old["employment_label"] == "possibly_outdated"


def test_unknown_employment_is_not_treated_as_negative_or_verified():
    r = cj.score(JOB, ct(employment_status="unknown"), TODAY)
    e = r["components"]["employment"]
    assert e["known"] is False and e["points"] == 12.5 and r["employment_label"] == "unknown"
    ex = cj.score(JOB, ct(employment_status="unknown"), TODAY, {"missing_policy": "exclude"})
    assert ex["components"]["employment"]["points"] == 0


def test_recommend_is_small_and_consolidation_links_jobs():
    rows = [{"contact_id": f"c{i}", "total": 90 - i, "general_confidence": 50} for i in range(8)]
    rec = cj.recommend(rows, 3)
    assert [r["recommended"] for r in rec] == [True] * 3 + [False] * 5 and rec[0]["rank_in_job"] == 1   # never blanket-recommend
    zero = cj.recommend([{"contact_id": "z", "total": 0.0}], 3)
    assert zero[0]["recommended"] is False
    cons = cj.consolidate({"jobA": cj.recommend(rows[:4], 2), "jobB": cj.recommend(rows[1:5], 2)})
    assert cons["c1"] == ["jobA", "jobB"] and cons["c0"] == ["jobA"]


# ---------------------------------------------------------------- opportunity priority
NOW = datetime(2026, 6, 1)


def opp(match, status, elig, **o):
    kw = dict(needs_reverify=False, best_contact=70.0, hr_contacts=0, deadline=None, now=NOW)
    kw.update(o)
    return op.score(match, status, kw["needs_reverify"], kw["best_contact"], kw["hr_contacts"], kw["deadline"], kw["now"], elig)


def test_groups_and_score_components():
    ok = {"SATISFIED": 3, "UNCERTAIN": 0, "VIOLATED": 0}
    assert opp(80, "ACTIVE_VERIFIED", ok)["group"] == 0
    assert opp(80, "ACTIVE_VERIFIED", {**ok, "UNCERTAIN": 1})["group"] == 1
    assert opp(80, "ACTIVE_UNCONFIRMED", ok)["group"] == 2 and opp(80, "UNKNOWN", ok)["group"] == 2
    assert opp(80, "CLOSED", ok)["group"] == 4 and opp(80, "POSSIBLY_CLOSED", ok)["group"] == 4  # dead roles sort below ineligible-but-open ones
    assert opp(80, "ACTIVE_VERIFIED", {**ok, "VIOLATED": 1})["group"] == 3 and opp(80, "UNKNOWN", {**ok, "VIOLATED": 1})["group"] == 3
    assert opp(80, "ACTIVE_VERIFIED", ok, best_contact=None)["components"]["contacts"]["explanation"].startswith("You know nobody")
    urgent = opp(80, "ACTIVE_VERIFIED", ok, deadline=NOW + timedelta(days=5))["components"]["deadline"]["value"]
    assert urgent == 1.0 and opp(80, "ACTIVE_VERIFIED", ok, deadline=NOW - timedelta(days=1))["components"]["deadline"]["value"] == 0.0
    assert opp(80, "ACTIVE_VERIFIED", ok, needs_reverify=True)["components"]["verification"]["value"] == 0.8


def test_uncertain_high_match_does_not_outrank_verified_eligible_but_shows_tradeoff():
    ok = {"SATISFIED": 3, "UNCERTAIN": 0, "VIOLATED": 0}
    rows = [{"job_id": "sure", "title": "Verified role", "company": "A", **{k: v for k, v in (("total", opp(60, "ACTIVE_VERIFIED", ok)["total"]), ("group", 0))}},
            {"job_id": "shiny", "title": "Shiny role", "company": "B", "total": opp(99, "UNKNOWN", ok)["total"], "group": 2},
            {"job_id": "dead", "title": "Closed role", "company": "C", "total": 99.0, "group": 4}]
    ranked = {r["job_id"]: r for r in op.rank_all(rows)}
    assert [ranked[k]["rank"] for k in ("sure", "shiny", "dead")] == [1, 2, 3]
    hi = [{"job_id": "sure", "title": "Verified role", "company": "A", "total": 50.0, "group": 0}, {"job_id": "shiny", "title": "Shiny role", "company": "B", "total": 90.0, "group": 2}]
    r = {x["job_id"]: x for x in op.rank_all(hi)}
    assert r["sure"]["rank"] == 1 and r["shiny"]["score_only_rank"] == 1 and "Verified role" in r["shiny"]["trade_off"] and r["sure"]["trade_off"] is None


def test_next_action_rules():
    sat = [{"status": "SATISFIED"}]
    assert "closed" in op.next_action("CLOSED", sat, True).lower()
    assert "Re-verify" in op.next_action("POSSIBLY_CLOSED", sat, True)
    assert "ineligib" in op.next_action("ACTIVE_VERIFIED", [{"status": "VIOLATED"}], True).lower()
    assert op.next_action("ACTIVE_VERIFIED", [{"status": "UNCERTAIN", "action": "Add your graduation date in Profile > Preferences."}], True).startswith("Add your graduation date")
    assert "Verify" in op.next_action("UNKNOWN", sat, True)
    assert op.next_action("ACTIVE_VERIFIED", sat, True) == "Tailor your resume for this role."
    assert op.next_action("ACTIVE_VERIFIED", sat, True, resume_status="approved") == "Review the recommended contacts and draft outreach."
