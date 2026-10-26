from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base, IdMixin, UserScoped
from ..util import utcnow


class ContactScore(IdMixin, UserScoped, Base):
    """Latest general Referral Priority Score per connection. inputs + config_snapshot make it reproducible."""
    __tablename__ = "contact_scores"
    __table_args__ = (Index("ix_cs_user_rank", "user_id", "rank"),)
    contact_id: Mapped[str] = mapped_column(String(32), ForeignKey("contacts.id", ondelete="CASCADE"), unique=True, index=True)
    total: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    rank: Mapped[int] = mapped_column(Integer)
    tier: Mapped[int | None] = mapped_column(Integer, nullable=True)
    excluded: Mapped[bool] = mapped_column(Boolean, default=False)
    components: Mapped[dict] = mapped_column(JSON)
    confidence_parts: Mapped[dict] = mapped_column(JSON)
    inputs: Mapped[dict] = mapped_column(JSON)
    scoring_version: Mapped[str] = mapped_column(String(40))
    config_snapshot: Mapped[dict] = mapped_column(JSON)
    computed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
