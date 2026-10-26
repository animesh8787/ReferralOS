from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import ratelimit, tasks
from ..audit import audit
from ..models.contacts import Company, Contact
from ..models.core import User, UserSetting
from ..models.jobs import Job, UserJob
from ..models.matching import JobContactScore, UserJobMatch
from ..models.profile import ProfileVersion
from ..security import current_user, scoped_db
from ..services import contact_job, matching, opportunity, referral_route
from ..services.matching_run import get_config
from .contacts import page_args

router = APIRouter(prefix="/api", tags=["matching"])


# ---------------------------------------------------------------- config
@router.get("/matching/config")
def cfg(db: Session = Depends(scoped_db)):
    return get_config(db)


class CfgIn(BaseModel):
    match_weights: dict[str, float] | None = None
    contact_weights: dict[str, float] | None = None
    opportunity_weights: dict[str, float] | None = None
    contacts_per_job: int | None = None


@router.put("/matching/config")
def put_cfg(body: CfgIn, user: User = Depends(current_user), db: Session = Depends(scoped_db)):
    cur = get_config(db)
    try:
        for key, norm in (("match_weights", matching.normalize_match_weights), ("contact_weights", contact_job.normalize_weights),
                          ("opportunity_weights", opportunity.normalize_weights)):
            if getattr(body, key) is not None:
                cur[key] = norm(getattr(body, key))
    except ValueError as e:
        raise HTTPException(422, str(e))
    if body.contacts_per_job is not None:
        if not 1 <= body.contacts_per_job <= 5:
            raise HTTPException(422, "contacts_per_job must be 1-5 (we never recommend messaging everyone)")
        cur["contacts_per_job"] = body.contacts_per_job
    cur.pop("missing_policy", None)  # owned by the scoring config
    s = db.query(UserSetting).filter(UserSetting.key == "matching.config").first()
    if s:
        s.value = cur
    else:
        db.add(UserSetting(key="matching.config", value=cur))
    audit(db, user.id, "matching_config_changed")
    return {**cur, "note": "Re-run matching to apply."}


@router.post("/matching/run", status_code=202)
def run(user: User = Depends(current_user), db: Session = Depends(scoped_db)):
    ratelimit.check(f"match:{user.id}", 30, 3600)
    t = tasks.enqueue(db, "match_jobs")
    return {"task_id": t.id, "status": t.status, "result": t.result}


# ---------------------------------------------------------------- helpers
def _contacts(db, job_id) -> list[dict]:
    rows = db.query(JobContactScore, Contact).join(Contact, Contact.id == JobContactScore.contact_id) \
        .filter(JobContactScore.job_id == job_id).order_by(JobContactScore.rank_in_job).all()
    return [{"contact_id": c.id, "name": f"{c.first_name} {c.last_name}".strip(), "position": c.position, "linkedin_url": c.linkedin_url,
             "score": s.total, "rank_in_job": s.rank_in_job, "recommended": s.recommended, "employment": s.employment_label,
             "also_fits_jobs": s.also_fits_jobs, "components": s.components,
             "note": "Inferred from your connection data; not proof they work there or can refer."} for s, c in rows]


def _card(db: Session, m: UserJobMatch, j: Job, names: dict, detail: bool = False) -> dict:
    route = referral_route.get_route(db, j.company_id)
    contacts = _contacts(db, j.id)
    rec = [c for c in contacts if c["recommended"]]
    latest = db.query(ProfileVersion).order_by(ProfileVersion.version.desc()).first()
    why = [f"Matches {len(m.match_extra['aligned_skills'])} skill(s) you have used: {', '.join(m.match_extra['aligned_skills'][:5])}."] if m.match_extra["aligned_skills"] else []
    why += [v["explanation"] for k, v in m.match_components.items() if v["known"] and v["value"] and v["value"] >= 0.7][:2]
    out = {"job_id": j.id, "title": j.title, "company": names.get(j.company_id), "company_id": j.company_id, "location": j.location, "status": j.status,
           "status_reasons": j.status_reasons, "outreach_eligible": j.status == "ACTIVE_VERIFIED", "match_score": m.match_total,
           "priority_score": m.priority_total, "readiness_group": m.readiness_group, "readiness_label": opportunity.GROUPS[m.readiness_group], "rank": m.rank,
           "score_only_rank": m.score_only_rank, "trade_off": m.trade_off, "prioritize_applying": m.match_extra["prioritize_applying"],
           "why_pursue": why or ["No strong alignment found yet; check the requirement matrix."], "eligibility": m.eligibility,
           "eligibility_summary": m.match_extra["eligibility_summary"], "referral_route": route.status if route else "UNKNOWN",
           "best_contacts": rec, "contact_first": rec[0] if rec else None, "message": {"status": "not_drafted"}, "resume": {"status": "not_tailored"},
           "next_action": m.next_action, "stale": latest is not None and m.profile_version != latest.version, "computed_at": m.computed_at}
    if detail:
        out |= {"analysis": m.analysis, "matrix": m.matrix, "match_components": m.match_components, "match_extra": m.match_extra,
                "priority_components": m.priority_components, "contacts": contacts, "config_snapshot": m.config_snapshot,
                "scoring_versions": {"match": matching.MATCH_VERSION, "contact": contact_job.VERSION, "opportunity": opportunity.VERSION}}
    return out


def _names(db, ids):
    return {c.id: c.name for c in db.query(Company).filter(Company.id.in_(set(ids) or {""})).all()}


def _visible(db, job_id):
    if not db.query(UserJob.id).filter(UserJob.job_id == job_id).first():
        raise HTTPException(404, "Not found")


# ---------------------------------------------------------------- endpoints
@router.get("/jobs/{job_id}/match")
def job_match(job_id: str, db: Session = Depends(scoped_db)):
    _visible(db, job_id)
    r = db.query(UserJobMatch, Job).join(Job, Job.id == UserJobMatch.job_id).filter(Job.id == job_id).first()
    if not r:
        return {"computed": False, "note": "Run matching to analyse this job."}
    return {"computed": True, **_card(db, r[0], r[1], _names(db, [r[1].company_id]), detail=True)}


@router.get("/opportunities")
def opportunities(group: int | None = None, status: str | None = None, min_score: float | None = None, page: int = 1, page_size: int = 25,
                  db: Session = Depends(scoped_db)):
    q = db.query(UserJobMatch, Job).join(Job, Job.id == UserJobMatch.job_id).join(UserJob, UserJob.job_id == Job.id).filter(UserJob.hidden.is_(False))
    if group is not None:
        q = q.filter(UserJobMatch.readiness_group == group)
    if status:
        q = q.filter(Job.status == status)
    if min_score is not None:
        q = q.filter(UserJobMatch.priority_total >= min_score)
    total = q.count()
    off, lim = page_args(page, page_size)
    rows = q.order_by(UserJobMatch.rank).offset(off).limit(lim).all()
    names = _names(db, [j.company_id for _, j in rows])
    return {"total": total, "page": page, "page_size": lim, "items": [_card(db, m, j, names) for m, j in rows]}


@router.get("/opportunities/{job_id}")
def opportunity_detail(job_id: str, db: Session = Depends(scoped_db)):
    return job_match(job_id, db)
