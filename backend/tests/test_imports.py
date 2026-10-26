import time

import pytest

from app.services import contacts_import
from tests import synth_contacts as sc


def do_import(a, data, kind="linkedin", name="c.csv", mapping=None, provenance=None, region="US", expect=202):
    r = a.c.post("/api/imports", data={"kind": kind}, files={"file": (name, data, "text/csv")}, headers=a._h())
    assert r.status_code == 201, r.text
    prev = r.json()
    body = {"mapping": mapping, "region": region}
    if provenance:
        body["provenance"] = provenance
    s = a.post(f"/api/imports/{prev['import_id']}/start", body)
    assert s.status_code == expect, s.text
    return prev, s.json()


def report(a, imp_id):
    return a.get(f"/api/imports/{imp_id}").json()


def contacts(a, **q):
    qs = "&".join(f"{k}={v}" for k, v in q.items())
    return a.get(f"/api/contacts?page_size=200&{qs}").json()


# ---------------------------------------------------------------- LinkedIn
def test_linkedin_preamble_header_detection_and_import(env, mk):
    a = mk("a@example.com")
    prev, s = do_import(a, sc.linkedin_csv(30))
    assert prev["header_row"] > 0 and prev["unmapped"] == [] and prev["total_rows"] == 30
    assert prev["mapping"]["linkedin_url"] == "URL" and prev["mapping"]["email"] == "Email Address"
    rep = report(a, prev["import_id"])
    assert rep["status"] == "done" and rep["report"]["valid"] == 30 and rep["row_counts"] == {"valid": 30}
    first = contacts(a)["items"][0]
    assert first["company"] and first["linkedin_url"].startswith("https://www.linkedin.com/in/synthetic-")


def test_company_variants_collapse_conservatively(env, mk):
    a = mk("a@example.com")
    do_import(a, sc.linkedin_csv(24))  # 12 companies x 6 legal-suffix spellings
    comps = a.get("/api/companies").json()
    assert comps["total"] == 12 and {c["connections"] for c in comps["items"]} == {2}
    assert "Acme Test Co" in {c["name"] for c in comps["items"]} or any(c["name"].startswith("Acme Test Co") for c in comps["items"])


@pytest.mark.parametrize("enc,delim", [("utf-8", ";"), ("utf-8", "\t"), ("latin-1", ","), ("utf-16", ",")], ids=["semicolon", "tab", "latin1", "utf16"])
def test_encodings_and_delimiters(env, mk, enc, delim):
    a = mk("a@example.com")
    rows = [["José", "Müller", "https://www.linkedin.com/in/synthetic-jose", "", "Café Systems GmbH", "Ingénieur", "01 Mar 2023"]]
    data = sc.to_csv(sc.LI_HEADER, rows, delimiter=delim, preamble="", encoding=enc)
    if enc == "utf-16":
        data = b"\xff\xfe" + data if not data.startswith(b"\xff\xfe") else data
    prev, _ = do_import(a, data)
    assert report(a, prev["import_id"])["report"]["valid"] == 1
    assert contacts(a)["items"][0]["name"] == "José Müller"  # accents survive every supported encoding
    assert prev["encoding"]


def test_missing_columns_and_values_are_reported_not_dropped(env, mk):
    a = mk("a@example.com")
    data = sc.to_csv(["First Name", "Last Name", "URL"], [["Alex", "Banson", "https://www.linkedin.com/in/synthetic-1"], ["Sam", "Koson", ""]], preamble="")
    prev, _ = do_import(a, data)
    rep = report(a, prev["import_id"])["report"]
    assert rep["valid"] == 2 and rep["missing"]["company"] == 2 and rep["missing"]["position"] == 2 and rep["missing"]["linkedin_url"] == 1


def test_invalid_url_email_date_are_flagged_but_person_kept(env, mk):
    a = mk("a@example.com")
    rows = [["Alex", "Banson", "https://twitter.com/alex", "not-an-email", "Acme Test Co", "Engineer", "someday"]]
    prev, _ = do_import(a, sc.to_csv(sc.LI_HEADER, rows, preamble=""))
    r = a.get(f"/api/imports/{prev['import_id']}/rows").json()["rows"][0]
    assert r["status"] == "valid" and {x["code"] for x in r["reasons"]} == {"invalid_url", "invalid_email", "unparsed_date"}
    assert r["raw"]["Connected On"] == "someday"  # original preserved verbatim
    c = contacts(a)["items"][0]
    assert c["linkedin_url"] is None and c["email"] is None


def test_rows_without_names_are_invalid_with_reason(env, mk):
    a = mk("a@example.com")
    rows = [["", "", "https://www.linkedin.com/in/synthetic-9", "", "Acme Test Co", "Engineer", ""], ["Alex", "Banson", "", "", "", "", ""]]
    prev, _ = do_import(a, sc.to_csv(sc.LI_HEADER, rows, preamble=""))
    rows_ = a.get(f"/api/imports/{prev['import_id']}/rows?status=invalid").json()
    assert rows_["total"] == 1 and rows_["rows"][0]["reasons"][0]["code"] == "missing_name"


def test_every_row_is_accounted_for(env, mk):
    a = mk("a@example.com")
    body = sc.linkedin_csv(10).decode() + "\n\n,,,,,,\nAlex,Banson\nSam,Ko,https://www.linkedin.com/in/synthetic-x,a,b,c,d,EXTRA\n"
    prev, _ = do_import(a, body.encode())
    rep = report(a, prev["import_id"])
    r = rep["report"]
    assert r["read"] == sum(rep["row_counts"].values())  # rows in == rows recorded
    assert r["valid"] + r["duplicate"] + r["invalid"] == r["read"] and r["empty"] >= 1
    mism = [x for x in a.get(f"/api/imports/{prev['import_id']}/rows?page_size=200").json()["rows"] if any(y["code"] == "column_count_mismatch" for y in x["reasons"])]
    assert len(mism) == 2


def test_duplicate_rules_never_merge_on_name_alone(env, mk):
    a = mk("a@example.com")
    U = "https://www.linkedin.com/in/synthetic-"
    rows = [["Alex", "Banson", U + "1", "", "Acme Test Co", "", ""],
            ["Alex", "Banson", U + "1/?trk=x", "", "Acme Test Co", "", ""],      # same URL (normalised) -> dup
            ["Alex", "Banson", U + "2", "", "Acme Test Co", "", ""],             # same name+company, different URL -> different person
            ["Alex", "Banson", "", "", "Globex Example", "", ""],                # no URL, other company -> new
            ["Alex", "Banson", "", "", "Globex Example Inc", "", ""],            # no URL, same name+company -> dup
            ["Alex", "Banson", "", "", "", "", ""]]                              # name only -> kept, never merged
    prev, _ = do_import(a, sc.to_csv(sc.LI_HEADER, rows, preamble=""))
    r = report(a, prev["import_id"])
    assert r["row_counts"] == {"valid": 4, "duplicate": 2}
    prev2, _ = do_import(a, sc.to_csv(sc.LI_HEADER, rows, preamble=""))  # re-import: URL dupes; name-only row has no key
    assert report(a, prev2["import_id"])["row_counts"].get("duplicate", 0) >= 5
    assert contacts(a)["total"] == 4 + 1  # only the identity-less name-only row can be re-added


def test_unsupported_files(env, mk):
    a = mk("a@example.com")
    for data, code in ((b"", 422), (b"First Name,Last Name\n", 422)):
        assert a.c.post("/api/imports", data={"kind": "linkedin"}, files={"file": ("c.csv", data)}, headers=a._h()).status_code == code
    assert a.c.post("/api/imports", data={"kind": "nope"}, files={"file": ("c.csv", b"a,b\n1,2")}, headers=a._h()).status_code == 422
    junk = bytes(range(256)) * 10 + b"\nx,y\n1,2\n"  # binary junk must be refused cleanly, never a 500
    r = a.c.post("/api/imports", data={"kind": "linkedin"}, files={"file": ("c.csv", junk)}, headers=a._h())
    assert r.status_code in (201, 422)
    if r.status_code == 201:
        assert a.post(f"/api/imports/{r.json()['import_id']}/start", {}).status_code == 422  # no recognisable columns


def test_mapping_override_and_validation(env, mk):
    a = mk("a@example.com")
    data = sc.to_csv(["Who", "Employer X", "Link"], [["Alex Banson", "Acme Test Co", "https://www.linkedin.com/in/synthetic-1"]], preamble="")
    prev, _ = do_import(a, data, mapping={"full_name": "Who", "company": "Employer X", "linkedin_url": "Link"})
    c = contacts(a)["items"][0]
    assert c["name"] == "Alex Banson" and c["company"] == "Acme Test Co"
    r = a.c.post("/api/imports", data={"kind": "linkedin"}, files={"file": ("c.csv", data)}, headers=a._h()).json()
    assert a.post(f"/api/imports/{r['import_id']}/start", {"mapping": {"bogus": "Who"}}).status_code == 422
    assert a.post(f"/api/imports/{r['import_id']}/start", {"mapping": {"company": None}}).status_code == 422
    ok = a.post(f"/api/imports/{r['import_id']}/start", {"mapping": {"full_name": "Who"}})
    assert ok.status_code == 202 and a.post(f"/api/imports/{r['import_id']}/start", {}).status_code == 409


def test_list_pagination_search_and_caps(env, mk):
    a = mk("a@example.com")
    do_import(a, sc.linkedin_csv(130))
    p1 = a.get("/api/contacts?page=1&page_size=50").json()
    p3 = a.get("/api/contacts?page=3&page_size=50").json()
    assert p1["total"] == 130 and len(p1["items"]) == 50 and len(p3["items"]) == 30
    assert not ({i["id"] for i in p1["items"]} & {i["id"] for i in p3["items"]})
    assert len(a.get("/api/contacts?page_size=9999").json()["items"]) == 130 and a.get("/api/contacts?page_size=9999").json()["page_size"] == 200
    assert all("recruiter" in i["position"].lower() for i in a.get("/api/contacts?q=recruiter&page_size=200").json()["items"])
    assert a.get("/api/contacts?q=zzzznomatch").json()["total"] == 0
    assert a.get("/api/contacts?q=%25%27%3B--").json()["total"] == 0  # injection-ish input is just text


def test_resumable_after_mid_import_failure(env, mk, monkeypatch):
    a = mk("a@example.com")
    monkeypatch.setattr(contacts_import, "CHUNK", 4)
    orig, state = contacts_import._li_row, {"n": 0, "failed": False}

    def flaky(*args, **kw):
        state["n"] += 1
        if state["n"] == 7 and not state["failed"]:
            state["failed"] = True
            raise RuntimeError("worker died")
        return orig(*args, **kw)

    monkeypatch.setattr(contacts_import, "_li_row", flaky)
    prev, s = do_import(a, sc.linkedin_csv(20))
    rep = report(a, prev["import_id"])
    assert state["failed"] and rep["status"] == "done" and rep["report"]["valid"] == 20 and contacts(a)["total"] == 20


def test_purge_removes_raw_keeps_contacts(env, mk):
    a = mk("a@example.com")
    prev, _ = do_import(a, sc.linkedin_csv(5))
    assert a.post(f"/api/imports/{prev['import_id']}/purge", {}).status_code == 200
    assert a.get(f"/api/imports/{prev['import_id']}/rows").json()["rows"][0]["raw"] == {}
    assert report(a, prev["import_id"])["status"] == "purged" and contacts(a)["total"] == 5
    assert not list((env / "users").rglob("*.csv"))


# ---------------------------------------------------------------- company review queue
def test_fuzzy_company_goes_to_review_and_merge_is_remembered(env, mk):
    a = mk("a@example.com")
    U = "https://www.linkedin.com/in/synthetic-"
    mk_csv = lambda rows: sc.to_csv(sc.LI_HEADER, rows, preamble="")  # noqa: E731
    do_import(a, mk_csv([["Alex", "Banson", U + "1", "", "Northwind Labs", "", ""], ["Sam", "Koson", U + "2", "", "Northwnd Labs", "", ""]]))
    assert a.get("/api/companies").json()["total"] == 2  # not auto-merged: ambiguous
    rv = a.get("/api/company-reviews").json()
    assert len(rv) == 1 and rv[0]["raw_name"] == "Northwnd Labs" and rv[0]["candidate"] == "Northwind Labs"
    assert a.post(f"/api/company-reviews/{rv[0]['id']}/resolve", {"action": "merge"}).status_code == 200
    comps = a.get("/api/companies").json()
    assert comps["total"] == 1 and comps["items"][0]["connections"] == 2
    do_import(a, mk_csv([["Kai", "Rason", U + "3", "", "Northwnd Labs", "", ""]]))  # remembered alias
    assert a.get("/api/companies").json()["items"][0]["connections"] == 3 and a.get("/api/company-reviews").json() == []


def test_near_identical_long_names_auto_merge_but_similar_short_names_do_not(env, mk):
    a = mk("a@example.com")
    U = "https://www.linkedin.com/in/synthetic-"
    rows = [["A", "One", U + "1", "", "International Business Machines Test", "", ""], ["B", "Two", U + "2", "", "International Business Machine Test", "", ""],
            ["C", "Three", U + "3", "", "Meta Test", "", ""], ["D", "Four", U + "4", "", "Metal Test", "", ""]]
    do_import(a, sc.to_csv(sc.LI_HEADER, rows, preamble=""))
    assert a.get("/api/companies").json()["total"] == 3


# ---------------------------------------------------------------- HR CSV
HR = lambda rows: sc.to_csv(sc.HR_HEADER, rows, preamble="")  # noqa: E731


def hr_mixed():
    return HR([
        ["Acme Test Co", "Pat Recruiter", "Recruiter", "pat@acme-test.example.com", "+1 415 555 0134", "linkedin.com/in/synthetic-00005", "SF", ""],
        ["Acme Test Co", "Dup Person", "Recruiter", "PAT@acme-test.example.com", "", "", "", ""],         # duplicate (case-insens.)
        ["Globex Example", "Bad Mail", "HR", "not-an-email", "", "", "", ""],                             # bad email, name+company -> kept
        ["Globex Example", "", "", "info@globex-example.example.com", "", "", "", ""],                           # role account
        ["Initech Sample", "No Reply", "", "noreply@initech-sample.example.com", "", "", "", ""],                # noreply flag
        ["Umbrella Demo", "Opt Out", "Recruiter", "optout@umbrella-demo.example.com", "", "", "", ""],          # will be suppressed
        ["", "", "", "", "", "", "", ""],                                                                 # blank
        ["", "Nobody", "", "", "123", "", "", ""],                                                        # nothing usable
    ])


def test_hr_provenance_is_required(env, mk):
    a = mk("a@example.com")
    r = a.c.post("/api/imports", data={"kind": "hr"}, files={"file": ("h.csv", hr_mixed())}, headers=a._h()).json()
    assert "purchased" in r["provenance_options"]
    assert a.post(f"/api/imports/{r['import_id']}/start", {}).status_code == 422
    assert a.post(f"/api/imports/{r['import_id']}/start", {"provenance": "made-up"}).status_code == 422
    assert a.post(f"/api/imports/{r['import_id']}/start", {"provenance": "self_collected"}).status_code == 202


def test_hr_mixed_quality_cleaned_report_and_suppression(env, mk):
    a = mk("a@example.com")
    assert a.post("/api/suppression", {"value": "Optout@Umbrella-Demo.example.com", "reason": "unsubscribed"}).status_code == 201  # before import
    prev, s = do_import(a, hr_mixed(), kind="hr", provenance="self_collected")
    rep = report(a, prev["import_id"])
    assert rep["row_counts"] == {"valid": 5, "duplicate": 1, "invalid": 2}  # 8 rows in, 8 recorded
    assert rep["report"]["suppressed"] == 1
    ec = {c["name"] or c["email"]: c for c in a.get("/api/email-contacts?page_size=200").json()["items"]}
    assert ec["Pat Recruiter"]["email"] == "pat@acme-test.example.com" and ec["Pat Recruiter"]["phone"] == "+14155550134"
    assert ec["Bad Mail"]["email_valid"] is False and ec["Bad Mail"]["email"] is None and ec["Bad Mail"]["email_raw"] == "not-an-email"
    assert "role_account" in ec["info@globex-example.example.com"]["email_flags"] and "noreply" in ec["No Reply"]["email_flags"]
    assert ec["Opt Out"]["suppressed"] is True and ec["Pat Recruiter"]["suppressed"] is False
    assert [c["name"] for c in a.get("/api/email-contacts?suppressed=true").json()["items"]] == ["Opt Out"]
    assert a.get("/api/email-contacts?suppressed=false").json()["total"] == 4
    assert [c["name"] for c in a.get("/api/email-contacts?flag=noreply").json()["items"]] == ["No Reply"]
    reasons = {x["code"] for r in a.get(f"/api/imports/{prev['import_id']}/rows?status=invalid").json()["rows"] for x in r["reasons"]}
    assert {"empty_row", "no_usable_identifier"} <= reasons


def test_suppression_survives_reimport_and_domain_rules(env, mk):
    a = mk("a@example.com")
    do_import(a, hr_mixed(), kind="hr", provenance="self_collected")
    a.post("/api/suppression", {"value": "pat@acme-test.example.com", "reason": "do_not_contact"})
    a.post("/api/suppression", {"value": "globex-example.example.com", "kind": "domain", "reason": "blocklist"})
    do_import(a, hr_mixed(), kind="hr", provenance="self_collected")  # re-import changes nothing
    sup = {c["email"] for c in a.get("/api/email-contacts?page_size=200").json()["items"] if c["suppressed"]}
    assert sup == {"pat@acme-test.example.com", "info@globex-example.example.com"}
    assert a.get("/api/suppression").json()["total"] == 2
    assert a.post("/api/suppression", {"value": "pat@acme-test.example.com"}).json() == {"created": False}
    b = a.post("/api/suppression/bulk", {"emails": ["x@example.com", "bad", "X@example.com"]}).json()
    assert b == {"added": 1, "already_present": 1, "invalid": 1}
    assert a.post("/api/suppression", {"value": "nodot", "kind": "domain"}).status_code == 422


def test_purchased_lists_are_blocked_for_bulk_sending(env, mk):
    a = mk("a@example.com")
    prev, s = do_import(a, hr_mixed(), kind="hr", provenance="purchased")
    assert "not legal advice" in s["warning"]
    assert all(c["bulk_send_blocked"] for c in a.get("/api/email-contacts?page_size=200").json()["items"])
    prev2, s2 = do_import(a, HR([["Acme Test Co", "New Person", "", "new@acme-test.example.com", "", "", "", ""]]), kind="hr", provenance="company_published")
    assert s2["warning"] is None
    assert [c["bulk_send_blocked"] for c in a.get("/api/email-contacts?q=new%20person").json()["items"]] == [False]


def test_phone_regions_and_country_hints(env, mk):
    a = mk("a@example.com")
    rows = [["Acme Test Co", "Uk Person", "", "uk@acme-test.co.uk", "020 7946 0958", "", "", ""], ["Acme Test Co", "In Person", "", "", "98765 43210", "", "", ""]]
    do_import(a, HR(rows), kind="hr", provenance="self_collected", region="GB")
    ec = {c["name"]: c for c in a.get("/api/email-contacts?page_size=200").json()["items"]}
    assert ec["Uk Person"]["phone"] == "+442079460958" and ec["Uk Person"]["country_hint"] == "GB"
    assert ec["In Person"]["phone"] is None and ec["In Person"]["phone_raw"] == "98765 43210"  # invalid for GB: kept raw, not guessed


def test_hr_contacts_link_to_linkedin_connections(env, mk):
    a = mk("a@example.com")
    do_import(a, sc.linkedin_csv(10))
    do_import(a, hr_mixed(), kind="hr", provenance="self_collected")
    pat = [c for c in a.get("/api/email-contacts?q=pat").json()["items"] if c["name"] == "Pat Recruiter"][0]
    assert pat["linked_contact_id"] and a.get(f"/api/contacts/{pat['linked_contact_id']}").json()["linkedin_url"].endswith("synthetic-00005")


def test_manual_contacts(env, mk):
    a = mk("a@example.com")
    assert a.post("/api/email-contacts", {"name": "Solo", "email": "bad"}).status_code == 422
    assert a.post("/api/email-contacts", {"name": "Solo", "email": "solo@example.com", "company": "Acme Test Co"}).status_code == 201
    assert a.post("/api/email-contacts", {"email": "SOLO@example.com"}).status_code == 409
    assert a.post("/api/contacts", {"first_name": "Man", "last_name": "Ual", "company": "Acme Test Co"}).json()["source"] == "MANUAL"


# ---------------------------------------------------------------- scale (synthetic)
@pytest.mark.slow
def test_import_11k_linkedin_and_5k_hr(env, mk, capsys):
    a = mk("a@example.com")
    t = time.perf_counter()
    prev, _ = do_import(a, sc.linkedin_csv(11000))
    li_s = time.perf_counter() - t
    rep = report(a, prev["import_id"])
    assert rep["report"]["valid"] == 11000 and rep["row_counts"] == {"valid": 11000}
    t = time.perf_counter()
    prev2, _ = do_import(a, sc.to_csv(sc.HR_HEADER, sc.hr_rows(5000), preamble=""), kind="hr", provenance="self_collected")
    hr_s = time.perf_counter() - t
    assert report(a, prev2["import_id"])["report"]["valid"] == 5000
    t = time.perf_counter()
    r = a.get("/api/contacts?page=100&page_size=100&q=engineer")
    q_ms = (time.perf_counter() - t) * 1000
    assert r.status_code == 200
    with capsys.disabled():
        print(f"\n[perf] linkedin 11000 rows: {li_s:.1f}s ({11000 / li_s:.0f}/s); hr 5000 rows: {hr_s:.1f}s ({5000 / hr_s:.0f}/s); search+page: {q_ms:.0f}ms")
