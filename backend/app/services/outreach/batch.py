"""Batch preparation: pick real, verified jobs; pick the few best people per job; draft one honest message per PERSON (covering
every role of theirs that fits); skip anyone who was already contacted; flag risks. Nothing here sends anything.
"""
from datetime import date, datetime

from sqlalchemy.orm import Session

from ...adapters.http import PoliteFetcher
from ...models.contacts import Company, Contact, EmailContact, SuppressionEntry
from ...models.jobs import Job, UserJob
from ...models.matching import JobContactScore, UserJobMatch
from ...models.outreach import OutreachBatch, OutreachMessage, OutreachPair
from ...models.tailoring import TailoredResume
from ...util import utcnow
from .. import job_verify, jobs_tasks, matching, referral_route
from ..tailoring import service as tservice, validate
from . import compliance, drafts, send

ACTIVE_STATES = ("awaiting_approval", "approved", "draft")
SENT_STATES = ("sent", "manual_sent", "delivery_unconfirmed", "sending", "queued", "manual_pending")


def _already_contacted(db: Session, *, contact_id: str | None = None, email: str | None = None) -> bool:
    q = db.query(OutreachMessage.id).join(OutreachPair, OutreachPair.id == OutreachMessage.pair_id).filter(OutreachMessage.is_initial.is_(True))
    if contact_id:
        q = q.filter(OutreachPair.contact_id == contact_id)
    elif email:
        q = q.filter(OutreachMessage.to_email == email.lower())
    else:
        return False
    return bool(q.filter((OutreachMessage.approval_state.in_(ACTIVE_STATES)) | (OutreachMessage.send_state.in_(SENT_STATES))).first())


def risk_flags(*, email_contact=None, contact=None, job=None, to_email=None, bulk: bool = False, region=None, unverified_job: bool = False) -> list[dict]:
    f = []
    if email_contact is not None:
        for code, txt in (("role_account", "Shared mailbox: replies may go to several people."), ("mx_missing", "The domain has no mail server record."), ("noreply", "A no-reply address.")):
            if code in (email_contact.email_flags or []):
                f.append({"code": code.upper(), "severity": "warn", "detail": txt})
        f.append({"code": "UNVERIFIED_EMAIL", "severity": "info", "detail": "We checked the address format only; deliverability is not verified."})
    if contact is not None and contact.employment_status != "verified":
        st = contact.employment_status or "unknown"
        f.append({"code": "EMPLOYMENT_" + st.upper(), "severity": "warn" if st == "possibly_outdated" else "info",
                  "detail": {"possibly_outdated": "Their employer is inferred from an old connection and may be out of date.",
                             "likely_current": "Their employer is inferred from a recent connection; it is not verified."}.get(st, "Their current employer is not verified.")})
    if unverified_job:
        f.append({"code": "JOB_NOT_VERIFIED", "severity": "high", "detail": "This job is not verified as open. Check it before sending anything."})
    if bulk:
        f.append({"code": "BULK_BLOCKED", "severity": "high", "detail": "From a purchased/unknown-source list: only manual one-off sending is allowed."})
    g = compliance.guidance_for(region)
    if region and g["requires_extra_ack"]:
        f.append({"code": "JURISDICTION", "severity": "warn", "detail": g["text"] + " " + g["disclaimer"]})
    if region and region not in ("US", "GB", "CA", "AU", "IN") and region not in compliance.EU:
        f.append({"code": "LANGUAGE", "severity": "info", "detail": "The recipient may prefer another language; this draft is in English."})
    return f


def _job_dict(db: Session, j: Job, company: str) -> dict:
    return {"title": j.title, "company": company, "apply_url": j.apply_url, "employment_type": j.employment_type}


def _extra_roles(jobs: list[dict], company: str) -> str:
    return "I'm also interested in " + "; ".join(f"the {x['title']} role ({x['apply_url'] or '{{job_link}}'})" for x in jobs) + f" at {company}."


def _store(db: Session, *, pair_kwargs: dict, draft: dict, variants: dict, items: list[dict], cfg: dict, batch: OutreachBatch | None, job_id: str | None, covers: list[str],
           to: dict, flags: list[dict], options: dict, attach: str | None, company_name: str) -> OutreachMessage:
    pair = OutreachPair(**pair_kwargs, status="DRAFT_READY")
    db.add(pair)
    db.flush()
    ledger = drafts.check_claims(draft["ledger"], items)
    m = OutreachMessage(pair_id=pair.id, batch_id=batch.id if batch else None, job_id=job_id, covers_job_ids=covers, channel=draft["channel"], kind=draft["kind"],
                        is_initial=draft["kind"] != "follow_up", to_name=to.get("name"), to_email=to.get("email"), to_linkedin_url=to.get("linkedin_url"),
                        subject=draft.get("subject"), body=draft["body"], connect_note=draft.get("connect_note"), subject_options=draft.get("subject_options", []),
                        variants=variants, options={**options, "company": company_name, "contact_type": draft.get("contact_type")}, attach_resume_id=attach, ledger=ledger,
                        risk_flags=flags, approval_state="awaiting_approval", send_state="not_sent")
    if any(c["status"] == "needs_confirmation" for c in ledger):
        m.risk_flags = flags + [{"code": "UNVERIFIED_CLAIMS", "severity": "high", "detail": "A statement in this draft is not supported by your profile."}]
    db.add(m)
    pair.status = "AWAITING_APPROVAL"
    db.flush()
    return m


def generate(db: Session, params: dict, cfg: dict, now: datetime | None = None) -> dict:
    now = now or utcnow()
    items = tservice.items_for(db)
    prof = matching.summarize_profile(items, date.today())
    opts = {"tone": params.get("tone") or cfg["tone"], "length": params.get("length") or cfg["length"], "ask": params.get("ask", "referral")}
    include_unconf, max_jobs = bool(params.get("include_unconfirmed")), int(params.get("max_jobs", 5))
    notes = params.get("relationship_notes") or {}
    q = db.query(UserJobMatch, Job).join(Job, Job.id == UserJobMatch.job_id).join(UserJob, UserJob.job_id == Job.id).filter(UserJob.hidden.is_(False))
    if params.get("job_ids"):
        q = q.filter(Job.id.in_(params["job_ids"]))
    else:
        q = q.filter(UserJobMatch.readiness_group.in_((0, 1, 2) if include_unconf else (0,)))
    rows = q.order_by(UserJobMatch.rank).limit(max_jobs if not params.get("job_ids") else 50).all()
    res = {"jobs_considered": len(rows), "jobs_used": [], "skipped": [], "messages": []}
    # stale evidence must be refreshed BEFORE preparing outreach
    stale = [j.id for _, j in rows if job_verify.needs_reverify(j, now)]
    if stale:
        jobs_tasks.verify_many(db, stale, PoliteFetcher())
        db.flush()  # keep the refreshed status/last_verified (expire_all would discard unflushed changes)
        rows = [(m, db.get(Job, j.id)) for m, j in rows]
    batch = OutreachBatch(summary={})
    db.add(batch)
    db.flush()
    names = {c.id: c.name for c in db.query(Company.id, Company.name).all()}
    chosen: list[tuple[UserJobMatch, Job]] = []
    for m, j in rows:
        if j.company_id in set(cfg["excluded_company_ids"]):
            res["skipped"].append({"job_id": j.id, "why": "company excluded"})
        elif j.status == "CLOSED" or j.status == "POSSIBLY_CLOSED":
            res["skipped"].append({"job_id": j.id, "why": f"job is {j.status.lower().replace('_', ' ')}: no outreach is prepared"})
        elif j.status != "ACTIVE_VERIFIED" and not include_unconf:
            res["skipped"].append({"job_id": j.id, "why": "job is not verified as open"})
        elif m.match_extra.get("eligibility_summary", {}).get("VIOLATED"):
            res["skipped"].append({"job_id": j.id, "why": "you appear ineligible for this role"})
        else:
            chosen.append((m, j))
            res["jobs_used"].append(j.id)
    # people: recommended contacts, consolidated across the chosen jobs at the same company
    by_contact: dict[str, list[tuple[UserJobMatch, Job]]] = {}
    for m, j in chosen:
        for r in db.query(JobContactScore).filter(JobContactScore.job_id == j.id, JobContactScore.recommended.is_(True)).all():
            by_contact.setdefault(r.contact_id, []).append((m, j))
    for cid, mj in by_contact.items():
        mj.sort(key=lambda t: -t[0].match_total)
        m0, j0 = mj[0]
        c = db.get(Contact, cid)
        if _already_contacted(db, contact_id=cid):
            res["skipped"].append({"contact_id": cid, "why": "you already have an outreach to this person (one consolidated message per person)"})
            continue
        company = names.get(j0.company_id) or c.company_raw or ""
        facts = drafts.sender_facts(items, m0.matrix, cfg.get("sender_name"), prof)
        route = referral_route.get_route(db, j0.company_id)
        rt = {"status": route.status, "evidence_url": route.evidence_url} if route else None
        ct = {"first": c.first_name, "position": c.position, "role_category": c.role_category, "seniority": c.seniority, "relationship_note": notes.get(cid)}
        job = _job_dict(db, j0, company)
        extra = _extra_roles([_job_dict(db, j, company) for _, j in mj[1:]], company) if len(mj) > 1 else None
        d = drafts.referral_message(facts, ct, job, rt, {**opts, "variant": "A", "extra": extra})
        b = drafts.referral_message(facts, ct, job, rt, {**opts, "variant": "B", "extra": extra})
        msg = _store(db, pair_kwargs={"job_id": j0.id, "contact_id": cid, "company_id": j0.company_id, "channel": "linkedin", "match_score": m0.match_total,
                                      "contact_score": db.query(JobContactScore.total).filter(JobContactScore.job_id == j0.id, JobContactScore.contact_id == cid).scalar()},
                     draft=d, variants={"A": {"body": d["body"]}, "B": {"body": b["body"]}}, items=items, cfg=cfg, batch=batch, job_id=j0.id, covers=[j.id for _, j in mj],
                     to={"name": f"{c.first_name} {c.last_name}".strip(), "linkedin_url": c.linkedin_url}, flags=risk_flags(contact=c, unverified_job=j0.status != "ACTIVE_VERIFIED"),
                     options=opts, attach=None, company_name=company)
        res["messages"].append(msg.id)
    # HR / recruiter emails from the user's own CSV, one job-specific email per person
    supp = {s.value for s in db.query(SuppressionEntry).filter(SuppressionEntry.kind == "email").all()}
    supp_d = {s.value for s in db.query(SuppressionEntry).filter(SuppressionEntry.kind == "domain").all()}
    done_company: dict[str, int] = {}
    for m, j in chosen:
        if done_company.get(j.company_id, 0) >= int(params.get("max_hr_per_company", 2)):
            continue
        for ec in db.query(EmailContact).filter(EmailContact.company_id == j.company_id, EmailContact.email_valid.is_(True)).order_by(EmailContact.created_at).all():
            if done_company.get(j.company_id, 0) >= int(params.get("max_hr_per_company", 2)):
                break
            dom = ec.email_norm.rsplit("@", 1)[-1]
            if ec.email_norm in supp or dom in supp_d or dom in cfg["domain_blocklist"] or "noreply" in (ec.email_flags or []):
                res["skipped"].append({"email_contact_id": ec.id, "why": "suppressed, blocked or a no-reply address"})
                continue
            if ec.bulk_send_blocked:
                res["skipped"].append({"email_contact_id": ec.id, "why": "from a purchased/unknown-source list: bulk drafts are blocked (create a one-off manual draft instead)"})
                continue
            if _already_contacted(db, email=ec.email_norm):
                res["skipped"].append({"email_contact_id": ec.id, "why": "an email to this address already exists (never a second cold email)"})
                continue
            mine = [(mm, jj) for mm, jj in chosen if jj.company_id == j.company_id]
            mine.sort(key=lambda t: -t[0].match_total)
            m0, j0 = mine[0]
            company = names.get(j0.company_id) or ec.company_raw or ""
            facts = drafts.sender_facts(items, m0.matrix, cfg.get("sender_name"), prof)
            appr = db.query(TailoredResume).filter(TailoredResume.job_id == j0.id, TailoredResume.status == "approved").order_by(TailoredResume.version.desc()).first()
            attach = appr.id if appr and cfg["attach_resume_default"] else None
            to = {"first": drafts.first_name(ec.name), "name": ec.name, "email": ec.email_norm}
            job = _job_dict(db, j0, company)
            extra = _extra_roles([_job_dict(db, jj, company) for _, jj in mine[1:]], company) if len(mine) > 1 else None
            d = drafts.cold_email("cold_job", facts, to, job, company, {**opts, "variant": "A", "extra": extra}, cfg.get("sender_email"), bool(attach))
            bd = drafts.cold_email("cold_job", facts, to, job, company, {**opts, "variant": "B", "extra": extra}, cfg.get("sender_email"), bool(attach))
            region = compliance.region_of(ec.email_norm, ec.country_hint)
            msg = _store(db, pair_kwargs={"job_id": j0.id, "email_contact_id": ec.id, "company_id": j0.company_id, "channel": "email", "match_score": m0.match_total, "resume_id": attach},
                         draft=d, variants={"A": {"subject": d["subject"], "body": d["body"]}, "B": {"subject": bd["subject"], "body": bd["body"]}}, items=items, cfg=cfg, batch=batch,
                         job_id=j0.id, covers=[jj.id for _, jj in mine], to=to, flags=risk_flags(email_contact=ec, region=region, unverified_job=j0.status != "ACTIVE_VERIFIED"),
                         options=opts, attach=attach, company_name=company)
            res["messages"].append(msg.id)
            done_company[j.company_id] = done_company.get(j.company_id, 0) + 1
    batch.summary = {"jobs": len(res["jobs_used"]), "messages": len(res["messages"]), "skipped": len(res["skipped"]),
                     "linkedin": sum(1 for i in res["messages"] if db.get(OutreachMessage, i).channel == "linkedin"),
                     "email": sum(1 for i in res["messages"] if db.get(OutreachMessage, i).channel == "email")}
    res["batch_id"], res["summary"] = batch.id, batch.summary
    return res


def create_intro(db: Session, ec: EmailContact, cfg: dict, opts: dict, manual_ok: bool = True) -> OutreachMessage:
    """Speculative intro: clearly says there is no specific opening. Allowed for bulk-blocked contacts only as a manual one-off."""
    if _already_contacted(db, email=ec.email_norm):
        raise ValueError("An email to this address already exists (never a second cold email)")
    items = tservice.items_for(db)
    prof = matching.summarize_profile(items, date.today())
    facts = drafts.sender_facts(items, [], cfg.get("sender_name"), prof)
    company = db.get(Company, ec.company_id).name if ec.company_id else (ec.company_raw or "")
    to = {"first": drafts.first_name(ec.name), "name": ec.name, "email": ec.email_norm}
    d = drafts.cold_email("cold_intro", facts, to, None, company, {**opts, "variant": "A"}, cfg.get("sender_email"), False)
    bd = drafts.cold_email("cold_intro", facts, to, None, company, {**opts, "variant": "B"}, cfg.get("sender_email"), False)
    region = compliance.region_of(ec.email_norm, ec.country_hint)
    return _store(db, pair_kwargs={"email_contact_id": ec.id, "company_id": ec.company_id, "channel": "email"}, draft=d,
                  variants={"A": {"subject": d["subject"], "body": d["body"]}, "B": {"subject": bd["subject"], "body": bd["body"]}}, items=items, cfg=cfg, batch=None,
                  job_id=None, covers=[], to=to, flags=risk_flags(email_contact=ec, bulk=ec.bulk_send_blocked, region=region), options=opts, attach=None, company_name=company)


def create_job_email(db: Session, ec: EmailContact, job: Job, cfg: dict, opts: dict) -> OutreachMessage:
    """One-off job-specific email to a single HR contact (also the only route for bulk-blocked contacts, manual sending only)."""
    if _already_contacted(db, email=ec.email_norm):
        raise ValueError("An email to this address already exists (never a second cold email)")
    items = tservice.items_for(db)
    prof = matching.summarize_profile(items, date.today())
    m = db.query(UserJobMatch).filter(UserJobMatch.job_id == job.id).first()
    company = db.get(Company, job.company_id).name
    facts = drafts.sender_facts(items, m.matrix if m else [], cfg.get("sender_name"), prof)
    appr = db.query(TailoredResume).filter(TailoredResume.job_id == job.id, TailoredResume.status == "approved").order_by(TailoredResume.version.desc()).first()
    attach = appr.id if appr and cfg["attach_resume_default"] else None
    to = {"first": drafts.first_name(ec.name), "name": ec.name, "email": ec.email_norm}
    d = drafts.cold_email("cold_job", facts, to, _job_dict(db, job, company), company, {**opts, "variant": "A"}, cfg.get("sender_email"), bool(attach))
    bd = drafts.cold_email("cold_job", facts, to, _job_dict(db, job, company), company, {**opts, "variant": "B"}, cfg.get("sender_email"), bool(attach))
    region = compliance.region_of(ec.email_norm, ec.country_hint)
    return _store(db, pair_kwargs={"job_id": job.id, "email_contact_id": ec.id, "company_id": job.company_id, "channel": "email", "match_score": m.match_total if m else None, "resume_id": attach},
                  draft=d, variants={"A": {"subject": d["subject"], "body": d["body"]}, "B": {"subject": bd["subject"], "body": bd["body"]}}, items=items, cfg=cfg, batch=None,
                  job_id=job.id, covers=[job.id], to=to, flags=risk_flags(email_contact=ec, bulk=ec.bulk_send_blocked, region=region, unverified_job=job.status != "ACTIVE_VERIFIED"),
                  options=opts, attach=attach, company_name=company)
