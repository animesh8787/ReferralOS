from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import String, cast, func, or_, select, update
from sqlalchemy.orm import Session

from ..audit import audit
from ..models.contacts import (Company, CompanyReview, Contact, EmailContact, SuppressionEntry, UserCompanyAlias)
from ..models.core import User
from ..security import current_user, scoped_db
from ..services.companies import CompanyResolver, company_key
from ..services.contact_validate import check_email, check_phone, linkedin_identity
from ..services.contacts_import import norm_name

router = APIRouter(prefix="/api", tags=["contacts"])
MAX_PAGE = 200


def page_args(page: int, page_size: int) -> tuple[int, int]:
    return (max(page, 1) - 1) * min(max(page_size, 1), MAX_PAGE), min(max(page_size, 1), MAX_PAGE)


def _c(c: Contact, names: dict) -> dict:
    return {"id": c.id, "name": f"{c.first_name} {c.last_name}".strip(), "linkedin_url": c.linkedin_url, "email": c.email,
            "company": names.get(c.company_id) or c.company_raw, "company_id": c.company_id, "company_raw": c.company_raw,
            "position": c.position, "connected_on": c.connected_on, "role_category": c.role_category,
            "seniority": c.seniority, "employment_status": c.employment_status, "source": c.source}


def _names(db, ids) -> dict:
    ids = {i for i in ids if i}
    return {c.id: c.name for c in db.query(Company).filter(Company.id.in_(ids)).all()} if ids else {}


@router.get("/contacts")
def list_contacts(q: str | None = None, company_id: str | None = None, page: int = 1, page_size: int = 50,
                  sort: str = "name", db: Session = Depends(scoped_db)):
    base = db.query(Contact)
    if company_id:
        base = base.filter(Contact.company_id == company_id)
    if q:
        like = f"%{q.strip().lower()}%"
        base = base.filter(or_(Contact.name_norm.like(like), func.lower(Contact.company_raw).like(like), func.lower(Contact.position).like(like)))
    total = base.count()
    order = {"name": Contact.name_norm, "company": Contact.company_raw, "connected": Contact.connected_on.desc()}.get(sort, Contact.name_norm)
    off, lim = page_args(page, page_size)
    rows = base.order_by(order, Contact.id).offset(off).limit(lim).all()
    names = _names(db, [r.company_id for r in rows])
    return {"total": total, "page": page, "page_size": lim, "items": [_c(r, names) for r in rows]}


@router.get("/contacts/{contact_id}")
def get_contact(contact_id: str, db: Session = Depends(scoped_db)):
    c = db.query(Contact).filter(Contact.id == contact_id).first()
    if not c:
        raise HTTPException(404, "Not found")
    return _c(c, _names(db, [c.company_id]))


class ContactIn(BaseModel):
    first_name: str
    last_name: str = ""
    company: str | None = None
    position: str | None = None
    linkedin_url: str | None = None
    email: str | None = None


@router.post("/contacts", status_code=201)
def add_contact(body: ContactIn, db: Session = Depends(scoped_db)):
    url, key = linkedin_identity(body.linkedin_url)
    if key and db.query(Contact.id).filter(Contact.linkedin_key == key).first():
        raise HTTPException(409, "A contact with this LinkedIn URL already exists")
    em = check_email(body.email) if body.email else None
    c = Contact(source="MANUAL", first_name=body.first_name.strip(), last_name=body.last_name.strip(),
                name_norm=norm_name(f"{body.first_name} {body.last_name}"), linkedin_url=url, linkedin_key=key,
                email=em["norm"] if em and em["valid"] else None, company_raw=body.company, position=body.position,
                company_id=CompanyResolver(db).resolve(body.company))
    db.add(c)
    db.flush()
    return _c(c, _names(db, [c.company_id]))


# ---------------------------------------------------------------- HR / email contacts
def _supp_sets(db):
    rows = db.query(SuppressionEntry.kind, SuppressionEntry.value).all()
    return {v for k, v in rows if k == "email"}, {v for k, v in rows if k == "domain"}


def _ec(e: EmailContact, names: dict, emails: set, domains: set) -> dict:
    suppressed = bool(e.email_norm and (e.email_norm in emails or e.email_norm.rsplit("@", 1)[1] in domains))
    return {"id": e.id, "name": e.name, "title": e.title, "company": names.get(e.company_id) or e.company_raw, "company_id": e.company_id,
            "email": e.email_norm, "email_raw": e.email_raw, "email_valid": e.email_valid, "email_flags": e.email_flags,
            "phone": e.phone_e164, "phone_raw": e.phone_raw, "linkedin_url": e.linkedin_url, "location": e.location,
            "notes": e.notes, "provenance": e.provenance, "bulk_send_blocked": e.bulk_send_blocked, "suppressed": suppressed,
            "country_hint": e.country_hint, "linked_contact_id": e.contact_id}


@router.get("/email-contacts")
def list_email_contacts(q: str | None = None, company_id: str | None = None, valid: bool | None = None,
                        flag: str | None = None, suppressed: bool | None = None, page: int = 1, page_size: int = 50,
                        db: Session = Depends(scoped_db)):
    base = db.query(EmailContact)
    if company_id:
        base = base.filter(EmailContact.company_id == company_id)
    if valid is not None:
        base = base.filter(EmailContact.email_valid == valid)
    if flag:
        base = base.filter(cast(EmailContact.email_flags, String).like(f'%"{flag}"%'))
    if suppressed is not None:
        sub = select(SuppressionEntry.value).where(SuppressionEntry.kind == "email")
        base = base.filter(EmailContact.email_norm.in_(sub)) if suppressed else base.filter(
            or_(EmailContact.email_norm.is_(None), EmailContact.email_norm.notin_(sub)))
    if q:
        like = f"%{q.strip().lower()}%"
        base = base.filter(or_(func.lower(EmailContact.name).like(like), func.lower(EmailContact.company_raw).like(like),
                               func.lower(EmailContact.email_norm).like(like), func.lower(EmailContact.title).like(like)))
    total = base.count()
    off, lim = page_args(page, page_size)
    rows = base.order_by(EmailContact.company_raw, EmailContact.name, EmailContact.id).offset(off).limit(lim).all()
    emails, domains = _supp_sets(db)
    names = _names(db, [r.company_id for r in rows])
    return {"total": total, "page": page, "page_size": lim, "items": [_ec(r, names, emails, domains) for r in rows]}


class EmailContactIn(BaseModel):
    name: str | None = None
    title: str | None = None
    company: str | None = None
    email: str | None = None
    phone: str | None = None
    provenance: str = "self_collected"


@router.post("/email-contacts", status_code=201)
def add_email_contact(body: EmailContactIn, db: Session = Depends(scoped_db)):
    em, ph = check_email(body.email), check_phone(body.phone)
    if not (em["valid"] or ph["valid"]):
        raise HTTPException(422, "Provide a valid email or phone")
    if em["valid"] and db.query(EmailContact.id).filter(EmailContact.email_norm == em["norm"]).first():
        raise HTTPException(409, "This email is already in your contacts")
    e = EmailContact(name=body.name, title=body.title, company_raw=body.company, company_id=CompanyResolver(db).resolve(body.company),
                     email_raw=body.email, email_norm=em["norm"], email_valid=em["valid"], email_flags=em["flags"],
                     phone_raw=body.phone, phone_e164=ph["e164"], provenance=body.provenance,
                     bulk_send_blocked=body.provenance == "purchased")
    db.add(e)
    db.flush()
    emails, domains = _supp_sets(db)
    return _ec(e, _names(db, [e.company_id]), emails, domains)


# ---------------------------------------------------------------- companies (derived from the user's own contacts)
@router.get("/companies")
def list_companies(q: str | None = None, page: int = 1, page_size: int = 50, db: Session = Depends(scoped_db)):
    li = dict(db.query(Contact.company_id, func.count()).filter(Contact.company_id.isnot(None)).group_by(Contact.company_id).all())
    hr = dict(db.query(EmailContact.company_id, func.count()).filter(EmailContact.company_id.isnot(None)).group_by(EmailContact.company_id).all())
    ids = set(li) | set(hr)
    rows = db.query(Company).filter(Company.id.in_(ids)).all() if ids else []
    if q:
        rows = [c for c in rows if q.lower() in c.name.lower()]
    rows.sort(key=lambda c: (-(li.get(c.id, 0) + hr.get(c.id, 0)), c.name))
    off, lim = page_args(page, page_size)
    return {"total": len(rows), "page": page, "items": [{"id": c.id, "name": c.name, "connections": li.get(c.id, 0),
                                                          "hr_contacts": hr.get(c.id, 0)} for c in rows[off:off + lim]]}


@router.get("/company-reviews")
def list_reviews(db: Session = Depends(scoped_db)):
    rows = db.query(CompanyReview).filter(CompanyReview.status == "pending").order_by(CompanyReview.score.desc()).limit(200).all()
    names = _names(db, [r.company_id for r in rows] + [r.candidate_id for r in rows])
    return [{"id": r.id, "raw_name": r.raw_name, "candidate": names.get(r.candidate_id), "score": r.score} for r in rows]


class ResolveIn(BaseModel):
    action: str  # merge | separate


@router.post("/company-reviews/{review_id}/resolve")
def resolve_review(review_id: str, body: ResolveIn, user: User = Depends(current_user), db: Session = Depends(scoped_db)):
    r = db.query(CompanyReview).filter(CompanyReview.id == review_id).first()
    if not r:
        raise HTTPException(404, "Not found")
    if body.action not in ("merge", "separate") or r.status != "pending":
        raise HTTPException(422, "Invalid action or already resolved")
    target = r.candidate_id if body.action == "merge" else r.company_id
    db.add(UserCompanyAlias(alias_key=company_key(r.raw_name), company_id=target))
    if body.action == "merge":
        for m in (Contact, EmailContact):
            db.execute(update(m).where(m.company_id == r.company_id, m.user_id == user.id).values(company_id=target))
    r.status = "merged" if body.action == "merge" else "separate"
    audit(db, user.id, "company_review_resolved", choice=body.action)
    return {"status": r.status}


# ---------------------------------------------------------------- suppression list
class SuppIn(BaseModel):
    value: str
    kind: str = "email"
    reason: str = "do_not_contact"


REASONS = {"unsubscribed", "bounced", "do_not_contact", "complained", "blocklist"}


def add_suppression(db: Session, value: str, kind: str, reason: str, source: str = "manual") -> bool:
    if kind == "email":
        e = check_email(value)
        if not e["valid"]:
            raise HTTPException(422, "Invalid email address")
        value = e["norm"]
    elif kind == "domain":
        value = value.strip().lower().lstrip("@")
        if "." not in value or " " in value:
            raise HTTPException(422, "Invalid domain")
    else:
        raise HTTPException(422, "kind must be email or domain")
    if reason not in REASONS:
        raise HTTPException(422, "Unknown reason")
    if db.query(SuppressionEntry.id).filter(SuppressionEntry.kind == kind, SuppressionEntry.value == value).first():
        return False
    db.add(SuppressionEntry(kind=kind, value=value, reason=reason, source=source))
    return True


@router.get("/suppression")
def list_suppression(page: int = 1, page_size: int = 100, db: Session = Depends(scoped_db)):
    off, lim = page_args(page, page_size)
    q = db.query(SuppressionEntry)
    return {"total": q.count(), "items": [{"id": s.id, "kind": s.kind, "value": s.value, "reason": s.reason, "source": s.source}
                                          for s in q.order_by(SuppressionEntry.created_at.desc()).offset(off).limit(lim).all()]}


@router.post("/suppression", status_code=201)
def add_supp(body: SuppIn, user: User = Depends(current_user), db: Session = Depends(scoped_db)):
    created = add_suppression(db, body.value, body.kind, body.reason)
    audit(db, user.id, "suppression_added", kind=body.kind)
    return {"created": created}


class BulkSupp(BaseModel):
    emails: list[str]
    reason: str = "do_not_contact"


@router.post("/suppression/bulk")
def bulk_supp(body: BulkSupp, user: User = Depends(current_user), db: Session = Depends(scoped_db)):
    ok = bad = dup = 0
    for e in body.emails[:5000]:
        try:
            if add_suppression(db, e, "email", body.reason):
                ok += 1
            else:
                dup += 1
        except HTTPException:
            bad += 1
    audit(db, user.id, "suppression_bulk", added=ok)
    return {"added": ok, "already_present": dup, "invalid": bad}


@router.delete("/suppression/{entry_id}")
def del_supp(entry_id: str, user: User = Depends(current_user), db: Session = Depends(scoped_db)):
    s = db.query(SuppressionEntry).filter(SuppressionEntry.id == entry_id).first()
    if not s:
        raise HTTPException(404, "Not found")
    db.delete(s)
    audit(db, user.id, "suppression_removed", kind=s.kind)
    return {"deleted": True}
