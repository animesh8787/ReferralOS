from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base, IdMixin, UserScoped
from ..util import utcnow

PAIR_STATUSES = ["JOB_DISCOVERED", "JOB_VERIFIED", "JOB_MATCHED", "CONTACT_IDENTIFIED", "DRAFT_READY", "AWAITING_APPROVAL", "APPROVED", "QUEUED", "SENT",
                 "DELIVERY_UNCONFIRMED", "REPLIED", "REFERRAL_OFFERED", "REFERRAL_SUBMITTED", "APPLICATION_SUBMITTED", "REJECTED", "CLOSED", "DO_NOT_CONTACT"]


class OAuthToken(IdMixin, UserScoped, Base):
    """Encrypted OAuth tokens (envelope encryption). Never returned by the API, never logged."""
    __tablename__ = "oauth_tokens"
    provider: Mapped[str] = mapped_column(String(16), default="gmail")
    account_email: Mapped[str] = mapped_column(String(320))
    encrypted_access: Mapped[str] = mapped_column(Text)
    encrypted_refresh: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    scopes: Mapped[list] = mapped_column(JSON, default=list)


class Campaign(IdMixin, UserScoped, Base):
    __tablename__ = "campaigns"
    name: Mapped[str] = mapped_column(String(120))
    goal: Mapped[str] = mapped_column(String(300), default="")
    channel: Mapped[str] = mapped_column(String(10), default="email")
    paused: Mapped[bool] = mapped_column(Boolean, default=False)
    daily_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)  # may only lower the account limit


class OutreachBatch(IdMixin, UserScoped, Base):
    __tablename__ = "outreach_batches"
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    approval_confirmation: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # what the user typed back (count + limit)


class OutreachPair(IdMixin, UserScoped, Base):
    """One job-contact (or company-contact) outreach relationship and its pipeline status."""
    __tablename__ = "outreach_pairs"
    __table_args__ = (Index("ix_pairs_user_status", "user_id", "status"),)
    job_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True, index=True)
    contact_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True, index=True)
    email_contact_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("email_contacts.id", ondelete="SET NULL"), nullable=True, index=True)
    company_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("companies.id"), nullable=True)
    channel: Mapped[str] = mapped_column(String(10))  # linkedin | email
    status: Mapped[str] = mapped_column(String(24), default="CONTACT_IDENTIFIED")
    match_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    contact_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    resume_id: Mapped[str | None] = mapped_column(String(32), nullable=True)  # the APPROVED tailored resume referenced by drafts
    follow_up_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)  # user-supplied proof for REFERRAL_SUBMITTED
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class OutreachMessage(IdMixin, UserScoped, Base):
    __tablename__ = "outreach_messages"
    __table_args__ = (Index("ix_msg_user_state", "user_id", "approval_state", "send_state"),)
    pair_id: Mapped[str] = mapped_column(String(32), ForeignKey("outreach_pairs.id", ondelete="CASCADE"), index=True)
    batch_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("outreach_batches.id", ondelete="SET NULL"), nullable=True, index=True)
    campaign_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True)
    parent_id: Mapped[str | None] = mapped_column(String(32), nullable=True)  # follow-ups point at the message they follow
    job_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    covers_job_ids: Mapped[list] = mapped_column(JSON, default=list)  # one consolidated message can cover several roles at a company
    channel: Mapped[str] = mapped_column(String(10))
    kind: Mapped[str] = mapped_column(String(16))  # referral | cold_job | cold_intro | follow_up | thank_you
    is_initial: Mapped[bool] = mapped_column(Boolean, default=True)
    to_name: Mapped[str | None] = mapped_column(String(250), nullable=True)
    to_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    to_linkedin_url: Mapped[str | None] = mapped_column(String(300), nullable=True)
    subject: Mapped[str | None] = mapped_column(String(300), nullable=True)
    body: Mapped[str] = mapped_column(Text)
    connect_note: Mapped[str | None] = mapped_column(String(320), nullable=True)  # LinkedIn connection note (<= 300 chars)
    subject_options: Mapped[list] = mapped_column(JSON, default=list)
    variants: Mapped[dict] = mapped_column(JSON, default=dict)  # {"A": {subject, body}, "B": {...}}: the user picks one, never automatic
    options: Mapped[dict] = mapped_column(JSON, default=dict)
    attach_resume_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ledger: Mapped[list] = mapped_column(JSON, default=list)
    risk_flags: Mapped[list] = mapped_column(JSON, default=list)
    approval_state: Mapped[str] = mapped_column(String(24), default="awaiting_approval")  # draft|awaiting_approval|approved|rejected|skipped|cancelled
    send_state: Mapped[str] = mapped_column(String(22), default="not_sent")  # not_sent|queued|sending|sent|delivery_unconfirmed|failed|manual_pending|manual_sent|dry_run
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    rfc_message_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    provider_message_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    provider_thread_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    last_block: Mapped[list] = mapped_column(JSON, default=list)  # why the last send attempt did not go out


class EmailEvent(IdMixin, UserScoped, Base):
    __tablename__ = "email_events"
    message_id: Mapped[str] = mapped_column(String(32), ForeignKey("outreach_messages.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(28))  # SENT|DELIVERY_UNCONFIRMED|BOUNCED_HARD|BOUNCED_SOFT|REPLIED|UNSUBSCRIBE_REQUESTED|FOLLOW_UP_DUE|OOO_AUTOREPLY|DRY_RUN|MANUAL_SENT|...
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    label: Mapped[str | None] = mapped_column(String(24), nullable=True)  # reply class: positive|neutral|negative|ooo|unsubscribe|referral_offered|bounce
    confirmed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)  # user confirmation of a suggested classification
