import hashlib
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import ratelimit, storage, tasks
from ..adapters import github_api
from ..adapters.http import UnsafeUrl, check_public_url
from ..audit import audit
from ..models.core import User
from ..models.profile import ProfileItem, ProfileVersion, Resume
from ..security import current_user, scoped_db
from ..services import consent, profile as svc
from ..services.resume_parse import MAX_BYTES

router = APIRouter(prefix="/api", tags=["profile"])


def _task(t):
    return {"task_id": t.id, "status": t.status, "task_status": t.status, "result": t.result}


# ---------------------------------------------------------------- consents
@router.get("/consents")
def consents(db: Session = Depends(scoped_db)):
    return {n: {"granted": consent.get(db, n), "description": d} for n, d in consent.NAMES.items()}


class ConsentIn(BaseModel):
    granted: bool


@router.put("/consents/{name}")
def set_consent(name: str, body: ConsentIn, user: User = Depends(current_user), db: Session = Depends(scoped_db)):
    consent.set_(db, name, body.granted)
    audit(db, user.id, "consent_changed", name=name, granted=body.granted)
    return {"name": name, "granted": body.granted}


# ---------------------------------------------------------------- resumes
@router.post("/resumes", status_code=201)
async def upload_resume(file: UploadFile = File(...), user: User = Depends(current_user), db: Session = Depends(scoped_db)):
    ratelimit.check(f"upload:{user.id}", 20, 3600)
    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    if ext not in ("pdf", "docx"):
        raise HTTPException(422, "Only PDF and DOCX files are supported")
    data = await file.read(MAX_BYTES + 1)
    if not data:
        raise HTTPException(422, "The file is empty")
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "The file is larger than 5 MB")
    r = Resume(filename=(file.filename or "resume")[-200:], ext=ext, size=len(data), sha256=hashlib.sha256(data).hexdigest())
    db.add(r)
    db.flush()
    storage.put(user.id, "resumes", r.id, data, f".{ext}")
    db.commit()
    t = tasks.enqueue(db, "parse_resume", {"resume_id": r.id})
    audit(db, user.id, "resume_uploaded", resume_id=r.id)
    db.refresh(r)
    return {**_task(t), "resume_id": r.id, "status": r.status}  # status = resume status; task state is in result


@router.get("/resumes")
def list_resumes(db: Session = Depends(scoped_db)):
    return [{"id": r.id, "filename": r.filename, "status": r.status, "created_at": r.created_at}
            for r in db.query(Resume).order_by(Resume.created_at.desc()).all()]


@router.get("/resumes/{resume_id}")
def get_resume(resume_id: str, db: Session = Depends(scoped_db)):
    r = db.query(Resume).filter(Resume.id == resume_id).first()
    if not r:
        raise HTTPException(404, "Not found")
    items = db.query(ProfileItem).filter(ProfileItem.source == "resume", ProfileItem.source_ref == r.id).all()
    return {"id": r.id, "filename": r.filename, "status": r.status, "parse_info": r.parse_info, "raw_text": r.raw_text,
            "items": [svc.serialize(i) | {"span": i.source_span} for i in items]}


@router.get("/resumes/{resume_id}/file")
def download_resume(resume_id: str, user: User = Depends(current_user), db: Session = Depends(scoped_db)):
    r = db.query(Resume).filter(Resume.id == resume_id).first()
    if not r:
        raise HTTPException(404, "Not found")
    mt = "application/pdf" if r.ext == "pdf" else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return Response(storage.get(user.id, "resumes", r.id, f".{r.ext}"), media_type=mt,
                    headers={"Content-Disposition": f'attachment; filename="resume.{r.ext}"'})


# ---------------------------------------------------------------- profile
@router.get("/profile")
def get_profile(db: Session = Depends(scoped_db)):
    rows = db.query(ProfileItem).filter(ProfileItem.status != "rejected").order_by(ProfileItem.created_at).all()
    grouped: dict[str, list] = {}
    for r in rows:
        grouped.setdefault(r.section, []).append(svc.serialize(r))
    return {"items": grouped, "completeness": svc.completeness(rows), "questions": svc.questions(rows)}


class ItemIn(BaseModel):
    section: str
    data: dict


class ItemPatch(BaseModel):
    data: dict | None = None
    verified: bool | None = None
    status: Literal["active", "rejected"] | None = None


@router.post("/profile/items", status_code=201)
def add_item(body: ItemIn, db: Session = Depends(scoped_db)):
    if body.section not in svc.SECTIONS:
        raise HTTPException(422, "Unknown section")
    row = ProfileItem(section=body.section, data=body.data, source="manual", verified=True, confidence=1.0)
    db.add(row)
    db.flush()
    svc.snapshot(db, f"Added {body.section}")
    return svc.serialize(row)


def _own(db, item_id) -> ProfileItem:
    r = db.query(ProfileItem).filter(ProfileItem.id == item_id).first()
    if not r:
        raise HTTPException(404, "Not found")
    return r


@router.patch("/profile/items/{item_id}")
def patch_item(item_id: str, body: ItemPatch, db: Session = Depends(scoped_db)):
    r = _own(db, item_id)
    if body.data is not None:
        r.data, r.source, r.verified, r.confidence = body.data, "manual", True, 1.0  # the user's edit is the new source of truth
    if body.verified is not None:
        r.verified = body.verified
    if body.status:
        r.status = body.status
    r.flags = [f for f in (r.flags or []) if f.get("type") != "conflict"] if body.data is not None else r.flags
    svc.snapshot(db, f"Edited {r.section}")
    return svc.serialize(r)


@router.post("/profile/items/{item_id}/confirm")
def confirm_item(item_id: str, db: Session = Depends(scoped_db)):
    r = _own(db, item_id)
    r.status, r.verified = "active", True
    svc.snapshot(db, f"Confirmed {r.section}")
    return svc.serialize(r)


@router.delete("/profile/items/{item_id}")
def delete_item(item_id: str, db: Session = Depends(scoped_db)):
    r = _own(db, item_id)
    sec = r.section
    db.delete(r)
    db.flush()
    svc.snapshot(db, f"Deleted {sec}")
    return {"deleted": True}


@router.get("/profile/versions")
def versions(db: Session = Depends(scoped_db)):
    return [{"id": v.id, "version": v.version, "reason": v.reason, "created_at": v.created_at}
            for v in db.query(ProfileVersion).order_by(ProfileVersion.version.desc()).all()]


@router.get("/profile/versions/{version_id}")
def get_version(version_id: str, db: Session = Depends(scoped_db)):
    v = db.query(ProfileVersion).filter(ProfileVersion.id == version_id).first()
    if not v:
        raise HTTPException(404, "Not found")
    return {"id": v.id, "version": v.version, "reason": v.reason, "snapshot": v.snapshot}


class Prefs(BaseModel):
    target_roles: list[str] = []
    target_companies: list[str] = []
    excluded_companies: list[str] = []
    locations: list[str] = []
    work_arrangement: list[str] = []  # remote|hybrid|onsite
    employment_type: list[str] = []  # internship|full_time|part_time|contract
    graduation_date: str | None = None  # YYYY-MM
    work_authorization: str | None = None  # voluntary


@router.put("/profile/preferences")
def put_prefs(body: Prefs, db: Session = Depends(scoped_db)):
    r = db.query(ProfileItem).filter(ProfileItem.section == "preference").first()
    if r:
        r.data = body.model_dump()
    else:
        db.add(ProfileItem(section="preference", data=body.model_dump(), source="manual", verified=True, confidence=1.0))
    db.flush()
    svc.snapshot(db, "Updated preferences")
    return body


# ---------------------------------------------------------------- enrichment
class GithubIn(BaseModel):
    username: str


class PortfolioIn(BaseModel):
    url: str


@router.post("/profile/github", status_code=202)
def import_github(body: GithubIn, user: User = Depends(current_user), db: Session = Depends(scoped_db)):
    consent.require(db, "github")
    try:
        name = github_api.parse_username(body.username)
    except github_api.GitHubError as e:
        raise HTTPException(422, str(e))
    ratelimit.check(f"github:{user.id}", 10, 3600)
    audit(db, user.id, "github_import", username=name)
    return _task(tasks.enqueue(db, "github_import", {"username": name}))


@router.post("/profile/portfolio", status_code=202)
def import_portfolio(body: PortfolioIn, user: User = Depends(current_user), db: Session = Depends(scoped_db)):
    consent.require(db, "portfolio")
    try:
        check_public_url(body.url)  # cheap syntax/literal-IP check now; DNS check happens in the worker
    except UnsafeUrl as e:
        raise HTTPException(422, str(e))
    ratelimit.check(f"portfolio:{user.id}", 10, 3600)
    audit(db, user.id, "portfolio_import")
    return _task(tasks.enqueue(db, "portfolio_import", {"url": body.url}))


class TokenIn(BaseModel):
    token: str | None = None


@router.put("/settings/github-token")
def put_github_token(body: TokenIn, user: User = Depends(current_user), db: Session = Depends(scoped_db)):
    """Optional: a GitHub token only raises the API rate limit for public data. Stored encrypted; never returned or exported."""
    from .. import crypto
    from ..models.core import UserSetting
    consent.require(db, "github")
    row = db.query(UserSetting).filter(UserSetting.key == "github.token").first()
    if not body.token:
        if row:
            db.delete(row)
        audit(db, user.id, "github_token_removed")
        return {"token_set": False}
    t = body.token.strip()
    if not 20 <= len(t) <= 300 or any(c.isspace() for c in t):
        raise HTTPException(422, "That does not look like a GitHub token")
    val = {"enc": crypto.encrypt(t)}
    if row:
        row.value = val
    else:
        db.add(UserSetting(key="github.token", value=val))
    audit(db, user.id, "github_token_set")
    return {"token_set": True}


@router.get("/settings/github-token")
def get_github_token(db: Session = Depends(scoped_db)):
    from ..models.core import UserSetting
    return {"token_set": bool(db.query(UserSetting.id).filter(UserSetting.key == "github.token").first())}
