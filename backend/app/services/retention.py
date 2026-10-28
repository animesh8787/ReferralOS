"""Data-retention: raw import files and verbatim CSV values can be auto-purged after N days. Derived contacts stay."""
from datetime import timedelta

from sqlalchemy.orm import Session

from .. import storage
from ..db import new_session
from ..models.contacts import ImportBatch, ImportRow
from ..models.core import UserSetting
from ..util import utcnow

KEY = "privacy.retention"


def get_days(db: Session) -> int | None:
    row = db.query(UserSetting).filter(UserSetting.key == KEY).first()
    return (row.value or {}).get("raw_import_days") if row else None


def set_days(db: Session, days: int | None) -> None:
    row = db.query(UserSetting).filter(UserSetting.key == KEY).first()
    if row:
        row.value = {"raw_import_days": days}
    else:
        db.add(UserSetting(key=KEY, value={"raw_import_days": days}))


def purge_old_imports(db: Session, user_id: str, days: int) -> int:
    n = 0
    cutoff = utcnow() - timedelta(days=days)
    for imp in db.query(ImportBatch).filter(ImportBatch.created_at < cutoff, ImportBatch.status != "purged").all():
        if imp.status == "running":
            continue
        storage.delete(user_id, "imports", imp.id, ".csv")
        db.query(ImportRow).filter(ImportRow.import_id == imp.id).update({"raw": {}})
        imp.status = "purged"
        n += 1
    return n


def run_all() -> int:
    """Called periodically by the worker: applies every user's retention setting."""
    sysdb = new_session()
    try:
        users = [(r.user_id, r.value.get("raw_import_days")) for r in sysdb.query(UserSetting).filter(UserSetting.key == KEY).all()]
    finally:
        sysdb.close()
    total = 0
    for uid, days in users:
        if not days:
            continue
        db = new_session(uid)
        try:
            total += purge_old_imports(db, uid, int(days))
            db.commit()
        finally:
            db.close()
    return total
