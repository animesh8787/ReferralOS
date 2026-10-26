"""The one gate every message passes. check() returns blocks (must fix / cannot send) and warnings (shown, not blocking).

stage="approve": content rules only (a message with bad content cannot even be approved).
stage="send": content rules + every sending rule (approval, pause, suppression, duplicates, job state, limits, acknowledgements).

Temporary blocks (limits, pause, stale job, no provider, follow-up spacing) leave the message queued; PERMANENT blocks
(suppressed, do-not-contact, duplicate, closed job, bad content) mark it blocked so nothing retries it silently.
"""
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .. import job_verify
from . import compliance, drafts

TEMPORARY = {"GLOBAL_PAUSE", "CAMPAIGN_PAUSED", "DAILY_LIMIT", "COMPANY_DAILY_LIMIT", "INTRO_DAILY_LIMIT", "CAMPAIGN_DAILY_LIMIT", "JOB_STALE", "NO_PROVIDER",
             "FOLLOWUP_SPACING", "ACK_REQUIRED", "CONSENT_REGION_ACK_REQUIRED", "MANUAL_MODE"}
EMAIL_RX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass
class Ctx:
    settings: dict
    now: datetime
    suppressed_emails: set = field(default_factory=set)
    suppressed_domains: set = field(default_factory=set)
    sent_today_total: int = 0
    sent_today_company: int = 0
    sent_today_intro: int = 0
    sent_today_campaign: int = 0
    other_initial_to_same: list = field(default_factory=list)  # [(message id, send_state, created_at)] initial emails to the same address
    job: object | None = None
    pair_status: str = ""
    provider_ready: bool = False
    campaign: object | None = None
    attachment: dict | None = None  # {"approved": bool, "for_job": bool, "size": int}
    followups_sent: int = 0
    last_sent_at: datetime | None = None
    contact_email: object | None = None
    bulk_blocked: bool = False
    region: str | None = None
    msg_id: str = ""


def business_days(a: datetime, b: datetime) -> int:
    d, n = a.date(), 0
    while d < b.date():
        d += timedelta(days=1)
        n += d.weekday() < 5
    return n


def add_business_days(a: datetime, n: int) -> datetime:
    d = a
    while n > 0:
        d += timedelta(days=1)
        n -= d.weekday() < 5
    return d


def _b(code: str, detail: str) -> dict:
    return {"code": code, "detail": detail, "permanent": code not in TEMPORARY}


def content_checks(m, ctx: Ctx) -> list[dict]:
    out = []
    s = ctx.settings
    text = "\n".join(x for x in (m.subject, m.body, m.connect_note) if x)
    if drafts.unresolved(text):
        out.append(_b("UNRESOLVED_PLACEHOLDER", "Fill in: " + ", ".join(sorted(set(drafts.unresolved(text))))))
    if m.channel == "email":
        if not (m.subject or "").strip() or not (m.body or "").strip():
            out.append(_b("MISSING_SUBJECT_OR_BODY", "An email needs a subject and a body."))
        if m.subject and compliance.DECEPTIVE_SUBJECT.search(m.subject):
            out.append(_b("DECEPTIVE_SUBJECT", "The subject looks like a fake reply/forward or uses pressure wording. Rewrite it plainly."))
        if "unsubscribe" not in (m.body or "").lower():
            out.append(_b("MISSING_OPT_OUT", "Every cold email needs a clear line telling the recipient how to opt out."))
        if not (s.get("sender_name") and s.get("sender_email") and EMAIL_RX.match(s["sender_email"])):
            out.append(_b("MISSING_SENDER_IDENTITY", "Set your real name and your own email address in Outreach settings."))
        if not m.to_email or not EMAIL_RX.match(m.to_email):
            out.append(_b("INVALID_EMAIL", "The recipient address is missing or invalid."))
        elif re.match(r"^(no[-_.]?reply|do[-_.]?not[-_.]?reply|donotreply|mailer-daemon|postmaster)@", m.to_email, re.I):
            out.append(_b("INVALID_EMAIL", "This is a no-reply address; it cannot receive a reply."))
        if m.attach_resume_id:
            a = ctx.attachment or {}
            if not a.get("approved") or not a.get("for_job"):
                out.append(_b("ATTACHMENT_INVALID", "Only a resume you approved for this job can be attached."))
            elif a.get("size", 0) > 2 * 1024 * 1024:
                out.append(_b("ATTACHMENT_INVALID", "The resume file is over 2 MB."))
    else:
        if len(m.body or "") > drafts.LINKEDIN_BODY_MAX:
            out.append(_b("LINKEDIN_TOO_LONG", f"LinkedIn messages here are limited to {drafts.LINKEDIN_BODY_MAX} characters."))
        if m.connect_note and len(m.connect_note) > drafts.CONNECT_NOTE_MAX:
            out.append(_b("LINKEDIN_TOO_LONG", f"A connection note is limited to {drafts.CONNECT_NOTE_MAX} characters."))
    if m.job_id and ctx.job is not None and ctx.job.status in ("CLOSED", "POSSIBLY_CLOSED") and m.kind != "thank_you":
        out.append(_b("JOB_CLOSED", "The job is closed or may be closed, so this draft is stale. Nothing is sent about it."))
    if m.kind != "thank_you" and (hits := drafts.forbidden_hits(text)):
        out.append(_b("FORBIDDEN_CLAIM", "The text claims a relationship, promise or credential we cannot support: " + ", ".join(sorted(set(hits)))))
    bad = [c for c in (m.ledger or []) if c.get("status") == "needs_confirmation"] + [f for f in (m.risk_flags or []) if f.get("code") == "UNVERIFIED_CLAIMS"]
    if bad:
        out.append(_b("UNVERIFIED_CLAIMS", "The message mentions technologies or numbers not found in your profile. Remove them, or add them to your profile if true."))
    return out


def send_checks(m, ctx: Ctx) -> list[dict]:
    out, s = [], ctx.settings
    if m.approval_state != "approved":
        out.append(_b("NOT_APPROVED", "Nothing is sent without your explicit approval."))
    if m.channel != "email":
        out.append(_b("CHANNEL_NOT_SENDABLE", "LinkedIn messages are never sent by this app. Copy it and send it yourself."))
        return out
    if s["delivery_mode"] == "MANUAL_REVIEW":
        out.append(_b("MANUAL_MODE", "Delivery mode is manual: copy or open the email and send it yourself, then mark it sent."))
    elif s["delivery_mode"] == "AUTHORISED_INTEGRATION" and not ctx.provider_ready:
        out.append(_b("NO_PROVIDER", "Connect your Gmail account (or switch to manual mode)."))
    if s["global_pause"]:
        out.append(_b("GLOBAL_PAUSE", "Sending is paused for your whole account."))
    if ctx.campaign is not None and ctx.campaign.paused:
        out.append(_b("CAMPAIGN_PAUSED", "This campaign is paused."))
    if ctx.pair_status == "DO_NOT_CONTACT":
        out.append(_b("DO_NOT_CONTACT", "This person is marked do-not-contact."))
    to = (m.to_email or "").lower()
    dom = to.rsplit("@", 1)[-1] if "@" in to else ""
    if to in ctx.suppressed_emails:
        out.append(_b("SUPPRESSED_EMAIL", "This address is on your do-not-contact list."))
    if dom and (dom in ctx.suppressed_domains or dom in set(s.get("domain_blocklist", []))):
        out.append(_b("SUPPRESSED_DOMAIN", f"The domain {dom} is blocked."))
    if m.is_initial and ctx.other_initial_to_same:
        out.append(_b("DUPLICATE_INITIAL", "An initial email to this address already exists. Only one cold email is ever sent per recipient."))
    if ctx.bulk_blocked:
        out.append(_b("BULK_BLOCKED_PROVENANCE", "This contact came from a purchased/unknown-source list: no automated sending; use manual one-off drafts."))
    if m.kind in ("cold_job", "follow_up") and m.job_id:
        j = ctx.job
        if j is None or j.status in ("CLOSED", "POSSIBLY_CLOSED"):
            out.append(_b("JOB_NOT_ACTIVE", "The job is closed or may be closed; nothing is sent about it."))
        elif j.status != "ACTIVE_VERIFIED":
            out.append(_b("JOB_NOT_ACTIVE", "Only verified-open jobs get job-specific emails."))
        elif job_verify.needs_reverify(j, ctx.now):
            out.append(_b("JOB_STALE", "The job was last verified over 3 days ago. Re-verify it first."))
    if not s.get("lawful_use_ack"):
        out.append(_b("ACK_REQUIRED", "Acknowledge the lawful-use statement in Outreach settings first."))
    if compliance.needs_region_ack(ctx.region, s):
        out.append(_b("CONSENT_REGION_ACK_REQUIRED", f"Recipients in {ctx.region} are in a region that usually requires prior consent. Read the guidance and acknowledge it for this region."))
    cap = s["intro_daily"] if m.kind == "cold_intro" else None
    if ctx.sent_today_total >= s["daily_limit"]:
        out.append(_b("DAILY_LIMIT", f"Today's limit of {s['daily_limit']} emails is reached."))
    if ctx.sent_today_company >= s["per_company_daily"]:
        out.append(_b("COMPANY_DAILY_LIMIT", f"Today's limit of {s['per_company_daily']} emails to this company is reached."))
    if cap is not None and ctx.sent_today_intro >= cap:
        out.append(_b("INTRO_DAILY_LIMIT", f"Today's limit of {cap} introductory emails is reached."))
    if ctx.campaign is not None and ctx.campaign.daily_limit is not None and ctx.sent_today_campaign >= ctx.campaign.daily_limit:
        out.append(_b("CAMPAIGN_DAILY_LIMIT", "This campaign's daily limit is reached."))
    if m.kind == "follow_up":
        if ctx.followups_sent >= s["max_followups"]:
            out.append(_b("FOLLOWUP_LIMIT", f"At most {s['max_followups']} follow-up(s) per person."))
        if ctx.last_sent_at and business_days(ctx.last_sent_at, ctx.now) < s["followup_spacing_business_days"]:
            out.append(_b("FOLLOWUP_SPACING", f"Follow-ups need {s['followup_spacing_business_days']} business days since the last email."))
    return out


def warnings(m, ctx: Ctx) -> list[dict]:
    w = []
    ec = ctx.contact_email
    if ec is not None:
        for fl, txt in (("role_account", "Shared mailbox (info@, hr@): replies may go to several people."), ("mx_missing", "The domain has no mail server record.")):
            if fl in (ec.email_flags or []):
                w.append({"code": fl.upper(), "detail": txt})
    if m.channel == "email" and ctx.region:
        g = compliance.guidance_for(ctx.region)
        if g["requires_extra_ack"]:
            w.append({"code": "JURISDICTION", "detail": g["text"] + " " + g["disclaimer"]})
    return w


def check(m, ctx: Ctx, stage: str = "send") -> dict:
    blocks = content_checks(m, ctx) + (send_checks(m, ctx) if stage == "send" else [])
    return {"blocks": blocks, "warnings": warnings(m, ctx), "ok": not blocks, "permanent": any(b["permanent"] for b in blocks)}
