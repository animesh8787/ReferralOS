"""Generic per-user export and hard delete, driven by metadata: any table with a user_id column is covered,
so new user-owned tables are included automatically."""
import json

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..db import Base
from .. import storage

SECRET_COLS = {"password_hash", "token_hash", "csrf_token", "encrypted_token", "encrypted_key"}


def _user_tables():
    return [t for t in Base.metadata.sorted_tables if "user_id" in t.c]


def export_user(db: Session, user_id: str) -> dict:
    """db must be unscoped; we filter explicitly here."""
    out = {}
    for t in _user_tables():
        cols = [c for c in t.c if c.name not in SECRET_COLS]
        rows = db.execute(select(*cols).where(t.c.user_id == user_id)).mappings().all()
        out[t.name] = [dict(r) for r in rows]
    u = Base.metadata.tables["users"]
    row = db.execute(select(u.c.id, u.c.email, u.c.display_name, u.c.created_at).where(u.c.id == user_id)).mappings().first()
    out["users"] = [dict(row)] if row else []
    return json.loads(json.dumps(out, default=str))


def delete_user_data(db: Session, user_id: str) -> dict:
    counts = {}
    for t in reversed(_user_tables()):
        counts[t.name] = db.execute(delete(t).where(t.c.user_id == user_id)).rowcount
    db.execute(delete(Base.metadata.tables["users"]).where(Base.metadata.tables["users"].c.id == user_id))
    storage.delete_user(user_id)
    return counts
