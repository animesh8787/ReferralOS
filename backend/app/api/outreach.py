import base64
import csv
import hashlib
import io
import secrets
from datetime import timedelta
from urllib.parse import quote, urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from .. import crypto, ratelimit, tasks
from ..adapters.http import make_client
from ..audit import audit
from ..config import get_settings
from ..models.contacts import Company, Contact, EmailContact
from ..models.core import User, UserSetting
from ..models.jobs import Job
from ..models.outreach import Campaign, EmailEvent, OAuthToken, OutreachBatch, OutreachMessage, OutreachPair
from ..security import current_user, scoped_db
from ..services import consent
from ..services.outreach import batch as obatch, compliance, drafts, providers, replies, send, settings as osettings
from ..services.tailoring import service as tservice, validate
from ..util import utcnow
from .contacts import page_args
from .scoring import safe

router = APIRouter(prefix="/api", tags=["outreach"])


def _msg(db: Session, mid: str) -> OutreachMessage:
    m = db.query(OutreachMessage).filter(OutreachMessage.id == mid).first()
    if not m:
        raise HTTPException(404, "Not found")
    return m


def _ser(db: Session, m: OutreachMessage, cfg: dict, detail: bool = False) -> dict:
    pair = db.get(OutreachPair, m.pair_id)
    job = db.get(Job, m.job_id) if m.job_id else None
    company = db.get(Company, pair.company_id).name if pair and pair.company_id else None
    check = send.evaluate(db, m, cfg, "approve")
    out = {"id": m.id, "pair_id": m.pair_id, "batch_id": m.batch_id, "channel": m.channel, "kind": m.kind, "is_initial": m.is_initial,
           "to_name": m.to_name, "to_email": m.to_email, "to_linkedin_url": m.to_linkedin_url, "company": company, "job_id": m.job_id,
           "job_title": job.title if job else None, "job_status": job.status if job else None, "covers_job_ids": m.covers_job_ids,
           "match_score": pair.match_score if pair else None, "contact_score": pair.contact_score if pair else None, "subject": m.subject,
           "preview": (m.body or "")[:240], "risk_flags": m.risk_flags, "approval_state": m.approval_state, "send_state": m.send_state,
           "pair_status": pair.status if pair else None, "content_blocks": check["blocks"], "warnings": check["warnings"], "can_approve": check["ok"] and m.approval_state in ("awaiting_approval", "draft"),
           "last_block": m.last_block, "sent_at": m.sent_at, "attach_resume_id": m.attach_resume_id, "created_at": m.created_at,
           "stale": bool(job and job.status in ("CLOSED", "POSSIBLY_CLOSED") and m.send_state not in ("sent", "manual_sent")),
           "stale_reason": "The job is closed or may be closed; this draft is stale." if job and job.status in ("CLOSED", "POSSIBLY_CLOSED") else None}
    if detail:
        mailto = f"mailto:{quote(m.to_email or '')}?" + urlencode({"subject": m.subject or "", "body": m.body}, quote_via=quote) if m.channel == "email" else None
        out |= {"body": m.body, "connect_note": m.connect_note, "subject_options": m.subject_options, "variants": m.variants, "ledger": m.ledger, "options": m.options,
                "mailto": mailto, "mailto_too_long": bool(mailto and len(mailto) > 1900),
                "region_guidance": compliance.guidance_for(compliance.region_of(m.to_email, None)) if m.channel == "email" else None}
    return out


def _facts_text(db: Session, m: OutreachMessage) -> str:
    items = tservice.items_for(db)
    job = db.get(Job, m.job_id) if m.job_id else None
    ctx = " ".join(x for x in (job.title if job else "", m.to_name or "", m.options.get("company", ""), job.apply_url if job and job.apply_url else "", m.to_email or "", m.to_linkedin_url or "") if x)
    cfg = osettings.get(db)
    return " \n ".join(validate.strings([i["data"] for i in items if i["status"] == "active"])) + " \n " + ctx + " \n " + (cfg["sender_name"] or "") + " " + (cfg["sender_email"] or "")


# ---------------------------------------------------------------- settings, acknowledgements, Gmail status
def _gmail(db: Session) -> dict:
    t = db.query(OAuthToken).filter(OAuthToken.provider == "gmail").first()
    return {"connected": bool(t), "account": t.account_email if t else None, "scopes": t.scopes if t else [], "mode": get_settings().adapter_mode,
            "real_oauth_configured": bool(get_settings().google_client_id)}


@router.get("/outreach/settings")
def get_settings_(db: Session = Depends(scoped_db)):
    cfg = osettings.get(db)
    dmax, cmax = osettings.hard_max()
    return {**cfg, "hard_max_daily": dmax, "hard_max_per_company": cmax, "defaults": {"daily_limit": osettings.DEFAULT_DAILY, "per_company_daily": osettings.DEFAULT_COMPANY},
            "lawful_use_text": compliance.LAWFUL_USE_TEXT, "disclaimer": compliance.NOT_LEGAL_ADVICE, "gmail": _gmail(db),
            "scopes_explained": {"gmail.send": "Lets this app send the emails you approve from your Gmail. It cannot read your mail.",
                                 "gmail.readonly": "Only requested if you turn on reply tracking: lets the app see replies and bounces on threads it started."}}


@router.put("/outreach/settings")
def put_settings(body: dict, user: User = Depends(current_user), db: Session = Depends(scoped_db)):
    cfg, warn, err = osettings.apply_update(osettings.get(db), body)
    if err:
        raise HTTPException(422, "; ".join(err))
    if body.get("reply_tracking") and not consent.get(db, "reply_tracking"):
        raise HTTPException(403, "Consent required: turn on reply tracking consent first (it reads replies on threads this app started).")
    osettings.save(db, cfg)
    audit(db, user.id, "outreach_settings_changed", keys=sorted(body))
    return {**cfg, "warnings": warn}


class AckIn(BaseModel):
    kind: str


@router.post("/outreach/acknowledge")
def ack(body: AckIn, user: User = Depends(current_user), db: Session = Depends(scoped_db)):
    try:
        cfg = osettings.acknowledge(osettings.get(db), body.kind)
    except ValueError as e:
        raise HTTPException(422, str(e))
    osettings.save(db, cfg)
    audit(db, user.id, "outreach_acknowledged", kind=body.kind.split(":")[0])
    return {"ok": True, "lawful_use_ack": cfg["lawful_use_ack"], "region_acks": cfg["region_acks"]}


@router.get("/outreach/guidance")
def guidance(region: str | None = None):
    return compliance.guidance_for(region)


class PauseIn(BaseModel):
    paused: bool


@router.post("/outreach/pause")
def pause(body: PauseIn, user: User = Depends(current_user), db: Session = Depends(scoped_db)):
    cfg = osettings.get(db)
    cfg["global_pause"] = body.paused
    osettings.save(db, cfg)
    audit(db, user.id, "outreach_global_pause", paused=body.paused)
    return {"global_pause": body.paused}


# ---------------------------------------------------------------- generation
class GenIn(BaseModel):
    job_ids: list[str] | None = None
    include_unconfirmed: bool = False
    max_jobs: int = 5
    max_hr_per_company: int = 2
    tone: str | None = None
    length: str | None = None
    ask: str = "referral"
    relationship_notes: dict[str, str] = {}
    campaign_id: str | None = None


@router.post("/outreach/generate", status_code=201)
def generate(body: GenIn, user: User = Depends(current_user), db: Session = Depends(scoped_db)):
    ratelimit.check(f"outreach-gen:{user.id}", 20, 3600)
    if body.ask not in ("referral", "guidance") or (body.tone and body.tone not in ("formal", "conversational")) or (body.length and body.length not in ("short", "medium")):
        raise HTTPException(422, "Invalid ask, tone or length")
    if not 1 <= body.max_jobs <= 20 or not 0 <= body.max_hr_per_company <= 3:
        raise HTTPException(422, "max_jobs must be 1-20 and max_hr_per_company 0-3 (small, high-quality batches)")
    cfg = osettings.get(db)
    res = obatch.generate(db, body.model_dump(), cfg)
    if body.campaign_id:
        if not db.query(Campaign.id).filter(Campaign.id == body.campaign_id).first():
            raise HTTPException(404, "Campaign not found")
        for mid in res["messages"]:
            db.get(OutreachMessage, mid).campaign_id = body.campaign_id
    audit(db, user.id, "outreach_batch_generated", messages=len(res["messages"]))
    return res


class IntroIn(BaseModel):
    email_contact_id: str
    tone: str | None = None
    length: str | None = None


@router.post("/outreach/intro", status_code=201)
def intro(body: IntroIn, db: Session = Depends(scoped_db)):
    ec = db.query(EmailContact).filter(EmailContact.id == body.email_contact_id).first()
    if not ec or not ec.email_valid:
        raise HTTPException(404, "Contact not found or has no valid email")
    cfg = osettings.get(db)
    try:
        m = obatch.create_intro(db, ec, cfg, {"tone": body.tone or cfg["tone"], "length": body.length or cfg["length"]})
    except ValueError as e:
        raise HTTPException(409, str(e))
    return _ser(db, m, cfg, True)


class EmailDraftIn(BaseModel):
    email_contact_id: str
    job_id: str


@router.post("/outreach/email-draft", status_code=201)
def email_draft(body: EmailDraftIn, db: Session = Depends(scoped_db)):
    from ..models.jobs import UserJob
    ec = db.query(EmailContact).filter(EmailContact.id == body.email_contact_id).first()
    job = db.query(Job).join(UserJob, UserJob.job_id == Job.id).filter(Job.id == body.job_id).first()
    if not ec or not ec.email_valid or not job:
        raise HTTPException(404, "Contact or job not found")
    if job.status == "CLOSED":
        raise HTTPException(409, "The job is closed; no outreach is prepared for it.")
    cfg = osettings.get(db)
    try:
        m = obatch.create_job_email(db, ec, job, cfg, {"tone": cfg["tone"], "length": cfg["length"]})
    except ValueError as e:
        raise HTTPException(409, str(e))
    return _ser(db, m, cfg, True)


# ---------------------------------------------------------------- review
@router.get("/outreach/batches")
def batches(db: Session = Depends(scoped_db)):
    return [{"id": b.id, "summary": b.summary, "created_at": b.created_at, "approved_at": b.approved_at} for b in db.query(OutreachBatch).order_by(OutreachBatch.created_at.desc()).limit(50).all()]


@router.get("/outreach/batches/{batch_id}")
def batch_detail(batch_id: str, db: Session = Depends(scoped_db)):
    b = db.query(OutreachBatch).filter(OutreachBatch.id == batch_id).first()
    if not b:
        raise HTTPException(404, "Not found")
    cfg = osettings.get(db)
    ms = db.query(OutreachMessage).filter(OutreachMessage.batch_id == batch_id).order_by(OutreachMessage.created_at).all()
    return {"id": b.id, "summary": b.summary, "approved_at": b.approved_at, "daily_limit": cfg["daily_limit"], "messages": [_ser(db, m, cfg) for m in ms]}


@router.get("/outreach/messages")
def messages(batch_id: str | None = None, approval_state: str | None = None, send_state: str | None = None, channel: str | None = None, kind: str | None = None,
             q: str | None = None, page: int = 1, page_size: int = 50, db: Session = Depends(scoped_db)):
    base = db.query(OutreachMessage)
    for col, v in ((OutreachMessage.batch_id, batch_id), (OutreachMessage.approval_state, approval_state), (OutreachMessage.send_state, send_state),
                   (OutreachMessage.channel, channel), (OutreachMessage.kind, kind)):
        if v:
            base = base.filter(col == v)
    if q:
        like = f"%{q.strip().lower()}%"
        base = base.filter(or_(func.lower(OutreachMessage.to_name).like(like), func.lower(OutreachMessage.to_email).like(like), func.lower(OutreachMessage.subject).like(like)))
    off, lim = page_args(page, page_size)
    cfg = osettings.get(db)
    return {"total": base.count(), "items": [_ser(db, m, cfg) for m in base.order_by(OutreachMessage.created_at.desc()).offset(off).limit(lim).all()]}


@router.get("/outreach/messages/{message_id}")
def message(message_id: str, db: Session = Depends(scoped_db)):
    return _ser(db, _msg(db, message_id), osettings.get(db), True)


class EditIn(BaseModel):
    subject: str | None = None
    body: str | None = None
    connect_note: str | None = None
    variant: str | None = None
    attach_resume_id: str | None = None
    detach_resume: bool = False


@router.patch("/outreach/messages/{message_id}")
def edit_message(message_id: str, body: EditIn, user: User = Depends(current_user), db: Session = Depends(scoped_db)):
    m = _msg(db, message_id)
    if m.send_state in ("sent", "manual_sent", "sending", "delivery_unconfirmed"):
        raise HTTPException(409, "This message was already sent.")
    patch = {k: v for k, v in body.model_dump().items() if v is not None and k != "detach_resume"}
    if body.detach_resume:
        patch["attach_resume_id"] = None
    cfg = osettings.get(db)
    send.edit(db, m, patch, cfg, _facts_text(db, m))
    audit(db, user.id, "outreach_message_edited")
    return _ser(db, m, cfg, True)


@router.post("/outreach/messages/{message_id}/approve")
def approve_one(message_id: str, user: User = Depends(current_user), db: Session = Depends(scoped_db)):
    m, cfg = _msg(db, message_id), osettings.get(db)
    res = send.approve(db, m, cfg)
    if not res["ok"]:
        raise HTTPException(409, {"message": "This message cannot be approved yet.", "blocks": res["blocks"]})
    audit(db, user.id, "outreach_approved", count=1, channel=m.channel)
    return _ser(db, m, cfg)


def _decline(db: Session, user: User, message_id: str, state: str) -> dict:
    m = _msg(db, message_id)
    try:
        send.reject(db, m, state)
    except ValueError as e:
        raise HTTPException(409, str(e))
    audit(db, user.id, f"outreach_{state}")
    return _ser(db, m, osettings.get(db))


@router.post("/outreach/messages/{message_id}/reject")
def reject_one(message_id: str, user: User = Depends(current_user), db: Session = Depends(scoped_db)):
    return _decline(db, user, message_id, "rejected")


@router.post("/outreach/messages/{message_id}/skip")
def skip_one(message_id: str, user: User = Depends(current_user), db: Session = Depends(scoped_db)):
    return _decline(db, user, message_id, "skipped")


class ApproveIn(BaseModel):
    message_ids: list[str] | None = None
    scope: str = "selected"  # selected | recommended
    confirm_count: int | None = None
    confirm_daily_limit: int | None = None
    batch_id: str | None = None


@router.post("/outreach/approve")
def approve_many(body: ApproveIn, user: User = Depends(current_user), db: Session = Depends(scoped_db)):
    """Approving more than one message needs a confirmation that restates the count and the daily limit."""
    cfg = osettings.get(db)
    q = db.query(OutreachMessage).filter(OutreachMessage.approval_state.in_(("awaiting_approval", "draft")))
    if body.batch_id:
        q = q.filter(OutreachMessage.batch_id == body.batch_id)
    if body.scope == "selected":
        if not body.message_ids:
            raise HTTPException(422, "Choose the messages to approve.")
        q = q.filter(OutreachMessage.id.in_(body.message_ids))
    elif body.scope != "recommended":
        raise HTTPException(422, "scope must be selected or recommended")
    ms = q.order_by(OutreachMessage.created_at).all()
    if body.scope == "recommended":  # only clean drafts: no content problem, no high-severity risk
        ms = [m for m in ms if send.evaluate(db, m, cfg, "approve")["ok"] and not any(f.get("severity") == "high" for f in m.risk_flags or [])]
    if len(ms) > 1 and (body.confirm_count != len(ms) or body.confirm_daily_limit != cfg["daily_limit"]):
        raise HTTPException(409, {"message": f"To approve {len(ms)} messages, confirm the count and your daily sending limit.", "confirm_count": len(ms),
                                  "confirm_daily_limit": cfg["daily_limit"]})
    approved, blocked = [], []
    for m in ms:
        r = send.approve(db, m, cfg)
        (approved if r["ok"] else blocked).append(m.id if r["ok"] else {"id": m.id, "blocks": [b["code"] for b in r["blocks"]]})
    if body.batch_id and approved:
        b = db.query(OutreachBatch).filter(OutreachBatch.id == body.batch_id).first()
        if b:
            b.approved_at, b.approval_confirmation = utcnow(), {"count": body.confirm_count, "daily_limit": body.confirm_daily_limit}
    audit(db, user.id, "outreach_approved", count=len(approved), batch=bool(body.batch_id))
    return {"approved": approved, "blocked": blocked, "daily_limit": cfg["daily_limit"]}


class ExcludeIn(BaseModel):
    company_id: str


@router.post("/outreach/exclude-company")
def exclude_company(body: ExcludeIn, user: User = Depends(current_user), db: Session = Depends(scoped_db)):
    cfg = osettings.get(db)
    cfg["excluded_company_ids"] = sorted(set(cfg["excluded_company_ids"]) | {body.company_id})
    osettings.save(db, cfg)
    n = 0
    for m in db.query(OutreachMessage).join(OutreachPair, OutreachPair.id == OutreachMessage.pair_id).filter(OutreachPair.company_id == body.company_id,
                                                                                                          OutreachMessage.send_state.in_(("not_sent", "queued", "manual_pending"))).all():
        send.reject(db, m, "skipped")
        n += 1
    audit(db, user.id, "outreach_company_excluded")
    return {"excluded": True, "messages_skipped": n}


# ---------------------------------------------------------------- sending, manual marks, reconciliation
@router.post("/outreach/send", status_code=202)
def send_now(user: User = Depends(current_user), db: Session = Depends(scoped_db)):
    """Starts the sender as a BACKGROUND task (pacing can take minutes, so it never runs inside a request). It sends only approved,
    queued emails that pass every check, paces them, and never retries an ambiguous send. Poll /api/tasks/{id} for the result."""
    from ..models.core import BackgroundTask
    ratelimit.check(f"send:{user.id}", 30, 3600)
    running = db.query(BackgroundTask).filter(BackgroundTask.kind == "send_outbox", BackgroundTask.status.in_(("queued", "running"))).first()
    t = running or tasks.enqueue(db, "send_outbox")
    if not running:
        audit(db, user.id, "outreach_send_started")
    db.refresh(t)
    return {"task_id": t.id, "task_status": t.status, "status": t.status, **(t.result or {})}


@router.post("/outreach/messages/{message_id}/mark-sent")
def mark_sent(message_id: str, user: User = Depends(current_user), db: Session = Depends(scoped_db)):
    m = _msg(db, message_id)
    try:
        send.mark_sent(db, m)
    except ValueError as e:
        raise HTTPException(409, str(e))
    audit(db, user.id, "outreach_marked_sent", channel=m.channel)
    return _ser(db, m, osettings.get(db))


@router.post("/outreach/messages/{message_id}/reconcile")
def reconcile(message_id: str, db: Session = Depends(scoped_db)):
    m = _msg(db, message_id)
    try:
        return send.reconcile(db, m, osettings.get(db))
    except ValueError as e:
        raise HTTPException(409, str(e))


class ResolveIn(BaseModel):
    outcome: str


@router.post("/outreach/messages/{message_id}/resolve")
def resolve(message_id: str, body: ResolveIn, user: User = Depends(current_user), db: Session = Depends(scoped_db)):
    m = _msg(db, message_id)
    try:
        send.resolve_unconfirmed(db, m, body.outcome)
    except ValueError as e:
        raise HTTPException(409, str(e))
    audit(db, user.id, "outreach_unconfirmed_resolved", outcome=body.outcome)
    return _ser(db, m, osettings.get(db))


@router.get("/outreach/messages/{message_id}/eml")
def eml(message_id: str, db: Session = Depends(scoped_db)):
    m, cfg = _msg(db, message_id), osettings.get(db)
    if m.channel != "email" or not (cfg["sender_name"] and cfg["sender_email"]):
        raise HTTPException(409, "Only emails can be exported, and your sender name and address must be set.")
    att = None
    if m.attach_resume_id:
        from .. import storage
        att = ("resume.pdf", storage.bundle_path(m.user_id, m.attach_resume_id, "resume.pdf").read_bytes())
    data, _ = providers.build_mime(cfg["sender_name"], cfg["sender_email"], m.to_email or "", m.subject or "", m.body, att)
    return Response(data, media_type="message/rfc822", headers={"Content-Disposition": 'attachment; filename="draft.eml"'})


# ---------------------------------------------------------------- replies, bounces, follow-ups
class ReplyIn(BaseModel):
    from_addr: str = ""
    subject: str = ""
    body: str


@router.post("/outreach/messages/{message_id}/reply")
def add_reply(message_id: str, body: ReplyIn, user: User = Depends(current_user), db: Session = Depends(scoped_db)):
    m = _msg(db, message_id)
    if m.send_state not in ("sent", "manual_sent", "delivery_unconfirmed"):
        raise HTTPException(409, "Only a message that was sent can have a reply.")
    r = replies.ingest(db, m, body.from_addr, body.subject, body.body)
    audit(db, user.id, "reply_recorded", label=r["label"])
    return r


@router.get("/outreach/messages/{message_id}/events")
def events(message_id: str, db: Session = Depends(scoped_db)):
    _msg(db, message_id)
    return [{"id": e.id, "type": e.type, "label": e.label, "confirmed": e.confirmed, "detail": e.detail, "at": e.created_at}
            for e in db.query(EmailEvent).filter(EmailEvent.message_id == message_id).order_by(EmailEvent.created_at, EmailEvent.id).all()]


class ConfirmIn(BaseModel):
    confirmed: bool


@router.post("/outreach/events/{event_id}/confirm")
def confirm_optout(event_id: str, body: ConfirmIn, user: User = Depends(current_user), db: Session = Depends(scoped_db)):
    ev = db.query(EmailEvent).filter(EmailEvent.id == event_id).first()
    if not ev:
        raise HTTPException(404, "Not found")
    try:
        r = replies.confirm_optout(db, ev, body.confirmed)
    except ValueError as e:
        raise HTTPException(409, str(e))
    audit(db, user.id, "optout_confirmed" if body.confirmed else "optout_dismissed")
    return r


class RelabelIn(BaseModel):
    label: str


@router.patch("/outreach/events/{event_id}")
def relabel(event_id: str, body: RelabelIn, db: Session = Depends(scoped_db)):
    ev = db.query(EmailEvent).filter(EmailEvent.id == event_id).first()
    if not ev:
        raise HTTPException(404, "Not found")
    try:
        replies.relabel(ev, body.label)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {"id": ev.id, "label": ev.label}


@router.post("/outreach/followups/scan")
def scan(user: User = Depends(current_user), db: Session = Depends(scoped_db)):
    """Creates follow-up DRAFTS that wait for your approval. Nothing is sent."""
    cfg = osettings.get(db)
    items = tservice.items_for(db)
    from ..services import matching
    from datetime import date
    facts = drafts.sender_facts(items, [], cfg["sender_name"], matching.summarize_profile(items, date.today()))
    r = replies.scan_followups(db, cfg, facts, cfg["sender_email"])
    audit(db, user.id, "followups_scanned", drafts=len(r["drafts_created"]))
    return r


@router.post("/outreach/replies/sync")
def sync_replies(user: User = Depends(current_user), db: Session = Depends(scoped_db)):
    cfg = osettings.get(db)
    if not (cfg["reply_tracking"] and consent.get(db, "reply_tracking")):
        raise HTTPException(403, "Reply tracking is off. Enable the consent and the setting first; it only reads threads this app started.")
    provider, ready = send.provider_for(db, user.id, cfg)
    if not ready or provider.name == "dry_run":
        raise HTTPException(409, "Connect Gmail (with read access) first.")
    new = 0
    for m in db.query(OutreachMessage).filter(OutreachMessage.send_state == "sent", OutreachMessage.channel == "email").all():
        seen = {e.detail.get("provider_id") for e in db.query(EmailEvent).filter(EmailEvent.message_id == m.id).all()}
        for r in provider.fetch_replies(user.id, m.provider_thread_id, m.rfc_message_id):
            if r.get("id") in seen:
                continue
            res = replies.ingest(db, m, r.get("from", ""), r.get("subject", ""), r.get("body", ""))
            ev = db.get(EmailEvent, res["event_id"])
            ev.detail = {**ev.detail, "provider_id": r.get("id")}
            new += 1
    return {"new_events": new}


# ---------------------------------------------------------------- Gmail connection (official OAuth; mock in mock mode)
SEND_SCOPE, READ_SCOPE = "https://www.googleapis.com/auth/gmail.send", "https://www.googleapis.com/auth/gmail.readonly"


@router.get("/email/gmail/status")
def gmail_status(db: Session = Depends(scoped_db)):
    return _gmail(db)


class MockConnect(BaseModel):
    email: str


@router.post("/email/gmail/mock-connect")
def mock_connect(body: MockConnect, user: User = Depends(current_user), db: Session = Depends(scoped_db)):
    if get_settings().adapter_mode != "mock":
        raise HTTPException(404, "Not found")
    consent.require(db, "gmail")
    db.query(OAuthToken).delete()
    db.add(OAuthToken(provider="gmail", account_email=body.email, encrypted_access=crypto.encrypt("mock-access-token"), encrypted_refresh=crypto.encrypt("mock-refresh-token"),
                      expires_at=utcnow() + timedelta(hours=1), scopes=[SEND_SCOPE]))
    audit(db, user.id, "gmail_connected", mode="mock")
    return {"connected": True, "account": body.email, "mode": "mock"}


@router.get("/email/gmail/authorize")
def gmail_authorize(user: User = Depends(current_user), db: Session = Depends(scoped_db)):
    s = get_settings()
    if s.adapter_mode == "mock" or not s.google_client_id:
        raise HTTPException(409, "Gmail OAuth is not configured on this server (set GOOGLE_CLIENT_ID/SECRET and ADAPTER_MODE=real).")
    consent.require(db, "gmail")
    cfg = osettings.get(db)
    scopes = [SEND_SCOPE] + ([READ_SCOPE] if cfg["reply_tracking"] and consent.get(db, "reply_tracking") else [])
    verifier = secrets.token_urlsafe(48)
    state = secrets.token_urlsafe(24)
    row = db.query(UserSetting).filter(UserSetting.key == "oauth.gmail.pending").first()
    val = {"state": state, "verifier": verifier, "scopes": scopes}
    if row:
        row.value = val
    else:
        db.add(UserSetting(key="oauth.gmail.pending", value=val))
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({"client_id": s.google_client_id, "redirect_uri": f"{s.cors_origins[0]}/settings/gmail/callback", "response_type": "code",
                                                                       "scope": " ".join(scopes), "access_type": "offline", "prompt": "consent", "state": state,
                                                                       "code_challenge": challenge, "code_challenge_method": "S256"})
    return {"url": url, "scopes": scopes}


class CallbackIn(BaseModel):
    code: str
    state: str


@router.post("/email/gmail/callback")
def gmail_callback(body: CallbackIn, user: User = Depends(current_user), db: Session = Depends(scoped_db)):
    s = get_settings()
    pend = db.query(UserSetting).filter(UserSetting.key == "oauth.gmail.pending").first()
    if not pend or not secrets.compare_digest(pend.value["state"], body.state):
        raise HTTPException(400, "Invalid OAuth state")
    c = make_client()
    try:
        r = c.post(providers.TOKEN_URL, data={"grant_type": "authorization_code", "code": body.code, "client_id": s.google_client_id, "client_secret": s.google_client_secret,
                                              "redirect_uri": f"{s.cors_origins[0]}/settings/gmail/callback", "code_verifier": pend.value["verifier"]})
        r.raise_for_status()
        j = r.json()
        who = c.get("https://openidconnect.googleapis.com/v1/userinfo", headers={"Authorization": f"Bearer {j['access_token']}"}).json()
    except (httpx.HTTPError, KeyError, ValueError):
        raise HTTPException(502, "Google did not complete the connection. Nothing was saved.")
    db.query(OAuthToken).delete()
    db.add(OAuthToken(provider="gmail", account_email=who.get("email", ""), encrypted_access=crypto.encrypt(j["access_token"]),
                      encrypted_refresh=crypto.encrypt(j["refresh_token"]) if j.get("refresh_token") else None,
                      expires_at=utcnow() + timedelta(seconds=int(j.get("expires_in", 3600))), scopes=pend.value["scopes"]))
    db.delete(pend)
    audit(db, user.id, "gmail_connected", mode="real")
    return {"connected": True, "account": who.get("email")}


@router.delete("/email/gmail")
def gmail_disconnect(user: User = Depends(current_user), db: Session = Depends(scoped_db)):
    t = db.query(OAuthToken).filter(OAuthToken.provider == "gmail").first()
    if t and get_settings().adapter_mode == "real":
        try:
            make_client().post("https://oauth2.googleapis.com/revoke", data={"token": crypto.decrypt(t.encrypted_access)})  # best effort
        except Exception:  # noqa: BLE001
            pass
    db.query(OAuthToken).delete()
    audit(db, user.id, "gmail_disconnected")
    return {"connected": False}


@router.post("/email/test-send")
def test_send(user: User = Depends(current_user), db: Session = Depends(scoped_db)):
    """Sends ONE test email to your own address. The only place the app sends without a draft, and only ever to you."""
    ratelimit.check(f"test-send:{user.id}", 5, 3600)
    cfg = osettings.get(db)
    if not (cfg["sender_name"] and cfg["sender_email"]):
        raise HTTPException(409, "Set your name and your own email address first.")
    provider, ready = send.provider_for(db, user.id, cfg)
    if not ready:
        raise HTTPException(409, "Switch delivery mode to dry-run or connect Gmail first.")
    mime, rfc = providers.build_mime(cfg["sender_name"], cfg["sender_email"], cfg["sender_email"], "ReferralOS test email", "This is a test email sent to yourself to check the connection.\n")
    r = provider.send(user.id, mime, rfc, cfg["sender_email"])
    audit(db, user.id, "test_email", ok=r.ok, provider=provider.name)
    return {"ok": r.ok, "provider": provider.name, "detail": r.detail, "to": cfg["sender_email"]}


# ---------------------------------------------------------------- campaigns
class CampIn(BaseModel):
    name: str
    goal: str = ""
    daily_limit: int | None = None


@router.post("/campaigns", status_code=201)
def new_campaign(body: CampIn, db: Session = Depends(scoped_db)):
    cfg = osettings.get(db)
    if body.daily_limit is not None and not 0 <= body.daily_limit <= cfg["daily_limit"]:
        raise HTTPException(422, "A campaign limit can only lower your account limit.")
    c = Campaign(name=body.name[:120], goal=body.goal[:300], daily_limit=body.daily_limit)
    db.add(c)
    db.flush()
    return {"id": c.id, "name": c.name, "paused": c.paused, "daily_limit": c.daily_limit}


@router.get("/campaigns")
def campaigns(db: Session = Depends(scoped_db)):
    return [{"id": c.id, "name": c.name, "goal": c.goal, "paused": c.paused, "daily_limit": c.daily_limit} for c in db.query(Campaign).order_by(Campaign.created_at).all()]


@router.post("/campaigns/{campaign_id}/pause")
def pause_campaign(campaign_id: str, body: PauseIn, db: Session = Depends(scoped_db)):
    c = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not c:
        raise HTTPException(404, "Not found")
    c.paused = body.paused
    return {"id": c.id, "paused": c.paused}


# ---------------------------------------------------------------- tracking and exports
class PairIn(BaseModel):
    status: str | None = None
    note: str | None = None
    evidence: str | None = None


@router.get("/tracking/pairs")
def pairs(status: str | None = None, page: int = 1, page_size: int = 50, db: Session = Depends(scoped_db)):
    q = db.query(OutreachPair)
    if status:
        q = q.filter(OutreachPair.status == status)
    off, lim = page_args(page, page_size)
    rows = q.order_by(OutreachPair.updated_at.desc()).offset(off).limit(lim).all()
    out = []
    for p in rows:
        last = db.query(OutreachMessage).filter(OutreachMessage.pair_id == p.id).order_by(OutreachMessage.created_at.desc()).first()
        job = db.get(Job, p.job_id) if p.job_id else None
        who = db.get(Contact, p.contact_id) if p.contact_id else db.get(EmailContact, p.email_contact_id) if p.email_contact_id else None
        out.append({"id": p.id, "status": p.status, "channel": p.channel, "job_title": job.title if job else None, "company_id": p.company_id,
                    "who": (f"{who.first_name} {who.last_name}".strip() if isinstance(who, Contact) else (who.name or who.email_norm)) if who else None,
                    "match_score": p.match_score, "contact_score": p.contact_score, "resume_id": p.resume_id, "follow_up_at": p.follow_up_at, "note": p.note,
                    "last_message": {"id": last.id, "kind": last.kind, "send_state": last.send_state, "subject": last.subject} if last else None})
    counts = dict(db.query(OutreachPair.status, func.count()).group_by(OutreachPair.status).all())
    return {"total": q.count(), "counts": counts, "items": out}


@router.patch("/tracking/pairs/{pair_id}")
def update_pair(pair_id: str, body: PairIn, user: User = Depends(current_user), db: Session = Depends(scoped_db)):
    p = db.query(OutreachPair).filter(OutreachPair.id == pair_id).first()
    if not p:
        raise HTTPException(404, "Not found")
    try:
        if body.status:
            if body.status not in send.MANUAL_PATHS:
                raise ValueError("That status is set by the app (drafting, approval and sending); you can set: " + ", ".join(sorted(send.MANUAL_PATHS)))
            send.set_pair(db, p, body.status, body.evidence, body.note)
            if body.status == "DO_NOT_CONTACT":
                replies.cancel_followups(db, [p.id], "marked do-not-contact", include_all_unsent=True)
        elif body.note is not None:
            p.note = body.note
    except ValueError as e:
        raise HTTPException(422, str(e))
    audit(db, user.id, "pair_status_changed", status=body.status)
    return {"id": p.id, "status": p.status}


@router.get("/exports/outreach-queue.csv")
def export_queue(user: User = Depends(current_user), db: Session = Depends(scoped_db)):
    ratelimit.check(f"export:{user.id}", 5, 3600)
    cfg = osettings.get(db)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Channel", "Kind", "Recipient", "Email", "LinkedIn", "Company", "Job", "Job status", "Subject", "Approval", "Send state", "Risk flags", "Created"])
    for m in db.query(OutreachMessage).order_by(OutreachMessage.created_at).limit(20000).all():
        s = _ser(db, m, cfg)
        w.writerow([safe(x) if isinstance(x, str) else x for x in (s["channel"], s["kind"], s["to_name"], s["to_email"], s["to_linkedin_url"], s["company"], s["job_title"], s["job_status"],
                                                                     s["subject"], s["approval_state"], s["send_state"], ";".join(f["code"] for f in s["risk_flags"]), s["created_at"])])
    audit(db, user.id, "export_outreach_queue")
    return Response(buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="outreach-queue.csv"'})
