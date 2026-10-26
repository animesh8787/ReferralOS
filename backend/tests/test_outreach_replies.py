import base64
import email as emaillib
import json
from datetime import timedelta
from types import SimpleNamespace

import httpx
import pytest

from app import crypto
from app.adapters import http as http_mod
from app.config import get_settings
from app.models.outreach import OAuthToken, OutreachMessage
from app.services.outreach import providers, replies
from app.util import utcnow
from tests.outreach_helpers import *  # noqa: F401,F403
from tests.outreach_helpers import _reset_world  # noqa: F401


def sent_pair(a, **kw):
    jobs = prep(a, **kw)
    gen(a)
    approve_emails(a)
    assert a.post("/api/outreach/send", {}).json()["sent"] == 2
    return jobs, {m["to_email"]: m["id"] for m in emails_(a)}


def age(a, days):
    db = scoped(a)
    for m in db.query(OutreachMessage).filter(OutreachMessage.sent_at.isnot(None)).all():
        m.sent_at -= timedelta(days=days)
    db.commit()


def suppressed(a):
    return {s["value"]: s["reason"] for s in a.get("/api/suppression").json()["items"]}


def pair_of(a, mid):
    return a.get(f"/api/outreach/messages/{mid}").json()["pair_status"]


# ---------------------------------------------------------------- classification
@pytest.mark.parametrize("text,frm,label", [
    ("Delivery Status Notification (Failure) 550 5.1.1 user unknown", "mailer-daemon@x.com", "bounce_hard"),
    ("Undeliverable: no such user here", "postmaster@x.com", "bounce_hard"),
    ("Your mailbox is full, try again later", "mailer-daemon@x.com", "bounce_soft"),
    ("Mail delivery failed. Details unavailable.", "mailer-daemon@x.com", "bounce_soft"),   # unreadable delivery notice: never suppress on the sender alone
    ("550 5.1.1 The email account that you tried to reach does not exist", "mailer-daemon@x.com", "bounce_hard"),
    ("I am out of the office until Monday. This is an automatic reply.", "a@x.com", "ooo"),
    ("Please unsubscribe me from your emails", "a@x.com", "unsubscribe"),
    ("Stop emailing me.", "a@x.com", "unsubscribe"),
    ("Happy to refer you, send your resume", "a@x.com", "referral_offered"),
    ("Unfortunately we are not hiring at the moment", "a@x.com", "negative"),
    ("Sure, let's chat next week", "a@x.com", "positive"),
    ("Thanks for reaching out.", "a@x.com", "neutral"),
])
def test_reply_classification_rules(text, frm, label):
    assert replies.classify(text, frm)[0] == label


# ---------------------------------------------------------------- replies, bounces, opt-outs
def test_a_real_reply_cancels_followups_and_moves_the_pair(env, mk):
    a = mk("a@example.com")
    _, ids = sent_pair(a)
    lee = ids["lee@acme-test.example.com"]
    assert a.post(f"/api/outreach/messages/{lee}/reply", {"from_addr": "lee@acme-test.example.com", "subject": "Re: role", "body": "Sure, happy to chat. Send your resume."}).json()["label"] == "positive"
    assert pair_of(a, lee) == "REPLIED"
    r = a.post(f"/api/outreach/messages/{ids['pat@acme-test.example.com']}/reply", {"body": "I'm happy to refer you!"}).json()
    assert r["label"] == "referral_offered" and pair_of(a, ids["pat@acme-test.example.com"]) == "REFERRAL_OFFERED"
    age(a, 8)
    assert a.post("/api/outreach/followups/scan", {}).json()["drafts_created"] == []  # both replied: nothing to chase


def test_reply_to_an_unsent_message_is_rejected(env, mk):
    a = mk("a@example.com")
    prep(a)
    gen(a)
    assert a.post(f"/api/outreach/messages/{emails_(a)[0]['id']}/reply", {"body": "hi"}).status_code == 409


def test_hard_bounce_suppresses_automatically_and_stops_everything(env, mk):
    a = mk("a@example.com")
    _, ids = sent_pair(a)
    pat = ids["pat@acme-test.example.com"]
    r = a.post(f"/api/outreach/messages/{pat}/reply", {"from_addr": "mailer-daemon@googlemail.com", "subject": "Delivery Status Notification (Failure)", "body": "550 5.1.1 user unknown"}).json()
    assert r["label"] == "bounce_hard" and r["automatic"] == ["address suppressed"]
    assert suppressed(a) == {"pat@acme-test.example.com": "bounced"} and pair_of(a, pat) == "DO_NOT_CONTACT"
    assert [e["type"] for e in a.get(f"/api/outreach/messages/{pat}/events").json()][-1] == "BOUNCED_HARD"


def test_ooo_and_soft_bounce_are_not_replies(env, mk):
    a = mk("a@example.com")
    _, ids = sent_pair(a)
    lee = ids["lee@acme-test.example.com"]
    assert a.post(f"/api/outreach/messages/{lee}/reply", {"from_addr": "lee@x.com", "body": "I am out of office until 3 June. Automatic reply."}).json()["label"] == "ooo"
    assert pair_of(a, lee) == "SENT" and suppressed(a) == {}
    assert a.post(f"/api/outreach/messages/{lee}/reply", {"from_addr": "mailer-daemon@x", "body": "Mailbox is full. Try again later."}).json()["label"] == "bounce_soft"
    assert pair_of(a, lee) == "SENT" and suppressed(a) == {}
    age(a, 8)
    assert len(a.post("/api/outreach/followups/scan", {}).json()["drafts_created"]) == 2  # still waiting for a human answer


def test_opt_out_is_a_suggestion_until_the_user_confirms(env, mk):
    a = mk("a@example.com")
    _, ids = sent_pair(a)
    pat = ids["pat@acme-test.example.com"]
    r = a.post(f"/api/outreach/messages/{pat}/reply", {"from_addr": "pat@acme-test.example.com", "body": "Please unsubscribe me, stop emailing."}).json()
    assert r["label"] == "unsubscribe" and "Confirm" in r["needs_confirmation"] and suppressed(a) == {}  # NOT suppressed yet
    assert pair_of(a, pat) == "REPLIED"
    ev = [e for e in a.get(f"/api/outreach/messages/{pat}/events").json() if e["type"] == "UNSUBSCRIBE_REQUESTED"][0]
    assert ev["confirmed"] is None
    assert a.post(f"/api/outreach/events/{ev['id']}/confirm", {"confirmed": False}).json() == {"suppressed": False} and suppressed(a) == {}
    assert a.post(f"/api/outreach/events/{ev['id']}/confirm", {"confirmed": True}).json() == {"suppressed": True}
    assert suppressed(a) == {"pat@acme-test.example.com": "unsubscribed"} and pair_of(a, pat) == "DO_NOT_CONTACT"
    other = a.get(f"/api/outreach/messages/{ids['lee@acme-test.example.com']}/events").json()[0]
    assert a.post(f"/api/outreach/events/{other['id']}/confirm", {"confirmed": True}).status_code == 409  # only opt-out requests can be confirmed


def test_the_user_can_correct_a_classification(env, mk):
    a = mk("a@example.com")
    _, ids = sent_pair(a)
    lee = ids["lee@acme-test.example.com"]
    a.post(f"/api/outreach/messages/{lee}/reply", {"body": "Unfortunately not hiring."})
    ev = [e for e in a.get(f"/api/outreach/messages/{lee}/events").json() if e["label"] == "negative"][0]
    assert a.patch(f"/api/outreach/events/{ev['id']}", {"label": "positive"}).json()["label"] == "positive"
    assert a.patch(f"/api/outreach/events/{ev['id']}", {"label": "weird"}).status_code == 422
    assert [e for e in a.get(f"/api/outreach/messages/{lee}/events").json() if e["id"] == ev["id"]][0]["detail"]["relabelled_by_user"] is True


# ---------------------------------------------------------------- follow-ups: drafts only, capped, spaced, cancellable
def test_follow_ups_are_drafted_for_approval_after_the_spacing_and_never_sent_silently(env, mk):
    a = mk("a@example.com")
    _, ids = sent_pair(a)
    assert a.post("/api/outreach/followups/scan", {}).json()["drafts_created"] == []  # too soon
    assert {s["why"] for s in a.post("/api/outreach/followups/scan", {}).json()["skipped"]} == {"too soon"}
    age(a, 8)
    r = a.post("/api/outreach/followups/scan", {}).json()
    assert len(r["drafts_created"]) == 2 and not outbox(a)[2:]
    fu = [m for m in emails_(a) if m["kind"] == "follow_up"]
    assert all(m["approval_state"] == "awaiting_approval" and m["send_state"] == "not_sent" and m["subject"].startswith("Follow-up: ") and not m["is_initial"] for m in fu)
    d = a.get(f"/api/outreach/messages/{fu[0]['id']}").json()
    assert "unsubscribe" in d["body"] and "04 " not in d["body"] and not d["subject"].lower().startswith("re:")
    assert a.post("/api/outreach/followups/scan", {}).json()["drafts_created"] == []  # a waiting draft is not duplicated
    assert a.post("/api/outreach/send", {}).json()["sent"] == 0 and len(outbox(a)) == 2  # drafts alone never go out
    approve_ids(a, [m["id"] for m in fu])
    assert a.post("/api/outreach/send", {}).json()["sent"] == 2 and len(outbox(a)) == 4


def test_follow_ups_are_capped_per_person(env, mk):
    a = mk("a@example.com")
    sent_pair(a)
    for n in range(2):
        age(a, 8)
        made = a.post("/api/outreach/followups/scan", {}).json()["drafts_created"]
        assert len(made) == 2
        approve_ids(a, made)
        assert a.post("/api/outreach/send", {}).json()["sent"] == 2
    age(a, 8)
    r = a.post("/api/outreach/followups/scan", {}).json()
    assert r["drafts_created"] == [] and {s["why"] for s in r["skipped"]} == {"follow-up limit reached"}


def test_follow_up_spacing_is_enforced_at_send_time_too(env, mk):
    a = mk("a@example.com")
    sent_pair(a)
    age(a, 8)
    made = a.post("/api/outreach/followups/scan", {}).json()["drafts_created"]
    approve_ids(a, made)
    db = scoped(a)
    for m in db.query(OutreachMessage).filter(OutreachMessage.kind != "follow_up", OutreachMessage.send_state == "sent").all():
        m.sent_at = utcnow()  # the previous email was sent just now
    db.commit()
    r = a.post("/api/outreach/send", {}).json()
    assert r["sent"] == 0 and {c for h in r["held"] for c in h["codes"]} == {"FOLLOWUP_SPACING"}


def test_follow_ups_stop_when_the_job_closes_or_sending_is_paused(env, mk):
    a = mk("a@example.com")
    jobs, _ = sent_pair(a)
    age(a, 8)
    a.post("/api/outreach/pause", {"paused": True})
    assert {s["why"] for s in a.post("/api/outreach/followups/scan", {}).json()["skipped"]} == {"sending is paused"}
    a.post("/api/outreach/pause", {"paused": False})
    fake_ats.STATE["greenhouse"]["acme-test"] = [j for j in fake_ats.STATE["greenhouse"]["acme-test"] if j["id"] != 1001]  # noqa: F405
    a.post(f"/api/jobs/{jobs['Backend Engineer']['id']}/verify", {})
    r = a.post("/api/outreach/followups/scan", {}).json()
    assert r["drafts_created"] == [] and {s["why"] for s in r["skipped"]} == {"the job is closed"}


def test_pending_follow_up_is_cancelled_by_a_reply_after_it_was_drafted(env, mk):
    a = mk("a@example.com")
    _, ids = sent_pair(a)
    age(a, 8)
    made = a.post("/api/outreach/followups/scan", {}).json()["drafts_created"]
    a.post(f"/api/outreach/messages/{ids['lee@acme-test.example.com']}/reply", {"body": "Thanks, let's chat."})
    states = {m["to_email"]: (m["approval_state"], m["send_state"]) for m in emails_(a) if m["kind"] == "follow_up"}
    assert states["lee@acme-test.example.com"] == ("cancelled", "not_sent") and states["pat@acme-test.example.com"][0] == "awaiting_approval" and len(made) == 2
    r = a.post(f"/api/outreach/messages/{[m['id'] for m in emails_(a) if m['kind'] == 'follow_up' and m['to_email'] == 'lee@acme-test.example.com'][0]}/approve", {})
    assert r.status_code == 409


# ---------------------------------------------------------------- pipeline statuses (manual updates need evidence)
def test_pair_status_rules(env, mk):
    a = mk("a@example.com")
    _, ids = sent_pair(a)
    pair = a.get("/api/tracking/pairs?status=SENT").json()["items"][0]["id"]
    assert a.patch(f"/api/tracking/pairs/{pair}", {"status": "SENT"}).status_code == 422          # set by the app only
    assert a.patch(f"/api/tracking/pairs/{pair}", {"status": "AWAITING_APPROVAL"}).status_code == 422
    assert a.patch(f"/api/tracking/pairs/{pair}", {"status": "REFERRAL_SUBMITTED"}).status_code == 422  # no evidence
    assert a.patch(f"/api/tracking/pairs/{pair}", {"status": "REFERRAL_SUBMITTED", "evidence": "  "}).status_code == 422
    ok = a.patch(f"/api/tracking/pairs/{pair}", {"status": "REFERRAL_SUBMITTED", "evidence": "Pat confirmed by email on 3 June (ref #1234)"})
    assert ok.status_code == 200 and ok.json()["status"] == "REFERRAL_SUBMITTED"
    assert a.patch(f"/api/tracking/pairs/{pair}", {"status": "APPLICATION_SUBMITTED"}).json()["status"] == "APPLICATION_SUBMITTED"
    assert a.get("/api/tracking/pairs").json()["counts"]["APPLICATION_SUBMITTED"] == 1
    assert a.patch(f"/api/tracking/pairs/{pair}", {"status": "NONSENSE"}).status_code == 422


def test_marking_do_not_contact_cancels_pending_messages(env, mk):
    a = mk("a@example.com")
    prep(a)
    gen(a)
    approve_emails(a)
    pair = [p for p in a.get("/api/tracking/pairs?status=QUEUED").json()["items"] if p["who"] == "Pat Recruiter"][0]["id"]
    assert a.patch(f"/api/tracking/pairs/{pair}", {"status": "DO_NOT_CONTACT"}).status_code == 200
    r = a.post("/api/outreach/send", {}).json()
    assert [o["to"] for o in outbox(a)] == ["lee@acme-test.example.com"] and r["sent"] == 1
    assert by_to(a, "pat@acme-test.example.com")["approval_state"] == "cancelled"


def test_sent_pair_status_requires_a_real_send(env, mk):
    a = mk("a@example.com")
    prep(a)
    gen(a)
    db = scoped(a)
    from app.models.outreach import OutreachPair
    from app.services.outreach import send as osend
    p = db.query(OutreachPair).first()
    with pytest.raises(ValueError):
        osend.set_pair(db, p, "SENT")


# ---------------------------------------------------------------- Gmail adapter (verified against mock HTTP only)
def gmail(handler, **tok):
    t = SimpleNamespace(encrypted_access=crypto.encrypt("access-1"), encrypted_refresh=crypto.encrypt("refresh-1"), expires_at=utcnow() + timedelta(hours=1), **tok)
    return providers.GmailProvider(t, httpx.Client(transport=httpx.MockTransport(handler)), "cid", "secret"), t


def test_gmail_send_request_shape_and_ok_result(env):
    seen = {}

    def h(req):
        seen["auth"], seen["url"], seen["json"] = req.headers["authorization"], str(req.url), json.loads(req.content)
        return httpx.Response(200, json={"id": "gm-1", "threadId": "th-1"})

    p, _ = gmail(h)
    mime, rid = providers.build_mime("Alex Example", "alex@example.com", "pat@x.example.com", "Subject", "Body", ("resume.pdf", b"%PDF-1.4 fake"))
    r = p.send("u", mime, rid, "pat@x.example.com")
    assert r.ok and r.provider_message_id == "gm-1" and r.thread_id == "th-1"
    assert seen["auth"] == "Bearer access-1" and seen["url"] == "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
    em = emaillib.message_from_bytes(base64.urlsafe_b64decode(seen["json"]["raw"]))
    assert em["From"] == "Alex Example <alex@example.com>" and em["To"] == "pat@x.example.com" and em["Message-ID"] == rid
    assert [x.get_filename() for x in em.walk() if x.get_filename()] == ["resume.pdf"]


@pytest.mark.parametrize("resp,kind", [
    (lambda r: httpx.Response(401, json={"error": "invalid_grant"}), "hard"),
    (lambda r: httpx.Response(400, json={"error": "bad recipient"}), "hard"),
    (lambda r: httpx.Response(403, json={"error": {"errors": [{"reason": "rateLimitExceeded"}]}}), "hard"),
    (lambda r: httpx.Response(500, text="oops"), "ambiguous"),
    (lambda r: httpx.Response(503, text="unavailable"), "ambiguous"),
    (lambda r: httpx.Response(429, text="slow down"), "ambiguous"),
    (lambda r: httpx.Response(200, text="not json at all"), "ambiguous"),
    (lambda r: (_ for _ in ()).throw(httpx.ReadTimeout("slow")), "ambiguous"),
    (lambda r: (_ for _ in ()).throw(httpx.RemoteProtocolError("reset")), "ambiguous"),
    (lambda r: (_ for _ in ()).throw(httpx.ConnectError("refused")), "hard"),
    (lambda r: (_ for _ in ()).throw(httpx.ConnectTimeout("no route")), "hard"),
], ids=["401", "400", "403-rate", "500", "503", "429", "200-garbage", "read-timeout", "reset", "connect-error", "connect-timeout"])
def test_gmail_outcomes_are_classified_conservatively(env, resp, kind):
    p, _ = gmail(resp)
    r = p.send("u", b"x", "<id@x>", "a@b.example.com")
    assert not r.ok and r.kind == kind and r.detail  # only definite non-delivery is 'hard'; anything after the request left is 'ambiguous'


def test_gmail_refreshes_an_expiring_token_and_stores_it_encrypted(env):
    calls = []

    def h(req):
        calls.append(str(req.url))
        if "oauth2.googleapis.com/token" in str(req.url):
            body = req.content.decode()
            assert "grant_type=refresh_token" in body and "refresh-1" in body
            return httpx.Response(200, json={"access_token": "access-2", "expires_in": 3600})
        assert req.headers["authorization"] == "Bearer access-2"
        return httpx.Response(200, json={"id": "gm-2", "threadId": "t"})

    p, t = gmail(h)
    t.expires_at = utcnow() + timedelta(seconds=5)
    assert p.send("u", b"x", "<id@x>", "a@b.example.com").ok and len(calls) == 2
    assert "access-2" not in t.encrypted_access and crypto.decrypt(t.encrypted_access) == "access-2"


def test_gmail_refresh_failure_is_a_hard_non_send(env):
    p, t = gmail(lambda r: httpx.Response(400, json={"error": "invalid_grant"}))
    t.expires_at = utcnow() - timedelta(minutes=1)
    r = p.send("u", b"x", "<id@x>", "a@b.example.com")
    assert not r.ok and r.kind == "hard" and "reconnect" in r.detail.lower()


def test_gmail_finds_sent_mail_by_our_message_id_and_reads_thread_replies(env):
    def h(req):
        if req.url.path.endswith("/messages"):
            assert "rfc822msgid:abc@x" in req.url.params["q"] and "in:sent" in req.url.params["q"]
            return httpx.Response(200, json={"messages": [{"id": "gm-9", "threadId": "th-9"}]})
        return httpx.Response(200, json={"messages": [{"id": "own", "payload": {"headers": []}}, {"id": "r1", "snippet": "Happy to chat", "payload": {"headers": [{"name": "From", "value": "Pat <pat@x.example.com>"}, {"name": "Subject", "value": "Re: hi"}]}}]})

    p, _ = gmail(h)
    assert p.find_sent("u", "<abc@x>") == {"id": "gm-9", "thread": "th-9", "at": None}
    rep = p.fetch_replies("u", "th-9", None)
    assert len(rep) == 1 and rep[0]["from"].startswith("Pat") and rep[0]["body"] == "Happy to chat"
    assert p.fetch_replies("u", None, None) == []


# ---------------------------------------------------------------- OAuth, token security, reply sync
def test_tokens_are_encrypted_at_rest_and_never_exposed(env, mk):
    a = mk("a@example.com")
    prep(a)
    db = scoped(a)
    tok = db.query(OAuthToken).one()
    assert "mock-access-token" not in tok.encrypted_access and crypto.decrypt(tok.encrypted_access) == "mock-access-token"
    blob = json.dumps([a.get("/api/email/gmail/status").json(), a.get("/api/outreach/settings").json(), a.get("/api/me/export").json(), a.get("/api/tasks").json()])
    assert "mock-access-token" not in blob and "mock-refresh-token" not in blob and tok.encrypted_access not in blob and "encrypted_" not in blob
    assert a.get("/api/email/gmail/status").json()["connected"] is True
    assert a.delete("/api/email/gmail").json() == {"connected": False} and a.get("/api/email/gmail/status").json()["connected"] is False
    assert scoped(a).query(OAuthToken).count() == 0


def test_connecting_gmail_needs_consent_and_mock_connect_is_mock_only(env, mk, monkeypatch):
    a = mk("a@example.com")
    assert a.post("/api/email/gmail/mock-connect", {"email": "x@example.com"}).status_code == 403  # consent first
    a.put("/api/consents/gmail", {"granted": True})
    assert a.post("/api/email/gmail/mock-connect", {"email": "x@example.com"}).status_code == 200
    monkeypatch.setenv("ADAPTER_MODE", "real")
    get_settings.cache_clear()
    try:
        assert a.post("/api/email/gmail/mock-connect", {"email": "x@example.com"}).status_code == 404
        assert a.get("/api/email/gmail/authorize").status_code == 409  # no OAuth app configured on this server
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()


def test_real_oauth_flow_against_mock_google(env, mk, monkeypatch):
    log = []

    def google(req):
        log.append((req.method, str(req.url)))
        if "oauth2.googleapis.com/token" in str(req.url):
            assert "code_verifier=" in req.content.decode() and "code=the-code" in req.content.decode()
            return httpx.Response(200, json={"access_token": "ya29.real-looking-access", "refresh_token": "1//real-refresh", "expires_in": 3599})
        if "userinfo" in str(req.url):
            return httpx.Response(200, json={"email": "alex.example@example.com"})
        return httpx.Response(200, json={})

    a = mk("a@example.com")
    a.put("/api/consents/gmail", {"granted": True})
    monkeypatch.setenv("ADAPTER_MODE", "real")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid-123")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret-xyz")
    get_settings.cache_clear()
    monkeypatch.setattr(http_mod, "TRANSPORT_OVERRIDE", httpx.MockTransport(google))
    try:
        auth = a.get("/api/email/gmail/authorize").json()
        assert "client_id=cid-123" in auth["url"] and "code_challenge_method=S256" in auth["url"] and auth["scopes"] == ["https://www.googleapis.com/auth/gmail.send"]
        assert "gmail.readonly" not in auth["url"]  # read access only if the user opted into reply tracking
        state = [p.split("=")[1] for p in auth["url"].split("?")[1].split("&") if p.startswith("state=")][0]
        assert a.post("/api/email/gmail/callback", {"code": "the-code", "state": "wrong"}).status_code == 400
        r = a.post("/api/email/gmail/callback", {"code": "the-code", "state": state}).json()
        assert r == {"connected": True, "account": "alex.example@example.com"}
        tok = scoped(a).query(OAuthToken).one()
        assert "ya29" not in tok.encrypted_access and crypto.decrypt(tok.encrypted_refresh) == "1//real-refresh"
        s = settings_(a, delivery_mode="AUTHORISED_INTEGRATION")
        db = scoped(a)
        from app.services.outreach import send as osend
        prov, ready = osend.provider_for(db, uid(a), s)
        assert ready and prov.name == "gmail"
        a.delete("/api/email/gmail")
        assert any("oauth2.googleapis.com/revoke" in u for _, u in log)  # the grant is revoked at Google too
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()


def test_reply_tracking_is_opt_in_and_syncs_replies_from_the_thread(env, mk):
    a = mk("a@example.com")
    _, ids = sent_pair(a)
    assert a.post("/api/outreach/replies/sync", {}).status_code == 403
    assert a.put("/api/outreach/settings", {"reply_tracking": True}).status_code == 403  # consent first
    a.put("/api/consents/reply_tracking", {"granted": True})
    assert a.put("/api/outreach/settings", {"reply_tracking": True}).status_code == 200
    rec = [o for o in outbox(a) if o["to"] == "lee@acme-test.example.com"][0]
    providers.mock_state(uid(a)).replies[rec["rfc_id"]] = [{"id": "r-1", "from": "lee@acme-test.example.com", "subject": "Re: role", "body": "Happy to refer you.", "at": None}]
    assert a.post("/api/outreach/replies/sync", {}).json() == {"new_events": 1}
    assert a.post("/api/outreach/replies/sync", {}).json() == {"new_events": 0}  # idempotent
    assert pair_of(a, ids["lee@acme-test.example.com"]) == "REFERRAL_OFFERED"


# ---------------------------------------------------------------- isolation, exports, deletion
def test_outreach_is_isolated_between_users(env, mk):
    a, b = mk("a@example.com"), mk("b@example.com")
    _, ids = sent_pair(a)
    mid, bid = ids["lee@acme-test.example.com"], a.get("/api/outreach/batches").json()[0]["id"]
    for call in (b.get(f"/api/outreach/messages/{mid}"), b.get(f"/api/outreach/messages/{mid}/events"), b.get(f"/api/outreach/messages/{mid}/eml"),
                 b.post(f"/api/outreach/messages/{mid}/approve", {}), b.post(f"/api/outreach/messages/{mid}/mark-sent", {}), b.patch(f"/api/outreach/messages/{mid}", {"body": "x"}),
                 b.post(f"/api/outreach/messages/{mid}/reply", {"body": "x"}), b.get(f"/api/outreach/batches/{bid}")):
        assert call.status_code == 404, call.request.url
    assert b.get("/api/outreach/messages").json()["total"] == 0 and b.get("/api/tracking/pairs").json()["total"] == 0
    assert b.get("/api/outreach/settings").json()["sender_email"] == "" and b.get("/api/email/gmail/status").json()["connected"] is False
    a.post("/api/suppression", {"value": "someone@example.com"})
    assert b.get("/api/suppression").json()["total"] == 0  # one user's do-not-contact list never leaks into another's


def test_queue_export_is_formula_safe_and_the_account_deletion_removes_everything(env, mk):
    a = mk("a@example.com")
    prep(a)
    gen(a)
    m = by_to(a, "pat@acme-test.example.com")
    a.patch(f"/api/outreach/messages/{m['id']}", {"subject": "=HYPERLINK(\"http://evil\")"})
    csv_text = a.get("/api/exports/outreach-queue.csv").text
    assert "'=HYPERLINK" in csv_text and csv_text.splitlines()[0].startswith("Channel,Kind,Recipient")
    assert a.post("/api/me/delete", {"password": "correct-horse-9"}).status_code == 200
    db = new_session()  # noqa: F405
    from app.models.outreach import EmailEvent, OutreachBatch, OutreachPair
    for model in (OutreachMessage, OutreachPair, OutreachBatch, EmailEvent, OAuthToken):
        assert db.query(model).count() == 0, model.__name__
