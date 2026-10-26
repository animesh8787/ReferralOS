"""Referral-route discovery. We never assume a programme exists: only official pages the user points us at can
produce VERIFIED_REFERRAL_PROGRAM, and missing evidence is NO_PUBLIC_EVIDENCE / UNKNOWN, never a claim either way."""
import re

from sqlalchemy.orm import Session

from ..adapters.ats import html_to_text
from ..adapters.http import FetchError, PoliteFetcher
from ..models.jobs import ReferralRoute
from ..util import utcnow

PHRASE = re.compile(r"(employee|staff|team member) referral|referral (program|programme|bonus|scheme|policy)|refer a (friend|colleague|candidate|someone)|refer (someone|candidates)", re.I)
STATUSES = {"VERIFIED_REFERRAL_PROGRAM", "REFERRAL_ROUTE_UNCONFIRMED", "NO_PUBLIC_EVIDENCE", "NOT_APPLICABLE", "UNKNOWN"}
USER_SETTABLE = STATUSES - {"VERIFIED_REFERRAL_PROGRAM"}  # verification requires evidence from an official page


def get_route(db: Session, company_id: str) -> ReferralRoute | None:
    return db.query(ReferralRoute).filter(ReferralRoute.company_id == company_id).first()


def _upsert(db, company_id) -> ReferralRoute:
    r = get_route(db, company_id)
    if not r:
        r = ReferralRoute(company_id=company_id)
        db.add(r)
    return r


def check_official_pages(db: Session, company_id: str, urls: list[str], fetcher: PoliteFetcher) -> ReferralRoute:
    ok_pages, found = 0, None
    for u in urls[:5]:
        try:
            r = fetcher.get(u)
        except FetchError:
            continue
        if r.status_code != 200:
            continue
        ok_pages += 1
        text = html_to_text(r.text)
        m = PHRASE.search(text)
        if m and not found:
            s = max(0, m.start() - 80)
            found = (u, text[s:m.end() + 100])
    route = _upsert(db, company_id)
    route.checked_at = utcnow()
    if found:
        route.status, route.source, route.evidence_url, route.evidence_excerpt = "VERIFIED_REFERRAL_PROGRAM", "official_page", found[0], found[1][:300]
    elif ok_pages:
        if route.source != "user":  # don't overwrite what the user told us with an absence of evidence
            route.status, route.source, route.evidence_url, route.evidence_excerpt = "NO_PUBLIC_EVIDENCE", "official_page", urls[0], None
    elif route.status == "UNKNOWN" or route.source == "none":
        route.status = "UNKNOWN"  # pages could not be read; say nothing either way
    db.flush()
    return route


def set_by_user(db: Session, company_id: str, status: str) -> ReferralRoute:
    if status not in USER_SETTABLE:
        raise ValueError("Only an official page can verify a referral programme")
    r = _upsert(db, company_id)
    r.status, r.source, r.checked_at = status, "user", utcnow()
    db.flush()
    return r


def wording_allows_programme_claim(route: ReferralRoute | None) -> bool:
    """Message templates may only assert a programme when this is True."""
    return bool(route and route.status == "VERIFIED_REFERRAL_PROGRAM")
