from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import ratelimit
from ..audit import audit
from ..models.core import BackgroundTask, User
from ..security import current_user, get_db, scoped_db, verify_password
from ..services.privacy import delete_user_data, export_user

router = APIRouter(prefix="/api", tags=["me"])


class DeleteIn(BaseModel):
    password: str


@router.get("/me/export")
def export(user: User = Depends(current_user), db: Session = Depends(get_db)):
    ratelimit.check(f"export:{user.id}", 5, 3600)
    audit(db, user.id, "data_exported")
    return export_user(db, user.id)


@router.post("/me/delete")
def delete_me(body: DeleteIn, response: Response, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not verify_password(user.password_hash, body.password):
        raise HTTPException(403, "Password incorrect")
    delete_user_data(db, user.id)
    response.delete_cookie("sid")
    response.delete_cookie("csrf")
    return {"deleted": True}


@router.get("/tasks")
def list_tasks(db: Session = Depends(scoped_db)):
    ts = db.query(BackgroundTask).order_by(BackgroundTask.created_at.desc()).limit(100).all()
    return [_task(t) for t in ts]


@router.get("/tasks/{task_id}")
def get_task(task_id: str, db: Session = Depends(scoped_db)):
    t = db.query(BackgroundTask).filter(BackgroundTask.id == task_id).first()
    if not t:
        raise HTTPException(404, "Not found")
    return _task(t)


def _task(t: BackgroundTask) -> dict:
    return {"id": t.id, "kind": t.kind, "status": t.status, "progress": t.progress, "attempts": t.attempts,
            "error": t.error, "result": t.result}
