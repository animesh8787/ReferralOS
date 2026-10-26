"""Outreach settings. Conservative defaults; user limits are clamped to hard maximums (below Gmail's published limits)
and raising a limit above the default is reported as a warning in the response."""
from sqlalchemy.orm import Session

from ...config import get_settings
from ...models.core import UserSetting
from ...util import utcnow

KEY = "outreach.settings"
DEFAULT_DAILY, DEFAULT_COMPANY, DEFAULT_INTRO = 20, 5, 5
MODES = ("MANUAL_REVIEW", "AUTHORISED_INTEGRATION", "DRY_RUN")
DEFAULTS = {
    "sender_name": "", "sender_email": "", "delivery_mode": "MANUAL_REVIEW", "daily_limit": DEFAULT_DAILY, "per_company_daily": DEFAULT_COMPANY,
    "intro_daily": DEFAULT_INTRO, "pacing_seconds": [30, 120], "max_followups": 2, "followup_spacing_business_days": 5, "global_pause": False,
    "domain_blocklist": [], "excluded_company_ids": [], "reply_tracking": False, "attach_resume_default": True, "tone": "conversational",
    "length": "short", "lawful_use_ack": None, "region_acks": {},
}


def hard_max() -> tuple[int, int]:
    s = get_settings()
    return s.hard_max_daily_emails, s.hard_max_per_company_daily


def get(db: Session) -> dict:
    row = db.query(UserSetting).filter(UserSetting.key == KEY).first()
    return {**DEFAULTS, **(row.value if row else {})}


def save(db: Session, cfg: dict) -> None:
    row = db.query(UserSetting).filter(UserSetting.key == KEY).first()
    if row:
        row.value = cfg
    else:
        db.add(UserSetting(key=KEY, value=cfg))


def apply_update(cfg: dict, patch: dict) -> tuple[dict, list[str], list[str]]:
    """-> (new cfg, warnings, errors). Never exceeds the hard maximums."""
    out, warn, err = dict(cfg), [], []
    dmax, cmax = hard_max()
    for k, v in patch.items():
        if k not in DEFAULTS or k in ("lawful_use_ack", "region_acks"):  # acknowledgements have their own endpoint
            err.append(f"Unknown or protected setting: {k}")
            continue
        if k in ("daily_limit", "per_company_daily", "intro_daily"):
            if not isinstance(v, int) or v < 0:
                err.append(f"{k} must be a whole number >= 0")
                continue
            cap = cmax if k == "per_company_daily" else dmax
            if v > cap:
                warn.append(f"{k} was capped at the hard maximum of {cap} (kept under Gmail's published sending limits).")
                v = cap
            default = {"daily_limit": DEFAULT_DAILY, "per_company_daily": DEFAULT_COMPANY, "intro_daily": DEFAULT_INTRO}[k]
            if v > default:
                warn.append(f"{k} is now {v}, above the recommended {default}. Higher volume raises the chance of spam filtering and annoyed recipients.")
        elif k == "delivery_mode" and v not in MODES:
            err.append("delivery_mode must be one of " + ", ".join(MODES))
            continue
        elif k == "pacing_seconds":
            if not (isinstance(v, list) and len(v) == 2 and all(isinstance(x, int) and 0 <= x <= 3600 for x in v) and v[0] <= v[1]):
                err.append("pacing_seconds must be [min, max] seconds, 0-3600")
                continue
        elif k in ("max_followups",) and not (isinstance(v, int) and 0 <= v <= 3):
            err.append("max_followups must be 0-3")
            continue
        elif k == "followup_spacing_business_days" and not (isinstance(v, int) and 3 <= v <= 30):
            err.append("followup_spacing_business_days must be 3-30")
            continue
        elif k in ("tone",) and v not in ("formal", "conversational"):
            err.append("tone must be formal or conversational")
            continue
        elif k == "length" and v not in ("short", "medium"):
            err.append("length must be short or medium")
            continue
        elif k == "domain_blocklist":
            v = sorted({str(d).strip().lower().lstrip("@") for d in v if str(d).strip()})
        elif k in ("sender_name", "sender_email"):
            v = str(v).strip()[:200]
        out[k] = v
    out["intro_daily"] = min(out["intro_daily"], out["daily_limit"])
    return out, warn, err


def acknowledge(cfg: dict, kind: str) -> dict:
    out = dict(cfg)
    if kind == "lawful_use":
        out["lawful_use_ack"] = utcnow().isoformat()
    elif kind.startswith("region:"):
        out["region_acks"] = {**out["region_acks"], kind.split(":", 1)[1].upper(): utcnow().isoformat()}
    else:
        raise ValueError("Unknown acknowledgement")
    return out
