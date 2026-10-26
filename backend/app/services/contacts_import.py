"""Import task: turns a stored CSV into ImportRow (source, verbatim) + Contact/EmailContact (derived) rows.

Resumable: progress is checkpointed per chunk; a retry continues after the last committed row number.
Every input row ends up in import_rows with a status and reasons, so the report always adds up.
"""
import re
import unicodedata
from datetime import datetime

from .. import storage
from ..models.contacts import Contact, EmailContact, ImportBatch, ImportRow, SuppressionEntry
from ..tasks import handler
from . import csv_import
from .companies import CompanyResolver, company_key
from .contact_validate import check_email, check_phone, linkedin_identity

CHUNK = 500
DATE_FORMATS = ("%d %b %Y", "%d %B %Y", "%Y-%m-%d", "%b %d, %Y", "%B %d, %Y", "%m/%d/%Y")
PURCHASED = {"purchased", "scraped", "unknown"}
CCTLD = {"uk": "GB", "de": "DE", "fr": "FR", "es": "ES", "it": "IT", "nl": "NL", "ie": "IE", "in": "IN", "ca": "CA", "au": "AU",
         "se": "SE", "pl": "PL", "be": "BE", "at": "AT", "dk": "DK", "fi": "FI", "pt": "PT", "ch": "CH", "no": "NO"}


def norm_name(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^a-z ]+", " ", s).split())


def parse_date(s: str | None):
    for f in DATE_FORMATS:
        try:
            return datetime.strptime(s.strip(), f).date() if s else None
        except ValueError:
            continue
    return None


def _split_name(v: dict) -> tuple[str, str]:
    f, l = v.get("first_name") or "", v.get("last_name") or ""
    if not (f or l) and (v.get("full_name") or v.get("name")):
        parts = (v.get("full_name") or v.get("name")).split()
        f, l = (parts[0], " ".join(parts[1:])) if parts else ("", "")
    return f.strip(), l.strip()


@handler("import_contacts")
def import_contacts(ctx):
    db = ctx.db
    imp = db.query(ImportBatch).filter(ImportBatch.id == ctx.payload["import_id"]).one()
    imp.status = "running"
    text, _, _ = csv_import.decode(storage.get(imp.user_id, "imports", imp.id, ".csv"))
    rows = csv_import.read_rows(text, imp.delimiter)
    resolver = CompanyResolver(db)
    done_through = ctx.checkpoint.get("row", 0)
    total = max(1, len(rows) - imp.header_row - 1)
    rep = ctx.checkpoint.get("report") or {"read": 0, "valid": 0, "duplicate": 0, "invalid": 0, "empty": 0, "warnings": 0,
                                           "missing": {}, "suppressed": 0, "reviews": 0}
    hr = imp.kind == "hr"
    seen_url, seen_fb, seen_email = set(), set(), set()
    for (k,) in db.query(Contact.linkedin_key).filter(Contact.linkedin_key.isnot(None)):
        seen_url.add(k)
    for (k,) in db.query(Contact.dedup_fallback).filter(Contact.dedup_fallback.isnot(None)):
        seen_fb.add(k)
    for (k,) in db.query(EmailContact.email_norm).filter(EmailContact.email_norm.isnot(None)):
        seen_email.add(k)
    supp = {(s.kind, s.value) for s in db.query(SuppressionEntry).all()}
    li_by_key = {c.linkedin_key: c.id for c in db.query(Contact.id, Contact.linkedin_key).filter(Contact.linkedin_key.isnot(None))} if hr else {}
    li_by_email = {c.email: c.id for c in db.query(Contact.id, Contact.email).filter(Contact.email.isnot(None))} if hr else {}
    pending = 0
    for n, raw, vals, notes in csv_import.iter_records(rows, imp.header_row, imp.mapping):
        if n <= done_through:
            continue
        rep["read"] += 1
        if raw is None:
            rep["empty"] += 1  # a subset of "invalid", so read == valid + duplicate + invalid always holds
            rep["invalid"] += 1
            db.add(ImportRow(import_id=imp.id, row_number=n, raw={}, status="invalid", reasons=[{"code": "empty_row", "note": "Blank line"}]))
        else:
            reasons = [{"code": c, "note": c.replace("_", " ")} for c in notes]
            status = _hr_row(db, imp, vals, reasons, resolver, seen_email, supp, li_by_key, li_by_email, rep) if hr else \
                _li_row(db, imp, vals, reasons, resolver, seen_url, seen_fb, rep)
            rep[status] += 1
            rep["warnings"] += 1 if reasons and status == "valid" else 0
            db.add(ImportRow(import_id=imp.id, row_number=n, raw=raw, status=status, reasons=reasons))
        pending += 1
        if pending >= CHUNK:
            rep["reviews"] = resolver.reviews_created
            ctx.update(progress=min(0.99, (n - imp.header_row) / total), checkpoint={"row": n, "report": rep})
            pending = 0
    rep["reviews"] = resolver.reviews_created
    imp.report, imp.status = rep, "done"
    return rep


def _missing(rep, field):
    rep["missing"][field] = rep["missing"].get(field, 0) + 1


def _li_row(db, imp, v, reasons, resolver, seen_url, seen_fb, rep) -> str:
    first, last = _split_name(v)
    if not (first or last):
        reasons.append({"code": "missing_name", "note": "No first or last name"})
        return "invalid"
    url, key = linkedin_identity(v.get("linkedin_url"))
    if v.get("linkedin_url") and not key:
        reasons.append({"code": "invalid_url", "note": f"Not a linkedin.com/in/ profile URL: {v['linkedin_url'][:80]}"})
    if not v.get("linkedin_url"):
        _missing(rep, "linkedin_url")
    em = check_email(v.get("email")) if v.get("email") else None
    if em and not em["valid"]:
        reasons.append({"code": "invalid_email", "note": "Email ignored: " + em["error"]})
    for f in ("company", "position"):
        if not v.get(f):
            _missing(rep, f)
    cid = resolver.resolve(v.get("company"))
    nn = norm_name(f"{first} {last}")
    fb = f"{nn}|{company_key(v.get('company'))}" if not key and v.get("company") else None
    if key and key in seen_url or fb and fb in seen_fb:
        reasons.append({"code": "duplicate", "note": "Same LinkedIn URL" if key else "Same name and company, no URL to tell them apart"})
        return "duplicate"
    if key:
        seen_url.add(key)
    if fb:
        seen_fb.add(fb)
    c = Contact(import_id=imp.id, first_name=first, last_name=last, name_norm=nn, linkedin_url=url, linkedin_key=key,
                email=em["norm"] if em and em["valid"] else None, company_raw=v.get("company"), company_id=cid,
                position=v.get("position"), connected_on=parse_date(v.get("connected_on")), dedup_fallback=fb,
                employment_status="unknown")
    if v.get("connected_on") and not c.connected_on:
        reasons.append({"code": "unparsed_date", "note": "Connected On could not be parsed; kept in the original row"})
    db.add(c)
    return "valid"


def _hr_row(db, imp, v, reasons, resolver, seen_email, supp, li_by_key, li_by_email, rep) -> str:
    em = check_email(v.get("email"))
    ph = check_phone(v.get("phone"), imp.region)
    first, last = _split_name(v)
    name = f"{first} {last}".strip() or None
    if v.get("email") and not em["valid"]:
        reasons.append({"code": "invalid_email", "note": f"Invalid email '{v['email'][:60]}': {em['error']}"})
    if v.get("phone") and not ph["valid"]:
        reasons.append({"code": "invalid_phone", "note": "Phone could not be validated for region " + imp.region})
    for f in ("company", "title", "email"):
        if not v.get(f):
            _missing(rep, f)
    if not (em["valid"] or ph["valid"] or (name and v.get("company"))):
        reasons.append({"code": "no_usable_identifier", "note": "Needs a valid email, a valid phone, or a name with a company"})
        return "invalid"
    if em["valid"] and em["norm"] in seen_email:
        reasons.append({"code": "duplicate", "note": "Email already imported"})
        return "duplicate"
    for fl in em["flags"]:
        reasons.append({"code": fl, "note": {"role_account": "Shared role mailbox (info@, hr@ ...)", "noreply": "No-reply address cannot receive replies"}.get(fl, fl)})
    if em["valid"]:
        seen_email.add(em["norm"])
        dom = em["norm"].rsplit("@", 1)[1]
        if ("email", em["norm"]) in supp or ("domain", dom) in supp:
            reasons.append({"code": "suppressed", "note": "On your do-not-contact list; will never be emailed"})
            rep["suppressed"] += 1
    _, key = linkedin_identity(v.get("linkedin_url"))
    link = li_by_key.get(key) or li_by_email.get(em["norm"] if em["valid"] else None)
    tld = em["norm"].rsplit(".", 1)[-1] if em["valid"] else None
    db.add(EmailContact(import_id=imp.id, contact_id=link, name=name, title=v.get("title"), company_raw=v.get("company"),
                        company_id=resolver.resolve(v.get("company")), email_raw=v.get("email"), email_norm=em["norm"],
                        email_valid=em["valid"], email_flags=em["flags"], phone_raw=v.get("phone"), phone_e164=ph["e164"],
                        linkedin_url=linkedin_identity(v.get("linkedin_url"))[0], location=v.get("location"),
                        notes=v.get("notes"), provenance=imp.provenance or "other",
                        country_hint=CCTLD.get(tld) or ph["country"], bulk_send_blocked=(imp.provenance or "other") in PURCHASED))
    return "valid"
