"""Master Career Profile operations. db must be a tenant-scoped session."""
import re

from sqlalchemy.orm import Session

from ..models.profile import ProfileItem, ProfileVersion
from .resume_parse import Item

SECTIONS = {"personal", "education", "experience", "project", "skill", "certification", "award", "publication",
            "summary", "preference"}
SINGLETON = {"personal", "summary", "preference"}


def item_key(section: str, d: dict) -> str:
    n = lambda x: re.sub(r"\s+", " ", str(x or "")).strip().lower()  # noqa: E731
    if section == "experience":
        return f"{n(d.get('title'))}|{n(d.get('organization'))}|{n(d.get('start'))}"
    if section == "education":
        return f"{n(d.get('institution'))}|{n(d.get('degree'))}"
    if section in ("project", "skill", "certification", "award", "publication"):
        return n(d.get("name"))
    return section


def add_parsed(db: Session, items: list[Item], source: str, source_ref: str, status: str = "active",
               confidence_cap: float | None = None) -> dict:
    """Insert items without ever overwriting existing facts: identical -> skipped; different data under the
    same key -> added as a 'suggested' item flagged as a conflict for the user to resolve."""
    existing = db.query(ProfileItem).filter(ProfileItem.status.in_(("active", "suggested"))).all()
    by_key = {}
    for e in existing:
        by_key.setdefault((e.section, item_key(e.section, e.data)), e)
    added = skipped = conflicts = 0
    for it in items:
        key = (it.section, item_key(it.section, it.data))
        prev = by_key.get(key)
        flags = list(it.flags)
        st = status
        if prev is not None:
            if prev.data == it.data:
                skipped += 1
                continue
            if it.section in ("skill",):  # same skill name seen again: not a conflict, just corroboration
                skipped += 1
                continue
            flags.append({"type": "conflict", "with": prev.id, "note": "Differs from an existing entry; review both"})
            st = "suggested"
            conflicts += 1
        conf = min(it.confidence, confidence_cap) if confidence_cap else it.confidence
        row = ProfileItem(section=it.section, data=it.data, status=st, source=source, source_ref=source_ref,
                          source_span={"start": it.span[0], "end": it.span[1]}, confidence=conf, flags=flags,
                          evidence_level=it.evidence_level)
        db.add(row)
        by_key.setdefault(key, row)
        added += 1
    db.flush()
    return {"added": added, "skipped": skipped, "conflicts": conflicts}


def snapshot(db: Session, reason: str) -> ProfileVersion:
    rows = db.query(ProfileItem).filter(ProfileItem.status == "active").order_by(ProfileItem.created_at).all()
    last = db.query(ProfileVersion).order_by(ProfileVersion.version.desc()).first()
    v = ProfileVersion(version=(last.version + 1) if last else 1, reason=reason[:120],
                       snapshot=[serialize(r) for r in rows])
    db.add(v)
    db.flush()
    return v


def serialize(r: ProfileItem) -> dict:
    return {"id": r.id, "section": r.section, "data": r.data, "status": r.status, "source": r.source,
            "source_ref": r.source_ref, "verified": r.verified, "confidence": r.confidence,
            "evidence_level": r.evidence_level, "flags": r.flags,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None}


def _has_number(texts) -> bool:
    return any(re.search(r"\d", str(t)) for t in texts)


def completeness(items: list[ProfileItem]) -> dict:
    act = [i for i in items if i.status == "active"]
    has = lambda s: [i for i in act if i.section == s]  # noqa: E731
    p = (has("personal") or [None])[0]
    pd = p.data if p else {}
    prefs = (has("preference") or [None])[0]
    parts = {"contact": (15, bool(pd.get("name") and pd.get("email"))), "education": (15, bool(has("education"))),
             "experience": (20, bool(has("experience"))), "projects": (20, bool(has("project"))),
             "skills": (15, len(has("skill")) >= 3),
             "preferences": (10, bool(prefs and prefs.data.get("target_roles"))),
             "links": (5, bool(pd.get("links")))}
    score = sum(w for w, ok in parts.values() if ok)
    return {"score": score, "parts": {k: ok for k, (_, ok) in parts.items()},
            "missing": [k for k, (_, ok) in parts.items() if not ok]}


def questions(items: list[ProfileItem]) -> list[dict]:
    """Specific, answerable prompts. We ask; we never fill gaps ourselves."""
    qs = []
    act = [i for i in items if i.status == "active"]
    for i in act:
        d = i.data
        if i.section == "skill" and i.evidence_level == "CLAIMED_ONLY":
            qs.append({"item_id": i.id, "type": "unsupported_skill",
                       "text": f"You list {d.get('name')}, but no project or job shows it. Where did you use it? Until then it won't be featured."})
        if i.section == "project" and not _has_number(list(d.get("description", [])) + list(d.get("outcomes", []))):
            qs.append({"item_id": i.id, "type": "missing_metric",
                       "text": f"Your project '{d.get('name')}' has no measurable outcome. Do you have a number (users, latency, accuracy, time saved)?"})
        if i.section == "experience" and not _has_number(d.get("bullets", [])) and not d.get("metrics"):
            qs.append({"item_id": i.id, "type": "missing_metric",
                       "text": f"Your role '{d.get('title')}' at {d.get('organization')} lists no measurable results. Do you have any numbers?"})
    for i in items:
        for f in i.flags or []:
            if f.get("type") in ("conflict", "date_order", "duplicate"):
                qs.append({"item_id": i.id, "type": f["type"], "text": f["note"]})
    c = completeness(items)
    for m in c["missing"]:
        qs.append({"item_id": None, "type": "missing_section", "text": f"Your profile has no {m} information yet."})
    return qs
