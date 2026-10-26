"""Task match_jobs: analyse every visible job for this user, score contacts per job, rank opportunities.

shortcut: job-specific contact scores are computed for the 40 best general-ranked contacts at each company and the top 10 per
job are stored; a company where the right person ranks below 40 generally needs a re-rank (raise CANDIDATES) first.
"""
import hashlib
from datetime import date

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models.contacts import Company, Contact, EmailContact
from ..models.core import UserSetting
from ..models.jobs import Job, UserJob
from ..models.matching import JobContactScore, UserJobMatch
from ..models.profile import ProfileItem, ProfileVersion
from ..models.tailoring import TailoredResume
from ..models.scoring import ContactScore
from ..tasks import handler
from ..util import utcnow
from . import classify, contact_job, job_verify, jd_analysis, matching, opportunity, profile as profile_svc, scoring_run
from .companies import company_key

CANDIDATES, STORE_PER_JOB = 40, 10
DEFAULTS = {"match_weights": matching.DEFAULT_MATCH_WEIGHTS, "contact_weights": contact_job.DEFAULT_WEIGHTS,
            "opportunity_weights": opportunity.DEFAULT_WEIGHTS, "contacts_per_job": 3}


def get_config(db: Session) -> dict:
    s = db.query(UserSetting).filter(UserSetting.key == "matching.config").first()
    cfg = {**DEFAULTS, **(s.value if s else {})}
    cfg["match_weights"] = matching.normalize_match_weights(cfg["match_weights"])
    cfg["contact_weights"] = contact_job.normalize_weights(cfg["contact_weights"])
    cfg["opportunity_weights"] = opportunity.normalize_weights(cfg["opportunity_weights"])
    cfg["contacts_per_job"] = max(1, min(int(cfg["contacts_per_job"]), 5))
    cfg["missing_policy"] = scoring_run.get_config(db)["missing_policy"]  # one policy for all scores
    return cfg


def _items(db: Session) -> list[dict]:
    return [profile_svc.serialize(i) for i in db.query(ProfileItem).filter(ProfileItem.status.in_(("active", "suggested"))).all()]


def job_domains(job: Job, analysis: dict) -> list[str]:
    text = job.title + " " + " ".join(analysis.get("keywords", [])[:15]) + " " + " ".join(r["term"] for r in analysis["requirements"] if r["type"] == "skill")
    return sorted(classify.domain_tags(text))


def run_matching(db: Session, job_ids: list[str] | None = None, today: date | None = None) -> dict:
    today, now = today or date.today(), utcnow()
    cfg = get_config(db)
    user = scoring_run.user_context(db)
    prof = matching.summarize_profile(_items(db), today)
    last_v = db.query(ProfileVersion).order_by(ProfileVersion.version.desc()).first()
    q = db.query(Job).join(UserJob, UserJob.job_id == Job.id).filter(UserJob.hidden.is_(False))
    if job_ids:
        q = q.filter(Job.id.in_(job_ids))
    jobs = q.all()
    names = {c.id: c.name for c in db.query(Company.id, Company.name).all()}
    existing = {m.job_id: m for m in db.query(UserJobMatch).all()}
    cands: dict[str, list] = {}
    hr_count = dict(db.query(EmailContact.company_id, func.count()).filter(EmailContact.email_valid.is_(True)).group_by(EmailContact.company_id).all())
    rstat: dict[str, str] = {}
    for jid, st in db.query(TailoredResume.job_id, TailoredResume.status).all():
        rstat[jid] = "approved" if st == "approved" or rstat.get(jid) == "approved" else "draft"
    by_job_rows: dict[str, list[dict]] = {}
    rows_for_rank = []
    for job in jobs:
        dh = hashlib.sha1((job.description or "").encode()).hexdigest()
        prev = existing.get(job.id)
        analysis = prev.analysis if prev and prev.desc_hash == dh else jd_analysis.analyse(job.description)
        matrix = matching.build_matrix(analysis, prof)
        jinfo = {"title": job.title, "work_arrangement": job.work_arrangement, "location": job.location, "employment_type": job.employment_type, "status": job.status}
        elig = matching.eligibility(analysis, prof, jinfo, matrix)
        mcfg = {"weights": cfg["match_weights"], "missing_policy": cfg["missing_policy"]}
        ms = matching.match_score(analysis, matrix, elig, prof, jinfo, mcfg)

        if job.company_id not in cands:
            cands[job.company_id] = db.query(Contact, ContactScore).outerjoin(ContactScore, ContactScore.contact_id == Contact.id) \
                .filter(Contact.company_id == job.company_id).order_by(ContactScore.rank.asc().nullslast()).limit(CANDIDATES).all()
        jd_dom = job_domains(job, analysis)
        scored = []
        ckey = company_key(names.get(job.company_id))
        for c, gs in cands[job.company_id]:
            if gs is not None and gs.excluded:
                continue
            cl = classify.classify(c.position)
            ct = {"role_category": cl["role_category"], "role_position": c.position, "seniority": cl["seniority"], "domains": cl["domains"],
                  "connected_on": c.connected_on, "employment_status": c.employment_status or "unknown", "employment_verified": c.employment_verified_at is not None,
                  "general_confidence": gs.confidence if gs else None, "prior_employer": ckey in user["prior_employer_keys"]}
            r = contact_job.score({"title": job.title, "domains": jd_dom}, ct, today, {"weights": cfg["contact_weights"], "missing_policy": cfg["missing_policy"]})
            scored.append({"contact_id": c.id, "total": r["total"], "components": r["components"], "employment_label": r["employment_label"],
                           "general_confidence": ct["general_confidence"]})
        rec = contact_job.recommend(scored, cfg["contacts_per_job"])[:STORE_PER_JOB]
        by_job_rows[job.id] = rec
        best = max((r["total"] for r in rec if r["recommended"]), default=None)
        es = ms["eligibility_summary"]
        pr = opportunity.score(ms["total"], job.status, job_verify.needs_reverify(job, now), best, hr_count.get(job.company_id, 0), job.deadline, now, es,
                               {"weights": cfg["opportunity_weights"], "missing_policy": cfg["missing_policy"]})
        rows_for_rank.append({"job_id": job.id, "total": pr["total"], "group": pr["group"], "title": job.title, "company": names.get(job.company_id)})
        m = existing.get(job.id) or UserJobMatch(job_id=job.id)
        if m.id is None:
            db.add(m)
        m.desc_hash, m.analysis, m.matrix, m.eligibility = dh, analysis, matrix, elig
        m.match_total, m.match_components = ms["total"], ms["components"]
        m.match_extra = {k: ms[k] for k in ("prioritize_applying", "aligned_skills", "missing_qualifications", "to_verify", "eligibility_summary")}
        m.priority_total, m.priority_components, m.readiness_group = pr["total"], pr["components"], pr["group"]
        m.next_action = opportunity.next_action(job.status, elig, best is not None, rstat.get(job.id, "not_started"))
        m.profile_version, m.config_snapshot, m.computed_at = (last_v.version if last_v else 0), cfg, now
    # contacts: replace this run's rows, then link one person across several jobs at a company
    if jobs:
        db.query(JobContactScore).filter(JobContactScore.job_id.in_([j.id for j in jobs])).delete(synchronize_session=False)
    cons = contact_job.consolidate(by_job_rows)
    for jid, rec in by_job_rows.items():
        for r in rec:
            db.add(JobContactScore(job_id=jid, contact_id=r["contact_id"], total=r["total"], components=r["components"], employment_label=r["employment_label"],
                                   rank_in_job=r["rank_in_job"], recommended=r["recommended"],
                                   also_fits_jobs=[x for x in cons.get(r["contact_id"], []) if x != jid] if r["recommended"] else [],
                                   config_snapshot={"contact_weights": cfg["contact_weights"], "missing_policy": cfg["missing_policy"]}))
    db.flush()
    # rank across ALL of the user's matches (a partial run still re-ranks the whole list)
    all_rows = [{"job_id": m.job_id, "total": m.priority_total, "group": m.readiness_group, "title": j.title, "company": names.get(j.company_id)}
                for m, j in db.query(UserJobMatch, Job).join(Job, Job.id == UserJobMatch.job_id).all()]
    ranked = {r["job_id"]: r for r in opportunity.rank_all(all_rows)}
    for m in db.query(UserJobMatch).all():
        r = ranked.get(m.job_id)
        if r:
            m.rank, m.score_only_rank, m.trade_off = r["rank"], r["score_only_rank"], r["trade_off"]
    return {"matched": len(jobs), "total_opportunities": len(ranked)}


@handler("match_jobs")
def match_jobs(ctx):
    return run_matching(ctx.db, ctx.payload.get("job_ids"))
