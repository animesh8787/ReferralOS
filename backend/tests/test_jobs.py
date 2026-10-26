from datetime import datetime, timedelta

import httpx
import pytest

from app.adapters import ats, fake_ats
from app.adapters.http import PoliteFetcher
from app.db import new_session
from app.models.contacts import Company
from app.models.jobs import Job, JobSource, JobVerification
from app.services import jobs_store, job_verify as jv, referral_route
from app.services.job_verify import Ev, decide

NOW = datetime(2026, 6, 10, 12, 0)
D = lambda days: NOW - timedelta(days=days)  # noqa: E731


@pytest.fixture(autouse=True)
def _fresh_fake_ats():
    fake_ats.reset()
    yield
    fake_ats.reset()


# ---------------------------------------------------------------- state machine (all five statuses + the 5.3 rules)
@pytest.mark.parametrize("evidence,deadline,expected", [
    ([Ev("api_listed", D(0))], None, "ACTIVE_VERIFIED"),
    ([Ev("api_listed", D(2)), Ev("page_ok", D(0))], None, "ACTIVE_VERIFIED"),
    ([Ev("api_listed", D(4))], None, "ACTIVE_UNCONFIRMED"),                       # stale evidence needs re-verification
    ([Ev("page_ok", D(0))], None, "ACTIVE_UNCONFIRMED"),                          # HTTP 200 alone is not proof
    ([Ev("jsonld_valid", D(0))], None, "ACTIVE_UNCONFIRMED"),
    ([], None, "UNKNOWN"),
    ([Ev("inaccessible", D(0))], None, "UNKNOWN"),                                # inaccessible never means closed
    ([Ev("api_listed", D(5)), Ev("inaccessible", D(0))], None, "ACTIVE_UNCONFIRMED"),
    ([Ev("page_gone", D(0))], None, "POSSIBLY_CLOSED"),                           # 404 alone is not enough
    ([Ev("api_absent", D(0))], None, "POSSIBLY_CLOSED"),                          # absence alone is not enough
    ([Ev("page_closed_text", D(0))], None, "POSSIBLY_CLOSED"),
    ([Ev("page_gone", D(0)), Ev("api_absent", D(0))], None, "CLOSED"),
    ([Ev("page_closed_text", D(1)), Ev("api_absent", D(0))], None, "CLOSED"),
    ([Ev("page_gone", D(4)), Ev("api_absent", D(0))], None, "POSSIBLY_CLOSED"),   # closed evidence went stale
    ([Ev("api_listed", D(5)), Ev("page_gone", D(0)), Ev("api_absent", D(0))], None, "CLOSED"),
    ([Ev("page_gone", D(2)), Ev("api_absent", D(2)), Ev("api_listed", D(0))], None, "ACTIVE_VERIFIED"),  # re-opened
    ([Ev("api_listed", D(2)), Ev("api_absent", D(1))], None, "POSSIBLY_CLOSED"),
    ([Ev("api_listed", D(0)), Ev("page_closed_text", D(0))], None, "POSSIBLY_CLOSED"),  # contradictory same-time evidence: be conservative
    ([Ev("api_listed", D(0))], D(1), "ACTIVE_UNCONFIRMED"),                       # deadline passed but still listed
    ([Ev("page_ok", D(0))], D(1), "POSSIBLY_CLOSED"),                              # loading page + passed deadline: not proof of open
    ([], D(1), "POSSIBLY_CLOSED"),
    ([Ev("api_listed", D(0))], NOW + timedelta(days=9), "ACTIVE_VERIFIED"),
])
def test_decide(evidence, deadline, expected):
    status, reasons = decide(evidence, NOW, deadline)
    assert status == expected and reasons and all(isinstance(r, str) for r in reasons)


def test_decide_never_returns_verified_without_api_listing():
    import itertools
    kinds = ["api_absent", "page_gone", "page_closed_text", "page_ok", "jsonld_valid", "inaccessible"]
    for n in range(0, 4):
        for combo in itertools.combinations(kinds, n):
            assert decide([Ev(k, D(0)) for k in combo], NOW)[0] != "ACTIVE_VERIFIED"


# ---------------------------------------------------------------- adapters (hand-built fixtures, not live services)
def fetcher():
    from app.adapters import fakes
    return PoliteFetcher(httpx.Client(transport=httpx.MockTransport(fakes.handler)), respect_robots=False)


@pytest.mark.parametrize("kind,token,title,loc,emp,remote", [
    ("greenhouse", "acme-test", "Backend Engineer", "Remote - US", None, None),
    ("lever", "globex-test", "Platform Engineer", "Austin, TX", "Full-time", None),
    ("ashby", "northwind-test", "Machine Learning Engineer", "Remote", "FullTime", True),
    ("workable", "initech-test", "Data Engineer", "Pune, MH, India", "Full-time", False),
    ("smartrecruiters", "umbrella-test", "DevOps Engineer", "Berlin, de", "Full-time", False),
])
def test_each_adapter_maps_to_rawjob(kind, token, title, loc, emp, remote):
    jobs = ats.list_jobs(fetcher(), kind, token)
    j = jobs[0]
    assert (j.source_type, j.board_token, j.title, j.location, j.employment_type) == (kind, token, title, loc, emp)
    assert j.remote == remote and j.source_job_id and j.apply_url


def test_html_description_is_cleaned_and_unknown_board_is_reported():
    gh = ats.list_jobs(fetcher(), "greenhouse", "acme-test")[0]
    assert "<" not in gh.description and "Python and PostgreSQL" in gh.description
    with pytest.raises(ats.BoardNotFound):
        ats.list_jobs(fetcher(), "lever", "no-such-board")
    for bad in ("../x", "a b", "", "x" * 80, "a/b"):
        with pytest.raises(ats.AtsError):
            ats.list_jobs(fetcher(), "greenhouse", bad)
    with pytest.raises(ats.AtsError):
        ats.list_jobs(fetcher(), "taleo", "x")


def test_board_url_recognition():
    assert ats.board_from_url("https://boards.greenhouse.io/acme-test") == ("greenhouse", "acme-test")
    assert ats.board_from_url("https://jobs.lever.co/globex-test/abc") == ("lever", "globex-test")
    assert ats.board_from_url("https://example.com/careers") is None


def test_jsonld_variants():
    page = ('<script type="application/ld+json">{"@context":"https://schema.org","@graph":[{"@type":"JobPosting","title":"SRE",'
            '"hiringOrganization":{"name":"Acme Test Co"},"jobLocation":{"address":{"addressLocality":"Austin","addressRegion":"TX"}},'
            '"validThrough":"2026-01-01T00:00:00Z","employmentType":"FULL_TIME","description":"&lt;p&gt;Run things&lt;/p&gt;"}]}</script>'
            '<script type="application/ld+json">{not json</script>')
    j = ats.parse_jsonld(page, "https://x.example.com/j")[0]
    assert (j.title, j.company_name, j.location, j.deadline) == ("SRE", "Acme Test Co", "Austin, TX", "2026-01-01T00:00:00Z") and j.description == "Run things"
    assert ats.parse_jsonld("<html>nothing</html>", "https://x") == []


# ---------------------------------------------------------------- canonical dedup
def mkco(db, name="Acme Test Co"):
    from app.services.companies import CompanyResolver
    cid = CompanyResolver(db).resolve(name)
    db.commit()
    return cid


def raw(**o):
    d = dict(source_type="greenhouse", board_token="acme-test", source_job_id="1", title="Backend Engineer", location="Remote - US",
             apply_url="https://boards.greenhouse.io/acme-test/jobs/1", source_url="https://boards.greenhouse.io/acme-test/jobs/1")
    return ats.RawJob(**{**d, **o})


def test_dedup_rules(env):
    db = new_session()
    cid = mkco(db)
    j1, how = jobs_store.upsert_job(db, raw(), cid)
    assert how == "new"
    assert jobs_store.upsert_job(db, raw(title="Backend Engineer v2"), cid) == (j1, "same_source")                          # same source id
    j2, how = jobs_store.upsert_job(db, raw(source_type="jsonld", board_token="", source_job_id="x", location=None), cid)
    assert (j2.id, how) == (j1.id, "same_url")                                                                             # same apply URL
    j3, how = jobs_store.upsert_job(db, raw(source_type="lever", board_token="acme", source_job_id="L1", apply_url="https://jobs.lever.co/acme/L1",
                                            source_url=None, title="Backend Engineer (Remote)", location="Remote"), cid)
    assert (j3.id, how) == (j1.id, "merged")                                                                               # similar title + same place
    j4, how = jobs_store.upsert_job(db, raw(source_job_id="2", apply_url="https://boards.greenhouse.io/acme-test/jobs/2", location="Berlin"), cid)
    assert how == "new" and j4.id != j1.id                                                                                 # other city: separate
    j5, how = jobs_store.upsert_job(db, raw(source_job_id="3", apply_url="https://boards.greenhouse.io/acme-test/jobs/3", title="Frontend Engineer"), cid)
    assert how == "new"
    j6, how = jobs_store.upsert_job(db, raw(source_job_id="9", apply_url="https://boards.greenhouse.io/other/jobs/9"), mkco(db, "Globex Example"))
    assert how == "new"                                                                                                    # other company: never merged
    assert db.query(JobSource).filter(JobSource.job_id == j1.id).count() == 3
    priv, how = jobs_store.upsert_job(db, raw(source_type="manual", board_token="", source_job_id="p", apply_url=None, source_url=None), cid, owner="u" * 32)
    assert how == "new" and priv.id != j1.id and priv.owner_user_id == "u" * 32                                           # private copy stays separate


# ---------------------------------------------------------------- API flows
BOARDS = [("Acme Test Co", "greenhouse", "acme-test"), ("Globex Example", "lever", "globex-test"), ("Northwind Labs", "ashby", "northwind-test"),
          ("Initech Sample", "workable", "initech-test"), ("Umbrella Demo", "smartrecruiters", "umbrella-test")]


def add_boards(a, boards=BOARDS):
    return [a.post("/api/boards", {"company": c, "ats": t, "token": k}) for c, t, k in boards]


def jobs(a, qs=""):
    return a.get(f"/api/jobs?page_size=100{qs}").json()


def discover(a):
    return a.post("/api/jobs/discover", {}).json()


def test_boards_validation_and_suggestions(env, mk):
    a = mk("a@example.com")
    assert all(r.status_code == 201 for r in add_boards(a))
    assert a.post("/api/boards", {"company": "Acme Test Co", "ats": "greenhouse", "token": "acme-test"}).status_code == 409
    assert a.post("/api/boards", {"company": "X", "board_url": "https://jobs.lever.co/zzz"}).status_code == 201
    assert a.post("/api/boards", {"company": "X", "board_url": "https://example.com/careers"}).status_code == 422
    assert a.post("/api/boards", {"company": "X", "ats": "greenhouse", "token": "../etc"}).status_code == 422
    assert a.post("/api/boards", {"company": "X", "ats": "taleo", "token": "x"}).status_code == 422
    s = a.post("/api/boards/suggest", {"company": "Acme Test Co Inc"}).json()
    assert [c["ats"] for c in s["candidates"]] == [] or s["candidates"][0]["sample"] is not None  # slug 'acme-test' is derived from the name
    s = a.post("/api/boards/suggest", {"company": "Acme Test"}).json()
    assert s["candidates"][0]["token"] == "acme-test" and "Backend Engineer" in s["candidates"][0]["sample"] and "check that it is the right company" in s["candidates"][0]["basis"]
    assert len(a.get("/api/boards").json()) == 6


def test_discovery_verifies_and_reports_coverage_honestly(env, mk):
    a = mk("a@example.com")
    add_boards(a)
    a.post("/api/boards", {"company": "Ghost Corp", "ats": "greenhouse", "token": "ghost-board"})  # board that does not exist
    a.post("/api/contacts", {"first_name": "Pat", "company": "Ghost Corp"})
    a.post("/api/contacts", {"first_name": "Lee", "company": "Acme Test Co"})
    r = discover(a)["result"]
    assert (r["boards"], r["reachable"], r["jobs_seen"], r["new_jobs"]) == (6, 5, 6, 6)
    assert r["contact_companies"] == 2 and r["contact_companies_without_reachable_board"] == 1
    run = a.get("/api/jobs/discovery-runs").json()[0]
    ghost = [c for c in run["coverage"] if c["token"] == "ghost-board"][0]
    assert ghost["reachable"] is False and "not found" in ghost["error"].lower()
    items = jobs(a)["items"]
    assert len(items) == 6 and {j["status"] for j in items} == {"ACTIVE_VERIFIED"} and all(j["outreach_eligible"] for j in items)
    d = a.get(f"/api/jobs/{items[0]['id']}").json()
    assert d["verification_evidence"][0]["kind"] == "api_listed" and d["verification_evidence"][0]["checked_at"] and d["status_reasons"]
    intern = [j for j in items if j["title"] == "Software Engineering Intern"][0]
    assert intern["employment_type"] == "internship"
    assert [j["work_arrangement"] for j in items if j["title"] == "Backend Engineer"] == ["remote"]
    assert [j["work_arrangement"] for j in items if j["title"] == "Platform Engineer"] == ["hybrid"]


def test_scenario_closed_job_is_marked_closed_and_never_eligible(env, mk):
    a = mk("a@example.com")
    add_boards(a, BOARDS[:1])
    discover(a)
    job = [j for j in jobs(a)["items"] if j["title"] == "Backend Engineer"][0]
    fake_ats.STATE["greenhouse"]["acme-test"] = [j for j in fake_ats.STATE["greenhouse"]["acme-test"] if j["id"] != 1001]  # removed from API and its page 404s
    assert a.post(f"/api/jobs/{job['id']}/verify", {}).json()["result"]["statuses"][job["id"]] == "CLOSED"
    d = a.get(f"/api/jobs/{job['id']}").json()
    assert d["status"] == "CLOSED" and d["outreach_eligible"] is False and "Only verified-active" in d["outreach_note"]
    assert {e["kind"] for e in d["verification_evidence"]} >= {"api_listed", "api_absent", "page_gone"}
    assert [j["id"] for j in jobs(a, "&outreach_eligible=true")["items"]] == [j["id"] for j in jobs(a)["items"] if j["title"] != "Backend Engineer"]


def test_missing_from_api_but_page_still_loads_is_only_possibly_closed(env, mk):
    a = mk("a@example.com")
    add_boards(a, BOARDS[:1])
    discover(a)
    job = [j for j in jobs(a)["items"] if j["title"] == "Backend Engineer"][0]
    fake_ats.STATE["greenhouse"]["acme-test"] = [j for j in fake_ats.STATE["greenhouse"]["acme-test"] if j["id"] != 1001]
    fake_ats.STATE["pages"]["https://boards.greenhouse.io/acme-test/jobs/1001"] = (200, "<html>Backend Engineer. Apply now.</html>")
    assert a.post(f"/api/jobs/{job['id']}/verify", {}).json()["result"]["statuses"][job["id"]] == "POSSIBLY_CLOSED"


def test_closed_banner_on_page_while_api_lists_it_is_not_verified(env, mk):
    a = mk("a@example.com")
    add_boards(a, BOARDS[:1])
    discover(a)
    job = jobs(a)["items"][0]
    fake_ats.STATE["closed_text_urls"].append(a.get(f"/api/jobs/{job['id']}").json()["sources"][0]["source_url"])
    st = a.post(f"/api/jobs/{job['id']}/verify", {}).json()["result"]["statuses"][job["id"]]
    assert st == "POSSIBLY_CLOSED"


def test_unreachable_sources_never_close_a_job(env, mk):
    a = mk("a@example.com")
    add_boards(a, BOARDS[:1])
    discover(a)
    job = [j for j in jobs(a)["items"] if j["title"] == "Backend Engineer"][0]
    fake_ats.STATE["broken_urls"].append("https://boards.greenhouse.io/acme-test/jobs/1001")  # page returns 503
    del fake_ats.STATE["greenhouse"]["acme-test"]  # board API now answers 404: we can't tell if the job closed
    st = a.post(f"/api/jobs/{job['id']}/verify", {}).json()["result"]["statuses"][job["id"]]
    kinds = [e["kind"] for e in a.get(f"/api/jobs/{job['id']}").json()["verification_evidence"]]
    assert kinds.count("inaccessible") == 2 and "api_absent" not in kinds and "page_gone" not in kinds
    assert st == "ACTIVE_VERIFIED"  # the earlier fresh API listing still stands; failed re-checks add nothing negative


def test_stale_listings_are_flagged_and_reverified(env, mk):
    a = mk("a@example.com")
    add_boards(a, BOARDS[:1])
    discover(a)
    db = new_session()
    db.query(Job).update({"last_verified": datetime.utcnow() - timedelta(days=5)})
    db.query(JobVerification).update({"checked_at": datetime.utcnow() - timedelta(days=5)})
    db.commit()
    assert all(j["needs_reverify"] for j in jobs(a)["items"])
    assert {j["status"] for j in jobs(a)["items"]} == {"ACTIVE_VERIFIED"}  # status text not yet refreshed
    res = a.post("/api/jobs/verify-stale", {}).json()["result"]
    assert res["verified"] == 2 and not any(j["needs_reverify"] for j in jobs(a)["items"])


def test_scenario_duplicate_listings_across_sources_become_one_job(env, mk):
    a = mk("a@example.com")
    add_boards(a, BOARDS[:1])
    discover(a)
    fake_ats.STATE["pages"]["https://careers.acme-test.example.com/backend"] = (200, (
        '<script type="application/ld+json">{"@type":"JobPosting","title":"Backend Engineer","hiringOrganization":{"name":"Acme Test Co"},'
        '"jobLocation":{"address":{"addressLocality":"Remote"}},"url":"https://careers.acme-test.example.com/backend"}</script>'))
    r = a.post("/api/jobs/manual", {"url": "https://careers.acme-test.example.com/backend"})
    assert r.status_code == 201 and r.json()["company"].startswith("Acme Test Co")
    items = [j for j in jobs(a)["items"] if j["title"] == "Backend Engineer"]
    assert len(items) == 1
    d = a.get(f"/api/jobs/{items[0]['id']}").json()
    assert sorted(s["type"] for s in d["sources"]) == ["greenhouse", "jsonld"]


def test_manual_paste_is_unknown_private_and_never_verified(env, mk):
    a, b = mk("a@example.com"), mk("b@example.com")
    r = a.post("/api/jobs/manual", {"title": "Staff Engineer", "company": "Stealth Co", "description": "Secret JD text", "location": "Remote"})
    assert r.status_code == 201 and r.json()["status"] == "UNKNOWN" and r.json()["origin"] == "manual" and r.json()["outreach_eligible"] is False
    assert b.get(f"/api/jobs/{r.json()['id']}").status_code == 404 and jobs(b)["total"] == 0
    r2 = b.post("/api/jobs/manual", {"title": "Staff Engineer", "company": "Stealth Co", "location": "Remote"}).json()
    assert r2["id"] != r.json()["id"]  # never merged with another user's pasted job
    assert a.post("/api/jobs/manual", {"title": "x"}).status_code == 422
    assert a.post("/api/jobs/manual", {"url": "http://127.0.0.1/job"}).status_code == 422


def test_manual_url_respects_robots(env, mk):
    a = mk("a@example.com")
    fake_ats.STATE["robots"]["careers.blocked.example.com"] = "User-agent: *\nDisallow: /"
    fake_ats.STATE["pages"]["https://careers.blocked.example.com/j"] = (200, "<html></html>")
    r = a.post("/api/jobs/manual", {"url": "https://careers.blocked.example.com/j"})
    assert r.status_code == 422 and "robots" in r.json()["detail"]


def test_filters_search_hide(env, mk):
    a = mk("a@example.com")
    add_boards(a)
    a.post("/api/contacts", {"first_name": "Lee", "company": "Acme Test Co"})
    discover(a)
    assert jobs(a, "&employment_type=internship")["total"] == 1 and jobs(a, "&work_arrangement=remote")["total"] == 2
    assert jobs(a, "&has_contacts=true")["total"] == 2 and jobs(a, "&has_contacts=false")["total"] == 4
    assert jobs(a, "&q=kubernetes")["total"] == 2 and jobs(a, "&status=CLOSED")["total"] == 0
    first = jobs(a)["items"][0]
    assert a.post(f"/api/jobs/{first['id']}/hide", {}).json() == {"hidden": True}
    assert jobs(a)["total"] == 5 and jobs(a, "&include_hidden=true")["total"] == 6


def test_shared_job_cache_does_not_leak_between_users(env, mk):
    a, b = mk("a@example.com"), mk("b@example.com")
    add_boards(a, BOARDS[:2])
    discover(a)
    assert jobs(b)["total"] == 0 and b.get("/api/boards").json() == []
    ids = [j["id"] for j in jobs(a)["items"]]
    assert all(b.get(f"/api/jobs/{i}").status_code == 404 for i in ids)
    add_boards(b, BOARDS[:1])  # B discovers the same public board: shares the cached canonical job, gets own link
    discover(b)
    assert jobs(b)["total"] == 2 and {j["id"] for j in jobs(b)["items"]} <= set(ids)
    a.post(f"/api/jobs/{ids[0]}/hide", {})
    assert jobs(b)["total"] == 2  # A's hiding is A's own state
    db = new_session()
    assert db.query(Job).count() == 3  # 3 canonical jobs total, not 5


# ---------------------------------------------------------------- referral route
def test_scenario_no_public_referral_info_never_asserts_a_programme(env, mk):
    a = mk("a@example.com")
    a.post("/api/contacts", {"first_name": "Lee", "company": "Acme Test Co"})
    cid = a.get("/api/companies").json()["items"][0]["id"]
    assert a.get("/api/jobs").json()["total"] == 0
    fake_ats.STATE["pages"]["https://acme-test.example.com/careers"] = (200, "<html><body><h1>Careers</h1><p>Join our team.</p></body></html>")
    r = a.post(f"/api/companies/{cid}/referral-route/check", {"urls": ["https://acme-test.example.com/careers"]}).json()
    assert r["status"] == "NO_PUBLIC_EVIDENCE" and r["evidence_excerpt"] is None
    from app.models.jobs import ReferralRoute
    db = new_session()
    assert not referral_route.wording_allows_programme_claim(db.query(ReferralRoute).one())


def test_referral_programme_needs_official_page_evidence(env, mk):
    a = mk("a@example.com")
    a.post("/api/contacts", {"first_name": "Lee", "company": "Acme Test Co"})
    cid = a.get("/api/companies").json()["items"][0]["id"]
    assert a.put(f"/api/companies/{cid}/referral-route", {"status": "VERIFIED_REFERRAL_PROGRAM"}).status_code == 422  # cannot self-declare
    assert a.put(f"/api/companies/{cid}/referral-route", {"status": "REFERRAL_ROUTE_UNCONFIRMED"}).json()["source"] == "user"
    fake_ats.STATE["pages"]["https://acme-test.example.com/refer"] = (200, "<html><body><p>Ask us about our Employee Referral Program and bonus.</p></body></html>")
    r = a.post(f"/api/companies/{cid}/referral-route/check", {"urls": ["https://acme-test.example.com/refer"]}).json()
    assert r["status"] == "VERIFIED_REFERRAL_PROGRAM" and "Employee Referral Program" in r["evidence_excerpt"] and r["evidence_url"].endswith("/refer")
    fake_ats.STATE["pages"]["https://acme-test.example.com/refer"] = (200, "<html><body>Nothing here.</body></html>")  # absence later must not erase user input silently
    a.put(f"/api/companies/{cid}/referral-route", {"status": "NOT_APPLICABLE"})
    a.post(f"/api/companies/{cid}/referral-route/check", {"urls": ["https://acme-test.example.com/refer"]})
    assert a.put(f"/api/companies/{cid}/referral-route", {"status": "bogus"}).status_code == 422


def test_unreadable_referral_pages_stay_unknown(env, mk):
    a = mk("a@example.com")
    a.post("/api/contacts", {"first_name": "Lee", "company": "Acme Test Co"})
    cid = a.get("/api/companies").json()["items"][0]["id"]
    fake_ats.STATE["broken_urls"].append("https://acme-test.example.com/careers")
    assert a.post(f"/api/companies/{cid}/referral-route/check", {"urls": ["https://acme-test.example.com/careers"]}).json()["status"] == "UNKNOWN"
    assert a.post(f"/api/companies/{cid}/referral-route/check", {"urls": ["http://10.0.0.1/x"]}).status_code == 422


def test_job_detail_shows_route_and_contact_availability(env, mk):
    a = mk("a@example.com")
    add_boards(a, BOARDS[:1])
    a.post("/api/contacts", {"first_name": "Lee", "company": "Acme Test Co"})
    discover(a)
    d = a.get(f"/api/jobs/{jobs(a)['items'][0]['id']}").json()
    assert d["referral_route"]["status"] == "UNKNOWN" and d["contacts_at_company"] == 1
