"""Approve -> queue -> send, with the gate applied at every step.

Invariants (each covered by tests):
- nothing is sent unless approval_state == approved AND preflight passes at send time;
- LinkedIn messages are never sent by the app;
- an ambiguous provider outcome becomes delivery_unconfirmed and is NEVER re-sent automatically;
- editing a message after approval withdraws the approval;
- limits are counted from what was actually sent today (UTC), including unconfirmed sends.
"""
import random
import time
from datetime import datetime, timedelta

from sqlalchemy import func, update
from sqlalchemy.orm import Session

from ... import crypto, storage
from ...adapters.http import make_client
from ...config import get_settings
from ...models.contacts import EmailContact, SuppressionEntry
from ...models.jobs import Job
from ...models.outreach import Campaign, EmailEvent, OAuthToken, OutreachMessage, OutreachPair
from ...models.tailoring import TailoredResume
from ...util import utcnow
from . import compliance, preflight, providers, settings as osettings

COUNTED = ("sent", "delivery_unconfirmed", "manual_sent", "sending")
ACTIVE_INITIAL = ("sent", "delivery_unconfirmed", "manual_sent", "sending", "queued", "manual_pending")
MANUAL_PATHS = {"REFERRAL_OFFERED", "REPLIED", "REFERRAL_SUBMITTED", "APPLICATION_SUBMITTED", "REJECTED", "CLOSED", "DO_NOT_CONTACT"}


# ---------------------------------------------------------------- pair status
def set_pair(db: Session, pair: OutreachPair, status: str, evidence: str | None = None, note: str | None = None) -> None:
    from ...models.outreach import PAIR_STATUSES
    if status not in PAIR_STATUSES:
        raise ValueError("Unknown status")
    if status == "SENT" and not db.query(OutreachMessage.id).filter(OutreachMessage.pair_id == pair.id, OutreachMessage.send_state.in_(("sent", "manual_sent"))).first():
        raise ValueError("A pair is only SENT once a message was really sent or you confirmed sending it yourself")
    if status == "REFERRAL_SUBMITTED" and not (evidence or pair.evidence or "").strip():
        raise ValueError("Marking a referral as submitted needs your evidence (who submitted it, when, or a confirmation reference)")
    pair.status = status
    if evidence:
        pair.evidence = evidence
    if note is not None:
        pair.note = note


def event(db: Session, m: OutreachMessage, type_: str, **detail) -> EmailEvent:
    e = EmailEvent(message_id=m.id, type=type_, detail=detail)
    db.add(e)
    return e


# ---------------------------------------------------------------- context
def provider_for(db: Session, user_id: str, cfg: dict):
    """-> (provider|None, ready). Dry-run never needs Gmail. Gmail needs a connected token even in mock mode (mirrors reality)."""
    if cfg["delivery_mode"] == "DRY_RUN":
        return providers.DryRunProvider(), True
    tok = db.query(OAuthToken).filter(OAuthToken.provider == "gmail").first()
    if cfg["delivery_mode"] != "AUTHORISED_INTEGRATION" or tok is None:
        return None, False
    if get_settings().adapter_mode == "mock":
        return providers.MockProvider(), True
    s = get_settings()
    return providers.GmailProvider(tok, make_client(), getattr(s, "google_client_id", ""), getattr(s, "google_client_secret", "")), True


def build_ctx(db: Session, m: OutreachMessage, cfg: dict, now: datetime | None = None) -> preflight.Ctx:
    now = now or utcnow()
    day0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    pair = db.get(OutreachPair, m.pair_id)
    q = db.query(OutreachMessage).filter(OutreachMessage.channel == "email", OutreachMessage.send_state.in_(COUNTED), OutreachMessage.sent_at >= day0)
    ctx = preflight.Ctx(settings=cfg, now=now, pair_status=pair.status if pair else "", msg_id=m.id)
    ctx.sent_today_total = q.count()
    if pair and pair.company_id:
        ctx.sent_today_company = q.join(OutreachPair, OutreachPair.id == OutreachMessage.pair_id).filter(OutreachPair.company_id == pair.company_id).count()
    ctx.sent_today_intro = q.filter(OutreachMessage.kind == "cold_intro").count()
    if m.campaign_id:
        ctx.campaign = db.get(Campaign, m.campaign_id)
        ctx.sent_today_campaign = q.filter(OutreachMessage.campaign_id == m.campaign_id).count()
    for s in db.query(SuppressionEntry).all():
        (ctx.suppressed_emails if s.kind == "email" else ctx.suppressed_domains).add(s.value)
    if m.to_email:
        others = db.query(OutreachMessage).filter(OutreachMessage.to_email == m.to_email, OutreachMessage.is_initial.is_(True), OutreachMessage.id != m.id,
                                                  OutreachMessage.channel == "email", OutreachMessage.send_state.in_(ACTIVE_INITIAL)).all()
        # a queued twin only blocks the LATER one, so exactly one of two simultaneous drafts can ever go out
        ctx.other_initial_to_same = [o.id for o in others if o.send_state in COUNTED or (o.created_at, o.id) < (m.created_at, m.id)]
    if m.job_id:
        ctx.job = db.get(Job, m.job_id)
    if m.attach_resume_id:
        r = db.get(TailoredResume, m.attach_resume_id)
        size = 0
        if r:
            try:
                size = len(storage.get_bundle(m.user_id, r.id, "resume.pdf"))
            except OSError:
                size = 0
        ctx.attachment = {"approved": bool(r and r.status == "approved"), "for_job": bool(r and r.job_id == m.job_id), "size": size}
    ctx.provider_ready = provider_for(db, m.user_id, cfg)[1]
    if pair and pair.email_contact_id:
        ec = db.get(EmailContact, pair.email_contact_id)
        ctx.contact_email = ec
        ctx.bulk_blocked = bool(ec and ec.bulk_send_blocked)
        ctx.region = compliance.region_of(m.to_email, ec.country_hint if ec else None)
    else:
        ctx.region = compliance.region_of(m.to_email, None)
    if m.kind == "follow_up" and m.parent_id:
        sent = db.query(OutreachMessage).filter(OutreachMessage.pair_id == m.pair_id, OutreachMessage.send_state.in_(("sent", "manual_sent", "delivery_unconfirmed"))).order_by(OutreachMessage.sent_at.desc()).all()
        ctx.followups_sent = sum(1 for x in sent if x.kind == "follow_up")
        ctx.last_sent_at = sent[0].sent_at if sent else None
    return ctx


def evaluate(db: Session, m: OutreachMessage, cfg: dict, stage: str, now: datetime | None = None) -> dict:
    return preflight.check(m, build_ctx(db, m, cfg, now), stage)


# ---------------------------------------------------------------- approval and queueing
def edit(db: Session, m: OutreachMessage, patch: dict, cfg: dict, items_text: str) -> None:
    """Any edit withdraws approval: what was approved is exactly what gets sent."""
    from ..tailoring import validate
    for k in ("subject", "body", "connect_note"):
        if k in patch and patch[k] is not None:
            setattr(m, k, str(patch[k])[:8000] if k == "body" else str(patch[k])[:320])
    if patch.get("variant") in ("A", "B") and m.variants.get(patch["variant"]):
        v = m.variants[patch["variant"]]
        m.subject, m.body = v.get("subject", m.subject), v["body"]
    if "attach_resume_id" in patch:
        m.attach_resume_id = patch["attach_resume_id"] or None
    text = "\n".join(x for x in (m.subject, m.body, m.connect_note) if x)
    g = validate.ungrounded(text, items_text)
    m.risk_flags = [f for f in (m.risk_flags or []) if f.get("code") != "UNVERIFIED_CLAIMS"]
    if g["tech"] or g["numbers"]:
        m.risk_flags = m.risk_flags + [{"code": "UNVERIFIED_CLAIMS", "severity": "high", "detail": f"Not found in your profile: {', '.join(g['tech'] + g['numbers'])}"}]
    if m.approval_state == "approved":
        withdraw(db, m, "edited after approval")
    m.approval_state = "awaiting_approval" if m.approval_state in ("approved", "draft") else m.approval_state


def withdraw(db: Session, m: OutreachMessage, why: str) -> None:
    if m.send_state in ("sent", "manual_sent", "sending", "delivery_unconfirmed"):
        return
    m.approval_state, m.approved_at, m.send_state = "awaiting_approval", None, "not_sent"
    pair = db.get(OutreachPair, m.pair_id)
    if pair and pair.status in ("APPROVED", "QUEUED"):
        pair.status = "AWAITING_APPROVAL"
    event(db, m, "APPROVAL_WITHDRAWN", why=why)


def approve(db: Session, m: OutreachMessage, cfg: dict, now: datetime | None = None) -> dict:
    """Approval checks CONTENT only. Limits/pauses do not prevent approval; they hold the send."""
    if m.approval_state in ("rejected", "skipped", "cancelled"):
        return {"ok": False, "blocks": [{"code": "NOT_APPROVABLE", "detail": f"This message was {m.approval_state}."}], "warnings": []}
    res = evaluate(db, m, cfg, "approve", now)
    if not res["ok"]:
        return res
    now = now or utcnow()
    m.approval_state, m.approved_at = "approved", now
    pair = db.get(OutreachPair, m.pair_id)
    m.send_state = "queued" if m.channel == "email" and cfg["delivery_mode"] in ("AUTHORISED_INTEGRATION", "DRY_RUN") else "manual_pending"
    m.scheduled_at = now if m.send_state == "queued" else None
    if pair:
        pair.status = "QUEUED" if m.send_state == "queued" else "APPROVED"
    event(db, m, "APPROVED", mode=cfg["delivery_mode"])
    return res


def reject(db: Session, m: OutreachMessage, state: str = "rejected") -> None:
    if m.send_state in ("sent", "manual_sent", "sending", "delivery_unconfirmed"):
        raise ValueError("This message was already sent")
    m.approval_state, m.send_state = state, "not_sent"
    pair = db.get(OutreachPair, m.pair_id)
    if pair and pair.status in ("DRAFT_READY", "AWAITING_APPROVAL", "APPROVED", "QUEUED"):
        pair.status = "DRAFT_READY"


# ---------------------------------------------------------------- sending
def _attachment(db: Session, m: OutreachMessage):
    if not m.attach_resume_id:
        return None
    return ("resume.pdf", storage.get_bundle(m.user_id, m.attach_resume_id, "resume.pdf"))


def claim(db: Session, m: OutreachMessage) -> bool:
    """Atomically move queued -> sending. Only ONE runner can win, even if two sender tasks loaded the same message."""
    r = db.execute(update(OutreachMessage).where(OutreachMessage.id == m.id, OutreachMessage.send_state == "queued", OutreachMessage.approval_state == "approved")
                   .values(send_state="sending"))
    db.commit()  # make the claim visible to every other runner before anything is sent
    if r.rowcount != 1:
        return False
    db.refresh(m)
    return True


def send_outbox(db: Session, cfg: dict, sleep=time.sleep, rng=random.uniform, now: datetime | None = None, limit: int = 100, commit_each: bool = False) -> dict:
    """Send queued, approved emails that pass the gate, with human-like pacing between sends. Never retries an ambiguous send."""
    out = {"sent": 0, "dry_run": 0, "held": [], "blocked": [], "unconfirmed": 0, "failed": 0}
    msgs = db.query(OutreachMessage).filter(OutreachMessage.send_state == "queued", OutreachMessage.approval_state == "approved", OutreachMessage.channel == "email") \
        .order_by(OutreachMessage.scheduled_at, OutreachMessage.created_at).limit(limit).all()
    first = True
    for m in msgs:
        res = evaluate(db, m, cfg, "send", now)
        if not res["ok"]:
            m.last_block = res["blocks"]
            if res["permanent"]:
                m.send_state = "blocked"
                event(db, m, "SEND_BLOCKED", blocks=[b["code"] for b in res["blocks"]])
                pair = db.get(OutreachPair, m.pair_id)
                if pair and any(b["code"] in ("SUPPRESSED_EMAIL", "SUPPRESSED_DOMAIN", "DO_NOT_CONTACT") for b in res["blocks"]) and pair.status != "DO_NOT_CONTACT":
                    pair.status = "DO_NOT_CONTACT"
                out["blocked"].append({"id": m.id, "codes": [b["code"] for b in res["blocks"]]})
            else:
                out["held"].append({"id": m.id, "codes": [b["code"] for b in res["blocks"]]})
                if any(b["code"] in ("GLOBAL_PAUSE", "NO_PROVIDER", "MANUAL_MODE") for b in res["blocks"]):
                    break  # nothing else can go out either
            continue
        if not claim(db, m):
            continue  # someone else (another run) already took this message
        provider, _ = provider_for(db, m.user_id, cfg)
        if not first:
            lo, hi = cfg["pacing_seconds"]
            sleep(rng(lo, hi))  # pacing keeps us well inside provider limits; it is not an evasion technique
        first = False
        mime, rfc = providers.build_mime(cfg["sender_name"], cfg["sender_email"], m.to_email, m.subject, m.body, _attachment(db, m))
        m.rfc_message_id = rfc
        db.commit()  # persist "sending" + our Message-ID BEFORE the network call: a crash mid-send is then visible, never silently re-sent
        r = provider.send(m.user_id, mime, rfc, m.to_email)
        pair = db.get(OutreachPair, m.pair_id)
        if r.ok and provider.name == "dry_run":
            m.send_state = "dry_run"
            event(db, m, "DRY_RUN", detail=r.detail)
            out["dry_run"] += 1
        elif r.ok:
            m.send_state, m.sent_at, m.provider_message_id, m.provider_thread_id = "sent", now or utcnow(), r.provider_message_id, r.thread_id
            event(db, m, "SENT", provider=provider.name)
            if pair:
                pair.status = "SENT"
                if m.is_initial and cfg["max_followups"] > 0:
                    pair.follow_up_at = preflight.add_business_days(m.sent_at, cfg["followup_spacing_business_days"])
            out["sent"] += 1
        elif r.kind == "ambiguous":
            m.send_state, m.sent_at = "delivery_unconfirmed", now or utcnow()  # counts toward today's limit: it may well have gone out
            event(db, m, "DELIVERY_UNCONFIRMED", detail=r.detail)
            if pair:
                pair.status = "DELIVERY_UNCONFIRMED"
            out["unconfirmed"] += 1
        else:
            m.send_state, m.last_block = "failed", [{"code": "SEND_FAILED", "detail": r.detail, "permanent": False}]
            event(db, m, "SEND_FAILED", detail=r.detail)
            if pair and pair.status == "QUEUED":
                pair.status = "APPROVED"
            out["failed"] += 1
        if commit_each:
            db.commit()
    return out


def mark_sent(db: Session, m: OutreachMessage, now: datetime | None = None) -> None:
    """The user says they sent it themselves (manual mode / LinkedIn). We take their word; we cannot verify it."""
    if m.approval_state != "approved":
        raise ValueError("Approve the message first")
    if m.send_state in ("sent", "manual_sent", "sending"):
        raise ValueError("Already marked as sent")
    if m.channel == "email" and m.is_initial:
        ctx = build_ctx(db, m, osettings.get(db))
        if ctx.other_initial_to_same:
            raise ValueError("An initial email to this address already exists; only one cold email per recipient")
    m.send_state, m.sent_at = "manual_sent", now or utcnow()
    pair = db.get(OutreachPair, m.pair_id)
    if pair:
        pair.status = "SENT"
        cfg = osettings.get(db)
        if m.is_initial and m.channel == "email" and cfg["max_followups"] > 0:
            pair.follow_up_at = preflight.add_business_days(m.sent_at, cfg["followup_spacing_business_days"])
    event(db, m, "MANUAL_SENT")


def reconcile(db: Session, m: OutreachMessage, cfg: dict) -> dict:
    """Look in the provider's Sent mail for our own Message-ID. Never re-sends; the user decides what to do next."""
    if m.send_state != "delivery_unconfirmed":
        raise ValueError("Only unconfirmed deliveries need reconciling")
    provider, ready = provider_for(db, m.user_id, cfg)
    if not ready or provider.name == "dry_run":
        return {"found": None, "note": "Cannot look in Sent mail without a connected Gmail account with read access. Check your Sent folder, then tell us what you see."}
    try:
        f = provider.find_sent(m.user_id, m.rfc_message_id)
    except Exception as e:  # noqa: BLE001
        return {"found": None, "note": f"Could not check Sent mail ({type(e).__name__}). Check it yourself, then tell us what you see."}
    if f:
        m.send_state, m.provider_message_id, m.provider_thread_id = "sent", f["id"], f.get("thread")
        pair = db.get(OutreachPair, m.pair_id)
        if pair:
            pair.status = "SENT"
        event(db, m, "SENT", reconciled=True)
        return {"found": True, "note": "Found in your Sent mail: marked as sent."}
    return {"found": False, "note": "Not found in Sent mail. It probably did not go out, but this app will not resend on its own. Resolve it manually."}


def resolve_unconfirmed(db: Session, m: OutreachMessage, outcome: str) -> None:
    """Manual reconciliation. 'not_sent' does NOT re-queue: the user must edit/approve again deliberately."""
    if m.send_state != "delivery_unconfirmed":
        raise ValueError("Only unconfirmed deliveries need resolving")
    pair = db.get(OutreachPair, m.pair_id)
    if outcome == "sent":
        m.send_state = "manual_sent"
        if pair:
            pair.status = "SENT"
        event(db, m, "MANUAL_SENT", resolved="user confirmed it was delivered")
    elif outcome == "not_sent":
        m.send_state, m.approval_state, m.sent_at = "not_sent", "awaiting_approval", None
        if pair:
            pair.status = "AWAITING_APPROVAL"
        event(db, m, "RECONCILED_NOT_SENT")
    else:
        raise ValueError("outcome must be 'sent' or 'not_sent'")
