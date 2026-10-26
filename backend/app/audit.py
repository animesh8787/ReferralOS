from sqlalchemy.orm import Session

from .models.core import AuditLog


def audit(db: Session, user_id: str | None, action: str, **detail) -> None:
    """Metadata only. Never put emails, tokens or message content in detail."""
    db.add(AuditLog(user_id=user_id, action=action, detail=detail))
