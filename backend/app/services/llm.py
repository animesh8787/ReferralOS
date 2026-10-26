"""Pluggable LLM interface. The default is NoLLM: every feature works deterministically without any model.

An LLM may only PROPOSE a rewording of one existing resume bullet. The proposal is accepted only if it passes
tailoring.validate.check_rewrite (no new technologies, numbers or names); otherwise the original stands. Output is never trusted as fact.

Privacy and cost controls (spec 2.6):
- the user supplies their own API key; it is stored envelope-encrypted and is never returned by the API;
- calling a model needs the user's `llm` consent, a configured key, and remaining monthly budget; the call stops when the cap is hit;
- only the bullet text and the job's skill names are sent; emails, phone numbers and URLs are stripped first;
- every call logs metadata only (tokens, estimated cost), never prompt or output text.

STATUS: AnthropicLLM is verified only against httpx.MockTransport (request shape, budget stop, redaction). Prices are rough estimates
for budgeting, not billing.
"""
import re
from datetime import datetime
from typing import Protocol

import httpx
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import crypto
from ..models.core import UserSetting
from ..models.llm import LLMUsage
from ..util import utcnow

MODEL = "claude-haiku-5-5"
API = "https://api.anthropic.com/v1/messages"
PRICE_IN, PRICE_OUT = 1.00 / 1_000_000, 5.00 / 1_000_000  # USD per token: an ESTIMATE used only for the budget guard
PII = [re.compile(p) for p in (r"[\w.+-]+@[\w-]+\.[\w.-]+", r"https?://\S+|www\.\S+", r"\+?\d[\d ()-]{8,}\d")]


class LLMProvider(Protocol):
    name: str

    def rewrite_bullet(self, bullet: str, jd_terms: list[str]) -> str | None: ...


class NoLLM:
    name = "none"

    def rewrite_bullet(self, bullet: str, jd_terms: list[str]) -> str | None:
        return None


def strip_pii(text: str) -> str:
    for rx in PII:
        text = rx.sub("[removed]", text)
    return text


def est_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def month_start(now: datetime | None = None) -> datetime:
    n = now or utcnow()
    return n.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def spent(db: Session, now: datetime | None = None) -> float:
    return float(db.query(func.coalesce(func.sum(LLMUsage.est_cost_usd), 0.0)).filter(LLMUsage.created_at >= month_start(now)).scalar() or 0.0)


class AnthropicLLM:
    name = "anthropic"

    def __init__(self, db: Session, api_key: str, budget_usd: float, client: httpx.Client):
        self.db, self.key, self.budget, self.c = db, api_key, budget_usd, client

    def rewrite_bullet(self, bullet: str, jd_terms: list[str]) -> str | None:
        clean, terms = strip_pii(bullet), ", ".join(jd_terms[:12])
        prompt = ("Reword this resume bullet to be clearer and more concise. Keep every fact. Do NOT add any technology, number, name or claim that is not "
                  f"already in it. Return only the bullet.\nRelevant skills (use only if the bullet already shows them): {terms}\nBullet: {clean}")
        est_in, est_out = est_tokens(prompt), est_tokens(bullet) + 20
        est = est_in * PRICE_IN + est_out * PRICE_OUT
        if spent(self.db) + est > self.budget:
            return None  # hard stop at the monthly cap
        try:
            r = self.c.post(API, headers={"x-api-key": self.key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                            json={"model": MODEL, "max_tokens": 200, "messages": [{"role": "user", "content": prompt}]})
            r.raise_for_status()
            j = r.json()
            text = j["content"][0]["text"].strip()
            u = j.get("usage", {})
            tin, tout = int(u.get("input_tokens", est_in)), int(u.get("output_tokens", est_out))
        except (httpx.HTTPError, KeyError, IndexError, ValueError):
            return None
        self.db.add(LLMUsage(kind="bullet_rewrite", model=MODEL, input_tokens=tin, output_tokens=tout, est_cost_usd=tin * PRICE_IN + tout * PRICE_OUT))
        self.db.flush()
        return text or None


# ---------------------------------------------------------------- per-user configuration
KEY, SECRET = "llm.config", "llm.key"


def get_config(db: Session) -> dict:
    row = db.query(UserSetting).filter(UserSetting.key == KEY).first()
    secret = db.query(UserSetting).filter(UserSetting.key == SECRET).first()
    cfg = {"provider": "none", "monthly_budget_usd": 5.0, **(row.value if row else {})}
    return {**cfg, "key_set": bool(secret and secret.value.get("enc"))}


def save_config(db: Session, provider: str, budget: float | None, api_key: str | None) -> None:
    row = db.query(UserSetting).filter(UserSetting.key == KEY).first()
    val = {"provider": provider, "monthly_budget_usd": budget if budget is not None else (row.value.get("monthly_budget_usd", 5.0) if row else 5.0)}
    if row:
        row.value = val
    else:
        db.add(UserSetting(key=KEY, value=val))
    if api_key:
        s = db.query(UserSetting).filter(UserSetting.key == SECRET).first()
        enc = {"enc": crypto.encrypt(api_key)}
        if s:
            s.value = enc
        else:
            db.add(UserSetting(key=SECRET, value=enc))


def clear_key(db: Session) -> None:
    db.query(UserSetting).filter(UserSetting.key == SECRET).delete()


def get_provider(db: Session | None = None) -> LLMProvider:
    """NoLLM unless the user chose a provider, gave a key, and consented. Never raises."""
    if db is None:
        return NoLLM()
    from ..adapters.http import make_client
    from . import consent
    cfg = get_config(db)
    if cfg["provider"] != "anthropic" or not cfg["key_set"] or not consent.get(db, "llm"):
        return NoLLM()
    secret = db.query(UserSetting).filter(UserSetting.key == SECRET).first()
    try:
        return AnthropicLLM(db, crypto.decrypt(secret.value["enc"]), float(cfg["monthly_budget_usd"]), make_client())
    except Exception:  # noqa: BLE001
        return NoLLM()
