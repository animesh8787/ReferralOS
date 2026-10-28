"""System mailer (verification / reset). With RESEND_API_KEY set it sends through Resend; without one (or if Resend fails) the mail is
written as JSON to data/outbox so a local setup still works.

shortcut: Resend only; onboarding@resend.dev delivers to the Resend account owner only. Verify your own domain in Resend and set
MAIL_FROM before inviting other people.
"""
import json
import logging
import time

import httpx

from ..config import get_settings
from ..crypto import redact
from ..util import new_id

log = logging.getLogger("mailer")


def _outbox(to: str, subject: str, body: str) -> None:
    out = get_settings().data_dir / "outbox"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{time.time_ns()}-{new_id()[:8]}.json").write_text(json.dumps({"to": to, "subject": subject, "body": body}), encoding="utf-8")


def send_system_mail(to: str, subject: str, body: str) -> None:
    s = get_settings()
    if not s.resend_api_key:
        return _outbox(to, subject, body)
    try:
        r = httpx.post("https://api.resend.com/emails", timeout=10, headers={"Authorization": f"Bearer {s.resend_api_key}"},
                       json={"from": s.mail_from, "to": [to], "subject": subject, "text": body})
        r.raise_for_status()
    except Exception as e:  # noqa: BLE001  a mail problem must not break sign-up; the outbox copy is the fallback
        log.warning("Resend failed (%s); wrote the mail to data/outbox instead", redact(str(e))[:200])
        _outbox(to, subject, body)
