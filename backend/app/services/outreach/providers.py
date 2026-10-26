"""Email providers behind one interface. A provider NEVER raises from send(): it reports ok / hard failure / ambiguous.

  ok         the provider accepted the message (we have its id)
  hard       it definitely was not sent (auth error, invalid request, could not connect): safe for the user to retry manually
  ambiguous  we cannot tell (timeout after the request went out, 5xx, unreadable reply): marked DELIVERY_UNCONFIRMED and NEVER auto-resent

Providers: MockProvider (offline, scriptable, used by tests and mock mode), DryRunProvider (never delivers), GmailProvider
(real Gmail API, official OAuth). GmailProvider has only been exercised against httpx.MockTransport, never the live service.
"""
import base64
import email.utils
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from email.message import EmailMessage

import httpx

from ... import crypto
from ...util import utcnow

MAX_ATTACH = 2 * 1024 * 1024


@dataclass
class SendResult:
    ok: bool
    kind: str | None = None  # None | "hard" | "ambiguous"
    provider_message_id: str | None = None
    thread_id: str | None = None
    detail: str = ""


def build_mime(sender_name: str, sender_email: str, to: str, subject: str, body: str, attachment: tuple[str, bytes] | None = None) -> tuple[bytes, str]:
    """-> (rfc822 bytes, Message-ID). From is always the user's own address; the Message-ID lets us find the message later."""
    msg = EmailMessage()
    msg["From"] = email.utils.formataddr((sender_name, sender_email))
    msg["To"] = to
    msg["Subject"] = subject
    msg["Date"] = email.utils.formatdate()
    mid = email.utils.make_msgid(domain=sender_email.rsplit("@", 1)[-1])
    msg["Message-ID"] = mid
    msg.set_content(body)
    if attachment:
        msg.add_attachment(attachment[1], maintype="application", subtype="pdf", filename=attachment[0])
    return bytes(msg), mid


class Provider:
    name = "base"

    def send(self, user_id: str, mime: bytes, rfc_id: str, to: str) -> SendResult: ...
    def find_sent(self, user_id: str, rfc_id: str) -> dict | None: ...
    def fetch_replies(self, user_id: str, thread_id: str | None, rfc_id: str | None) -> list[dict]: ...


# ---------------------------------------------------------------- mock (offline, scriptable)
@dataclass
class _MockState:
    sent: list[dict] = field(default_factory=list)
    mode: str = "ok"  # ok | hard_fail | timeout_delivered | timeout_lost | server_error_delivered
    replies: dict[str, list[dict]] = field(default_factory=dict)  # rfc_id -> replies


MOCK: dict[str, _MockState] = {}


def mock_state(user_id: str) -> _MockState:
    return MOCK.setdefault(user_id, _MockState())


def reset_mock() -> None:
    MOCK.clear()


class MockProvider(Provider):
    name = "mock"

    def send(self, user_id, mime, rfc_id, to):
        st = mock_state(user_id)
        rec = {"id": f"mock-{len(st.sent) + 1}", "thread": f"thr-{len(st.sent) + 1}", "rfc_id": rfc_id, "to": to, "mime": mime, "at": utcnow()}
        if st.mode == "hard_fail":
            return SendResult(False, "hard", detail="mock: 400 invalid recipient")
        if st.mode in ("timeout_delivered", "server_error_delivered"):
            st.sent.append(rec)  # the provider DID deliver, but we never learn it
            return SendResult(False, "ambiguous", detail="mock: response lost")
        if st.mode == "timeout_lost":
            return SendResult(False, "ambiguous", detail="mock: timeout, nothing delivered")
        st.sent.append(rec)
        return SendResult(True, provider_message_id=rec["id"], thread_id=rec["thread"])

    def find_sent(self, user_id, rfc_id):
        r = next((x for x in mock_state(user_id).sent if x["rfc_id"] == rfc_id), None)
        return {"id": r["id"], "thread": r["thread"], "at": r["at"]} if r else None

    def fetch_replies(self, user_id, thread_id, rfc_id):
        return list(mock_state(user_id).replies.get(rfc_id or "", []))


class DryRunProvider(Provider):
    """Executes the whole pipeline (including MIME building) but delivers nothing."""
    name = "dry_run"

    def send(self, user_id, mime, rfc_id, to):
        return SendResult(True, provider_message_id="dry-run", thread_id=None, detail=f"would send {len(mime)} bytes to {to}")

    def find_sent(self, user_id, rfc_id):
        return None

    def fetch_replies(self, user_id, thread_id, rfc_id):
        return []


# ---------------------------------------------------------------- Gmail (official API; mock-verified only)
GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"
TOKEN_URL = "https://oauth2.googleapis.com/token"


class GmailProvider(Provider):
    name = "gmail"

    def __init__(self, token_row, client: httpx.Client, client_id: str = "", client_secret: str = ""):
        self.t, self.c, self.cid, self.secret = token_row, client, client_id, client_secret

    def _access(self) -> str:
        if self.t.expires_at and self.t.expires_at - utcnow() < timedelta(seconds=60) and self.t.encrypted_refresh:
            r = self.c.post(TOKEN_URL, data={"grant_type": "refresh_token", "refresh_token": crypto.decrypt(self.t.encrypted_refresh), "client_id": self.cid, "client_secret": self.secret})
            r.raise_for_status()
            j = r.json()
            self.t.encrypted_access = crypto.encrypt(j["access_token"])
            self.t.expires_at = utcnow() + timedelta(seconds=int(j.get("expires_in", 3600)))
        return crypto.decrypt(self.t.encrypted_access)

    def send(self, user_id, mime, rfc_id, to):
        try:
            tok = self._access()
        except httpx.HTTPError as e:
            return SendResult(False, "hard", detail=f"could not refresh the Gmail token ({type(e).__name__}); reconnect Gmail")
        raw = base64.urlsafe_b64encode(mime).decode()
        try:
            r = self.c.post(f"{GMAIL}/messages/send", headers={"Authorization": f"Bearer {tok}"}, json={"raw": raw})
        except (httpx.ConnectError, httpx.ConnectTimeout):
            return SendResult(False, "hard", detail="could not connect to Gmail; nothing was sent")
        except httpx.HTTPError as e:  # timeout / reset after the request left: we cannot know
            return SendResult(False, "ambiguous", detail=f"no response from Gmail ({type(e).__name__})")
        if r.status_code == 200:
            try:
                j = r.json()
                return SendResult(True, provider_message_id=j["id"], thread_id=j.get("threadId"))
            except (ValueError, KeyError):
                return SendResult(False, "ambiguous", detail="Gmail answered 200 but the reply was unreadable")
        if r.status_code in (400, 401, 403, 404) and r.status_code != 429:
            reason = r.text[:160].replace("\n", " ")
            if r.status_code == 403 and "rateLimit" in r.text:
                return SendResult(False, "hard", detail="Gmail rate limit reached; nothing was sent. Try later.")
            return SendResult(False, "hard", detail=f"Gmail rejected the request ({r.status_code}): {crypto.redact(reason)}")
        return SendResult(False, "ambiguous", detail=f"Gmail returned {r.status_code}; the message may or may not have been sent")

    def find_sent(self, user_id, rfc_id):
        r = self.c.get(f"{GMAIL}/messages", headers={"Authorization": f"Bearer {self._access()}"}, params={"q": f"rfc822msgid:{rfc_id.strip('<>')} in:sent", "maxResults": 1})
        r.raise_for_status()
        m = (r.json().get("messages") or [None])[0]
        return {"id": m["id"], "thread": m.get("threadId"), "at": None} if m else None

    def fetch_replies(self, user_id, thread_id, rfc_id):
        if not thread_id:
            return []
        r = self.c.get(f"{GMAIL}/threads/{thread_id}", headers={"Authorization": f"Bearer {self._access()}"}, params={"format": "metadata"})
        r.raise_for_status()
        out = []
        for m in r.json().get("messages", [])[1:]:
            h = {x["name"].lower(): x["value"] for x in m.get("payload", {}).get("headers", [])}
            out.append({"id": m["id"], "from": h.get("from", ""), "subject": h.get("subject", ""), "body": m.get("snippet", ""), "at": None})
        return out
