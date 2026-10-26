"""General Referral Priority Score (0-100) + a separate confidence score. Pure and reproducible:
score(inputs, config) depends only on its arguments (today is an input), so stored rows can be re-derived.

Unknown is never negative: a component with no usable data is 'unknown' and handled by the missing-data policy
  neutral : counts as 0.5 of its weight, and lowers confidence
  exclude : removed, remaining weights renormalised to 100, and lowers confidence
The confidence number describes how well-supported the score is. It is not a probability of getting a referral.
"""
from datetime import date

SCORING_VERSION = "referral-priority/1"
COMPONENTS = ["company_relevance", "referral_capability", "role_relevance", "seniority_context", "approachability", "hiring_relevance"]
DEFAULT_WEIGHTS = {"company_relevance": 25, "referral_capability": 25, "role_relevance": 20, "seniority_context": 10,
                   "approachability": 10, "hiring_relevance": 10}
DEFAULT_CONFIG = {"weights": DEFAULT_WEIGHTS, "missing_policy": "neutral", "tiers": [100, 400, 500], "stale_years": 5}

CAPABILITY = {"engineer": 0.7, "eng_manager": 0.8, "recruiter": 0.6, "leadership": 0.5, "product": 0.5, "other": 0.3}
SENIORITY = {"intern": 0.3, "junior": 0.6, "mid": 0.8, "senior": 0.9, "staff_principal": 0.8, "manager": 0.8, "director_plus": 0.5}
HIRING = {"recruiter": 1.0, "eng_manager": 0.9, "leadership": 0.6, "engineer": 0.5, "product": 0.3, "other": 0.2}
LABEL = {"engineer": "engineer", "eng_manager": "engineering manager", "recruiter": "recruiter / talent", "leadership": "leadership",
         "product": "product / program", "other": "other role"}


def normalize_weights(w: dict) -> dict:
    """Validate and rescale so weights sum to exactly 100. Raises ValueError on bad input."""
    if set(w) != set(COMPONENTS) or any((not isinstance(v, (int, float))) or v < 0 for v in w.values()) or sum(w.values()) <= 0:
        raise ValueError("weights need all six components, each >= 0, with a positive total")
    t = sum(w.values())
    out = {k: round(w[k] * 100 / t, 4) for k in COMPONENTS}
    out[COMPONENTS[0]] = round(out[COMPONENTS[0]] + (100 - sum(out.values())), 4)  # absorb rounding drift
    return out


def employment_status(connected_on: date | None, today: date, stale_years: int) -> str:
    """Inferred from connection age only; never 'verified'. LinkedIn exports carry no employment dates."""
    if not connected_on:
        return "unknown"
    age = (today - connected_on).days / 365.25
    return "likely_current" if age <= 2 else "possibly_outdated" if age >= stale_years else "unknown"


def _comp(value, why, known=True):
    return {"value": value, "known": known and value is not None, "explanation": why}


def score(inp: dict, cfg: dict | None = None) -> dict:
    """inp: role_category, role_keyword, seniority, domains, position, company_key, company_name, connected_on(date|None), has_url,
    has_email, user: {target_company_keys, excluded_company_keys, prior_employer_keys, user_domains, has_targets}, today(date),
    open_roles (int|None, Phase 6), employment_verified (bool)."""
    cfg = cfg or DEFAULT_CONFIG
    w = normalize_weights(cfg["weights"])
    u, today = inp["user"], inp["today"]
    cat, ck = inp["role_category"], inp["company_key"]
    status = employment_status(inp["connected_on"], today, cfg.get("stale_years", 5))
    c: dict[str, dict] = {}

    # company relevance
    if not ck:
        c["company_relevance"] = _comp(None, "No company on this connection.")
    elif ck in u["excluded_company_keys"]:
        c["company_relevance"] = _comp(0.0, f"{inp['company_name']} is on your excluded list.")
    elif ck in u["target_company_keys"]:
        c["company_relevance"] = _comp(1.0, f"{inp['company_name']} is one of your target companies.")
    elif u["target_company_keys"]:
        c["company_relevance"] = _comp(0.2, f"{inp['company_name']} is not on your target company list.")
    else:
        c["company_relevance"] = _comp(None, "You have not set target companies, so company fit is unknown.")

    # potential referral capability (potential only: nobody is assumed able to refer)
    if not ck or cat == "unknown":
        c["referral_capability"] = _comp(None, "Company or role is missing, so referral potential is unknown.")
    else:
        base = CAPABILITY[cat]
        why = f"Title '{inp['position']}' reads as {LABEL[cat]} (matched '{inp['role_keyword']}'); this is potential, not confirmed referral access."
        if status == "possibly_outdated":
            base *= 0.6
            why += f" Connected over {cfg.get('stale_years', 5)} years ago, so the employer may be out of date."
        c["referral_capability"] = _comp(round(base, 3), why)

    # technical / role relevance
    ud, cd = set(u["user_domains"]), set(inp["domains"])
    if cat == "unknown" or not u["has_targets"]:
        c["role_relevance"] = _comp(None, "Needs both their title and your target roles/skills to compare.")
    elif cat in ("engineer", "eng_manager") and cd:
        ov = ud & cd
        c["role_relevance"] = _comp(round(len(ov) / len(cd), 3), f"Their title points to {', '.join(sorted(cd))}; overlap with your profile: {', '.join(sorted(ov)) or 'none'}.")
    elif cat in ("engineer", "eng_manager"):
        c["role_relevance"] = _comp(0.5, "Engineering role without a stated specialty.")
    elif cat == "recruiter":
        tech = "technical" in (inp["position"] or "").lower() or "engineering" in (inp["position"] or "").lower()
        c["role_relevance"] = _comp(0.8 if tech else 0.5, "Technical recruiter." if tech else "Recruiter; technical focus not stated in the title.")
    else:
        c["role_relevance"] = _comp(0.3, f"{LABEL.get(cat, cat).capitalize()}: less directly tied to your target roles.")

    # seniority & organisational context (seniority is not referral ability)
    sv = SENIORITY.get(inp["seniority"])
    c["seniority_context"] = _comp(sv, f"Seniority read as {inp['seniority']}" + (f" (matched '{inp['seniority_keyword']}')." if inp.get("seniority_keyword") else " (inferred from a plain engineering title).")
                                   if sv is not None else "Seniority not stated in the title.")

    # approachability / relationship context (only facts we hold)
    co = inp["connected_on"]
    parts, why = [], []
    if co:
        yrs = (today - co).days / 365.25
        parts.append(1.0 if yrs <= 1 else 0.7 if yrs <= 3 else 0.5)
        why.append(f"Connected {co.isoformat()}.")
    if ck and ck in u["prior_employer_keys"]:
        parts.append(1.0)
        why.append(f"You list {inp['company_name']} as a past employer in your profile.")
    c["approachability"] = _comp(round(max(parts), 3) if parts else None, " ".join(why) or "No connection date or shared history on file.")

    # hiring relevance (open roles from verified jobs arrive in Phase 6)
    hv = HIRING.get(cat)
    if hv is not None and inp.get("open_roles"):
        hv, why = min(1.0, hv + 0.3), f"{LABEL[cat].capitalize()} at a company with {inp['open_roles']} verified open role(s)."
    else:
        why = f"{LABEL.get(cat, 'Role')} involvement in hiring is typical." if hv is not None else "Role unknown."
    c["hiring_relevance"] = _comp(hv, why)

    total = combine(c, w, cfg.get("missing_policy", "neutral"))
    if inp["user"]["excluded_company_keys"] and ck in inp["user"]["excluded_company_keys"]:
        total = 0.0

    return {"version": SCORING_VERSION, "total": total, "components": c, "employment_status": status,
            "excluded": bool(ck and ck in u["excluded_company_keys"]), "confidence": confidence(inp, c, w, status)}


def combine(c: dict, w: dict, policy: str) -> float:
    """Shared by every 0-100 score. c[k] = {"value": 0..1|None, "known": bool}; adds weight/effective_weight/points to each component
    in place and returns the 0-100 total under the missing-data policy (neutral: unknown = half weight; exclude: renormalise)."""
    known_w = sum(w[k] for k in c if c[k]["known"])
    total = 0.0
    for k, comp in c.items():
        if comp["known"]:
            eff_w = w[k] if policy == "neutral" or known_w == 0 else w[k] * 100 / known_w
            pts = comp["value"] * eff_w
        elif policy == "neutral":
            eff_w, pts = w[k], 0.5 * w[k]
        else:
            eff_w, pts = 0.0, 0.0
        comp.update(weight=round(w[k], 3), effective_weight=round(eff_w, 3), points=round(pts, 2))
        total += pts
    return round(min(100.0, max(0.0, total)), 2)


def confidence(inp: dict, c: dict, w: dict, status: str) -> dict:
    """0-100 support for the score. completeness 35 / source reliability 20 / freshness 20 / consistency 10 / verified-vs-inferred 15."""
    known = sum(w[k] for k in COMPONENTS if c[k]["known"]) / 100
    reliability = sum(bool(x) for x in (inp["company_key"], inp["position"], inp["has_url"])) / 3
    co, today = inp["connected_on"], inp["today"]
    fresh = 0.3 if not co else 1.0 if (today - co).days <= 730 else 0.6 if (today - co).days <= 365 * 5 else 0.25
    consistency = 0.5 if status == "possibly_outdated" else 1.0
    verified = 1.0 if inp.get("employment_verified") else 0.3
    parts = {"completeness": known, "source_reliability": reliability, "freshness": fresh, "consistency": consistency, "verified_vs_inferred": verified}
    wt = {"completeness": 35, "source_reliability": 20, "freshness": 20, "consistency": 10, "verified_vs_inferred": 15}
    return {"score": round(sum(parts[k] * wt[k] for k in parts), 1), "parts": {k: round(v, 2) for k, v in parts.items()},
            "note": "How well-supported this score is; not a probability of a referral."}


def rank_key(row: dict):
    """Higher total first, then higher confidence, then more recent connection, then name/id for determinism."""
    co = row["connected_on"].toordinal() if row.get("connected_on") else 0
    return (-row["total"], -row["confidence"], -co, row["name_norm"], row["id"])


def assign_tiers(rows: list[dict], sizes: list[int]) -> list[dict]:
    """rows sorted by rank_key. Each row lands in exactly one tier (1..n) or None; excluded companies are never tiered."""
    out, idx = [], 0
    bounds, acc = [], 0
    for s in sizes:
        acc += s
        bounds.append(acc)
    for rank, r in enumerate((r for r in sorted(rows, key=rank_key)), start=1):
        tier = None
        if not r.get("excluded"):
            idx += 1
            tier = next((i + 1 for i, b in enumerate(bounds) if idx <= b), None)
        out.append({**r, "rank": rank, "tier": tier})
    return out
