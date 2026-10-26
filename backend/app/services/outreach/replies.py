"""Replies, bounces, opt-outs and follow-ups.

Classification is rule-based and ALWAYS user-correctable. The only automatic actions are: a hard bounce suppresses that
address, and any real reply cancels pending follow-ups. An opt-out request is only a SUGGESTION until the user confirms it.
"""
import re
from datetime import datetime

from sqlalchemy.orm import Session

from ...models.contacts import SuppressionEntry
from ...models.jobs import Job
from ...models.outreach import EmailEvent, OutreachMessage, OutreachPair
from ...util import utcnow
from .. import job_verify
from . import drafts, preflight, send

R = lambda p: re.compile(p, re.I)  # noqa: E731
RULES = [
    # A hard bounce needs an explicit PERMANENT-failure phrase. The sender (mailer-daemon/postmaster) alone is never enough:
    # "mailbox full" notices come from the same sender and must not suppress a perfectly good address.
    ("bounce_soft", R(r"mailbox (is )?full|over quota|try again later|temporar(y|ily)|452[ -]4|deferred|\b4\.\d\.\d\b")),
    ("bounce_hard", R(r"delivery status notification \(failure\)|undeliverable|550[ -]5\.1\.1|\b5\.1\.1\b|user unknown|no such user|address (not found|rejected)|does not exist|account (has been )?disabled|recipient (address )?rejected")),
    ("ooo", R(r"out of (the )?office|automatic reply|auto-?reply|on (annual )?leave|on vacation|away from (my )?(desk|email)|will (be )?return(ing)? on")),
    ("unsubscribe", R(r"\bunsubscribe\b|remove me|stop (emailing|contacting|messaging)|do not (contact|email)|don'?t (contact|email) me|take me off|no more emails")),
    ("referral_offered", R(r"(happy|glad|willing) to refer|i can refer you|i('ll| will) refer you|submitted (a|your) referral|referred you|put (your name|you) forward")),
    ("negative", R(r"not hiring|no (current )?(openings|vacancies|roles)|unfortunately|cannot (refer|help)|can'?t (refer|help)|position (has been )?filled|not able to refer|no longer (hiring|open)")),
    ("positive", R(r"happy to (chat|talk|help)|send (me )?your (resume|cv)|let'?s (chat|talk|connect)|schedule a (call|chat)|interested|please apply|reach out to|forward your")),
]


def classify(text: str, from_addr: str = "") -> tuple[str, str]:
    """-> (label, matched phrase). Order matters: bounces and auto-replies first so they are never mistaken for human replies."""
    for label, rx in RULES:
        if m := rx.search(f"{from_addr}\n{text}" if label != "bounce_hard" else text):  # never judge a hard bounce by the sender alone
            return label, m.group(0)
    if re.search(r"mailer-daemon|postmaster", from_addr, re.I):  # a delivery notice we cannot read: treat as soft, suppress nothing
        return "bounce_soft", "automated delivery notice"
    return "neutral", ""


def cancel_followups(db: Session, pair_ids: list[str], why: str, include_all_unsent: bool = False) -> int:
    kinds = ("follow_up",) if not include_all_unsent else ("follow_up", "referral", "cold_job", "cold_intro", "thank_you")
    n = 0
    for m in db.query(OutreachMessage).filter(OutreachMessage.pair_id.in_(pair_ids), OutreachMessage.kind.in_(kinds),
                                              OutreachMessage.send_state.in_(("not_sent", "queued", "manual_pending", "blocked", "failed"))).all():
        if m.approval_state in ("cancelled", "rejected"):
            continue
        m.approval_state, m.send_state = "cancelled", "not_sent"
        send.event(db, m, "CANCELLED", why=why)
        n += 1
    return n


def suppress(db: Session, email: str, reason: str, source: str) -> bool:
    email = email.lower().strip()
    if db.query(SuppressionEntry.id).filter(SuppressionEntry.kind == "email", SuppressionEntry.value == email).first():
        return False
    db.add(SuppressionEntry(kind="email", value=email, reason=reason, source=source))
    return True


def ingest(db: Session, m: OutreachMessage, from_addr: str, subject: str, body: str, at: datetime | None = None) -> dict:
    """Record one inbound message about a sent email and apply the (limited) automatic consequences."""
    label, phrase = classify(f"{subject}\n{body}", from_addr)
    pair = db.get(OutreachPair, m.pair_id)
    ev = send.event(db, m, {"bounce_hard": "BOUNCED_HARD", "bounce_soft": "BOUNCED_SOFT", "ooo": "OOO_AUTOREPLY", "unsubscribe": "UNSUBSCRIBE_REQUESTED"}.get(label, "REPLIED"),
                    from_addr=from_addr[:200], subject=subject[:200], snippet=body[:300], matched=phrase, at=(at or utcnow()).isoformat())
    ev.label, auto = label, []
    if label == "bounce_hard":
        if m.to_email and suppress(db, m.to_email, "bounced", "hard_bounce"):
            auto.append("address suppressed")
        if pair:
            pair.status = "DO_NOT_CONTACT"
        cancel_followups(db, [m.pair_id], "hard bounce", include_all_unsent=True)
    elif label in ("bounce_soft", "ooo"):
        pass  # not a human reply: follow-ups stay scheduled, nothing is suppressed
    else:
        cancel_followups(db, [m.pair_id], "recipient replied")
        if pair and pair.status in ("SENT", "DELIVERY_UNCONFIRMED", "QUEUED"):
            pair.status = "REFERRAL_OFFERED" if label == "referral_offered" else "REPLIED"
        if label == "unsubscribe":
            ev.confirmed = None  # a SUGGESTION: nothing is suppressed until the user confirms
    return {"event_id": ev.id, "label": label, "matched": phrase, "automatic": auto,
            "needs_confirmation": "Looks like a request to stop contacting them. Confirm to add them to your do-not-contact list." if label == "unsubscribe" else None}


def confirm_optout(db: Session, ev: EmailEvent, confirmed: bool) -> dict:
    m = db.get(OutreachMessage, ev.message_id)
    if ev.type != "UNSUBSCRIBE_REQUESTED":
        raise ValueError("This event is not an opt-out request")
    ev.confirmed = confirmed
    if not confirmed:
        return {"suppressed": False}
    if m.to_email:
        suppress(db, m.to_email, "unsubscribed", "reply_confirmed")
        pairs = [p.id for p in db.query(OutreachPair).filter(OutreachPair.email_contact_id == db.get(OutreachPair, m.pair_id).email_contact_id).all()] if db.get(OutreachPair, m.pair_id).email_contact_id else [m.pair_id]
        for pid in pairs:
            p = db.get(OutreachPair, pid)
            if p:
                p.status = "DO_NOT_CONTACT"
        cancel_followups(db, pairs, "opt-out confirmed", include_all_unsent=True)
    return {"suppressed": True}


def relabel(ev: EmailEvent, label: str) -> None:
    if label not in ("positive", "neutral", "negative", "ooo", "unsubscribe", "referral_offered", "bounce_hard", "bounce_soft"):
        raise ValueError("Unknown label")
    ev.label = label
    ev.detail = {**ev.detail, "relabelled_by_user": True}


# ---------------------------------------------------------------- follow-ups (drafts only, never sent silently)
def scan_followups(db: Session, cfg: dict, facts: dict, sender_email: str | None, now: datetime | None = None) -> dict:
    now = now or utcnow()
    made, skipped = [], []
    sent = db.query(OutreachMessage).filter(OutreachMessage.channel == "email", OutreachMessage.send_state.in_(("sent", "manual_sent")),
                                            OutreachMessage.kind.in_(("referral", "cold_job", "cold_intro", "follow_up"))).order_by(OutreachMessage.sent_at).all()
    by_pair: dict[str, list[OutreachMessage]] = {}
    for m in sent:
        by_pair.setdefault(m.pair_id, []).append(m)
    for pid, msgs in by_pair.items():
        last, pair = msgs[-1], db.get(OutreachPair, pid)
        if db.query(EmailEvent.id).filter(EmailEvent.message_id.in_([x.id for x in msgs]), EmailEvent.label.in_(("positive", "neutral", "negative", "referral_offered", "unsubscribe", "bounce_hard"))).first():
            skipped.append({"pair": pid, "why": "recipient already replied or bounced"})
            continue
        if pair.status in ("DO_NOT_CONTACT", "REPLIED", "REFERRAL_OFFERED", "REJECTED", "CLOSED", "APPLICATION_SUBMITTED", "REFERRAL_SUBMITTED"):
            skipped.append({"pair": pid, "why": f"pair is {pair.status}"})
            continue
        n = sum(1 for x in msgs if x.kind == "follow_up")
        if n >= cfg["max_followups"]:
            skipped.append({"pair": pid, "why": "follow-up limit reached"})
            continue
        if preflight.business_days(last.sent_at, now) < cfg["followup_spacing_business_days"]:
            skipped.append({"pair": pid, "why": "too soon"})
            continue
        if db.query(OutreachMessage.id).filter(OutreachMessage.pair_id == pid, OutreachMessage.kind == "follow_up", OutreachMessage.approval_state.in_(("awaiting_approval", "approved")),
                                               OutreachMessage.send_state.in_(("not_sent", "queued", "manual_pending", "blocked", "failed"))).first():  # an UNSENT draft only
            skipped.append({"pair": pid, "why": "a follow-up draft is already waiting"})
            continue
        job = db.get(Job, last.job_id) if last.job_id else None
        if job is not None and (job.status in ("CLOSED", "POSSIBLY_CLOSED")):
            skipped.append({"pair": pid, "why": "the job is closed"})
            continue
        if cfg["global_pause"]:
            skipped.append({"pair": pid, "why": "sending is paused"})
            continue
        first = msgs[0]
        d = drafts.follow_up(facts, {"first": drafts.first_name(first.to_name)}, first.subject or "my earlier email", first.sent_at,
                             {"title": job.title} if job else None, (first.options or {}).get("company", "your company"), cfg, sender_email, n + 1)
        fm = OutreachMessage(pair_id=pid, parent_id=last.id, job_id=first.job_id, covers_job_ids=first.covers_job_ids, channel="email", kind="follow_up", is_initial=False,
                             to_name=first.to_name, to_email=first.to_email, subject=d["subject"], body=d["body"], options=first.options, campaign_id=first.campaign_id,
                             approval_state="awaiting_approval", send_state="not_sent")
        db.add(fm)
        db.flush()
        send.event(db, last, "FOLLOW_UP_DUE", draft_id=fm.id)
        made.append(fm.id)
    return {"drafts_created": made, "skipped": skipped}
