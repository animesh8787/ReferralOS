"""System mailer (verification / reset). Dev adapter writes JSON files to data/outbox; nothing leaves the machine.

shortcut: no real SMTP for system mail yet; add an SMTP adapter here before public deployment.
"""
import json
import time

from ..config import get_settings
from ..util import new_id


def send_system_mail(to: str, subject: str, body: str) -> None:
    out = get_settings().data_dir / "outbox"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{time.time_ns()}-{new_id()[:8]}.json").write_text(
        json.dumps({"to": to, "subject": subject, "body": body}), encoding="utf-8")
