import hashlib
import re
import secrets
from datetime import timedelta

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .config import get_settings
from .db import new_session
from .models.core import AuthSession, User
from .util import utcnow

_ph = PasswordHasher()
SAFE = {"GET", "HEAD", "OPTIONS"}


def hash_password(pw: str) -> str:
    return _ph.hash(pw)


def verify_password(h: str, pw: str) -> bool:
    try:
        return _ph.verify(h, pw)
    except VerificationError:
        return False


def check_password_policy(pw: str) -> None:
    if len(pw) < 10 or not re.search(r"[A-Za-z]", pw) or not re.search(r"\d", pw):
        raise HTTPException(422, "Password must be at least 10 characters and contain a letter and a digit")


def sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def new_token() -> str:
    return secrets.token_urlsafe(32)


def create_session(db: Session, user: User) -> tuple[str, str]:
    raw, csrf = new_token(), new_token()
    db.add(AuthSession(user_id=user.id, token_hash=sha(raw), csrf_token=csrf,
                       expires_at=utcnow() + timedelta(hours=get_settings().session_hours)))
    return raw, csrf


def set_auth_cookies(resp, raw: str, csrf: str) -> None:
    secure = get_settings().cookie_secure
    age = get_settings().session_hours * 3600
    resp.set_cookie("sid", raw, httponly=True, samesite="lax", secure=secure, max_age=age, path="/")
    resp.set_cookie("csrf", csrf, httponly=False, samesite="lax", secure=secure, max_age=age, path="/")


def get_db():
    """Unscoped session; used by auth endpoints that run before a user is known."""
    db = new_session()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def current_user(request: Request) -> User:
    """Authenticate, enforce CSRF on unsafe methods; stash user on the request."""
    raw = request.cookies.get("sid")
    if not raw:
        raise HTTPException(401, "Not authenticated")
    db = new_session()
    try:
        s = db.query(AuthSession).filter(AuthSession.token_hash == sha(raw)).first()
        if not s or s.expires_at < utcnow():
            raise HTTPException(401, "Session expired")
        if request.method not in SAFE:
            hdr, ck = request.headers.get("x-csrf-token"), request.cookies.get("csrf")
            if not hdr or not ck or not secrets.compare_digest(hdr, ck) or not secrets.compare_digest(hdr, s.csrf_token):
                raise HTTPException(403, "CSRF check failed")
        user = db.get(User, s.user_id)
        if not user:
            raise HTTPException(401, "Not authenticated")
        db.expunge(user)
        return user
    finally:
        db.close()


def scoped_db(user: User = Depends(current_user)):
    """Tenant-scoped session. Every user-data endpoint depends on this."""
    db = new_session(user.id)
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def require_verified(user: User = Depends(current_user)) -> User:
    if get_settings().require_email_verification and not user.email_verified:
        raise HTTPException(403, "Verify your email first")
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(403, "Admin only")
    return user
