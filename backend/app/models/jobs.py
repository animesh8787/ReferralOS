from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base, IdMixin, UserScoped
from ..util import new_id, utcnow

STATUSES = ("ACTIVE_VERIFIED", "ACTIVE_UNCONFIRMED", "POSSIBLY_CLOSED", "CLOSED", "UNKNOWN")


class Job(Base):
    """Shared canonical job (public posting data only). Per-user state lives in UserJob and later match tables.
    Manually pasted descriptions carry owner_user_id and are never merged with, or listed for, other users."""
    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_company_key", "company_id", "canonical_key"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(String(32), ForeignKey("companies.id"), index=True)
    owner_user_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)  # manual/private jobs only
    title: Mapped[str] = mapped_column(String(300))
    canonical_key: Mapped[str] = mapped_column(String(400))
    location: Mapped[str | None] = mapped_column(String(300), nullable=True)
    work_arrangement: Mapped[str] = mapped_column(String(10), default="unknown")  # remote|hybrid|onsite|unknown
    employment_type: Mapped[str] = mapped_column(String(12), default="unknown")  # full_time|internship|part_time|contract|unknown
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    apply_url: Mapped[str | None] = mapped_column(String(600), nullable=True)
    posted_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    deadline: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="UNKNOWN", index=True)
    status_reasons: Mapped[list] = mapped_column(JSON, default=list)
    first_discovered: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_verified: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class JobSource(Base):
    """Where a canonical job was seen. One job, many sources (dedup keeps every link)."""
    __tablename__ = "job_sources"
    __table_args__ = (UniqueConstraint("source_type", "board_token", "source_job_id"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(String(32), ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    source_type: Mapped[str] = mapped_column(String(16))  # greenhouse|lever|ashby|workable|smartrecruiters|jsonld|manual
    board_token: Mapped[str] = mapped_column(String(80), default="")
    source_job_id: Mapped[str] = mapped_column(String(200))
    source_url: Mapped[str | None] = mapped_column(String(600), nullable=True)
    apply_url: Mapped[str | None] = mapped_column(String(600), nullable=True)
    first_seen: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class JobVerification(Base):
    """One timestamped piece of evidence about whether a job is open. Append-only."""
    __tablename__ = "job_verifications"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(String(32), ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    source_type: Mapped[str] = mapped_column(String(16))
    kind: Mapped[str] = mapped_column(String(20))  # api_listed|api_absent|page_gone|page_closed_text|page_ok|jsonld_valid|deadline_passed|inaccessible
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


class UserBoard(IdMixin, UserScoped, Base):
    """An ATS job board the user wants searched. Suggested boards stay unconfirmed until the user confirms."""
    __tablename__ = "user_boards"
    __table_args__ = (UniqueConstraint("user_id", "ats", "token"),)
    company_id: Mapped[str] = mapped_column(String(32), ForeignKey("companies.id"))
    ats: Mapped[str] = mapped_column(String(16))
    token: Mapped[str] = mapped_column(String(80))
    careers_url: Mapped[str | None] = mapped_column(String(400), nullable=True)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=True)
    added_from: Mapped[str] = mapped_column(String(12), default="user")  # user|suggested
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(200), nullable=True)
    jobs_found: Mapped[int] = mapped_column(Integer, default=0)


class UserJob(IdMixin, UserScoped, Base):
    __tablename__ = "user_jobs"
    __table_args__ = (UniqueConstraint("user_id", "job_id"),)
    job_id: Mapped[str] = mapped_column(String(32), ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    origin: Mapped[str] = mapped_column(String(10), default="discovery")  # discovery|manual
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)


class DiscoveryRun(IdMixin, UserScoped, Base):
    __tablename__ = "discovery_runs"
    status: Mapped[str] = mapped_column(String(10), default="running")
    coverage: Mapped[list] = mapped_column(JSON, default=list)  # per board: reachable?, jobs, error
    summary: Mapped[dict] = mapped_column(JSON, default=dict)


class ReferralRoute(IdMixin, UserScoped, Base):
    """Does this company publish a referral programme? Never assumed; evidence or 'unknown'."""
    __tablename__ = "referral_routes"
    __table_args__ = (UniqueConstraint("user_id", "company_id"),)
    company_id: Mapped[str] = mapped_column(String(32), ForeignKey("companies.id"))
    status: Mapped[str] = mapped_column(String(28), default="UNKNOWN")
    source: Mapped[str] = mapped_column(String(14), default="none")  # official_page|user
    evidence_url: Mapped[str | None] = mapped_column(String(600), nullable=True)
    evidence_excerpt: Mapped[str | None] = mapped_column(String(300), nullable=True)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
