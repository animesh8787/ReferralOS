"""Job-Specific Referral Contact Score (0-100) and per-job recommendations. Pure.

Employment is INFERRED from connection age (LinkedIn exports hold no employment dates); it is never reported as verified
unless the user verified it. Company membership, seniority or a public profile is never treated as proof that someone can
submit a referral, and the explanations say so.
"""
from datetime import date

from . import scoring

VERSION = "job-contact/1"
COMPONENTS = ["employment", "role", "domain", "seniority", "relationship", "confidence"]
DEFAULT_WEIGHTS = {"employment": 25, "role": 25, "domain": 20, "seniority": 10, "relationship": 10, "confidence": 10}
EMPLOYMENT = {"verified": 1.0, "likely_current": 0.6, "possibly_outdated": 0.25}
LABEL = {"verified": "verified by you", "likely_current": "likely current (inferred from a recent connection)", "possibly_outdated": "possibly outdated (old connection)",
         "unknown": "unknown"}
ROLE = {"recruiter": 0.8, "eng_manager": 0.9, "engineer": 0.8, "leadership": 0.5, "product": 0.3, "other": 0.15}


def normalize_weights(w: dict) -> dict:
    if set(w) != set(COMPONENTS) or any((not isinstance(v, (int, float))) or v < 0 for v in w.values()) or sum(w.values()) <= 0:
        raise ValueError("weights need all six components, each >= 0, with a positive total")
    t = sum(w.values())
    out = {k: round(w[k] * 100 / t, 4) for k in COMPONENTS}
    out[COMPONENTS[0]] = round(out[COMPONENTS[0]] + 100 - sum(out.values()), 4)
    return out


def _c(value, why):
    return {"value": None if value is None else round(value, 3), "known": value is not None, "explanation": why}


def score(job: dict, ct: dict, today: date, cfg: dict | None = None) -> dict:
    """job: title, domains(list); ct: role_category, role_position, seniority, domains, connected_on, employment_status,
    employment_verified, general_confidence (0-100), prior_employer (bool)."""
    cfg = cfg or {}
    w = normalize_weights(cfg.get("weights", DEFAULT_WEIGHTS))
    c = {}
    st = "verified" if ct["employment_verified"] else ct["employment_status"]
    c["employment"] = _c(EMPLOYMENT.get(st), f"Employment at this company is {LABEL.get(st, 'unknown')}. Not proof they still work there.")
    cat = ct["role_category"]
    jd, cd = set(job["domains"]), set(ct["domains"])
    if cat == "unknown":
        c["role"] = _c(None, "Their title is missing, so their role is unknown.")
    else:
        base = ROLE.get(cat, 0.15)
        if cat == "recruiter" and "technical" in (ct.get("role_position") or "").lower():
            base = 1.0
        if cat == "engineer" and jd & cd:
            base = 1.0
        c["role"] = _c(base, f"Title '{ct.get('role_position')}' reads as {cat.replace('_', ' ')}. Role helps but does not prove they can submit referrals.")
    c["domain"] = _c(len(jd & cd) / len(jd) if jd and cd else None,
                     f"Job domains {', '.join(sorted(jd))}; theirs {', '.join(sorted(cd))}; shared: {', '.join(sorted(jd & cd)) or 'none'}." if jd and cd else "Job or contact domain is not stated.")
    sv = scoring.SENIORITY.get(ct["seniority"])
    c["seniority"] = _c(sv, f"Seniority read as {ct['seniority']}. Seniority is not referral ability." if sv is not None else "Seniority not stated.")
    parts, why = [], []
    if ct["connected_on"]:
        yrs = (today - ct["connected_on"]).days / 365.25
        parts.append(1.0 if yrs <= 1 else 0.7 if yrs <= 3 else 0.5)
        why.append(f"Connected {ct['connected_on'].isoformat()}.")
    if ct.get("prior_employer"):
        parts.append(1.0)
        why.append("You list this company as a past employer.")
    c["relationship"] = _c(max(parts) if parts else None, " ".join(why) or "No connection date or shared history on file.")
    gc = ct.get("general_confidence")
    c["confidence"] = _c(gc / 100 if gc is not None else None, f"Overall support for the information about this contact: {gc:.0f}/100." if gc is not None else "No general score yet.")
    total = scoring.combine(c, w, cfg.get("missing_policy", "neutral"))
    return {"version": VERSION, "total": total, "components": c, "employment_label": st,
            "note": "Ranks who to ask first. It does not predict whether anyone will, or can, refer you."}


def recommend(scored: list[dict], max_contacts: int = 3) -> list[dict]:
    """scored: [{contact_id, total, ...}] for ONE job. Returns the top few with recommended=True and rank; never blanket-recommends."""
    ordered = sorted(scored, key=lambda r: (-r["total"], -(r.get("general_confidence") or 0), r["contact_id"]))
    return [{**r, "rank_in_job": i + 1, "recommended": i < max_contacts and not r.get("excluded") and r["total"] > 0} for i, r in enumerate(ordered)]


def consolidate(by_job: dict[str, list[dict]]) -> dict[str, list[str]]:
    """job_id -> recommended rows  =>  contact_id -> [job_ids] so one person fitting several jobs gets ONE outreach strategy."""
    out: dict[str, list[str]] = {}
    for jid, rows in by_job.items():
        for r in rows:
            if r["recommended"]:
                out.setdefault(r["contact_id"], []).append(jid)
    return out
