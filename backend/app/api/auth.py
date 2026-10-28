from datetime import timedelta

from email_validator import EmailNotValidError, validate_email
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import ratelimit
from ..adapters.mailer import send_system_mail
from ..audit import audit
from ..config import get_settings
from ..models.core import AuthSession, EmailToken, User
from ..security import (check_password_policy, create_session, current_user, get_db, hash_password, new_token,
                        set_auth_cookies, sha, verify_password)
from ..util import utcnow

router = APIRouter(prefix="/api/auth", tags=["auth"])


class Signup(BaseModel):
    email: str
    password: str
    display_name: str = ""


class Login(BaseModel):
    email: str
    password: str


class TokenIn(BaseModel):
    token: str


class Forgot(BaseModel):
    email: str


class Reset(BaseModel):
    token: str
    password: str


def _ip(request: Request) -> str:
    return request.client.host if request.client else "?"


def _norm_email(e: str) -> str:
    try:
        return validate_email(e, check_deliverability=False).normalized.lower()
    except EmailNotValidError:
        raise HTTPException(422, "Invalid email address")


def _issue(db: Session, user: User, kind: str, hours: int) -> str:
    raw = new_token()
    db.add(EmailToken(user_id=user.id, kind=kind, token_hash=sha(raw), expires_at=utcnow() + timedelta(hours=hours)))
    return raw


def _send_verification(db: Session, u: User) -> None:
    tok = _issue(db, u, "verify", 48)
    link = f"{get_settings().app_url}/verify?token={tok}"
    send_system_mail(u.email, "Verify your ReferralOS email", f"Open this link to verify your email:\n{link}\n\nVerification token: {tok}")


def _public(u: User) -> dict:
    return {"id": u.id, "email": u.email, "display_name": u.display_name, "role": u.role,
            "email_verified": u.email_verified}


@router.post("/signup", status_code=201)
def signup(body: Signup, request: Request, db: Session = Depends(get_db)):
    ratelimit.check(f"signup:{_ip(request)}", 10, 3600)
    email = _norm_email(body.email)
    check_password_policy(body.password)
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(409, "An account with this email already exists")
    u = User(email=email, password_hash=hash_password(body.password), display_name=body.display_name[:200])
    db.add(u)
    db.flush()
    _send_verification(db, u)
    audit(db, u.id, "signup")
    return _public(u)


@router.post("/verify")
def verify(body: TokenIn, db: Session = Depends(get_db)):
    t = db.query(EmailToken).filter(EmailToken.token_hash == sha(body.token), EmailToken.kind == "verify").first()
    if not t or t.used or t.expires_at < utcnow():
        raise HTTPException(400, "Invalid or expired token")
    t.used = True
    db.get(User, t.user_id).email_verified = True
    audit(db, t.user_id, "email_verified")
    return {"ok": True}


@router.post("/login")
def login(body: Login, request: Request, response: Response, db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    ratelimit.check(f"login-ip:{_ip(request)}", 20, 300)
    ratelimit.check(f"login-acct:{email}", 5, 300)
    u = db.query(User).filter(User.email == email).first()
    if not u or not verify_password(u.password_hash, body.password):
        audit(db, u.id if u else None, "login_failed")
        db.commit()  # keep the audit row even though we raise
        raise HTTPException(401, "Invalid email or password")
    raw, csrf = create_session(db, u)
    audit(db, u.id, "login")
    set_auth_cookies(response, raw, csrf)
    return _public(u)


@router.post("/logout")
def logout(request: Request, response: Response, user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.query(AuthSession).filter(AuthSession.token_hash == sha(request.cookies["sid"])).delete()
    audit(db, user.id, "logout")
    response.delete_cookie("sid")
    response.delete_cookie("csrf")
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return _public(user)


@router.post("/resend-verification", status_code=202)
def resend_verification(user: User = Depends(current_user), db: Session = Depends(get_db)):
    ratelimit.check(f"resend:{user.id}", 3, 3600)
    if user.email_verified:
        raise HTTPException(409, "Your email is already verified")
    _send_verification(db, db.get(User, user.id))
    audit(db, user.id, "verification_resent")
    return {"ok": True}


@router.post("/forgot", status_code=202)
def forgot(body: Forgot, request: Request, db: Session = Depends(get_db)):
    ratelimit.check(f"forgot:{_ip(request)}", 5, 3600)
    u = db.query(User).filter(User.email == body.email.strip().lower()).first()
    if u:  # same response either way: no account enumeration
        tok = _issue(db, u, "reset", 1)
        link = f"{get_settings().app_url}/reset?token={tok}"
        send_system_mail(u.email, "Reset your ReferralOS password", f"Open this link to choose a new password:\n{link}\n\nReset token: {tok}")
        audit(db, u.id, "password_reset_requested")
    return {"ok": True}


@router.post("/reset")
def reset(body: Reset, db: Session = Depends(get_db)):
    check_password_policy(body.password)
    t = db.query(EmailToken).filter(EmailToken.token_hash == sha(body.token), EmailToken.kind == "reset").first()
    if not t or t.used or t.expires_at < utcnow():
        raise HTTPException(400, "Invalid or expired token")
    t.used = True
    db.get(User, t.user_id).password_hash = hash_password(body.password)
    db.query(AuthSession).filter(AuthSession.user_id == t.user_id).delete()  # log out everywhere
    audit(db, t.user_id, "password_reset")
    return {"ok": True}
