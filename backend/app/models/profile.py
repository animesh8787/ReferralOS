from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base, IdMixin, UserScoped
from ..util import utcnow


class Resume(IdMixin, UserScoped, Base):
    """Uploaded original. Immutable: edits happen on ProfileItems, never on this row or its file."""
    __tablename__ = "resumes"
    filename: Mapped[str] = mapped_column(String(255))
    ext: Mapped[str] = mapped_column(String(8))
    size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="uploaded")  # uploaded|parsed|image_only|failed
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    parse_info: Mapped[dict] = mapped_column(JSON, default=dict)


class ProfileItem(IdMixin, UserScoped, Base):
    """One fact group of the Master Career Profile (a job, a project, a skill ...), with provenance."""
    __tablename__ = "profile_items"
    section: Mapped[str] = mapped_column(String(24), index=True)  # personal|education|experience|project|skill|certification|award|publication|summary|preference
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(12), default="active", index=True)  # active|suggested|rejected
    source: Mapped[str] = mapped_column(String(16))  # resume|github|portfolio|manual|inferred
    source_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_span: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)  # user-confirmed
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    evidence_level: Mapped[str | None] = mapped_column(String(24), nullable=True)  # skills only
    flags: Mapped[list] = mapped_column(JSON, default=list)  # conflicts / possibly-not-original etc.
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class ProfileVersion(IdMixin, UserScoped, Base):
    """Immutable snapshot of active items after each change."""
    __tablename__ = "profile_versions"
    version: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(120))
    snapshot: Mapped[list] = mapped_column(JSON)
