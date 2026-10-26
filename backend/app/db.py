"""Engine, session and central tenant scoping.

Every model inheriting UserScoped is filtered on SELECT and stamped/validated on INSERT,
based on session.info["user_id"]. Sessions without it (auth bootstrap, worker claim) are unscoped.
"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, create_engine, event
from sqlalchemy.orm import (DeclarativeBase, Mapped, Session, declared_attr, mapped_column,
                            sessionmaker, with_loader_criteria)

from .config import get_settings
from .util import new_id, utcnow


class Base(DeclarativeBase):
    pass


class TenantViolation(Exception):
    pass


class UserScoped:
    """Mixin: non-null indexed user_id FK. Scoped centrally; never filter by user ad hoc."""

    @declared_attr
    def user_id(cls) -> Mapped[str]:
        return mapped_column(String(32), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)


class IdMixin:
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


_engine = None
_Session = None


def get_engine():
    global _engine, _Session
    if _engine is None:
        url = get_settings().database_url
        if url.startswith("sqlite"):
            get_settings().data_dir.mkdir(parents=True, exist_ok=True)
            _engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})

            @event.listens_for(_engine, "connect")
            def _fk(dbapi_conn, _):
                dbapi_conn.execute("PRAGMA foreign_keys=ON")
        else:
            _engine = create_engine(url, pool_pre_ping=True)
        _Session = sessionmaker(_engine, expire_on_commit=False)
    return _engine


def reset_engine():
    global _engine, _Session
    if _engine is not None:
        _engine.dispose()
    _engine = _Session = None


def new_session(user_id: str | None = None) -> Session:
    get_engine()
    s = _Session()
    if user_id:
        s.info["user_id"] = user_id
    return s


@event.listens_for(Session, "do_orm_execute")
def _scope_selects(state):
    uid = state.session.info.get("user_id")
    if uid and state.is_select:
        state.statement = state.statement.options(
            with_loader_criteria(UserScoped, lambda cls: cls.user_id == uid, include_aliases=True))


@event.listens_for(Session, "before_flush")
def _stamp_inserts(session, ctx, instances):
    uid = session.info.get("user_id")
    if not uid:
        return
    for obj in session.new:
        if isinstance(obj, UserScoped):
            if obj.user_id is None:
                obj.user_id = uid
            elif obj.user_id != uid:
                raise TenantViolation(f"{type(obj).__name__} user_id mismatch")


def get_owned(db: Session, model, obj_id: str):
    """The only by-id lookup for user data. Scoping turns foreign ids into None (-> 404)."""
    return db.query(model).filter(model.id == obj_id).first()
