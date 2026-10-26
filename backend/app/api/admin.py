from fastapi import APIRouter, Depends
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from ..models.core import BackgroundTask, User
from ..security import get_db, require_admin

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/health")
def health(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Aggregate counts only; admins never see user personal data."""
    db.execute(text("select 1"))
    by_status = dict(db.query(BackgroundTask.status, func.count()).group_by(BackgroundTask.status).all())
    return {"db": "ok", "users": db.query(func.count(User.id)).scalar(), "tasks": by_status}
