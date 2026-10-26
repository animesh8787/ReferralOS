"""Conservative company normalisation.

Exact normalized-key match -> same company. Near-identical (>=97, same first 3 chars) -> auto-merge (typo level).
88..97 -> keep separate AND queue a review for the user. Below 88 -> new company. Never merge on a guess.
"""
import re
import unicodedata

from rapidfuzz import fuzz, process
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models.contacts import Company, CompanyReview, UserCompanyAlias

AUTO = 97
REVIEW = 88
_SUFFIX = {"inc", "incorporated", "llc", "ltd", "limited", "pvt", "private", "corp", "corporation", "gmbh", "ag", "co",
           "company", "plc", "sa", "bv", "oy", "pte", "llp", "lp"}


def company_key(raw: str | None) -> str:
    if not raw:
        return ""
    s = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode().lower()
    s = s.replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    words = [w for w in s.split() if w]
    while words and words[-1] in _SUFFIX:  # strip legal suffixes only at the end, so "Co" inside a name survives
        words.pop()
    if words and words[0] == "the":
        words.pop(0)
    return " ".join(words)


def clean_display(raw: str) -> str:
    return re.sub(r"\s+", " ", raw).strip()[:200]


class CompanyResolver:
    """Per-import resolver with caches. db is the (scoped) task session."""

    def __init__(self, db: Session):
        self.db = db
        self.keys: dict[str, str] = {c.key: c.id for c in db.query(Company.key, Company.id).all()}
        self.alias: dict[str, str] = {a.alias_key: a.company_id for a in db.query(UserCompanyAlias).all()}
        self.reviewed: set[str] = set()
        self.reviews_created = 0

    def resolve(self, raw: str | None) -> str | None:
        k = company_key(raw)
        if not k:
            return None
        if k in self.alias:
            return self.alias[k]
        if k in self.keys:
            return self.keys[k]
        cand = process.extractOne(k, list(self.keys), scorer=fuzz.ratio) if self.keys else None
        if cand and cand[1] >= AUTO and cand[0][:3] == k[:3]:
            self.keys[k] = self.keys[cand[0]]
            return self.keys[k]
        cid = self._create(k, raw)
        if cand and cand[1] >= REVIEW and k not in self.reviewed:
            self.reviewed.add(k)
            self.db.add(CompanyReview(raw_name=clean_display(raw), company_id=cid, candidate_id=self.keys[cand[0]], score=cand[1]))
            self.reviews_created += 1
        return cid

    def _create(self, key: str, raw: str) -> str:
        c = Company(key=key, name=clean_display(raw))
        try:
            with self.db.begin_nested():
                self.db.add(c)
                self.db.flush()
        except IntegrityError:  # another worker created it first
            c = self.db.query(Company).filter(Company.key == key).one()
        self.keys[key] = c.id
        return c.id
