import json
from datetime import timedelta

import httpx
import pytest

from app import crypto, storage
from app.adapters import http as http_mod
from app.db import new_session
from app.models.contacts import ImportBatch, ImportRow
from app.models.llm import LLMUsage
from app.services import llm, retention
from app.util import utcnow
from tests import synth_contacts as sc
from tests import synth_resumes as sr
from tests.outreach_helpers import *  # noqa: F401,F403
from tests.outreach_helpers import _reset_world  # noqa: F401


# ---------------------------------------------------------------- dashboard
def test_dashboard_for_a_new_user_guides_the_first_steps(env, mk):
    d = mk("a@example.com").get("/api/dashboard").json()
    assert d["connections"] == 0 and d["usable_coverage"]["percent"] is None and d["profile_completeness"]["score"] == 0
    assert [f["stage"] for f in d["funnel"]] == ["Jobs discovered", "Verified open", "Matched to you", "Contact identified", "Drafted", "Approved", "Sent", "Response", "Referral", "Application"]
    assert all(f["count"] == 0 for f in d["funnel"])
    assert [s["href"] for s in d["next_steps"]][:3] == ["/onboarding", "/imports", "/jobs"]


def test_dashboard_funnel_reflects_real_progress_and_never_grows_downstream(env, mk):
    a = mk("a@example.com")
    prep(a)
    gen(a)
    d = a.get("/api/dashboard").json()
    f = {x["stage"]: x["count"] for x in d["funnel"]}
    assert f["Jobs discovered"] >= f["Verified open"] >= f["Matched to you"] >= f["Contact identified"] >= 1 and f["Drafted"] == 5 and f["Approved"] == 0 and f["Sent"] == 0
    assert d["connections"] == 6 and d["hr_contacts"] == 2 and d["usable_coverage"]["percent"] == 100 and d["ranked_prospects"] == 6 and d["drafts_awaiting_approval"] == 5
    approve_emails(a)
    a.post("/api/outreach/send", {})
    mid = by_to(a, "lee@acme-test.example.com")["id"]
    a.post(f"/api/outreach/messages/{mid}/reply", {"body": "Happy to refer you, send your resume."})
    d = a.get("/api/dashboard").json()
    f = {x["stage"]: x["count"] for x in d["funnel"]}
    assert (f["Approved"], f["Sent"], f["Response"], f["Referral"]) == (2, 2, 1, 1) and d["sent"] == 2 and d["replies"] == 1 and d["referrals_offered"] == 1
    assert any("Review 3" in s["text"] for s in d["next_steps"])


# ---------------------------------------------------------------- diagnostics
def test_diagnostics_show_what_was_read_and_why_rows_were_rejected(env, mk):
    a = mk("a@example.com")
    a.upload(sr.pdf_single())
    a.upload(sr.pdf_image_only(), "scan.pdf")
    rows = [["Alex", "Banson", "https://www.linkedin.com/in/synthetic-1", "", "Acme Test Co", "", "someday", "extra"], ["", "", "", "", "", "", "", ""]]
    hdr = sc.LI_HEADER + ["Notes"]
    do_import(a, sc.to_csv(hdr, rows, preamble=""))  # noqa: F405
    d = a.get("/api/diagnostics").json()
    good = [r for r in d["resumes"] if r["filename"] == "resume.pdf"][0]
    scan = [r for r in d["resumes"] if r["filename"] == "scan.pdf"][0]
    assert good["parser"] == "pymupdf" and good["items_extracted"] > 8 and 0 < good["mean_confidence"] <= 1 and "experience" in good["sections_found"]
    assert scan["image_only"] is True and "OCR" in scan["warnings"][0] and scan["items_extracted"] == 0
    imp = d["imports"][0]
    assert imp["unmapped_columns"] == ["Notes"] and imp["rows"] == {"valid": 1, "invalid": 1} and imp["rejected_reasons"]["empty_row"] == 1 and "company" in imp["mapped"]
    assert imp["encoding"] == "utf-8" and imp["header_line"] == 1


def test_diagnostics_integration_health_is_honest_about_what_was_verified(env, mk):
    a = mk("a@example.com")
    prep(a)
    d = a.get("/api/diagnostics").json()
    ints = {i["name"].split(" ")[0]: i for i in d["integrations"]}
    assert "mock HTTP only" in ints["Gmail"]["verified_against"] and "fixtures" in ints["GitHub"]["verified_against"] and ints["Job"]["state"] == "1 configured"
    assert ints["LinkedIn"]["state"] == "disabled by design" and d["jobs"]["sources_seen"]["greenhouse"] == 2 and d["jobs"]["boards"][0]["status"] == "ok"


# ---------------------------------------------------------------- onboarding, notifications, sources
def test_onboarding_progress_is_saved_and_validated(env, mk):
    a = mk("a@example.com")
    o = a.get("/api/onboarding").json()
    assert o["step"] == "resume" and o["done"] is False and o["steps"][0] == "account"
    assert a.put("/api/onboarding", {"step": "preferences", "skipped": ["links", "bogus"]}).json()["skipped"] == ["links"]
    assert a.get("/api/onboarding").json()["step"] == "preferences" and a.put("/api/onboarding", {"step": "nope"}).status_code == 422
    assert a.put("/api/onboarding", {"done": True}).json()["done"] is True


def test_notification_and_source_preferences(env, mk):
    a = mk("a@example.com")
    assert a.get("/api/settings/notifications").json()["replies"] is True
    assert a.put("/api/settings/notifications", {"replies": False}).json()["replies"] is False and a.put("/api/settings/notifications", {"spam": True}).status_code == 422
    assert a.get("/api/settings/sources").json()["lever"] is True and a.put("/api/settings/sources", {"taleo": True}).status_code == 422


def test_disabled_job_source_is_skipped_and_reported(env, mk):
    a = mk("a@example.com")
    a.post("/api/boards", {"company": "Acme Test Co", "ats": "greenhouse", "token": "acme-test"})
    a.post("/api/boards", {"company": "Globex Example", "ats": "lever", "token": "globex-test"})
    a.put("/api/settings/sources", {"greenhouse": False})
    r = a.post("/api/jobs/discover", {}).json()["result"]
    assert r["reachable"] == 1 and r["jobs_seen"] == 1
    run = a.get("/api/jobs/discovery-runs").json()[0]
    assert [c["error"] for c in run["coverage"] if c["ats"] == "greenhouse"] == ["Source disabled in your settings"]
    a.put("/api/settings/sources", {"greenhouse": True})
    assert a.post("/api/jobs/discover", {}).json()["result"]["reachable"] == 2


# ---------------------------------------------------------------- privacy and retention
def test_privacy_summary_and_retention_purge(env, mk):
    a = mk("a@example.com")
    prev, _ = do_import(a, sc.linkedin_csv(5))  # noqa: F405
    s = a.get("/api/privacy/summary").json()
    assert s["holds"]["connections"] == 5 and s["holds"]["imports_with_raw_data"] == 1 and s["raw_import_retention_days"] is None
    assert any("never sent to an AI service" in x for x in s["statements"]) and s["consents"]["gmail"] is False
    assert a.post("/api/privacy/purge", {}).status_code == 409
    assert a.put("/api/privacy/retention", {"raw_import_days": 0}).status_code == 422 and a.put("/api/privacy/retention", {"raw_import_days": 30}).status_code == 200
    assert a.post("/api/privacy/purge", {}).json() == {"purged_imports": 0}  # too new to purge
    db = scoped(a)  # noqa: F405
    db.query(ImportBatch).update({"created_at": utcnow() - timedelta(days=40)})
    db.commit()
    assert retention.run_all() == 1  # the hourly worker housekeeping does the same for every user
    assert a.get(f"/api/imports/{prev['import_id']}/rows").json()["rows"][0]["raw"] == {} and a.get("/api/contacts").json()["total"] == 5
    assert not list((env / "users").rglob("*.csv")) and a.get("/api/privacy/summary").json()["holds"]["imports_with_raw_data"] == 0


# ---------------------------------------------------------------- LLM provider: optional, consented, budgeted, minimal
def anthropic_handler(reply, log):
    def h(req):
        log.append(json.loads(req.content) | {"_headers": dict(req.headers)})
        return httpx.Response(200, json={"content": [{"type": "text", "text": reply}], "usage": {"input_tokens": 120, "output_tokens": 30}})
    return h


def test_llm_settings_need_consent_and_the_key_is_never_exposed(env, mk):
    a = mk("a@example.com")
    assert a.put("/api/settings/llm", {"provider": "anthropic", "api_key": "sk-ant-" + "x" * 30}).status_code == 403
    a.put("/api/consents/llm", {"granted": True})
    assert a.put("/api/settings/llm", {"provider": "anthropic", "api_key": "short"}).status_code == 422
    assert a.put("/api/settings/llm", {"provider": "anthropic", "monthly_budget_usd": 500, "api_key": "sk-ant-" + "x" * 30}).status_code == 422
    r = a.put("/api/settings/llm", {"provider": "anthropic", "monthly_budget_usd": 2, "api_key": "sk-ant-" + "k" * 30}).json()
    assert r["key_set"] is True and r["provider"] == "anthropic" and r["monthly_budget_usd"] == 2
    blob = json.dumps([a.get("/api/settings/llm").json(), a.get("/api/me/export").json(), a.get("/api/diagnostics").json()])
    assert "sk-ant-" not in blob and "kkkkkkkk" not in blob and "llm.key" not in blob
    raw = scoped(a).execute(__import__("sqlalchemy").text("select value from user_settings where key='llm.key'")).scalar()  # noqa: F405
    assert "kkkkkkkk" not in str(raw) and crypto.decrypt(json.loads(raw)["enc"]) == "sk-ant-" + "k" * 30
    assert a.put("/api/settings/llm", {"provider": "none", "clear_key": True}).json()["key_set"] is False


def test_llm_calls_are_minimal_budgeted_and_logged_as_metadata(env, mk, monkeypatch):
    a = mk("a@example.com")
    log = []
    monkeypatch.setattr(http_mod, "TRANSPORT_OVERRIDE", httpx.MockTransport(anthropic_handler("Developed REST APIs in Python.", log)))
    db = scoped(a)
    client = http_mod.make_client()
    p = llm.AnthropicLLM(db, "sk-ant-test-key-1234567890", 1.0, client)
    out = p.rewrite_bullet("Built REST APIs in Python. Contact jane.doe@corp.example.com or +1 415 555 0134, see https://corp.example.com/private", ["Python", "PostgreSQL"])
    assert out == "Developed REST APIs in Python."
    sent = log[0]
    prompt = sent["messages"][0]["content"]
    assert "jane.doe" not in prompt and "415 555" not in prompt and "corp.example.com" not in prompt and "[removed]" in prompt and "Python, PostgreSQL" in prompt
    assert sent["model"] == llm.MODEL and sent["_headers"]["x-api-key"] == "sk-ant-test-key-1234567890" and sent["_headers"]["anthropic-version"] == "2023-06-01"
    u = db.query(LLMUsage).one()
    assert (u.kind, u.input_tokens, u.output_tokens) == ("bullet_rewrite", 120, 30) and u.est_cost_usd > 0 and "REST" not in json.dumps([u.kind, u.model])  # metadata only, no text
    broke = llm.AnthropicLLM(db, "sk-ant-test-key-1234567890", 0.0, client)  # budget exhausted: no request is made
    assert broke.rewrite_bullet("Built things.", []) is None and len(log) == 1
    monkeypatch.setattr(http_mod, "TRANSPORT_OVERRIDE", httpx.MockTransport(lambda r: httpx.Response(500)))
    assert llm.AnthropicLLM(db, "k" * 30, 1.0, http_mod.make_client()).rewrite_bullet("Built things.", []) is None  # failures never break the resume


def test_a_model_proposal_still_has_to_pass_the_claim_validator(env, mk, monkeypatch):
    a = mk("a@example.com")
    jobs = prep(a)
    a.put("/api/consents/llm", {"granted": True})
    a.put("/api/settings/llm", {"provider": "anthropic", "monthly_budget_usd": 5, "api_key": "sk-ant-" + "z" * 30})
    log = []
    monkeypatch.setattr(http_mod, "TRANSPORT_OVERRIDE", httpx.MockTransport(anthropic_handler("Built REST APIs in Python on Kubernetes, serving 40% more traffic at Google.", log)))
    r = a.post("/api/tailoring", {"job_id": jobs["Backend Engineer"]["id"]}).json()
    assert log, "the model was consulted"
    txt = json.dumps(r["content"])
    assert "Kubernetes" not in txt and "Google" not in txt and "40%" not in txt  # rejected: the original bullets stand
    assert r["changes"]["llm_rewrites"]["used"] == 0 and r["changes"]["llm_rewrites"]["rejected"] and r["validation"]["ok_to_approve"]
    assert a.get("/api/settings/llm/usage").json()["calls"]
    monkeypatch.setattr(http_mod, "TRANSPORT_OVERRIDE", httpx.MockTransport(anthropic_handler("Built REST APIs in Python for an internal tools service.", log)))
    r2 = a.post("/api/tailoring", {"job_id": jobs["Backend Engineer"]["id"]}).json()
    assert r2["changes"]["llm_rewrites"]["used"] >= 1 and r2["validation"]["ok_to_approve"]


def test_without_a_provider_or_consent_no_model_is_ever_called(env, mk, monkeypatch):
    a = mk("a@example.com")
    jobs = prep(a)
    log = []
    monkeypatch.setattr(http_mod, "TRANSPORT_OVERRIDE", httpx.MockTransport(anthropic_handler("x", log)))
    a.post("/api/tailoring", {"job_id": jobs["Backend Engineer"]["id"]})
    assert log == [] and llm.get_provider(scoped(a)).name == "none"  # noqa: F405
