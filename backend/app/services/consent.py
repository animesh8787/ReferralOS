"""Opt-in consents (stored as user_settings 'consent.<name>'). Everything that talks to a third party checks here."""
from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..models.core import UserSetting

NAMES = {"github": "Fetch my public GitHub data", "portfolio": "Fetch the portfolio URLs I supply",
         "llm": "Send minimal profile fields to my chosen LLM provider", "gmail": "Connect my Gmail account",
         "reply_tracking": "Read reply/bounce state of messages sent from this app"}


def get(db: Session, name: str) -> bool:
    s = db.query(UserSetting).filter(UserSetting.key == f"consent.{name}").first()
    return bool(s and s.value.get("granted"))


def set_(db: Session, name: str, granted: bool) -> None:
    if name not in NAMES:
        raise HTTPException(404, "Unknown consent")
    s = db.query(UserSetting).filter(UserSetting.key == f"consent.{name}").first()
    if s:
        s.value = {"granted": granted}
    else:
        db.add(UserSetting(key=f"consent.{name}", value={"granted": granted}))


def require(db: Session, name: str) -> None:
    if not get(db, name):
        raise HTTPException(403, f"Consent required: {NAMES[name]}. Enable it in Settings > Privacy first.")
