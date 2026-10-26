"""Envelope encryption: per-record random DEK (AES-GCM) wrapped by a KEK from env or data/.kek."""
import base64
import logging
import os
import re

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .config import get_settings


def _kek() -> bytes:
    s = get_settings()
    if s.app_kek:
        return base64.b64decode(s.app_kek)
    p = s.data_dir / ".kek"  # shortcut: file-based dev key; use env/KMS in production
    if not p.exists():
        s.data_dir.mkdir(parents=True, exist_ok=True)
        p.write_bytes(base64.b64encode(os.urandom(32)))
    return base64.b64decode(p.read_bytes())


def _b(x: bytes) -> str:
    return base64.urlsafe_b64encode(x).decode()


def encrypt(plaintext: str) -> str:
    dek, n1, n2 = os.urandom(32), os.urandom(12), os.urandom(12)
    ct = AESGCM(dek).encrypt(n1, plaintext.encode(), None)
    wrapped = AESGCM(_kek()).encrypt(n2, dek, None)
    return "v1." + ".".join(_b(x) for x in (n2, wrapped, n1, ct))


def decrypt(blob: str) -> str:
    v, *parts = blob.split(".")
    if v != "v1" or len(parts) != 4:
        raise ValueError("bad ciphertext")
    n2, wrapped, n1, ct = (base64.urlsafe_b64decode(p) for p in parts)
    dek = AESGCM(_kek()).decrypt(n2, wrapped, None)
    return AESGCM(dek).decrypt(n1, ct, None).decode()


_PATTERNS = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[email]"),
    (re.compile(r"(?i)\b(bearer|token|secret|password|api[_-]?key)\b([\"'=: ]+)[\w\-./+=]{6,}"), r"\1\2[redacted]"),
    (re.compile(r"\+?\d[\d ()-]{8,}\d"), "[phone]"),
]


def redact(text: str) -> str:
    for rx, rep in _PATTERNS:
        text = rx.sub(rep, text)
    return text


class RedactFilter(logging.Filter):
    """No personal content or secrets in logs."""

    def filter(self, record):
        record.msg = redact(record.getMessage())
        record.args = ()
        return True
