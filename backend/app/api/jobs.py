import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from .. import ratelimit, tasks
from ..adapters import ats
from ..adapters.http import FetchError, PoliteFetcher, UnsafeUrl, check_public_url
from ..audit import audit
from ..models.contacts import Company, Contact
from ..models.core import User
from ..models.jobs import DiscoveryRun, Job, JobSource, JobVerification, UserBoard, UserJob
from ..security import current_user, scoped_db
from ..services import job_verify, jobs_store, referral_route
from ..services.companies import CompanyResolver, company_key
from .contacts import _names, page_args

router = APIRouter(prefix="/api", tags=["jobs"])


# ---------------------------------------------------------------- boards
def _b(b: UserBoard, name: str | None) -> dict:
    return {"id": b.id, "company_id": b.company_id, "company": name, "ats": b.ats, "token": b.token, "careers_url": b.careers_url,
            "confirmed": b.confirmed, "added_from": b.added_from, "last_run_at": b.last_run_at, "last_status": b.last_status, "jobs_found": b.jobs_found}


class BoardIn(BaseModel):
    company: str
    ats: str | None = None
    token: str | None = None
    board_url: str | None = None  # a public job-board URL; ats+token are read from it
    careers_url: str | None = None


@router.post("/boards", status_code=201)
def add_board(body: BoardIn, db: Session = Depends(scoped_db)):
    ats_name, token = body.ats, body.token
    if body.board_url:
        found = ats.board_from_url(body.board_url)
        if not found:
            raise HTTPException(422, "That URL is not a recognised public job board (Greenhouse, Lever, Ashby, Workable, SmartRecruiters)")
        ats_name, token = found
    if ats_name not in ats.ATS_TYPES or not token or not ats.TOKEN_RE.match(token):
        raise HTTPException(422, "Provide a supported ATS and a valid board token, or a board URL")
    cid = CompanyResolver(db).resolve(body.company)
    if not cid:
        raise HTTPException(422, "Company name is required")
    if db.query(UserBoard.id).filter(UserBoard.ats == ats_name, UserBoard.token == token).first():
        raise HTTPException(409, "This board is already added")
    b = UserBoard(company_id=cid, ats=ats_name, token=token, careers_url=body.careers_url, confirmed=True, added_from="user")
    db.add(b)
    db.flush()
    return _b(b, _names(db, [cid]).get(cid))


@router.get("/boards")
def list_boards(db: Session = Depends(scoped_db)):
    rows = db.query(UserBoard).order_by(UserBoard.created_at).all()
    names = _names(db, [b.company_id for b in rows])
    return [_b(b, names.get(b.company_id)) for b in rows]


@router.delete("/boards/{board_id}")
def del_board(board_id: str, db: Session = Depends(scoped_db)):
    b = db.query(UserBoard).filter(UserBoard.id == board_id).first()
    if not b:
        raise HTTPException(404, "Not found")
    db.delete(b)
    return {"deleted": True}


class SuggestIn(BaseModel):
    company: str
    careers_url: str | None = None


@router.post("/boards/suggest")
def suggest_boards(body: SuggestIn, user: User = Depends(current_user), db: Session = Depends(scoped_db)):
    """Candidates only (nothing is saved). A guessed token can belong to a different company with a similar name,
    so each hit shows sample job titles and must be confirmed by the user."""
    ratelimit.check(f"suggest:{user.id}", 20, 3600)
    out, f = [], PoliteFetcher(respect_robots=False)
    if body.careers_url and (found := ats.board_from_url(body.careers_url)):
        out.append({"ats": found[0], "token": found[1], "basis": "recognised from the URL you gave", "sample": []})
    slug = re.sub(r"[^a-z0-9]+", "-", company_key(body.company)).strip("-")
    if slug and ats.TOKEN_RE.match(slug):
        for name in ats.ATS_TYPES:
            if any(o["ats"] == name and o["token"] == slug for o in out):
                continue
            try:
                jobs = ats.list_jobs(f, name, slug)
            except (ats.AtsError, FetchError):
                continue
            out.append({"ats": name, "token": slug, "basis": "a board with this name exists; check that it is the right company",
                        "sample": [j.title for j in jobs[:3]]})
    return {"candidates": out, "note": "Confirm a candidate by adding it via POST /boards." if out else "No public board found with that name."}


# ---------------------------------------------------------------- discovery & verification
@router.post("/jobs/discover", status_code=202)
def discover(user: User = Depends(current_user), db: Session = Depends(scoped_db)):
    ratelimit.check(f"discover:{user.id}", 20, 3600)
    t = tasks.enqueue(db, "discover_jobs", {})
    audit(db, user.id, "job_discovery")
    return {"task_id": t.id, "status": t.status, "result": t.result}


@router.get("/jobs/discovery-runs")
def runs(db: Session = Depends(scoped_db)):
    return [{"id": r.id, "created_at": r.created_at, "summary": r.summary, "coverage": r.coverage}
            for r in db.query(DiscoveryRun).order_by(DiscoveryRun.created_at.desc()).limit(10).all()]


@router.post("/jobs/verify-stale", status_code=202)
def verify_stale(user: User = Depends(current_user), db: Session = Depends(scoped_db)):
    ratelimit.check(f"verify:{user.id}", 30, 3600)
    t = tasks.enqueue(db, "verify_jobs", {})
    return {"task_id": t.id, "status": t.status, "result": t.result}


# ---------------------------------------------------------------- jobs
def _visible(db: Session, job_id: str) -> tuple[Job, UserJob]:
    r = db.query(Job, UserJob).join(UserJob, UserJob.job_id == Job.id).filter(Job.id == job_id).first()
    if not r:
        raise HTTPException(404, "Not found")
    return r


def _j(j: Job, uj: UserJob, names: dict, contacts: dict) -> dict:
    return {"id": j.id, "title": j.title, "company": names.get(j.company_id), "company_id": j.company_id, "location": j.location,
            "work_arrangement": j.work_arrangement, "employment_type": j.employment_type, "apply_url": j.apply_url, "status": j.status,
            "status_reasons": j.status_reasons, "last_verified": j.last_verified, "needs_reverify": job_verify.needs_reverify(j),
            "deadline": j.deadline, "origin": uj.origin, "hidden": uj.hidden, "contacts_at_company": contacts.get(j.company_id, 0),
            "outreach_eligible": j.status == "ACTIVE_VERIFIED"}


@router.get("/jobs")
def list_jobs(q: str | None = None, status: str | None = None, company_id: str | None = None, employment_type: str | None = None,
              work_arrangement: str | None = None, has_contacts: bool | None = None, outreach_eligible: bool | None = None,
              include_hidden: bool = False, page: int = 1, page_size: int = 50, db: Session = Depends(scoped_db)):
    base = db.query(Job, UserJob).join(UserJob, UserJob.job_id == Job.id)
    if not include_hidden:
        base = base.filter(UserJob.hidden.is_(False))
    if status:
        base = base.filter(Job.status == status)
    if outreach_eligible:
        base = base.filter(Job.status == "ACTIVE_VERIFIED")
    if company_id:
        base = base.filter(Job.company_id == company_id)
    if employment_type:
        base = base.filter(Job.employment_type == employment_type)
    if work_arrangement:
        base = base.filter(Job.work_arrangement == work_arrangement)
    if has_contacts is not None:
        sub = db.query(Contact.company_id).filter(Contact.company_id.isnot(None))
        base = base.filter(Job.company_id.in_(sub) if has_contacts else Job.company_id.notin_(sub))
    if q:
        like = f"%{q.strip().lower()}%"
        base = base.filter(or_(func.lower(Job.title).like(like), func.lower(Job.location).like(like), func.lower(Job.description).like(like)))
    total = base.count()
    off, lim = page_args(page, page_size)
    rows = base.order_by(Job.first_discovered.desc(), Job.id).offset(off).limit(lim).all()
    names = _names(db, [j.company_id for j, _ in rows])
    counts = dict(db.query(Contact.company_id, func.count()).filter(Contact.company_id.in_({j.company_id for j, _ in rows} or {""})).group_by(Contact.company_id).all())
    return {"total": total, "page": page, "page_size": lim, "items": [_j(j, uj, names, counts) for j, uj in rows]}


@router.get("/jobs/{job_id}")
def get_job(job_id: str, db: Session = Depends(scoped_db)):
    j, uj = _visible(db, job_id)
    names = _names(db, [j.company_id])
    n = db.query(func.count(Contact.id)).filter(Contact.company_id == j.company_id).scalar()
    ev = db.query(JobVerification).filter(JobVerification.job_id == j.id).order_by(JobVerification.checked_at.desc()).limit(50).all()
    route = referral_route.get_route(db, j.company_id)
    srcs = db.query(JobSource).filter(JobSource.job_id == j.id).all()
    return {**_j(j, uj, names, {j.company_id: n}), "description": j.description, "posted_at": j.posted_at,
            "sources": [{"type": s.source_type, "board": s.board_token, "source_url": s.source_url, "apply_url": s.apply_url, "last_seen": s.last_seen} for s in srcs],
            "verification_evidence": [{"checked_at": e.checked_at, "source": e.source_type, "kind": e.kind, "detail": e.detail} for e in ev],
            "referral_route": {"status": route.status if route else "UNKNOWN", "source": route.source if route else "none",
                               "evidence_url": route.evidence_url if route else None, "evidence_excerpt": route.evidence_excerpt if route else None,
                               "checked_at": route.checked_at if route else None},
            "outreach_note": None if j.status == "ACTIVE_VERIFIED" else "Only verified-active jobs enter the default outreach queue. Review manually before contacting anyone."}


@router.post("/jobs/{job_id}/verify", status_code=202)
def verify_one(job_id: str, user: User = Depends(current_user), db: Session = Depends(scoped_db)):
    _visible(db, job_id)
    ratelimit.check(f"verify:{user.id}", 30, 3600)
    t = tasks.enqueue(db, "verify_jobs", {"job_ids": [job_id]})
    return {"task_id": t.id, "status": t.status, "result": t.result}


@router.post("/jobs/{job_id}/hide")
def hide(job_id: str, db: Session = Depends(scoped_db)):
    _, uj = _visible(db, job_id)
    uj.hidden = not uj.hidden
    return {"hidden": uj.hidden}


class ManualIn(BaseModel):
    url: str | None = None
    title: str | None = None
    company: str | None = None
    location: str | None = None
    description: str | None = None
    apply_url: str | None = None
    employment_type: str | None = None


@router.post("/jobs/manual", status_code=201)
def add_manual(body: ManualIn, user: User = Depends(current_user), db: Session = Depends(scoped_db)):
    """Paste a job URL (read via schema.org JobPosting, robots respected) or the description itself.
    Pasted text proves nothing about whether the role is open, so such jobs stay UNKNOWN until verified."""
    ratelimit.check(f"manual-job:{user.id}", 60, 3600)
    raw, now = None, job_verify.utcnow()
    if body.url:
        try:
            check_public_url(body.url)
            r = PoliteFetcher().get(body.url)
        except (UnsafeUrl, FetchError) as e:
            raise HTTPException(422, f"Could not read that page: {e}")
        found = ats.parse_jsonld(r.text, body.url) if r.status_code == 200 else []
        if found:
            raw = found[0]
            raw.company_name = body.company or raw.company_name
        elif not (body.title and body.company):
            raise HTTPException(422, "No structured job data on that page. Add the title and company, and paste the description.")
    if raw is None:
        if not (body.title and body.company):
            raise HTTPException(422, "Title and company are required")
        raw = ats.RawJob("manual", "", re.sub(r"\W+", "-", f"{body.title}-{body.company}-{user.id[:6]}").lower()[:150], body.title,
                         body.location, None, body.employment_type, body.description or "", body.apply_url or body.url, body.url)
    if raw.source_type == "manual":  # a fetched page keeps its own structured data; pasted fields only fill/override a manual entry
        raw.location, raw.employment_type = body.location or raw.location, body.employment_type or raw.employment_type
    raw.description = body.description or raw.description
    raw.apply_url = body.apply_url or raw.apply_url
    raw.company_name = raw.company_name or body.company
    cname = body.company or raw.company_name
    if not cname:
        raise HTTPException(422, "Company name is required")
    cid = CompanyResolver(db).resolve(cname)
    # only pasted text is private; a job read from a public page is shared like any discovered job
    job, how = jobs_store.upsert_job(db, raw, cid, owner=user.id if raw.source_type == "manual" else None)
    jobs_store.link_user(db, job, "manual")
    if raw.source_type == "jsonld":
        job_verify.record(db, job, "jsonld", "jsonld_valid", now, url=body.url)
        job_verify.apply_decision(db, job, now)
    audit(db, user.id, "job_added_manually", via="url" if body.url else "paste")
    names = _names(db, [cid])
    uj = db.query(UserJob).filter(UserJob.job_id == job.id).one()
    return _j(job, uj, names, {})


# ---------------------------------------------------------------- referral route
class RouteCheck(BaseModel):
    urls: list[str]


@router.post("/companies/{company_id}/referral-route/check")
def check_route(company_id: str, body: RouteCheck, user: User = Depends(current_user), db: Session = Depends(scoped_db)):
    ratelimit.check(f"route:{user.id}", 30, 3600)
    if not db.query(Contact.id).filter(Contact.company_id == company_id).first() and not db.query(Job.id).join(UserJob, UserJob.job_id == Job.id).filter(Job.company_id == company_id).first():
        raise HTTPException(404, "Not found")
    try:
        for u in body.urls[:5]:
            check_public_url(u)
    except UnsafeUrl as e:
        raise HTTPException(422, str(e))
    r = referral_route.check_official_pages(db, company_id, body.urls, PoliteFetcher())
    return {"status": r.status, "source": r.source, "evidence_url": r.evidence_url, "evidence_excerpt": r.evidence_excerpt}


class RouteSet(BaseModel):
    status: str


@router.put("/companies/{company_id}/referral-route")
def set_route(company_id: str, body: RouteSet, db: Session = Depends(scoped_db)):
    if not db.query(Contact.id).filter(Contact.company_id == company_id).first() and not db.query(Job.id).join(UserJob, UserJob.job_id == Job.id).filter(Job.company_id == company_id).first():
        raise HTTPException(404, "Not found")
    try:
        r = referral_route.set_by_user(db, company_id, body.status)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {"status": r.status, "source": r.source}
