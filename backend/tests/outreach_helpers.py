"""Shared setup for outreach tests: a complete synthetic user (profile, verified jobs, LinkedIn + HR contacts, settings)."""
import email as emaillib

import pytest

from app.adapters import fake_ats
from app.db import new_session
from app.services.outreach import providers, settings as osettings
from tests import synth_contacts as sc
from tests.test_imports import do_import
from tests.test_matching_api import ACME_CONTACTS, li
from tests.test_tailoring_api import profile as build_profile

HR_ROWS = [["Acme Test Co", "Pat Recruiter", "Technical Recruiter", "pat@acme-test.example.com", "", "", "", ""],
           ["Acme Test Co", "Lee Talent", "Recruiter", "lee@acme-test.example.com", "", "", "", ""]]


@pytest.fixture(autouse=True)
def _reset_world():
    fake_ats.reset()
    providers.reset_mock()
    yield
    fake_ats.reset()
    providers.reset_mock()


def uid(a) -> str:
    return a.get("/api/auth/me").json()["id"]


def scoped(a):
    return new_session(uid(a))


def settings_(a, **kw):
    base = {"sender_name": "Alex Example", "sender_email": "alex.example@example.com", "pacing_seconds": [0, 0]}
    r = a.put("/api/outreach/settings", {**base, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def prep(a, *, mode="AUTHORISED_INTEGRATION", ack=True, connect=True, hr=HR_ROWS, linkedin=ACME_CONTACTS, suppress=(), **settings):
    build_profile(a)
    a.post("/api/boards", {"company": "Acme Test Co", "ats": "greenhouse", "token": "acme-test"})
    if linkedin:
        do_import(a, li(linkedin))
    if hr:
        do_import(a, sc.to_csv(sc.HR_HEADER, hr, preamble=""), kind="hr", provenance="self_collected")
    for e in suppress:
        a.post("/api/suppression", {"value": e, "reason": "do_not_contact"})
    a.post("/api/jobs/discover", {})
    settings_(a, delivery_mode=mode, **settings)
    if ack:
        a.post("/api/outreach/acknowledge", {"kind": "lawful_use"})
    if connect:
        assert a.put("/api/consents/gmail", {"granted": True}).status_code == 200
        assert a.post("/api/email/gmail/mock-connect", {"email": "alex.example@example.com"}).status_code == 200
    a.post("/api/matching/run", {})
    return {j["title"]: j for j in a.get("/api/jobs?page_size=50").json()["items"]}


def gen(a, **body):
    r = a.post("/api/outreach/generate", body)
    assert r.status_code == 201, r.text
    return r.json()


def msgs(a, **q):
    qs = "&".join(f"{k}={v}" for k, v in q.items())
    return a.get(f"/api/outreach/messages?page_size=200&{qs}").json()["items"]


def emails_(a):
    return [m for m in msgs(a) if m["channel"] == "email"]


def linkedin_(a):
    return [m for m in msgs(a) if m["channel"] == "linkedin"]


def approve_ids(a, ids):
    for i in ids:
        r = a.post(f"/api/outreach/messages/{i}/approve", {})
        assert r.status_code == 200, r.text


def approve_emails(a):
    approve_ids(a, [m["id"] for m in emails_(a)])


def outbox(a):
    return providers.mock_state(uid(a)).sent


def parse(rec):
    return emaillib.message_from_bytes(rec["mime"])


def by_to(a, addr):
    return next(m for m in emails_(a) if m["to_email"] == addr)
