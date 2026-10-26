"""Loads the user's context, scores every LinkedIn connection, assigns ranks/tiers and stores rows (task: score_contacts)."""
from datetime import date

from sqlalchemy.orm import Session

from ..models.contacts import Company, Contact
from ..models.core import UserSetting
from ..models.profile import ProfileItem
from ..models.scoring import ContactScore
from ..tasks import handler
from . import classify, scoring
from .companies import company_key


def get_config(db: Session) -> dict:
    s = db.query(UserSetting).filter(UserSetting.key == "scoring.config").first()
    cfg = {**scoring.DEFAULT_CONFIG, **(s.value if s else {})}
    cfg["weights"] = scoring.normalize_weights(cfg["weights"])
    return cfg


def user_context(db: Session) -> dict:
    items = db.query(ProfileItem).filter(ProfileItem.status == "active").all()
    prefs = next((i.data for i in items if i.section == "preference"), {})
    keys = lambda names: {company_key(n) for n in names or [] if company_key(n)}  # noqa: E731
    text = " ".join(prefs.get("target_roles", []) + [i.data.get("name", "") for i in items if i.section == "skill"]
                    + [s for i in items if i.section == "project" for s in i.data.get("stack", [])]
                    + [i.data.get("title") or "" for i in items if i.section == "experience"])
    doms = classify.domain_tags(text)
    return {"target_company_keys": sorted(keys(prefs.get("target_companies"))), "excluded_company_keys": sorted(keys(prefs.get("excluded_companies"))),
            "prior_employer_keys": sorted(keys([i.data.get("organization") for i in items if i.section == "experience"])),
            "user_domains": sorted(doms), "has_targets": bool(prefs.get("target_roles") or doms)}


def contact_input(c: Contact, name: str | None, user: dict, today: date) -> dict:
    cl = classify.classify(c.position)
    return {"position": c.position, "company_name": name or c.company_raw, "company_key": company_key(name or c.company_raw),
            "role_category": cl["role_category"], "role_keyword": cl["role_keyword"], "seniority": cl["seniority"],
            "seniority_keyword": cl["seniority_keyword"], "domains": cl["domains"], "connected_on": c.connected_on,
            "has_url": bool(c.linkedin_url), "has_email": bool(c.email), "employment_verified": c.employment_verified_at is not None,
            "user": {**user, "target_company_keys": set(user["target_company_keys"]), "excluded_company_keys": set(user["excluded_company_keys"]),
                     "prior_employer_keys": set(user["prior_employer_keys"])}, "today": today, "open_roles": None}


def jsonable(inp: dict) -> dict:
    """Inputs as stored for reproducibility (dates as ISO, sets as sorted lists)."""
    out = {k: v for k, v in inp.items() if k not in ("user", "today", "connected_on")}
    out["connected_on"] = inp["connected_on"].isoformat() if inp["connected_on"] else None
    out["today"] = inp["today"].isoformat()
    out["user"] = {k: sorted(v) if isinstance(v, set) else v for k, v in inp["user"].items()}
    return out


def from_jsonable(d: dict) -> dict:
    out = dict(d)
    out["connected_on"] = date.fromisoformat(d["connected_on"]) if d["connected_on"] else None
    out["today"] = date.fromisoformat(d["today"])
    u = dict(d["user"])
    for k in ("target_company_keys", "excluded_company_keys", "prior_employer_keys"):
        u[k] = set(u[k])
    out["user"] = u
    return out


@handler("score_contacts")
def score_contacts(ctx):
    db = ctx.db
    cfg, user, today = get_config(db), user_context(db), date.today()
    names = {c.id: c.name for c in db.query(Company.id, Company.name).all()}
    rows = []
    for c in db.query(Contact).all():
        inp = contact_input(c, names.get(c.company_id), user, today)
        res = scoring.score(inp, cfg)
        c.role_category, c.seniority = inp["role_category"], inp["seniority"]
        c.employment_status = "verified" if c.employment_verified_at else res["employment_status"]  # only the user can verify
        rows.append({"id": c.id, "name_norm": c.name_norm, "connected_on": c.connected_on, "total": res["total"],
                     "confidence": res["confidence"]["score"], "excluded": res["excluded"], "res": res, "inp": inp})
    ranked = scoring.assign_tiers(rows, cfg["tiers"])
    db.query(ContactScore).delete()
    for r in ranked:
        db.add(ContactScore(contact_id=r["id"], total=r["total"], confidence=r["confidence"], rank=r["rank"], tier=r["tier"],
                            excluded=r["excluded"], components=r["res"]["components"], confidence_parts=r["res"]["confidence"],
                            inputs=jsonable(r["inp"]), scoring_version=scoring.SCORING_VERSION,
                            config_snapshot={**cfg, "weights": dict(cfg["weights"])}))
    return {"scored": len(ranked)}
