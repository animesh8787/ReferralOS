from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base, IdMixin, UserScoped
from ..util import utcnow


class User(IdMixin, Base):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="user")  # user | admin
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    display_name: Mapped[str] = mapped_column(String(200), default="")


class AuthSession(IdMixin, Base):
    """Server-side session; only the sha256 of the cookie token is stored."""
    __tablename__ = "auth_sessions"
    user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime)


class EmailToken(IdMixin, Base):
    """Email-verification and password-reset tokens (hashed, single use)."""
    __tablename__ = "email_tokens"
    user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # verify | reset
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used: Mapped[bool] = mapped_column(Boolean, default=False)


class AuditLog(IdMixin, Base):
    """Sensitive-action log. user_id nullable (failed logins); metadata only, no personal content."""
    __tablename__ = "audit_logs"
    user_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


class BackgroundTask(IdMixin, UserScoped, Base):
    __tablename__ = "background_tasks"
    kind: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)  # queued|running|done|failed
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    progress: Mapped[float] = mapped_column(default=0.0)
    checkpoint: Mapped[dict] = mapped_column(JSON, default=dict)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class UserSetting(IdMixin, UserScoped, Base):
    """Key/value settings and consents (key prefix 'consent.' for opt-ins)."""
    __tablename__ = "user_settings"
    __table_args__ = (UniqueConstraint("user_id", "key"),)
    key: Mapped[str] = mapped_column(String(100))
    value: Mapped[dict] = mapped_column(JSON, default=dict)
