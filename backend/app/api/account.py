from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import ratelimit
from ..audit import audit
from ..config import get_settings
from ..models.contacts import Contact, EmailContact, ImportBatch, ImportRow, SuppressionEntry
from ..models.core import User, UserSetting
from ..models.jobs import Job, JobSource, UserBoard, UserJob
from ..models.llm import LLMUsage
from ..models.matching import JobContactScore, UserJobMatch
from ..models.outreach import EmailEvent, OAuthToken, OutreachMessage, OutreachPair
from ..models.profile import ProfileItem, Resume
from ..models.scoring import ContactScore
from ..models.tailoring import TailoredResume
from ..security import current_user, scoped_db
from ..services import consent, llm, profile as profile_svc, retention

router = APIRouter(prefix="/api", tags=["account"])


def _setting(db: Session, key: str, default: dict) -> dict:
    row = db.query(UserSetting).filter(UserSetting.key == key).first()
    return {**default, **(row.value if row else {})}


def _put(db: Session, key: str, value: dict) -> None:
    row = db.query(UserSetting).filter(UserSetting.key == key).first()
    if row:
        row.value = value
    else:
        db.add(UserSetting(key=key, value=value))


# ---------------------------------------------------------------- dashboard
@router.get("/dashboard")
def dashboard(db: Session = Depends(scoped_db)):
    items = db.query(ProfileItem).filter(ProfileItem.status != "rejected").all()
    comp = profile_svc.completeness(items)
    n_contacts = db.query(func.count(Contact.id)).scalar()
    usable = db.query(func.count(Contact.id)).filter(Contact.company_id.isnot(None), Contact.position.isnot(None)).scalar()
    jobs = db.query(Job).join(UserJob, UserJob.job_id == Job.id).filter(UserJob.hidden.is_(False))
    n_jobs, n_verified = jobs.count(), jobs.filter(Job.status == "ACTIVE_VERIFIED").count()
    n_match = db.query(func.count(UserJobMatch.id)).scalar()
    n_with_contacts = db.query(func.count(func.distinct(JobContactScore.job_id))).filter(JobContactScore.recommended.is_(True)).scalar()
    pairs = {p.id: p.status for p in db.query(OutreachPair.id, OutreachPair.status).all()}
    ms = db.query(OutreachMessage.pair_id, OutreachMessage.approval_state, OutreachMessage.send_state).all()
    drafted = {m.pair_id for m in ms}
    approved = {m.pair_id for m in ms if m.approval_state == "approved"}
    sent_pairs = {m.pair_id for m in ms if m.send_state in ("sent", "manual_sent")}
    replied = {p for p, s in pairs.items() if s in ("REPLIED", "REFERRAL_OFFERED", "REFERRAL_SUBMITTED", "APPLICATION_SUBMITTED")}
    refs = {p for p, s in pairs.items() if s in ("REFERRAL_OFFERED", "REFERRAL_SUBMITTED")}
    apps = {p for p, s in pairs.items() if s == "APPLICATION_SUBMITTED"}
    funnel = [("Jobs discovered", n_jobs, "jobs"), ("Verified open", n_verified, "jobs"), ("Matched to you", n_match, "jobs"), ("Contact identified", n_with_contacts, "jobs"),
              ("Drafted", len(drafted), "outreach"), ("Approved", len(approved), "outreach"), ("Sent", len(sent_pairs), "outreach"), ("Response", len(replied), "outreach"),
              ("Referral", len(refs), "outreach"), ("Application", len(apps), "outreach")]
    steps = []
    if not db.query(Resume.id).first() and not items:
        steps.append({"text": "Upload your resume or enter your details", "href": "/onboarding"})
    elif comp["score"] < 70:
        steps.append({"text": f"Complete your profile ({comp['score']}% done)", "href": "/profile"})
    if n_contacts == 0:
        steps.append({"text": "Import your LinkedIn connections or an HR contact list", "href": "/imports"})
    if not db.query(UserBoard.id).first():
        steps.append({"text": "Add the job boards of companies you care about", "href": "/jobs"})
    awaiting = db.query(func.count(OutreachMessage.id)).filter(OutreachMessage.approval_state == "awaiting_approval").scalar()
    if awaiting:
        steps.append({"text": f"Review {awaiting} drafted message(s)", "href": "/outreach"})
    if n_verified and not db.query(TailoredResume.id).first():
        steps.append({"text": "Tailor a resume for your best verified job", "href": "/opportunities"})
    return {
        "profile_completeness": comp, "connections": n_contacts, "hr_contacts": db.query(func.count(EmailContact.id)).scalar(),
        "usable_coverage": {"contacts_with_employer_and_title": usable, "percent": round(100 * usable / n_contacts) if n_contacts else None},
        "ranked_prospects": db.query(func.count(ContactScore.id)).scalar(), "verified_jobs": n_verified, "matches": n_match,
        "drafts_awaiting_approval": awaiting,
        "sent": db.query(func.count(OutreachMessage.id)).filter(OutreachMessage.send_state.in_(("sent", "manual_sent"))).scalar(),
        "replies": db.query(func.count(func.distinct(EmailEvent.message_id))).filter(EmailEvent.label.in_(("positive", "neutral", "negative", "referral_offered", "unsubscribe"))).scalar(),
        "referrals_offered": len(refs), "applications": len(apps),
        "funnel": [{"stage": s, "count": c, "unit": u} for s, c, u in funnel], "next_steps": steps,
        "note": "Funnel stages count jobs up to 'Contact identified' and job-contact outreach pairs after that.",
    }


# ---------------------------------------------------------------- diagnostics (verify what the system actually read and did)
@router.get("/diagnostics")
def diagnostics(db: Session = Depends(scoped_db)):
    resumes = []
    for r in db.query(Resume).order_by(Resume.created_at.desc()).limit(10).all():
        its = db.query(ProfileItem).filter(ProfileItem.source == "resume", ProfileItem.source_ref == r.id).all()
        resumes.append({"id": r.id, "filename": r.filename, "status": r.status, "parser": (r.parse_info or {}).get("parser"), "pages": (r.parse_info or {}).get("pages"),
                        "columns_detected": (r.parse_info or {}).get("columns"), "image_only": (r.parse_info or {}).get("image_only", False),
                        "warnings": (r.parse_info or {}).get("warnings", []), "error": (r.parse_info or {}).get("error"),
                        "items_extracted": len(its), "items_rejected_untraceable": len((r.parse_info or {}).get("rejected", [])),
                        "mean_confidence": round(sum(i.confidence for i in its) / len(its), 2) if its else None,
                        "flagged_items": sum(1 for i in its if i.flags), "sections_found": (r.parse_info or {}).get("sections_found", [])})
    imports = []
    for i in db.query(ImportBatch).order_by(ImportBatch.created_at.desc()).limit(10).all():
        rows = dict(db.query(ImportRow.status, func.count()).filter(ImportRow.import_id == i.id).group_by(ImportRow.status).all())
        reasons: dict[str, int] = {}
        for (rs,) in db.query(ImportRow.reasons).filter(ImportRow.import_id == i.id, ImportRow.status != "valid").limit(5000):
            for x in rs or []:
                reasons[x["code"]] = reasons.get(x["code"], 0) + 1
        imports.append({"id": i.id, "kind": i.kind, "filename": i.filename, "status": i.status, "encoding": i.encoding, "delimiter": i.delimiter, "header_line": i.header_row + 1,
                        "mapped": {k: v for k, v in i.mapping.items() if v}, "unmapped_fields": [k for k, v in i.mapping.items() if not v],
                        "unmapped_columns": (i.report or {}).get("unmapped_columns", []), "rows": rows, "rejected_reasons": reasons, "provenance": i.provenance})
    by_source = dict(db.query(JobSource.source_type, func.count()).group_by(JobSource.source_type).all())
    boards = [{"company_id": b.company_id, "ats": b.ats, "token": b.token, "status": b.last_status, "jobs": b.jobs_found, "confirmed": b.confirmed} for b in db.query(UserBoard).all()]
    s = get_settings()
    tok = db.query(OAuthToken).filter(OAuthToken.provider == "gmail").first()
    cfg = llm.get_config(db)
    return {"resumes": resumes, "imports": imports, "jobs": {"sources_seen": by_source, "boards": boards},
            "integrations": [
                {"name": "Gmail", "state": "connected" if tok else "not connected", "mode": s.adapter_mode, "verified_against": "mock HTTP only (never run against Google)"},
                {"name": "GitHub (public REST API)", "state": "available", "mode": s.adapter_mode, "verified_against": "fixtures only"},
                {"name": "Job boards (Greenhouse, Lever, Ashby, Workable, SmartRecruiters)", "state": f"{len(boards)} configured", "mode": s.adapter_mode, "verified_against": "hand-built fixtures only"},
                {"name": "LLM provider", "state": cfg["provider"] if cfg["key_set"] else "off (deterministic mode)", "mode": s.adapter_mode, "verified_against": "mock HTTP only"},
                {"name": "LinkedIn messaging", "state": "disabled by design", "mode": "manual send only", "verified_against": "n/a"}]}


# ---------------------------------------------------------------- onboarding progress (resumable)
STEPS = ["account", "resume", "links", "review", "preferences", "sources", "discovery"]


class OnbIn(BaseModel):
    step: str | None = None
    done: bool | None = None
    skipped: list[str] | None = None


@router.get("/onboarding")
def onboarding(db: Session = Depends(scoped_db)):
    v = _setting(db, "onboarding", {"step": "resume", "done": False, "skipped": []})
    return {**v, "steps": STEPS}


@router.put("/onboarding")
def put_onboarding(body: OnbIn, db: Session = Depends(scoped_db)):
    v = _setting(db, "onboarding", {"step": "resume", "done": False, "skipped": []})
    if body.step is not None:
        if body.step not in STEPS:
            raise HTTPException(422, "Unknown step")
        v["step"] = body.step
    if body.done is not None:
        v["done"] = body.done
    if body.skipped is not None:
        v["skipped"] = [s for s in body.skipped if s in STEPS]
    _put(db, "onboarding", v)
    return {**v, "steps": STEPS}


# ---------------------------------------------------------------- privacy, retention, notifications, sources
@router.get("/privacy/summary")
def privacy_summary(db: Session = Depends(scoped_db)):
    days = retention.get_days(db)
    return {"holds": {"profile_entries": db.query(func.count(ProfileItem.id)).scalar(), "connections": db.query(func.count(Contact.id)).scalar(),
                      "hr_contacts": db.query(func.count(EmailContact.id)).scalar(), "uploaded_resumes": db.query(func.count(Resume.id)).scalar(),
                      "imports_with_raw_data": db.query(func.count(ImportBatch.id)).filter(ImportBatch.status != "purged").scalar(),
                      "suppression_entries": db.query(func.count(SuppressionEntry.id)).scalar()},
            "raw_import_retention_days": days, "consents": {k: consent.get(db, k) for k in consent.NAMES},
            "statements": ["Your data is processed on this server. Complete contact lists are never sent to an AI service.",
                           "If you enable an AI provider, only a single resume bullet and job skill names are sent, with emails, phone numbers and links removed.",
                           "Imported contacts are other people's data. You are responsible for lawful use, and the app helps you honour opt-outs.",
                           "You can export everything and delete your account and all data at any time (Settings > Privacy)."]}


class RetIn(BaseModel):
    raw_import_days: int | None = None


@router.put("/privacy/retention")
def put_retention(body: RetIn, user: User = Depends(current_user), db: Session = Depends(scoped_db)):
    if body.raw_import_days is not None and not 1 <= body.raw_import_days <= 3650:
        raise HTTPException(422, "Choose 1 to 3650 days, or turn it off")
    retention.set_days(db, body.raw_import_days)
    audit(db, user.id, "retention_changed", days=body.raw_import_days)
    return {"raw_import_days": body.raw_import_days}


@router.post("/privacy/purge")
def purge(user: User = Depends(current_user), db: Session = Depends(scoped_db)):
    days = retention.get_days(db)
    if not days:
        raise HTTPException(409, "Set a retention period first")
    n = retention.purge_old_imports(db, user.id, days)
    audit(db, user.id, "retention_purge", imports=n)
    return {"purged_imports": n}


@router.get("/settings/notifications")
def get_notifications(db: Session = Depends(scoped_db)):
    return _setting(db, "notifications", {"replies": True, "follow_ups_due": True, "job_closed": True, "delivery_problems": True})


@router.put("/settings/notifications")
def put_notifications(body: dict[str, bool], db: Session = Depends(scoped_db)):
    cur = _setting(db, "notifications", {"replies": True, "follow_ups_due": True, "job_closed": True, "delivery_problems": True})
    for k, v in body.items():
        if k not in cur:
            raise HTTPException(422, f"Unknown notification: {k}")
        cur[k] = bool(v)
    _put(db, "notifications", cur)
    return {**cur, "note": "Shown in the app. No emails are sent about your activity."}


@router.get("/settings/sources")
def get_sources(db: Session = Depends(scoped_db)):
    return _setting(db, "sources.enabled", {a: True for a in ("greenhouse", "lever", "ashby", "workable", "smartrecruiters")})


@router.put("/settings/sources")
def put_sources(body: dict[str, bool], db: Session = Depends(scoped_db)):
    cur = _setting(db, "sources.enabled", {a: True for a in ("greenhouse", "lever", "ashby", "workable", "smartrecruiters")})
    for k, v in body.items():
        if k not in cur:
            raise HTTPException(422, f"Unknown source: {k}")
        cur[k] = bool(v)
    _put(db, "sources.enabled", cur)
    return cur


# ---------------------------------------------------------------- LLM provider (optional; deterministic mode works without it)
class LLMIn(BaseModel):
    provider: str = "none"
    api_key: str | None = None
    monthly_budget_usd: float | None = None
    clear_key: bool = False


@router.get("/settings/llm")
def get_llm(db: Session = Depends(scoped_db)):
    cfg = llm.get_config(db)
    return {**cfg, "spent_this_month_usd": round(llm.spent(db), 4), "consent": consent.get(db, "llm"), "model": llm.MODEL,
            "what_is_sent": "One resume bullet and the job's skill names, with emails, phone numbers and links removed. Never your contact lists.",
            "estimate": "About 0.0005 USD per bullet; a 20-bullet resume is roughly 0.01 USD. Prices are estimates used only for the budget guard.",
            "status": "Verified against mock HTTP only; never run against the live API."}


@router.put("/settings/llm")
def put_llm(body: LLMIn, user: User = Depends(current_user), db: Session = Depends(scoped_db)):
    ratelimit.check(f"llm-cfg:{user.id}", 20, 3600)
    if body.provider not in ("none", "anthropic"):
        raise HTTPException(422, "provider must be none or anthropic")
    if body.monthly_budget_usd is not None and not 0 <= body.monthly_budget_usd <= 100:
        raise HTTPException(422, "The monthly budget must be between 0 and 100 USD")
    if body.provider != "none" and not consent.get(db, "llm"):
        raise HTTPException(403, "Consent required: allow sending minimal resume text to your chosen AI provider first.")
    if body.api_key is not None and not 20 <= len(body.api_key.strip()) <= 300:
        raise HTTPException(422, "That does not look like an API key")
    if body.clear_key:
        llm.clear_key(db)
    llm.save_config(db, body.provider, body.monthly_budget_usd, body.api_key.strip() if body.api_key else None)
    audit(db, user.id, "llm_config_changed", provider=body.provider, key_changed=bool(body.api_key or body.clear_key))
    return llm.get_config(db)


@router.get("/settings/llm/usage")
def llm_usage(db: Session = Depends(scoped_db)):
    rows = db.query(LLMUsage).order_by(LLMUsage.created_at.desc()).limit(50).all()
    return {"spent_this_month_usd": round(llm.spent(db), 4), "calls": [{"at": r.created_at, "kind": r.kind, "input_tokens": r.input_tokens, "output_tokens": r.output_tokens,
                                                                          "est_cost_usd": round(r.est_cost_usd, 6)} for r in rows]}
