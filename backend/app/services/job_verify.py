"""Active-job verification (spec 5.3). `decide` is a pure state machine over timestamped evidence.

Evidence kinds
  api_listed        the official ATS board API lists the job            (strongest; proof of "open")
  api_absent        the board API answered and the job is not in it
  page_gone         the official listing URL returned 404/410
  page_closed_text  the official listing says it is closed / filled
  page_ok           the listing page loads (HTTP 200 alone proves nothing)
  jsonld_valid      structured data on a page with no expired validThrough
  inaccessible      network error, 5xx, robots-blocked (never counts as closed)
Search-engine hits are not an evidence kind: they are never used.

Rules
  CLOSED            (page_gone | page_closed_text) AND api_absent, both fresh, with no later api_listed
  ACTIVE_VERIFIED   latest decisive evidence is a fresh api_listed and the deadline has not passed
  ACTIVE_UNCONFIRMED  api_listed that is stale or past its deadline, or only page_ok / jsonld_valid
  POSSIBLY_CLOSED   any negative signal newer than the last api_listed that does not amount to CLOSED, or a passed deadline w/o listing
  UNKNOWN           nothing conclusive
"""
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from ..adapters import ats
from ..adapters.http import FetchError, PoliteFetcher, RobotsDisallowed
from ..models.jobs import Job, JobSource, JobVerification
from ..util import utcnow

STALENESS = timedelta(days=3)
CLOSED_PHRASES = ("no longer accepting applications", "position has been filled", "this job is no longer available", "job posting has expired",
                  "this position is closed", "no longer open", "job is closed", "has been closed", "no longer available")
NEGATIVE = ("api_absent", "page_gone", "page_closed_text")


@dataclass
class Ev:
    kind: str
    at: datetime


def decide(evidence: list[Ev], now: datetime, deadline: datetime | None = None, window: timedelta = STALENESS) -> tuple[str, list[str]]:
    latest: dict[str, Ev] = {}
    for e in sorted(evidence, key=lambda e: e.at):
        latest[e.kind] = e
    listed, absent = latest.get("api_listed"), latest.get("api_absent")
    page_closed = max((e for e in (latest.get("page_gone"), latest.get("page_closed_text")) if e), key=lambda e: e.at, default=None)
    fresh = lambda e: e is not None and now - e.at <= window  # noqa: E731
    expired = deadline is not None and deadline < now
    reasons: list[str] = []

    if page_closed and absent and fresh(page_closed) and fresh(absent) and not (listed and listed.at > min(page_closed.at, absent.at)):
        return "CLOSED", ["The official listing is closed or gone AND the job is absent from the board API."]
    negs = [e for k, e in latest.items() if k in NEGATIVE]
    newest_neg = max(negs, key=lambda e: e.at, default=None)
    if listed and (newest_neg is None or listed.at > newest_neg.at):  # a tie goes to the negative signal
        if expired:
            return "ACTIVE_UNCONFIRMED", ["Still listed on the ATS, but the application deadline has passed. Needs a manual check."]
        if fresh(listed):
            return "ACTIVE_VERIFIED", ["Listed as open by the official ATS API."]
        return "ACTIVE_UNCONFIRMED", [f"Last seen listed {listed.at:%Y-%m-%d}; evidence is older than {window.days} days. Re-verify."]
    if newest_neg or expired:
        if newest_neg:
            reasons.append({"api_absent": "Missing from the board API", "page_gone": "Listing page not found (404/410)",
                            "page_closed_text": "Listing says it is closed"}[newest_neg.kind] + ", but this alone is not enough to call it closed.")
        if expired:
            reasons.append("The application deadline has passed.")
        return "POSSIBLY_CLOSED", reasons
    if latest.get("page_ok") or latest.get("jsonld_valid"):
        return "ACTIVE_UNCONFIRMED", ["The page loads, but a loading page is not proof the role is open."]
    return "UNKNOWN", ["No conclusive evidence yet." + (" Latest check could not reach the source." if "inaccessible" in latest else "")]


def needs_reverify(job: Job, now: datetime | None = None, window: timedelta = STALENESS) -> bool:
    return job.last_verified is None or (now or utcnow()) - job.last_verified > window


def record(db: Session, job: Job, source_type: str, kind: str, now: datetime, **detail) -> None:
    db.add(JobVerification(job_id=job.id, source_type=source_type, kind=kind, detail=detail, checked_at=now))


def apply_decision(db: Session, job: Job, now: datetime) -> str:
    rows = db.query(JobVerification).filter(JobVerification.job_id == job.id).all()
    job.status, job.status_reasons = decide([Ev(r.kind, r.checked_at) for r in rows if r.kind != "deadline_passed"], now, job.deadline)
    job.last_verified = now
    return job.status


def _page_evidence(db: Session, job: Job, src: JobSource, fetcher: PoliteFetcher, now: datetime) -> None:
    url = src.source_url or src.apply_url
    if not url:
        return
    try:
        r = fetcher.get(url)
    except RobotsDisallowed:
        return record(db, job, src.source_type, "inaccessible", now, url=url, why="robots.txt does not allow fetching")
    except FetchError as e:
        return record(db, job, src.source_type, "inaccessible", now, url=url, why=str(e))
    if r.status_code in (404, 410):
        return record(db, job, src.source_type, "page_gone", now, url=url, http=r.status_code)
    if r.status_code != 200:
        return record(db, job, src.source_type, "inaccessible", now, url=url, http=r.status_code)
    text = r.text.lower()
    hit = next((p for p in CLOSED_PHRASES if p in text), None)
    if hit:
        return record(db, job, src.source_type, "page_closed_text", now, url=url, phrase=hit)
    ld = ats.parse_jsonld(r.text, url)
    if ld and ld[0].deadline:
        try:
            if datetime.fromisoformat(ld[0].deadline.replace("Z", "+00:00")).replace(tzinfo=None) < now:
                record(db, job, src.source_type, "deadline_passed", now, url=url, valid_through=ld[0].deadline)
                job.deadline = job.deadline or datetime.fromisoformat(ld[0].deadline.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            pass
    record(db, job, src.source_type, "jsonld_valid" if ld else "page_ok", now, url=url, http=200)


def verify_job(db: Session, job: Job, fetcher: PoliteFetcher, board_cache: dict | None = None, now: datetime | None = None) -> str:
    """Gather fresh evidence from every source of this job, store it, and update the job's status."""
    now, cache = now or utcnow(), board_cache if board_cache is not None else {}
    for src in db.query(JobSource).filter(JobSource.job_id == job.id).all():
        if src.source_type in ats.ATS_TYPES:
            key = (src.source_type, src.board_token)
            if key not in cache:
                try:
                    cache[key] = {j.source_job_id for j in ats.list_jobs(fetcher, *key)}
                except ats.BoardNotFound:
                    cache[key] = "missing"
                except (ats.AtsError, FetchError) as e:
                    cache[key] = f"error:{e}"
            ids = cache[key]
            if isinstance(ids, set):
                record(db, job, src.source_type, "api_listed" if src.source_job_id in ids else "api_absent", now, board=src.board_token)
            else:
                record(db, job, src.source_type, "inaccessible", now, board=src.board_token, why=str(ids))
        _page_evidence(db, job, src, fetcher, now)
    return apply_decision(db, job, now)
