"""Background tasks: discover_jobs (search the user's confirmed ATS boards) and verify_jobs (re-check evidence)."""
from sqlalchemy.orm import Session

from ..adapters import ats
from ..adapters.http import FetchError, PoliteFetcher
from ..models.contacts import Company, Contact
from ..models.jobs import DiscoveryRun, Job, JobSource, JobVerification, UserBoard, UserJob
from ..tasks import enqueue_nowait, handler
from ..util import utcnow
from . import job_verify, jobs_store


def new_fetcher() -> PoliteFetcher:
    return PoliteFetcher()


def run_discovery(db: Session, board_ids: list[str] | None, fetcher: PoliteFetcher, ctx=None) -> dict:
    q = db.query(UserBoard).filter(UserBoard.confirmed.is_(True))
    if board_ids:
        q = q.filter(UserBoard.id.in_(board_ids))
    boards = q.all()
    run = DiscoveryRun()
    db.add(run)
    db.flush()
    from ..models.core import UserSetting
    toggles = db.query(UserSetting).filter(UserSetting.key == "sources.enabled").first()
    disabled = {k for k, v in (toggles.value if toggles else {}).items() if v is False}
    now, cov, new_jobs, total = utcnow(), [], 0, 0
    names = {c.id: c.name for c in db.query(Company.id, Company.name).all()}
    for i, b in enumerate(boards):
        entry = {"board_id": b.id, "company": names.get(b.company_id), "ats": b.ats, "token": b.token, "reachable": False, "jobs": 0, "error": None}
        fetcher.respect_robots = False  # documented public JSON endpoints; robots is re-enabled for page fetches
        try:
            if b.ats in disabled:
                raise ats.AtsError("Source disabled in your settings")
            raws = ats.list_jobs(fetcher, b.ats, b.token)
        except ats.BoardNotFound:
            entry["error"] = "Board not found: check the token"
        except (ats.AtsError, FetchError) as e:
            entry["error"] = str(e)
        else:
            entry.update(reachable=True, jobs=len(raws))
            seen = set()
            for raw in raws:
                job, how = jobs_store.upsert_job(db, raw, b.company_id)
                jobs_store.link_user(db, job, "discovery")
                job_verify.record(db, job, raw.source_type, "api_listed", now, board=b.token)
                seen.add(job.id)
                new_jobs += how == "new"
            # jobs we knew from this board that vanished from its API
            known = db.query(JobSource).filter(JobSource.source_type == b.ats, JobSource.board_token == b.token).all()
            for s in known:
                if s.job_id not in seen:
                    job = db.get(Job, s.job_id)
                    job_verify.record(db, job, b.ats, "api_absent", now, board=b.token)
                    job_verify.apply_decision(db, job, now)
            db.flush()
            for jid in seen:
                job_verify.apply_decision(db, db.get(Job, jid), now)
            total += len(raws)
        fetcher.respect_robots = True
        b.last_run_at, b.last_status, b.jobs_found = now, "ok" if entry["reachable"] else entry["error"], entry["jobs"]
        cov.append(entry)
        if ctx:
            ctx.update(progress=(i + 1) / max(1, len(boards)))
    in_contacts = {cid for (cid,) in db.query(Contact.company_id).filter(Contact.company_id.isnot(None)).distinct()}
    covered = {b.company_id for b in boards if any(e["board_id"] == b.id and e["reachable"] for e in cov)}
    run.coverage = cov
    run.summary = {"boards": len(boards), "reachable": sum(e["reachable"] for e in cov), "jobs_seen": total, "new_jobs": new_jobs,
                   "contact_companies": len(in_contacts), "contact_companies_without_reachable_board": len(in_contacts - covered)}
    run.status = "done"
    enqueue_nowait(db, "match_jobs")  # follow-up: analyse the new jobs against the profile
    return {"run_id": run.id, **run.summary}


@handler("discover_jobs")
def discover_jobs(ctx):
    return run_discovery(ctx.db, ctx.payload.get("board_ids"), new_fetcher(), ctx)


def verify_many(db: Session, job_ids: list[str], fetcher: PoliteFetcher) -> dict:
    cache: dict = {}
    out = {}
    for jid in job_ids:
        job = db.get(Job, jid)
        if job:
            out[jid] = job_verify.verify_job(db, job, fetcher, cache)
    return out


@handler("verify_jobs")
def verify_jobs(ctx):
    db = ctx.db
    ids = ctx.payload.get("job_ids")
    if not ids:  # stale ones the user can see
        ids = [j.id for j in db.query(Job).join(UserJob, UserJob.job_id == Job.id).filter(UserJob.hidden.is_(False)).all()
               if job_verify.needs_reverify(j)]
    res = verify_many(db, ids, new_fetcher())
    enqueue_nowait(db, "match_jobs")  # a status change moves the opportunity ranking
    return {"verified": len(res), "statuses": res}
