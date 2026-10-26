from sqlalchemy import Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base, IdMixin, UserScoped


class LLMUsage(IdMixin, UserScoped, Base):
    """One row per model call: metadata only (no prompt or output text is stored)."""
    __tablename__ = "llm_usage"
    kind: Mapped[str] = mapped_column(String(30))
    model: Mapped[str] = mapped_column(String(60))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    est_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
