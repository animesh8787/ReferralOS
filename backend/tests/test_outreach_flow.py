from datetime import timedelta

import pytest

from app.adapters import fake_ats
from app.models.jobs import Job
from app.models.outreach import OutreachMessage
from app.services.outreach import providers, send as osend, settings as osettings
from app.util import utcnow
from tests import synth_contacts as sc  # noqa: F401
from tests.outreach_helpers import *  # noqa: F401,F403
from tests.outreach_helpers import _reset_world  # noqa: F401  (autouse fixture)


# ---------------------------------------------------------------- generation (acceptance 1, 5, 6)
def test_generate_makes_a_small_reviewable_batch_and_sends_nothing(env, mk):
    a = mk("a@example.com")
    jobs = prep(a)
    g = gen(a)
    assert g["jobs_used"] == [jobs["Backend Engineer"]["id"]] and g["summary"] == {"jobs": 1, "messages": 5, "skipped": 0, "linkedin": 3, "email": 2}
    ms = msgs(a)
    assert {m["approval_state"] for m in ms} == {"awaiting_approval"} and {m["send_state"] for m in ms} == {"not_sent"} and not outbox(a)
    assert {m["pair_status"] for m in ms} == {"AWAITING_APPROVAL"}
    for m in emails_(a):
        d = a.get(f"/api/outreach/messages/{m['id']}").json()
        assert "unsubscribe" in d["body"] and d["body"].count("Backend Engineer") >= 1 and "{{" not in d["body"] and len(d["subject_options"]) >= 3
        assert d["variants"]["A"]["body"] != d["variants"]["B"]["body"] and d["content_blocks"] == [] and d["can_approve"]
    for m in linkedin_(a):
        d = a.get(f"/api/outreach/messages/{m['id']}").json()
        assert len(d["connect_note"]) <= 300 and "please feel free to decline" in d["body"] and d["to_linkedin_url"].startswith("https://www.linkedin.com/in/")
        assert any(f["code"].startswith("EMPLOYMENT_") for f in m["risk_flags"])  # employer is inferred, and says so
    assert len({m["to_name"] for m in linkedin_(a)}) == 3 and a.get("/api/outreach/batches").json()[0]["summary"]["messages"] == 5


def test_scenario_one_person_covering_several_roles_gets_one_message(env, mk):
    a = mk("a@example.com")
    fake_ats.STATE["greenhouse"]["acme-test"].append({"id": 1003, "title": "Platform Engineer", "location": {"name": "Remote"}, "updated_at": "2026-05-03T00:00:00Z",
                                                      "absolute_url": "https://boards.greenhouse.io/acme-test/jobs/1003",
                                                      "content": "&lt;h3&gt;Requirements:&lt;/h3&gt;&lt;ul&gt;&lt;li&gt;Experience with Python and Docker&lt;/li&gt;&lt;li&gt;Experience with PostgreSQL&lt;/li&gt;&lt;/ul&gt;&lt;p&gt;Operate internal platform services for developers.&lt;/p&gt;"})
    jobs = prep(a)
    g = gen(a)
    assert set(g["jobs_used"]) == {jobs["Backend Engineer"]["id"], jobs["Platform Engineer"]["id"]}
    li_msgs = linkedin_(a)
    assert len(li_msgs) == len({m["to_name"] for m in li_msgs}) <= 3  # one message per person, never one per role
    assert all(len(m["covers_job_ids"]) == 2 for m in li_msgs)
    body = a.get(f"/api/outreach/messages/{li_msgs[0]['id']}").json()["body"]
    assert "I'm also interested in the" in body and body.count("https://boards.greenhouse.io") == 2
    assert all(len(m["covers_job_ids"]) == 2 for m in emails_(a))


def test_second_generate_never_duplicates_outreach_to_the_same_people(env, mk):
    a = mk("a@example.com")
    prep(a)
    gen(a)
    g2 = gen(a)
    assert g2["messages"] == [] and len(g2["skipped"]) >= 3 and all("already" in s["why"] for s in g2["skipped"])
    assert len(msgs(a)) == 5


def test_relationship_note_is_used_only_when_the_user_supplies_it(env, mk):
    a = mk("a@example.com")
    prep(a)
    cid = a.get("/api/contacts?q=alex").json()["items"][0]["id"]
    gen(a, relationship_notes={cid: "I read your blog post on API design."})
    alex = [m for m in linkedin_(a) if m["to_name"] == "Alex Banson"][0]
    others = [m for m in linkedin_(a) if m["to_name"] != "Alex Banson"]
    assert "I read your blog post on API design." in a.get(f"/api/outreach/messages/{alex['id']}").json()["body"]
    assert all("blog" not in a.get(f"/api/outreach/messages/{m['id']}").json()["body"] for m in others)


def test_scenario_closed_job_gets_no_drafts_and_existing_drafts_become_stale(env, mk):
    a = mk("a@example.com")
    jobs = prep(a)
    gen(a)
    jid = jobs["Backend Engineer"]["id"]
    fake_ats.STATE["greenhouse"]["acme-test"] = [j for j in fake_ats.STATE["greenhouse"]["acme-test"] if j["id"] != 1001]
    a.post(f"/api/jobs/{jid}/verify", {})
    assert a.get(f"/api/jobs/{jid}").json()["status"] == "CLOSED"
    ms = msgs(a)
    assert ms and all(m["stale"] and "stale" in m["stale_reason"] for m in ms)
    for m in ms:
        r = a.post(f"/api/outreach/messages/{m['id']}/approve", {})
        assert r.status_code == 409 and "JOB_CLOSED" in str(r.json())
    g = gen(a)
    assert g["messages"] == [] and g["jobs_used"] == [] and not outbox(a)


def test_stale_job_evidence_is_refreshed_before_drafting(env, mk):
    a = mk("a@example.com")
    jobs = prep(a)
    db = scoped(a)
    db.query(Job).update({"last_verified": utcnow() - timedelta(days=9)})
    db.commit()
    before = len(a.get(f"/api/jobs/{jobs['Backend Engineer']['id']}").json()["verification_evidence"])
    gen(a)
    d = a.get(f"/api/jobs/{jobs['Backend Engineer']['id']}").json()
    assert len(d["verification_evidence"]) > before and not d["needs_reverify"]


def test_unverified_job_drafts_are_opt_in_flagged_high_risk_and_never_sent(env, mk):
    a = mk("a@example.com")
    prep(a)
    fake_ats.STATE["pages"]["https://careers.acme-test.example.com/be"] = (200, "<html><body>Backend Engineer. Apply now.</body></html>")  # loads, but a loading page proves nothing
    pasted = a.post("/api/jobs/manual", {"title": "Backend Engineer", "company": "Acme Test Co", "location": "Remote", "apply_url": "https://careers.acme-test.example.com/be",
                                         "description": "Requirements:\n- Experience with Python\n- Experience with PostgreSQL\n" + "x" * 100}).json()
    a.post("/api/matching/run", {})
    assert gen(a, job_ids=[pasted["id"]])["messages"] == []                      # default: verified jobs only
    g = gen(a, job_ids=[pasted["id"]], include_unconfirmed=True)
    ms = [m for m in msgs(a) if m["id"] in g["messages"]]
    assert ms and all(any(f["code"] == "JOB_NOT_VERIFIED" and f["severity"] == "high" for f in m["risk_flags"]) for m in ms)
    emails = [m for m in ms if m["channel"] == "email"]
    assert emails and a.post("/api/outreach/approve", {"scope": "recommended", "batch_id": ms[0]["batch_id"]}).json()["approved"] == []  # 'recommended' skips high-risk
    approve_ids(a, [emails[0]["id"]])
    r = a.post("/api/outreach/send", {}).json()
    assert r["sent"] == 0 and r["blocked"] and "JOB_NOT_ACTIVE" in r["blocked"][0]["codes"] and not outbox(a)


# ---------------------------------------------------------------- approval and sending
def test_approve_many_requires_restating_count_and_daily_limit(env, mk):
    a = mk("a@example.com")
    prep(a)
    g = gen(a)
    ids = g["messages"]
    r = a.post("/api/outreach/approve", {"message_ids": ids, "scope": "selected"})
    assert r.status_code == 409 and r.json()["detail"]["confirm_count"] == 5 and r.json()["detail"]["confirm_daily_limit"] == 20
    assert a.post("/api/outreach/approve", {"message_ids": ids, "scope": "selected", "confirm_count": 4, "confirm_daily_limit": 20}).status_code == 409
    assert a.post("/api/outreach/approve", {"message_ids": ids, "scope": "selected", "confirm_count": 5, "confirm_daily_limit": 99}).status_code == 409
    ok = a.post("/api/outreach/approve", {"message_ids": ids, "scope": "selected", "confirm_count": 5, "confirm_daily_limit": 20, "batch_id": g["batch_id"]}).json()
    assert len(ok["approved"]) == 5 and ok["blocked"] == []
    states = {(m["channel"], m["send_state"], m["pair_status"]) for m in msgs(a)}
    assert states == {("linkedin", "manual_pending", "APPROVED"), ("email", "queued", "QUEUED")}
    assert a.get(f"/api/outreach/batches/{g['batch_id']}").json()["approved_at"]


def test_nothing_is_sent_without_approval(env, mk):
    a = mk("a@example.com")
    prep(a)
    gen(a)
    assert a.post("/api/outreach/send", {}).json()["sent"] == 0 and not outbox(a)
    db = scoped(a)
    m = db.query(OutreachMessage).filter(OutreachMessage.channel == "email").first()
    m.send_state = "queued"  # even if something forces it into the queue...
    db.commit()
    assert a.post("/api/outreach/send", {}).json()["sent"] == 0 and not outbox(a)
    res = osend.evaluate(db, db.get(OutreachMessage, m.id), osettings.get(db), "send")
    assert "NOT_APPROVED" in {b["code"] for b in res["blocks"]}


def test_approved_emails_are_sent_once_from_the_users_own_address(env, mk):
    a = mk("a@example.com")
    prep(a)
    gen(a)
    approve_emails(a)
    r = a.post("/api/outreach/send", {}).json()
    assert r["sent"] == 2 and r["blocked"] == [] and {o["to"] for o in outbox(a)} == {"pat@acme-test.example.com", "lee@acme-test.example.com"}
    em = parse(outbox(a)[0])
    assert em["From"] == "Alex Example <alex.example@example.com>" and em["Message-ID"] and "unsubscribe" in em.get_payload(decode=True).decode()
    assert not any(p.get_filename() for p in em.walk())  # no resume was approved, so none attached
    assert a.post("/api/outreach/send", {}).json()["sent"] == 0 and len(outbox(a)) == 2  # a second run sends nothing new
    pat = by_to(a, "pat@acme-test.example.com")
    assert pat["send_state"] == "sent" and pat["pair_status"] == "SENT"
    assert [e["type"] for e in a.get(f"/api/outreach/messages/{pat['id']}/events").json()] == ["APPROVED", "SENT"]
    assert a.get("/api/tracking/pairs?status=SENT").json()["total"] == 2


def test_approved_resume_is_attached_only_when_it_is_the_approved_one_for_that_job(env, mk):
    a = mk("a@example.com")
    jobs = prep(a)
    v = a.post("/api/tailoring", {"job_id": jobs["Backend Engineer"]["id"]}).json()
    a.post(f"/api/tailoring/{v['id']}/approve", {})
    gen(a)
    m = emails_(a)[0]
    d = a.get(f"/api/outreach/messages/{m['id']}").json()
    assert d["attach_resume_id"] == v["id"] and "I've attached my resume." in d["body"]
    other = a.post("/api/tailoring", {"job_id": jobs["Backend Engineer"]["id"]}).json()  # a DRAFT version: not approved
    r = a.patch(f"/api/outreach/messages/{m['id']}", {"attach_resume_id": other["id"]})
    assert any(b["code"] == "ATTACHMENT_INVALID" for b in r.json()["content_blocks"]) and a.post(f"/api/outreach/messages/{m['id']}/approve", {}).status_code == 409
    a.patch(f"/api/outreach/messages/{m['id']}", {"attach_resume_id": v["id"]})
    approve_ids(a, [m["id"]])
    a.post("/api/outreach/send", {})
    att = [p for p in parse(outbox(a)[0]).walk() if p.get_filename()]
    assert len(att) == 1 and att[0].get_payload(decode=True)[:4] == b"%PDF" and att[0].get_filename() == "resume.pdf"


def test_editing_after_approval_withdraws_it_and_the_edit_is_what_gets_sent(env, mk):
    a = mk("a@example.com")
    prep(a)
    gen(a)
    m = by_to(a, "pat@acme-test.example.com")
    approve_ids(a, [m["id"]])
    assert a.get(f"/api/outreach/messages/{m['id']}").json()["send_state"] == "queued"
    d = a.get(f"/api/outreach/messages/{m['id']}").json()
    r = a.patch(f"/api/outreach/messages/{m['id']}", {"body": d["body"] + "\n\nP.S. I'm free for a call any afternoon."}).json()
    assert r["approval_state"] == "awaiting_approval" and r["send_state"] == "not_sent" and r["pair_status"] == "AWAITING_APPROVAL"
    assert a.post("/api/outreach/send", {}).json()["sent"] == 0
    approve_ids(a, [m["id"]])
    a.post("/api/outreach/send", {})
    assert "free for a call any afternoon" in parse(outbox(a)[0]).get_payload(decode=True).decode()


def test_content_rules_block_approval_with_specific_reasons(env, mk):
    a = mk("a@example.com")
    prep(a)
    gen(a)
    m = by_to(a, "pat@acme-test.example.com")
    mid = m["id"]
    d = a.get(f"/api/outreach/messages/{mid}").json()
    codes = lambda: {b["code"] for b in a.get(f"/api/outreach/messages/{mid}").json()["content_blocks"]}  # noqa: E731
    approve = lambda: a.post(f"/api/outreach/messages/{mid}/approve", {}).status_code  # noqa: E731
    a.patch(f"/api/outreach/messages/{mid}", {"subject": "Re: your application"})
    assert "DECEPTIVE_SUBJECT" in codes() and approve() == 409
    a.patch(f"/api/outreach/messages/{mid}", {"subject": "URGENT: act now"})
    assert "DECEPTIVE_SUBJECT" in codes()
    a.patch(f"/api/outreach/messages/{mid}", {"subject": d["subject_options"][1]})
    assert "DECEPTIVE_SUBJECT" not in codes()
    a.patch(f"/api/outreach/messages/{mid}", {"body": d["body"].replace("unsubscribe", "stop")})
    assert "MISSING_OPT_OUT" in codes()
    a.patch(f"/api/outreach/messages/{mid}", {"body": d["body"] + "\nAs discussed, I'm a perfect fit."})
    assert "FORBIDDEN_CLAIM" in codes()
    a.patch(f"/api/outreach/messages/{mid}", {"body": d["body"] + "\nI also run Kubernetes clusters serving 5000 users."})
    assert "UNVERIFIED_CLAIMS" in codes() and approve() == 409
    a.patch(f"/api/outreach/messages/{mid}", {"body": d["body"] + "\nPlease reply to {{reply_to}}."})
    assert "UNRESOLVED_PLACEHOLDER" in codes()
    a.patch(f"/api/outreach/messages/{mid}", {"body": ""})
    assert "MISSING_SUBJECT_OR_BODY" in codes()
    a.patch(f"/api/outreach/messages/{mid}", {"body": d["body"]})
    assert codes() == set() and approve() == 200


def test_variant_and_subject_choices_are_the_users(env, mk):
    a = mk("a@example.com")
    prep(a)
    gen(a)
    m = by_to(a, "pat@acme-test.example.com")
    d = a.get(f"/api/outreach/messages/{m['id']}").json()
    r = a.patch(f"/api/outreach/messages/{m['id']}", {"variant": "B"}).json()
    assert a.get(f"/api/outreach/messages/{m['id']}").json()["body"] == d["variants"]["B"]["body"] != d["variants"]["A"]["body"] and r["subject"]


def test_missing_sender_identity_blocks(env, mk):
    a = mk("a@example.com")
    prep(a, sender_name="", sender_email="")
    gen(a)
    m = emails_(a)[0]
    assert "MISSING_SENDER_IDENTITY" in {b["code"] for b in m["content_blocks"]} and not m["can_approve"]
    assert a.post(f"/api/outreach/messages/{m['id']}/approve", {}).status_code == 409


# ---------------------------------------------------------------- suppression, duplicates, blocklists (acceptance 10)
def test_scenario_suppressed_address_is_never_emailed_even_if_suppressed_after_approval(env, mk):
    a = mk("a@example.com")
    prep(a)
    gen(a)
    approve_emails(a)
    a.post("/api/suppression", {"value": "PAT@acme-test.example.com", "reason": "unsubscribed"})
    r = a.post("/api/outreach/send", {}).json()
    assert r["sent"] == 1 and r["blocked"][0]["codes"] == ["SUPPRESSED_EMAIL"] and [o["to"] for o in outbox(a)] == ["lee@acme-test.example.com"]
    pat = by_to(a, "pat@acme-test.example.com")
    assert pat["send_state"] == "blocked" and pat["pair_status"] == "DO_NOT_CONTACT"


def test_suppressed_hr_contacts_are_skipped_at_generation(env, mk):
    a = mk("a@example.com")
    prep(a, suppress=["pat@acme-test.example.com"])
    g = gen(a)
    assert [m["to_email"] for m in emails_(a)] == ["lee@acme-test.example.com"] and any("suppressed" in s["why"] for s in g["skipped"])


def test_domain_suppression_and_blocklist(env, mk):
    a = mk("a@example.com")
    prep(a)
    gen(a)
    approve_emails(a)
    a.post("/api/suppression", {"value": "acme-test.example.com", "kind": "domain", "reason": "blocklist"})
    r = a.post("/api/outreach/send", {}).json()
    assert r["sent"] == 0 and {c for b in r["blocked"] for c in b["codes"]} == {"SUPPRESSED_DOMAIN"} and not outbox(a)


def test_only_one_initial_email_per_recipient_ever(env, mk):
    a = mk("a@example.com")
    jobs = prep(a)
    gen(a)
    lee = by_to(a, "lee@acme-test.example.com")
    ec = a.get("/api/email-contacts?q=lee").json()["items"][0]["id"]
    assert a.post("/api/outreach/email-draft", {"email_contact_id": ec, "job_id": jobs["Backend Engineer"]["id"]}).status_code == 409
    assert a.post("/api/outreach/intro", {"email_contact_id": ec}).status_code == 409
    db = scoped(a)  # force a racing twin straight into the database
    src = db.get(OutreachMessage, lee["id"])
    twin = OutreachMessage(pair_id=src.pair_id, job_id=src.job_id, channel="email", kind="cold_job", is_initial=True, to_email=src.to_email, to_name=src.to_name,
                           subject=src.subject, body=src.body, approval_state="awaiting_approval", send_state="not_sent")
    db.add(twin)
    db.commit()
    approve_ids(a, [lee["id"], twin.id])
    r = a.post("/api/outreach/send", {}).json()
    sent_to_lee = [o for o in outbox(a) if o["to"] == "lee@acme-test.example.com"]
    assert len(sent_to_lee) == 1 and any("DUPLICATE_INITIAL" in b["codes"] for b in r["blocked"])
    assert a.post("/api/outreach/send", {}).json()["sent"] == 0 and len([o for o in outbox(a) if o["to"] == "lee@acme-test.example.com"]) == 1


# ---------------------------------------------------------------- limits, pause, pacing
def test_daily_limit_holds_the_rest_for_tomorrow(env, mk):
    a = mk("a@example.com")
    prep(a, daily_limit=1)
    gen(a)
    approve_emails(a)
    r = a.post("/api/outreach/send", {}).json()
    assert r["sent"] == 1 and r["held"][0]["codes"] == ["DAILY_LIMIT"] and len(outbox(a)) == 1
    held = next(m for m in emails_(a) if m["send_state"] == "queued")
    assert held["approval_state"] == "approved"
    db = scoped(a)
    res = osend.send_outbox(db, osettings.get(db), now=utcnow() + timedelta(days=1))
    db.commit()
    assert res["sent"] == 1 and len(outbox(a)) == 2


def test_company_and_intro_limits(env, mk):
    a = mk("a@example.com")
    prep(a, per_company_daily=1)
    gen(a)
    approve_emails(a)
    r = a.post("/api/outreach/send", {}).json()
    assert r["sent"] == 1 and r["held"][0]["codes"] == ["COMPANY_DAILY_LIMIT"]
    b = mk("b@example.com")
    settings_(b, delivery_mode="AUTHORISED_INTEGRATION", intro_daily=1)
    b.post("/api/outreach/acknowledge", {"kind": "lawful_use"})
    b.put("/api/consents/gmail", {"granted": True})
    b.post("/api/email/gmail/mock-connect", {"email": "b@example.com"})
    b.post("/api/profile/items", {"section": "personal", "data": {"name": "Bee Example", "email": "b@example.com"}})
    ids = [b.post("/api/email-contacts", {"name": n, "email": e, "company": c}).json()["id"] for n, e, c in
           (("One", "one@globex-test.example.com", "Globex Example"), ("Two", "two@initech-test.example.com", "Initech Sample"))]
    drafts_ = [b.post("/api/outreach/intro", {"email_contact_id": i}).json() for i in ids]
    assert all(d["kind"] == "cold_intro" and "not writing about a specific posting" in d["body"] for d in drafts_)
    approve_ids(b, [d["id"] for d in drafts_])
    r2 = b.post("/api/outreach/send", {}).json()
    assert r2["sent"] == 1 and r2["held"][0]["codes"] == ["INTRO_DAILY_LIMIT"]


def test_limits_are_clamped_to_hard_maximums_and_raising_warns(env, mk):
    a = mk("a@example.com")
    r = a.put("/api/outreach/settings", {"daily_limit": 500, "per_company_daily": 50})
    assert r.json()["daily_limit"] == 100 and r.json()["per_company_daily"] == 20 and any("hard maximum" in w for w in r.json()["warnings"])
    r = a.put("/api/outreach/settings", {"daily_limit": 30})
    assert r.json()["daily_limit"] == 30 and any("recommended 20" in w for w in r.json()["warnings"])
    assert a.put("/api/outreach/settings", {"daily_limit": 5, "intro_daily": 9}).json()["intro_daily"] == 5  # intro can never exceed the daily limit
    for bad in ({"daily_limit": -1}, {"delivery_mode": "BLAST"}, {"pacing_seconds": [5, 1]}, {"max_followups": 9}, {"tone": "rude"}, {"lawful_use_ack": "x"}, {"nonsense": 1}):
        assert a.put("/api/outreach/settings", bad).status_code == 422, bad
    s = a.get("/api/outreach/settings").json()
    assert s["hard_max_daily"] == 100 and s["defaults"]["daily_limit"] == 20 and "gmail.send" in s["scopes_explained"] and s["gmail"]["connected"] is False


def test_global_pause_and_campaign_pause(env, mk):
    a = mk("a@example.com")
    prep(a)
    camp = a.post("/api/campaigns", {"name": "June push", "daily_limit": 5}).json()
    assert a.post("/api/campaigns", {"name": "x", "daily_limit": 99}).status_code == 422  # can only lower the account limit
    gen(a, campaign_id=camp["id"])
    approve_emails(a)
    a.post("/api/outreach/pause", {"paused": True})
    r = a.post("/api/outreach/send", {}).json()
    assert r["sent"] == 0 and r["held"][0]["codes"] == ["GLOBAL_PAUSE"] and not outbox(a) and all(m["send_state"] == "queued" for m in emails_(a))
    a.post("/api/outreach/pause", {"paused": False})
    a.post(f"/api/campaigns/{camp['id']}/pause", {"paused": True})
    r = a.post("/api/outreach/send", {}).json()
    assert r["sent"] == 0 and {c for h in r["held"] for c in h["codes"]} == {"CAMPAIGN_PAUSED"}
    a.post(f"/api/campaigns/{camp['id']}/pause", {"paused": False})
    assert a.post("/api/outreach/send", {}).json()["sent"] == 2


def test_sends_are_paced_with_a_random_delay_between_them_not_before_the_first(env, mk):
    a = mk("a@example.com")
    prep(a, pacing_seconds=[30, 120])
    gen(a)
    approve_emails(a)
    waits = []
    db = scoped(a)
    r = osend.send_outbox(db, osettings.get(db), sleep=waits.append, rng=lambda lo, hi: (lo + hi) / 2)
    db.commit()
    assert r["sent"] == 2 and waits == [75.0]


# ---------------------------------------------------------------- ambiguous and failed sends (acceptance 8)
def test_scenario_ambiguous_result_is_unconfirmed_never_resent_and_can_be_reconciled(env, mk):
    a = mk("a@example.com")
    prep(a)
    gen(a)
    m = by_to(a, "pat@acme-test.example.com")
    approve_ids(a, [m["id"]])
    providers.mock_state(uid(a)).mode = "timeout_delivered"  # it WAS delivered, but we never heard back
    r = a.post("/api/outreach/send", {}).json()
    assert r["unconfirmed"] == 1 and r["sent"] == 0
    d = a.get(f"/api/outreach/messages/{m['id']}").json()
    assert d["send_state"] == "delivery_unconfirmed" and d["pair_status"] == "DELIVERY_UNCONFIRMED"
    providers.mock_state(uid(a)).mode = "ok"
    assert a.post("/api/outreach/send", {}).json()["sent"] == 0 and len(outbox(a)) == 1  # no automatic re-send: exactly one copy exists
    rec = a.post(f"/api/outreach/messages/{m['id']}/reconcile", {}).json()
    assert rec["found"] is True and a.get(f"/api/outreach/messages/{m['id']}").json()["send_state"] == "sent"


def test_unconfirmed_not_found_requires_a_deliberate_manual_decision(env, mk):
    a = mk("a@example.com")
    prep(a)
    gen(a)
    m = by_to(a, "pat@acme-test.example.com")
    approve_ids(a, [m["id"]])
    providers.mock_state(uid(a)).mode = "timeout_lost"
    a.post("/api/outreach/send", {})
    providers.mock_state(uid(a)).mode = "ok"
    assert a.post(f"/api/outreach/messages/{m['id']}/reconcile", {}).json()["found"] is False and not outbox(a)
    assert a.post(f"/api/outreach/messages/{m['id']}/resolve", {"outcome": "maybe"}).status_code == 409
    a.post(f"/api/outreach/messages/{m['id']}/resolve", {"outcome": "not_sent"})
    d = a.get(f"/api/outreach/messages/{m['id']}").json()
    assert d["approval_state"] == "awaiting_approval" and d["send_state"] == "not_sent" and not outbox(a)  # back to review, nothing re-queued
    assert a.post("/api/outreach/send", {}).json()["sent"] == 0
    approve_ids(a, [m["id"]])
    assert a.post("/api/outreach/send", {}).json()["sent"] == 1 and len(outbox(a)) == 1
    assert a.post(f"/api/outreach/messages/{m['id']}/reconcile", {}).status_code == 409  # only unconfirmed ones can be reconciled


def test_unconfirmed_sends_count_toward_the_daily_limit(env, mk):
    a = mk("a@example.com")
    prep(a, daily_limit=1)
    gen(a)
    approve_emails(a)
    providers.mock_state(uid(a)).mode = "timeout_delivered"
    r = a.post("/api/outreach/send", {}).json()
    assert r["unconfirmed"] == 1 and r["held"][0]["codes"] == ["DAILY_LIMIT"]


def test_hard_failure_is_reported_as_failed_not_unconfirmed(env, mk):
    a = mk("a@example.com")
    prep(a)
    gen(a)
    m = by_to(a, "pat@acme-test.example.com")
    approve_ids(a, [m["id"]])
    providers.mock_state(uid(a)).mode = "hard_fail"
    r = a.post("/api/outreach/send", {}).json()
    d = a.get(f"/api/outreach/messages/{m['id']}").json()
    assert r["failed"] == 1 and d["send_state"] == "failed" and d["pair_status"] == "APPROVED" and d["last_block"][0]["code"] == "SEND_FAILED" and not outbox(a)
    providers.mock_state(uid(a)).mode = "ok"
    assert a.post("/api/outreach/send", {}).json()["sent"] == 0  # a failure is not retried behind your back
    approve_ids(a, [m["id"]])  # re-approving is the deliberate retry
    assert a.post("/api/outreach/send", {}).json()["sent"] == 1


# ---------------------------------------------------------------- LinkedIn is always manual (acceptance 9)
def test_scenario_linkedin_messages_are_never_sent_by_the_app(env, mk):
    a = mk("a@example.com")
    prep(a)
    gen(a)
    li_ids = [m["id"] for m in linkedin_(a)]
    approve_ids(a, li_ids)
    assert {m["send_state"] for m in linkedin_(a)} == {"manual_pending"}
    r = a.post("/api/outreach/send", {}).json()
    assert r["sent"] == 0 and not outbox(a) and {m["send_state"] for m in linkedin_(a)} == {"manual_pending"}
    db = scoped(a)
    res = osend.evaluate(db, db.get(OutreachMessage, li_ids[0]), osettings.get(db), "send")
    assert "CHANNEL_NOT_SENDABLE" in {b["code"] for b in res["blocks"]}
    d = a.get(f"/api/outreach/messages/{li_ids[0]}").json()
    assert d["body"] and d["connect_note"] and d["to_linkedin_url"] and d["mailto"] is None  # copy buttons + profile link, nothing to auto-send
    m = a.post(f"/api/outreach/messages/{li_ids[0]}/mark-sent", {}).json()
    assert m["send_state"] == "manual_sent" and m["pair_status"] == "SENT"
    assert a.post(f"/api/outreach/messages/{li_ids[0]}/mark-sent", {}).status_code == 409
    assert a.post(f"/api/outreach/messages/{linkedin_(a)[1]['id']}/mark-sent", {}).json()["send_state"] == "manual_sent"  # each approved message is marked on its own


def test_marking_sent_requires_approval_first(env, mk):
    a = mk("a@example.com")
    prep(a)
    gen(a)
    assert a.post(f"/api/outreach/messages/{linkedin_(a)[0]['id']}/mark-sent", {}).status_code == 409


# ---------------------------------------------------------------- Gmail not connected / manual / dry-run (acceptance 11)
def test_scenario_without_gmail_drafting_and_manual_mode_still_work(env, mk):
    a = mk("a@example.com")
    prep(a, connect=False)
    gen(a)
    approve_emails(a)
    r = a.post("/api/outreach/send", {}).json()
    assert r["sent"] == 0 and r["held"][0]["codes"] == ["NO_PROVIDER"] and not outbox(a)  # integration mode: nothing without a connected account
    settings_(a, delivery_mode="MANUAL_REVIEW")
    m = emails_(a)[0]
    a.post(f"/api/outreach/messages/{m['id']}/reject", {})
    gen(a)  # rejected message's person can be drafted again
    m2 = [x for x in emails_(a) if x["approval_state"] == "awaiting_approval"][0]
    approve_ids(a, [m2["id"]])
    d = a.get(f"/api/outreach/messages/{m2['id']}").json()
    assert d["send_state"] == "manual_pending" and d["mailto"].startswith("mailto:") and "subject=" in d["mailto"]
    eml = a.get(f"/api/outreach/messages/{m2['id']}/eml")
    assert eml.status_code == 200 and b"From: Alex Example <alex.example@example.com>" in eml.content and b"Message-ID:" in eml.content
    assert a.post(f"/api/outreach/messages/{m2['id']}/mark-sent", {}).json()["send_state"] == "manual_sent"
    assert a.post("/api/outreach/send", {}).json()["sent"] == 0 and not outbox(a)


def test_dry_run_executes_everything_but_delivers_nothing(env, mk):
    a = mk("a@example.com")
    prep(a, mode="DRY_RUN", connect=False)
    gen(a)
    approve_emails(a)
    r = a.post("/api/outreach/send", {}).json()
    assert r["dry_run"] == 2 and r["sent"] == 0 and not outbox(a)
    assert {m["send_state"] for m in emails_(a)} == {"dry_run"}
    ev = a.get(f"/api/outreach/messages/{emails_(a)[0]['id']}/events").json()
    assert "DRY_RUN" in {e["type"] for e in ev} and "SENT" not in {e["type"] for e in ev}
    assert a.post("/api/outreach/send", {}).json()["dry_run"] == 0
    t = a.post("/api/email/test-send", {}).json()
    assert t["ok"] and t["provider"] == "dry_run" and not outbox(a)


def test_test_email_goes_only_to_the_users_own_address(env, mk):
    a = mk("a@example.com")
    prep(a)
    t = a.post("/api/email/test-send", {}).json()
    assert t["ok"] and t["to"] == "alex.example@example.com" and [o["to"] for o in outbox(a)] == ["alex.example@example.com"]
    assert parse(outbox(a)[0])["Subject"] == "ReferralOS test email"
    c = mk("c@example.com")
    assert c.post("/api/email/test-send", {}).status_code == 409  # no sender identity set yet


# ---------------------------------------------------------------- acknowledgements, jurisdictions, provenance
def test_lawful_use_acknowledgement_gates_sending(env, mk):
    a = mk("a@example.com")
    prep(a, ack=False)
    gen(a)
    approve_emails(a)
    r = a.post("/api/outreach/send", {}).json()
    assert r["sent"] == 0 and {c for h in r["held"] for c in h["codes"]} == {"ACK_REQUIRED"}
    assert a.post("/api/outreach/acknowledge", {"kind": "nonsense"}).status_code == 422
    a.post("/api/outreach/acknowledge", {"kind": "lawful_use"})
    assert a.post("/api/outreach/send", {}).json()["sent"] == 2


def test_consent_region_needs_its_own_acknowledgement_and_shows_guidance(env, mk):
    a = mk("a@example.com")
    jobs = prep(a, hr=[])
    ec = a.post("/api/email-contacts", {"name": "Uma Recruiter", "email": "uma@acme-test.co.uk", "company": "Acme Test Co"}).json()
    m = a.post("/api/outreach/email-draft", {"email_contact_id": ec["id"], "job_id": jobs["Backend Engineer"]["id"]}).json()
    assert any(f["code"] == "JURISDICTION" and "not legal advice" in f["detail"] for f in m["risk_flags"]) and m["region_guidance"]["region"] == "GB" and m["region_guidance"]["requires_extra_ack"] is True
    approve_ids(a, [m["id"]])
    r = a.post("/api/outreach/send", {}).json()
    assert r["sent"] == 0 and r["held"][0]["codes"] == ["CONSENT_REGION_ACK_REQUIRED"]
    g = a.get("/api/outreach/guidance?region=GB").json()
    assert g["requires_extra_ack"] and "PECR" in g["text"] and "not legal advice" in g["disclaimer"]
    assert a.get("/api/outreach/guidance?region=IN").json()["text"].count("TRAI") == 1
    a.post("/api/outreach/acknowledge", {"kind": "region:GB"})
    assert a.post("/api/outreach/send", {}).json()["sent"] == 1


def test_purchased_list_contacts_are_manual_one_offs_only(env, mk):
    a = mk("a@example.com")
    jobs = prep(a, hr=[])
    do_import(a, sc.to_csv(sc.HR_HEADER, [["Acme Test Co", "Bought Lead", "Recruiter", "lead@acme-test.example.com", "", "", "", ""]], preamble=""), kind="hr", provenance="purchased")  # noqa: F405
    g = gen(a)
    assert emails_(a) == [] and any("purchased" in s["why"] for s in g["skipped"])             # never part of a batch
    ec = a.get("/api/email-contacts?q=bought").json()["items"][0]
    m = a.post("/api/outreach/email-draft", {"email_contact_id": ec["id"], "job_id": jobs["Backend Engineer"]["id"]}).json()  # a deliberate one-off is allowed
    assert any(f["code"] == "BULK_BLOCKED" and f["severity"] == "high" for f in m["risk_flags"])
    approve_ids(a, [m["id"]])
    r = a.post("/api/outreach/send", {}).json()
    assert r["sent"] == 0 and r["blocked"][0]["codes"] == ["BULK_BLOCKED_PROVENANCE"] and not outbox(a)
    settings_(a, delivery_mode="MANUAL_REVIEW")
    m2 = a.post(f"/api/outreach/messages/{m['id']}/mark-sent", {}).json()
    assert m2["send_state"] == "manual_sent"


def test_exclude_company_skips_waiting_messages_and_future_batches(env, mk):
    a = mk("a@example.com")
    prep(a)
    gen(a)
    cid = a.get("/api/companies").json()["items"][0]["id"]
    assert a.post("/api/outreach/exclude-company", {"company_id": cid}).json()["messages_skipped"] == 5
    assert {m["approval_state"] for m in msgs(a)} == {"skipped"} and gen(a)["messages"] == []


def test_linkedin_adapter_is_a_disabled_stub_and_nothing_references_it():
    from pathlib import Path
    from app.adapters.linkedin_stub import LinkedInMessaging
    assert LinkedInMessaging.enabled is False and "manual send only" in LinkedInMessaging.reason
    with pytest.raises(NotImplementedError):
        LinkedInMessaging().send("hi")
    users = [p for p in Path("app").rglob("*.py") if "linkedin_stub" in p.read_text(encoding="utf-8") and p.name != "linkedin_stub.py"]
    assert users == []  # no code path can reach it


def test_no_module_other_than_the_providers_can_deliver_email():
    """Sending is only possible through providers.* via send.send_outbox / the self-addressed test email."""
    from pathlib import Path
    senders = sorted(str(p.as_posix()) for p in Path("app").rglob("*.py") if ".send(" in p.read_text(encoding="utf-8") and "providers.py" not in p.name and "linkedin_stub" not in p.name)
    assert senders == ["app/api/outreach.py", "app/services/outreach/send.py"]


# ---------------------------------------------------------------- sending is a background job and can never double-send
def test_claiming_a_message_is_atomic(env, mk):
    a = mk("a@example.com")
    prep(a)
    gen(a)
    approve_emails(a)
    mid = emails_(a)[0]["id"]
    s1, s2 = scoped(a), scoped(a)  # two runners that both loaded the same queued message
    m1, m2 = s1.get(OutreachMessage, mid), s2.get(OutreachMessage, mid)
    assert m1.send_state == m2.send_state == "queued"
    assert osend.claim(s1, m1) is True
    assert osend.claim(s2, m2) is False  # the second runner loses, even though its copy still says "queued"


def test_two_sender_runs_deliver_each_email_once(env, mk):
    a = mk("a@example.com")
    prep(a)
    gen(a)
    approve_emails(a)
    s1, s2 = scoped(a), scoped(a)
    cfg = osettings.get(s1)
    r1 = osend.send_outbox(s1, cfg, commit_each=True)
    r2 = osend.send_outbox(s2, cfg, commit_each=True)
    assert r1["sent"] == 2 and r2["sent"] == 0 and len(outbox(a)) == 2


def test_send_runs_as_a_background_task_not_inside_the_request(env, mk, monkeypatch):
    from app import tasks
    from app.config import get_settings
    a = mk("a@example.com")
    prep(a)
    gen(a)
    approve_emails(a)
    monkeypatch.setenv("TASKS_INLINE", "0")
    get_settings.cache_clear()
    try:
        r = a.post("/api/outreach/send", {})
        assert r.status_code == 202 and r.json()["task_status"] == "queued" and "sent" not in r.json() and not outbox(a)  # accepted, nothing sent yet
        again = a.post("/api/outreach/send", {}).json()
        assert again["task_id"] == r.json()["task_id"]  # a second click joins the running job instead of starting another
        assert tasks.run_task() is True  # the worker picks it up
        t = a.get(f"/api/tasks/{r.json()['task_id']}").json()
        assert t["status"] == "done" and t["result"]["sent"] == 2 and len(outbox(a)) == 2
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()


def test_long_pacing_keeps_the_task_heartbeat_alive(env):
    from app.services.outreach.send_task import heartbeat_sleep
    beats, slept = [], []
    ctx = type("C", (), {"update": lambda self, **k: beats.append(1)})()
    import time as _t
    real = _t.sleep
    _t.sleep = lambda s: slept.append(s)  # no real waiting
    try:
        mono = iter(x * 20.0 for x in range(0, 100))
        orig_mono = _t.monotonic
        _t.monotonic = lambda: next(mono)
        heartbeat_sleep(ctx, chunk=20.0)(60)
    finally:
        _t.sleep, _t.monotonic = real, orig_mono
    assert len(beats) >= 2 and all(s <= 20.0 for s in slept)  # a 60 s pause is slept in short chunks, refreshing the heartbeat each time
