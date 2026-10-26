from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base, IdMixin, UserScoped
from ..util import new_id, utcnow


class Company(Base):
    """Shared reference data (company names are not personal). Never exposes which user knows it."""
    __tablename__ = "companies"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    key: Mapped[str] = mapped_column(String(200), unique=True, index=True)  # normalized name
    name: Mapped[str] = mapped_column(String(200))  # display name (first seen, cleaned)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class UserCompanyAlias(IdMixin, UserScoped, Base):
    """The user's own resolution of a raw company string to a company (from the review queue)."""
    __tablename__ = "user_company_aliases"
    __table_args__ = (UniqueConstraint("user_id", "alias_key"),)
    alias_key: Mapped[str] = mapped_column(String(200))
    company_id: Mapped[str] = mapped_column(String(32), ForeignKey("companies.id"))


class CompanyReview(IdMixin, UserScoped, Base):
    """Ambiguous fuzzy company matches waiting for the user. Nothing is auto-merged below the high threshold."""
    __tablename__ = "company_reviews"
    raw_name: Mapped[str] = mapped_column(String(200))
    company_id: Mapped[str] = mapped_column(String(32), ForeignKey("companies.id"))  # the company created for raw_name
    candidate_id: Mapped[str] = mapped_column(String(32), ForeignKey("companies.id"))  # the possible match
    score: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(12), default="pending")  # pending|merged|separate


class ImportBatch(IdMixin, UserScoped, Base):
    __tablename__ = "imports"
    kind: Mapped[str] = mapped_column(String(12))  # linkedin | hr
    filename: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(12), default="uploaded")  # uploaded|running|done|failed|purged
    provenance: Mapped[str | None] = mapped_column(String(24), nullable=True)  # hr only
    provenance_note: Mapped[str | None] = mapped_column(String(300), nullable=True)
    encoding: Mapped[str] = mapped_column(String(24), default="utf-8")
    delimiter: Mapped[str] = mapped_column(String(2), default=",")
    header_row: Mapped[int] = mapped_column(Integer, default=0)
    mapping: Mapped[dict] = mapped_column(JSON, default=dict)
    report: Mapped[dict] = mapped_column(JSON, default=dict)
    region: Mapped[str] = mapped_column(String(2), default="US")  # phone parsing region


class ImportRow(IdMixin, UserScoped, Base):
    """Source record: original values are preserved verbatim; derived values live on Contact/EmailContact."""
    __tablename__ = "import_rows"
    __table_args__ = (Index("ix_import_rows_import_status", "import_id", "status"),)
    import_id: Mapped[str] = mapped_column(String(32), ForeignKey("imports.id", ondelete="CASCADE"), index=True)
    row_number: Mapped[int] = mapped_column(Integer)
    raw: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(10))  # valid | duplicate | invalid
    reasons: Mapped[list] = mapped_column(JSON, default=list)  # [{code, note}]


class Contact(IdMixin, UserScoped, Base):
    """A LinkedIn connection (or manually added person)."""
    __tablename__ = "contacts"
    __table_args__ = (UniqueConstraint("user_id", "linkedin_key"), Index("ix_contacts_user_company", "user_id", "company_id"),
                      Index("ix_contacts_user_name", "user_id", "name_norm"))
    source: Mapped[str] = mapped_column(String(12), default="LINKEDIN")  # LINKEDIN | MANUAL
    import_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("imports.id", ondelete="SET NULL"), nullable=True)
    first_name: Mapped[str] = mapped_column(String(120), default="")
    last_name: Mapped[str] = mapped_column(String(120), default="")
    name_norm: Mapped[str] = mapped_column(String(250), default="")
    linkedin_url: Mapped[str | None] = mapped_column(String(300), nullable=True)
    linkedin_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    company_raw: Mapped[str | None] = mapped_column(String(300), nullable=True)
    company_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("companies.id"), nullable=True)
    position: Mapped[str | None] = mapped_column(String(300), nullable=True)
    connected_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    # derived in Phase 5
    role_category: Mapped[str | None] = mapped_column(String(24), nullable=True)
    seniority: Mapped[str | None] = mapped_column(String(16), nullable=True)
    employment_status: Mapped[str] = mapped_column(String(20), default="unknown")  # unknown|likely_current|possibly_outdated
    employment_verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    dedup_fallback: Mapped[str | None] = mapped_column(String(300), nullable=True)  # name+company key, used only when no URL


class EmailContact(IdMixin, UserScoped, Base):
    """HR / recruiter contact from a CSV or manual entry. Separate from LinkedIn connections, optionally linked."""
    __tablename__ = "email_contacts"
    __table_args__ = (UniqueConstraint("user_id", "email_norm"), Index("ix_ec_user_company", "user_id", "company_id"))
    import_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("imports.id", ondelete="SET NULL"), nullable=True)
    contact_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True)
    name: Mapped[str | None] = mapped_column(String(250), nullable=True)
    title: Mapped[str | None] = mapped_column(String(300), nullable=True)
    company_raw: Mapped[str | None] = mapped_column(String(300), nullable=True)
    company_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("companies.id"), nullable=True)
    email_raw: Mapped[str | None] = mapped_column(String(320), nullable=True)
    email_norm: Mapped[str | None] = mapped_column(String(320), nullable=True)  # only when syntactically valid
    email_valid: Mapped[bool] = mapped_column(Boolean, default=False)
    email_flags: Mapped[list] = mapped_column(JSON, default=list)  # role_account | noreply | mx_missing | ...
    phone_raw: Mapped[str | None] = mapped_column(String(60), nullable=True)
    phone_e164: Mapped[str | None] = mapped_column(String(20), nullable=True)
    linkedin_url: Mapped[str | None] = mapped_column(String(300), nullable=True)
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    provenance: Mapped[str] = mapped_column(String(24), default="other")
    country_hint: Mapped[str | None] = mapped_column(String(2), nullable=True)  # from phone region or email ccTLD
    bulk_send_blocked: Mapped[bool] = mapped_column(Boolean, default=False)  # purchased/unknown-provenance lists


class SuppressionEntry(IdMixin, UserScoped, Base):
    """Per-user do-not-contact list. Keyed by normalized email (or domain); survives imports and contact deletion."""
    __tablename__ = "suppression_entries"
    __table_args__ = (UniqueConstraint("user_id", "kind", "value"),)
    kind: Mapped[str] = mapped_column(String(8), default="email")  # email | domain
    value: Mapped[str] = mapped_column(String(320))
    reason: Mapped[str] = mapped_column(String(20))  # unsubscribed|bounced|do_not_contact|complained|blocklist
    source: Mapped[str] = mapped_column(String(20), default="manual")
