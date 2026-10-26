from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base, IdMixin, UserScoped
from ..util import utcnow


class TailoredResume(IdMixin, UserScoped, Base):
    """One version of a resume tailored for one job. Approved versions are never modified: edits create a new version."""
    __tablename__ = "tailored_resumes"
    __table_args__ = (UniqueConstraint("user_id", "job_id", "version"), Index("ix_tr_user_job", "user_id", "job_id"))
    job_id: Mapped[str] = mapped_column(String(32), ForeignKey("jobs.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer)
    parent_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(10), default="draft")  # draft | approved
    content: Mapped[dict] = mapped_column(JSON)
    ledger: Mapped[list] = mapped_column(JSON)
    validation: Mapped[dict] = mapped_column(JSON)
    score: Mapped[dict] = mapped_column(JSON)
    changes: Mapped[dict] = mapped_column(JSON)  # diff vs the master profile + requirements the background does not support
    questions: Mapped[list] = mapped_column(JSON, default=list)
    options: Mapped[dict] = mapped_column(JSON, default=dict)
    matrix: Mapped[list] = mapped_column(JSON, default=list)
    profile_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    files: Mapped[list] = mapped_column(JSON, default=list)  # names under generated/<id>/
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    score_total: Mapped[float] = mapped_column(Float, default=0.0)
