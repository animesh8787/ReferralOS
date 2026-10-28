from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import ratelimit, storage, tasks
from ..audit import audit
from ..models.contacts import ImportBatch, ImportRow
from ..models.core import User
from ..security import current_user, scoped_db
from ..services import csv_import
from ..services import contacts_import  # noqa: F401  (registers the task handler)

router = APIRouter(prefix="/api/imports", tags=["imports"])
MAX_CSV = 25 * 1024 * 1024
PROVENANCE = {"self_collected": "I collected it myself", "company_published": "Published by the company",
              "event": "Event / networking", "purchased": "Purchased or scraped list", "other": "Other / unsure"}
WARN_PURCHASED = ("Purchased or scraped lists often lack consent and are restricted here: bulk sending is blocked for these "
                  "contacts (one-off manual drafts only). This is guidance, not legal advice.")


def _summary(i: ImportBatch) -> dict:
    return {"id": i.id, "kind": i.kind, "filename": i.filename, "status": i.status, "provenance": i.provenance,
            "created_at": i.created_at, "report": i.report}


@router.post("", status_code=201)
async def create_import(kind: str = Form(...), file: UploadFile = File(...), user: User = Depends(current_user),
                        db: Session = Depends(scoped_db)):
    """Step 1: store the file, detect encoding/delimiter/header, suggest a column mapping, preview rows."""
    ratelimit.check(f"upload:{user.id}", 20, 3600)
    if kind not in ("linkedin", "hr"):
        raise HTTPException(422, "kind must be 'linkedin' or 'hr'")
    data = await file.read(MAX_CSV + 1)
    if not data:
        raise HTTPException(422, "The file is empty")
    if len(data) > MAX_CSV:
        raise HTTPException(413, "The file is larger than 25 MB")
    text, enc, warnings = csv_import.decode(data)
    delim = csv_import.sniff_delimiter(text)
    try:
        rows = csv_import.read_rows(text, delim)
    except ValueError as e:
        raise HTTPException(422, str(e))
    if len(rows) < 2:
        raise HTTPException(422, "No data rows found")
    hdr = csv_import.find_header(rows, kind)
    headers = [h.strip() for h in rows[hdr]]
    mapping = csv_import.auto_map(headers, kind)
    imp = ImportBatch(kind=kind, filename=(file.filename or "import.csv")[-200:], encoding=enc, delimiter=delim,
                      header_row=hdr, mapping=mapping)
    db.add(imp)
    db.flush()
    storage.put(user.id, "imports", imp.id, data, ".csv")
    audit(db, user.id, "import_uploaded", import_id=imp.id, kind=kind)
    return {"import_id": imp.id, "encoding": enc, "delimiter": delim, "header_row": hdr, "headers": headers, "mapping": mapping,
            "unmapped": csv_import.unmapped(headers, mapping), "preview": [r for r in rows[hdr + 1: hdr + 6]],
            "total_rows": len(rows) - hdr - 1, "warnings": warnings,
            "provenance_options": PROVENANCE if kind == "hr" else None}


class StartIn(BaseModel):
    mapping: dict[str, str | None] | None = None
    provenance: str | None = None
    provenance_note: str | None = None
    region: str = "US"


@router.post("/{import_id}/start", status_code=202)
def start_import(import_id: str, body: StartIn, user: User = Depends(current_user), db: Session = Depends(scoped_db)):
    """Step 2: confirm mapping (+ required provenance for HR lists) and run the import in the background."""
    imp = db.query(ImportBatch).filter(ImportBatch.id == import_id).first()
    if not imp:
        raise HTTPException(404, "Not found")
    if imp.status != "uploaded":
        raise HTTPException(409, "This import was already started")
    if imp.kind == "hr":
        if body.provenance not in PROVENANCE:
            raise HTTPException(422, "Tell us where this list came from (provenance is required for HR/recruiter lists)")
        imp.provenance, imp.provenance_note = body.provenance, (body.provenance_note or "")[:300]
    if body.mapping is not None:
        valid = set(csv_import.FIELDS[imp.kind])
        if set(body.mapping) - valid:
            raise HTTPException(422, "Unknown field in mapping")
        imp.mapping = body.mapping
    if not any(imp.mapping.values()):
        raise HTTPException(422, "Map at least one column")
    imp.region = body.region.upper()[:2]
    try:  # remember which columns were NOT used, for the diagnostics page
        text, _, _ = csv_import.decode(storage.get(user.id, "imports", imp.id, ".csv"))
        rows = csv_import.read_rows(text, imp.delimiter)
        imp.report = {**(imp.report or {}), "unmapped_columns": csv_import.unmapped([h.strip() for h in rows[imp.header_row]], imp.mapping)}
    except (OSError, ValueError, IndexError):
        pass
    db.commit()
    t = tasks.enqueue(db, "import_contacts", {"import_id": imp.id})
    audit(db, user.id, "import_started", import_id=imp.id, provenance=imp.provenance)
    db.refresh(imp)
    return {"task_id": t.id, "task_status": t.status, "import": _summary(imp),
            "warning": WARN_PURCHASED if imp.provenance == "purchased" else None}


@router.get("")
def list_imports(db: Session = Depends(scoped_db)):
    return [_summary(i) for i in db.query(ImportBatch).order_by(ImportBatch.created_at.desc()).all()]


@router.get("/{import_id}")
def get_import(import_id: str, db: Session = Depends(scoped_db)):
    i = db.query(ImportBatch).filter(ImportBatch.id == import_id).first()
    if not i:
        raise HTTPException(404, "Not found")
    counts = dict(db.query(ImportRow.status, func.count()).filter(ImportRow.import_id == i.id).group_by(ImportRow.status).all())
    return {**_summary(i), "mapping": i.mapping, "encoding": i.encoding, "delimiter": i.delimiter, "row_counts": counts}


@router.get("/{import_id}/rows")
def import_rows(import_id: str, status: str | None = None, page: int = 1, page_size: int = 50, db: Session = Depends(scoped_db)):
    """Diagnostics: every source row with its status and reasons (why was this rejected?)."""
    if not db.query(ImportBatch.id).filter(ImportBatch.id == import_id).first():
        raise HTTPException(404, "Not found")
    q = db.query(ImportRow).filter(ImportRow.import_id == import_id)
    if status:
        q = q.filter(ImportRow.status == status)
    total = q.count()
    rows = q.order_by(ImportRow.row_number).offset((max(page, 1) - 1) * page_size).limit(min(page_size, 200)).all()
    return {"total": total, "page": page, "rows": [{"row": r.row_number, "status": r.status, "reasons": r.reasons, "raw": r.raw} for r in rows]}


@router.post("/{import_id}/purge")
def purge_raw(import_id: str, user: User = Depends(current_user), db: Session = Depends(scoped_db)):
    """Retention: delete the stored file and verbatim source values; derived contacts stay."""
    i = db.query(ImportBatch).filter(ImportBatch.id == import_id).first()
    if not i:
        raise HTTPException(404, "Not found")
    storage.delete(user.id, "imports", i.id, ".csv")
    db.query(ImportRow).filter(ImportRow.import_id == i.id).update({"raw": {}})
    i.status = "purged"
    audit(db, user.id, "import_purged", import_id=i.id)
    return {"purged": True}
