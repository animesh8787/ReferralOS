from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base, IdMixin, UserScoped
from ..util import utcnow


class UserJobMatch(IdMixin, UserScoped, Base):
    """Per-user analysis of one job: requirement matrix, eligibility, match score and opportunity priority."""
    __tablename__ = "user_job_matches"
    __table_args__ = (UniqueConstraint("user_id", "job_id"), Index("ix_ujm_user_rank", "user_id", "rank"))
    job_id: Mapped[str] = mapped_column(String(32), ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    desc_hash: Mapped[str] = mapped_column(String(40), default="")
    analysis: Mapped[dict] = mapped_column(JSON)
    matrix: Mapped[list] = mapped_column(JSON)
    eligibility: Mapped[list] = mapped_column(JSON)
    match_total: Mapped[float] = mapped_column(Float)
    match_components: Mapped[dict] = mapped_column(JSON)
    match_extra: Mapped[dict] = mapped_column(JSON)
    priority_total: Mapped[float] = mapped_column(Float, default=0.0)
    priority_components: Mapped[dict] = mapped_column(JSON, default=dict)
    readiness_group: Mapped[int] = mapped_column(Integer, default=2)
    rank: Mapped[int] = mapped_column(Integer, default=0)
    score_only_rank: Mapped[int] = mapped_column(Integer, default=0)
    trade_off: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_action: Mapped[str] = mapped_column(String(300), default="")
    profile_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    config_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    computed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class JobContactScore(IdMixin, UserScoped, Base):
    """Job-specific referral contact score. Only the best few contacts per job are stored."""
    __tablename__ = "job_contact_scores"
    __table_args__ = (UniqueConstraint("user_id", "job_id", "contact_id"),)
    job_id: Mapped[str] = mapped_column(String(32), ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    contact_id: Mapped[str] = mapped_column(String(32), ForeignKey("contacts.id", ondelete="CASCADE"), index=True)
    total: Mapped[float] = mapped_column(Float)
    components: Mapped[dict] = mapped_column(JSON)
    employment_label: Mapped[str] = mapped_column(String(20), default="unknown")
    rank_in_job: Mapped[int] = mapped_column(Integer)
    recommended: Mapped[bool] = mapped_column(Boolean, default=False)
    also_fits_jobs: Mapped[list] = mapped_column(JSON, default=list)  # other jobs this same person is recommended for (one strategy)
    config_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
