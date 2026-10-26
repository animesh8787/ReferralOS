import io
import zipfile

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import ratelimit, storage
from ..audit import audit
from ..models.core import User
from ..models.jobs import Job, UserJob
from ..models.tailoring import TailoredResume
from ..security import current_user, scoped_db
from ..services.tailoring import diff, engine, service
from .contacts import page_args

router = APIRouter(prefix="/api", tags=["tailoring"])
MIME = {"pdf": "application/pdf", "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "txt": "text/plain; charset=utf-8",
        "json": "application/json", "md": "text/markdown; charset=utf-8"}


def _row(db: Session, rid: str) -> TailoredResume:
    r = db.query(TailoredResume).filter(TailoredResume.id == rid).first()
    if not r:
        raise HTTPException(404, "Not found")
    return r


def _job(db: Session, job_id: str) -> Job:
    r = db.query(Job).join(UserJob, UserJob.job_id == Job.id).filter(Job.id == job_id).first()
    if not r:
        raise HTTPException(404, "Not found")
    return r


def _brief(r: TailoredResume) -> dict:
    return {"id": r.id, "job_id": r.job_id, "version": r.version, "parent_id": r.parent_id, "status": r.status, "score": r.score_total,
            "approved_at": r.approved_at, "created_at": r.created_at, "ok_to_approve": r.validation["ok_to_approve"],
            "needs_confirmation": len(r.validation["needs_confirmation"]), "render_ok": r.validation["render_check"]["ok"]}


def _full(r: TailoredResume) -> dict:
    return {**_brief(r), "content": r.content, "ledger": r.ledger, "validation": r.validation, "score_detail": r.score, "changes": r.changes,
            "questions": r.questions, "requirement_matrix": r.matrix, "files": r.files, "options": r.options, "profile_version": r.profile_version}


class CreateIn(BaseModel):
    job_id: str
    max_projects: int | None = None
    max_bullets: int | None = None
    excluded_item_ids: list[str] = []
    section_order: list[str] | None = None


@router.post("/tailoring", status_code=201)
def create(body: CreateIn, user: User = Depends(current_user), db: Session = Depends(scoped_db)):
    ratelimit.check(f"tailor:{user.id}", 60, 3600)
    job = _job(db, body.job_id)
    if job.status == "CLOSED":
        raise HTTPException(409, "This job is closed; there is nothing to tailor a resume for.")
    opts = {k: v for k, v in body.model_dump().items() if k != "job_id" and v is not None and v != []}
    if body.excluded_item_ids:
        opts["excluded_item_ids"] = body.excluded_item_ids
    if body.max_projects is not None and not 0 <= body.max_projects <= 6:
        raise HTTPException(422, "max_projects must be 0-6")
    if body.max_bullets is not None and not 1 <= body.max_bullets <= 8:
        raise HTTPException(422, "max_bullets must be 1-8")
    if body.section_order is not None and sorted(body.section_order) != sorted(engine.SECTIONS):
        raise HTTPException(422, "section_order must list every section exactly once: " + ", ".join(engine.SECTIONS))
    r = service.create(db, job, opts)
    audit(db, user.id, "resume_tailored", version=r.version)
    return _full(r)


@router.get("/tailoring")
def list_versions(job_id: str | None = None, db: Session = Depends(scoped_db)):
    q = db.query(TailoredResume)
    if job_id:
        _job(db, job_id)
        q = q.filter(TailoredResume.job_id == job_id)
    rows = q.order_by(TailoredResume.created_at.desc(), TailoredResume.version.desc()).limit(200).all()
    titles = {j.id: (j.title, j.company_id) for j in db.query(Job).filter(Job.id.in_({r.job_id for r in rows} or {""})).all()}
    return [{**_brief(r), "job_title": titles.get(r.job_id, ("", None))[0]} for r in rows]


@router.get("/jobs/{job_id}/resume")
def job_resume(job_id: str, db: Session = Depends(scoped_db)):
    _job(db, job_id)
    s = service.resume_status(db, job_id)
    return {**s, "approved": None if s["status"] != "approved" else _brief(_row(db, s["resume_id"]))}


@router.get("/tailoring/{tailored_id}")
def get_version(tailored_id: str, db: Session = Depends(scoped_db)):
    return _full(_row(db, tailored_id))


class EditIn(BaseModel):
    bullet_edits: list[dict] = []
    exclude_claims: list[str] = []


@router.patch("/tailoring/{tailored_id}")
def edit_version(tailored_id: str, body: EditIn, user: User = Depends(current_user), db: Session = Depends(scoped_db)):
    """Edits never change an existing version (approved or not); they create the next version."""
    parent = _row(db, tailored_id)
    try:
        r = service.edit(db, parent, body.bullet_edits, body.exclude_claims)
    except (ValueError, KeyError) as e:
        raise HTTPException(422, str(e))
    audit(db, user.id, "resume_edited", version=r.version)
    return _full(r)


class RegenIn(BaseModel):
    max_projects: int | None = None
    max_bullets: int | None = None
    excluded_item_ids: list[str] | None = None
    section_order: list[str] | None = None


@router.post("/tailoring/{tailored_id}/regenerate", status_code=201)
def regenerate(tailored_id: str, body: RegenIn, user: User = Depends(current_user), db: Session = Depends(scoped_db)):
    parent = _row(db, tailored_id)
    opts = {**parent.options, **{k: v for k, v in body.model_dump().items() if v is not None}}
    if body.section_order is not None and sorted(body.section_order) != sorted(engine.SECTIONS):
        raise HTTPException(422, "section_order must list every section exactly once")
    r = service.create(db, _job(db, parent.job_id), opts, parent)
    audit(db, user.id, "resume_regenerated", version=r.version)
    return _full(r)


class ConfirmIn(BaseModel):
    claim_id: str


@router.post("/tailoring/{tailored_id}/confirm-claim", status_code=201)
def confirm_claim(tailored_id: str, body: ConfirmIn, user: User = Depends(current_user), db: Session = Depends(scoped_db)):
    """Explicitly add an edited statement to your master profile as a confirmed fact, then re-validate as a new version."""
    parent = _row(db, tailored_id)
    try:
        r = service.confirm_claim(db, parent, body.claim_id)
    except ValueError as e:
        raise HTTPException(422, str(e))
    audit(db, user.id, "claim_confirmed_into_profile")
    return _full(r)


@router.post("/tailoring/{tailored_id}/approve")
def approve(tailored_id: str, user: User = Depends(current_user), db: Session = Depends(scoped_db)):
    r = _row(db, tailored_id)
    try:
        service.approve(db, r)
    except ValueError as e:
        raise HTTPException(409, str(e))
    audit(db, user.id, "resume_approved", version=r.version)
    return _brief(r)


@router.get("/tailoring/{tailored_id}/files/{name}")
def download(tailored_id: str, name: str, inline: bool = False, user: User = Depends(current_user), db: Session = Depends(scoped_db)):
    r = _row(db, tailored_id)
    if name not in r.files:
        raise HTTPException(404, "Not found")
    try:
        data = storage.bundle_path(user.id, r.id, name).read_bytes()
    except (OSError, ValueError):
        raise HTTPException(404, "Not found")
    disp = "inline" if inline and name.endswith(".pdf") else "attachment"  # inline only for the PDF preview
    return Response(data, media_type=MIME[name.rsplit(".", 1)[1]], headers={"Content-Disposition": f'{disp}; filename="{name}"', "X-Content-Type-Options": "nosniff"})


@router.get("/tailoring/{tailored_id}/bundle.zip")
def bundle(tailored_id: str, user: User = Depends(current_user), db: Session = Depends(scoped_db)):
    ratelimit.check(f"export:{user.id}", 30, 3600)
    r = _row(db, tailored_id)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for n in r.files:
            z.write(storage.bundle_path(user.id, r.id, n), n)
    audit(db, user.id, "resume_bundle_exported")
    return Response(buf.getvalue(), media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="resume-v{r.version}.zip"'})


@router.get("/tailoring/{tailored_id}/compare/{other_id}")
def compare(tailored_id: str, other_id: str, db: Session = Depends(scoped_db)):
    a, b = _row(db, tailored_id), _row(db, other_id)
    return {"a": _brief(a), "b": _brief(b), "text_diff": diff.text_diff(a.content, b.content), "score_delta": round(b.score_total - a.score_total, 2)}
