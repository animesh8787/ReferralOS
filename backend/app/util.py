import uuid
from datetime import datetime, timezone


def utcnow() -> datetime:
    """Naive UTC; SQLite drops tzinfo so we store naive UTC everywhere."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def new_id() -> str:
    return uuid.uuid4().hex
