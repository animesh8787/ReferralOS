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

def _password_only():
    """Local password auth is off once Firebase is configured, so there is exactly one way in."""
    if get_settings().firebase_project_id:
        raise HTTPException(404, "Not found")


router = APIRouter(prefix="/api/auth", tags=["auth"])
PW = [Depends(_password_only)]


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


@router.post("/signup", status_code=201, dependencies=PW)
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


@router.post("/verify", dependencies=PW)
def verify(body: TokenIn, db: Session = Depends(get_db)):
    t = db.query(EmailToken).filter(EmailToken.token_hash == sha(body.token), EmailToken.kind == "verify").first()
    if not t or t.used or t.expires_at < utcnow():
        raise HTTPException(400, "Invalid or expired token")
    t.used = True
    db.get(User, t.user_id).email_verified = True
    audit(db, t.user_id, "email_verified")
    return {"ok": True}


@router.post("/login", dependencies=PW)
def login(body: Login, request: Request, response: Response, db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    ratelimit.check(f"login-ip:{_ip(request)}", 20, 300)
    ratelimit.check(f"login-acct:{email}", 5, 300)
    u = db.query(User).filter(User.email == email).first()
    if not u or not u.password_hash or not verify_password(u.password_hash, body.password):
        audit(db, u.id if u else None, "login_failed")
        db.commit()  # keep the audit row even though we raise
        raise HTTPException(401, "Invalid email or password")
    raw, csrf = create_session(db, u)
    audit(db, u.id, "login")
    set_auth_cookies(response, raw, csrf)
    return _public(u)


class FirebaseIn(BaseModel):
    id_token: str


def _verify_firebase(token: str) -> dict:
    """Google's own verifier checks signature, expiry and audience; the issuer is checked here. Tests patch this function."""
    from google.auth.transport import requests as greq
    from google.oauth2 import id_token
    pid = get_settings().firebase_project_id
    claims = id_token.verify_firebase_token(token, greq.Request(), audience=pid)
    if not claims or claims.get("iss") != f"https://securetoken.google.com/{pid}":
        raise ValueError("wrong issuer")
    return claims


@router.post("/firebase")
def firebase_login(body: FirebaseIn, request: Request, response: Response, db: Session = Depends(get_db)):
    """Exchange a Firebase ID token (Google or email/password sign-in) for this app's own session cookie."""
    if not get_settings().firebase_project_id:
        raise HTTPException(404, "Not found")
    ratelimit.check(f"firebase:{_ip(request)}", 30, 300)
    try:
        claims = _verify_firebase(body.id_token)
    except Exception:  # noqa: BLE001  any verification failure is a plain 401; details would help an attacker
        raise HTTPException(401, "Sign-in could not be verified")
    uid, email, verified = claims.get("user_id") or claims.get("sub"), (claims.get("email") or "").strip().lower(), bool(claims.get("email_verified"))
    if not uid or not email:
        raise HTTPException(401, "Sign-in could not be verified")
    u = db.query(User).filter(User.firebase_uid == uid).first()
    if u is None:
        u = db.query(User).filter(User.email == email).first()
        if u is not None and not verified:  # linking by email needs a verified address, or anyone could claim someone else's account
            raise HTTPException(403, "Verify your email address with Firebase first, then sign in again")
        if u is None:
            u = User(email=email, firebase_uid=uid, email_verified=verified, display_name=(claims.get("name") or "")[:200])
            db.add(u)
            db.flush()
            audit(db, u.id, "signup", via="firebase")
        else:
            u.firebase_uid = uid
    if verified:
        u.email_verified = True
    raw, csrf = create_session(db, u)
    audit(db, u.id, "login", via="firebase")
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


@router.post("/resend-verification", status_code=202, dependencies=PW)
def resend_verification(user: User = Depends(current_user), db: Session = Depends(get_db)):
    ratelimit.check(f"resend:{user.id}", 3, 3600)
    if user.email_verified:
        raise HTTPException(409, "Your email is already verified")
    _send_verification(db, db.get(User, user.id))
    audit(db, user.id, "verification_resent")
    return {"ok": True}


@router.post("/forgot", status_code=202, dependencies=PW)
def forgot(body: Forgot, request: Request, db: Session = Depends(get_db)):
    ratelimit.check(f"forgot:{_ip(request)}", 5, 3600)
    u = db.query(User).filter(User.email == body.email.strip().lower()).first()
    if u:  # same response either way: no account enumeration
        tok = _issue(db, u, "reset", 1)
        link = f"{get_settings().app_url}/reset?token={tok}"
        send_system_mail(u.email, "Reset your ReferralOS password", f"Open this link to choose a new password:\n{link}\n\nReset token: {tok}")
        audit(db, u.id, "password_reset_requested")
    return {"ok": True}


@router.post("/reset", dependencies=PW)
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
