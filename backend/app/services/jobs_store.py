"""Normalisation and canonical de-duplication of discovered jobs.

The same position seen on several sources becomes ONE Job with several JobSource rows, so there is one outreach
strategy per canonical job. Matching order: same source id -> same apply URL -> same company + (equal key | very similar
title with compatible location). Manual/private jobs (owner_user_id set) only ever match the same owner's jobs.
"""
import re
from datetime import datetime
from urllib.parse import urlparse

from rapidfuzz import fuzz
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..adapters.ats import RawJob
from ..models.jobs import Job, JobSource, UserJob
from ..util import utcnow

TITLE_SIMILAR = 92


def norm_title(t: str) -> str:
    t = re.sub(r"\(.*?\)", " ", t.lower())  # "(Backend)" / "(Remote)" qualifiers are location-ish noise
    return " ".join(re.sub(r"[^a-z0-9+# ]+", " ", t).split())


def loc_key(loc: str | None) -> str:
    if not loc:
        return ""
    l = loc.lower()
    return "remote" if "remote" in l and "," not in l.replace("remote", "") else re.split(r"[,/;-]", l)[0].strip()


def norm_url(u: str | None) -> str:
    if not u:
        return ""
    p = urlparse(u.strip())
    return f"{(p.hostname or '').lower()}{p.path.rstrip('/')}".lower()


def employment_type(title: str, raw: str | None) -> str:
    s = f"{title} {raw or ''}".lower()
    if re.search(r"\bintern(ship)?\b|\bco-?op\b|working student", s):
        return "internship"
    if re.search(r"part[- ]?time", s):
        return "part_time"
    if re.search(r"contract|temporary|freelance|fixedterm", s):
        return "contract"
    if re.search(r"full[- ]?time|permanent|regular", s):
        return "full_time"
    return "unknown"


def work_arrangement(raw: RawJob) -> str:
    if raw.workplace in ("remote", "hybrid", "onsite"):
        return raw.workplace
    s = f"{raw.location or ''} {raw.title}".lower()
    if raw.remote is True or "remote" in s:
        return "remote"
    if "hybrid" in s:
        return "hybrid"
    return "onsite" if raw.remote is False and raw.location else "unknown"


def parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _compatible(a: str, b: str, ratio: float) -> bool:
    return a == b or ((not a or not b) and ratio >= 98)


def upsert_job(db: Session, raw: RawJob, company_id: str, owner: str | None = None) -> tuple[Job, str]:
    """-> (job, how) with how in new|same_source|same_url|merged. Never creates duplicates of the same posting."""
    now = utcnow()
    src = db.query(JobSource).filter(JobSource.source_type == raw.source_type, JobSource.board_token == raw.board_token,
                                     JobSource.source_job_id == raw.source_job_id).first()
    how = "same_source"
    job = db.get(Job, src.job_id) if src else None
    if job and job.owner_user_id != owner:
        job, src = None, None  # someone else's private copy: never touch, never share
    if not job:
        url = norm_url(raw.apply_url) or norm_url(raw.source_url)
        if url:
            cand = db.query(JobSource).join(Job, Job.id == JobSource.job_id).filter(Job.company_id == company_id, Job.owner_user_id == owner).all()
            m = next((c for c in cand if url in (norm_url(c.apply_url), norm_url(c.source_url))), None)
            job, how = (db.get(Job, m.job_id), "same_url") if m else (None, how)
    nt, lk = norm_title(raw.title), loc_key(raw.location)
    key = f"{nt}|{lk}"
    if not job:
        for cand in db.query(Job).filter(Job.company_id == company_id, Job.owner_user_id == owner).all():
            ratio = fuzz.token_set_ratio(nt, norm_title(cand.title))
            if cand.canonical_key == key or (ratio >= TITLE_SIMILAR and _compatible(lk, cand.canonical_key.split("|")[-1], ratio)):
                job, how = cand, "merged"
                break
    if not job:
        job = Job(company_id=company_id, owner_user_id=owner, title=raw.title.strip()[:300], canonical_key=key, location=raw.location,
                  work_arrangement=work_arrangement(raw), employment_type=employment_type(raw.title, raw.employment_type),
                  description=raw.description or None, apply_url=raw.apply_url, posted_at=raw.posted_at, deadline=parse_dt(raw.deadline))
        db.add(job)
        db.flush()
        how = "new"
    else:  # refresh public facts from the newest sighting; never blank out something we already have
        job.description = raw.description or job.description
        job.apply_url = job.apply_url or raw.apply_url
        job.deadline = parse_dt(raw.deadline) or job.deadline
        if job.employment_type == "unknown":
            job.employment_type = employment_type(raw.title, raw.employment_type)
    if src is None:
        db.add(JobSource(job_id=job.id, source_type=raw.source_type, board_token=raw.board_token, source_job_id=raw.source_job_id,
                         source_url=raw.source_url, apply_url=raw.apply_url))
    else:
        src.last_seen = now
    db.flush()
    return job, how


def link_user(db: Session, job: Job, origin: str) -> bool:
    """Per-user visibility of a (possibly shared) job. db is user-scoped."""
    if db.query(UserJob.id).filter(UserJob.job_id == job.id).first():
        return False
    db.add(UserJob(job_id=job.id, origin=origin))
    return True
