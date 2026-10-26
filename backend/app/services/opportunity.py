"""Opportunity Priority Score + readiness grouping. Pure.

An uncertain job with a high match score must not silently outrank a verified, eligible opening, so display order is
(readiness group, score). Each item also carries `score_only_rank` and a plain-language trade-off whenever the two differ.
"""
from datetime import datetime

from . import scoring

VERSION = "opportunity/1"
COMPONENTS = ["match", "verification", "contacts", "deadline", "eligibility"]
DEFAULT_WEIGHTS = {"match": 35, "verification": 20, "contacts": 20, "deadline": 10, "eligibility": 15}
VERIF = {"ACTIVE_VERIFIED": 1.0, "ACTIVE_UNCONFIRMED": 0.5, "UNKNOWN": 0.25, "POSSIBLY_CLOSED": 0.1, "CLOSED": 0.0}
GROUPS = {0: "Verified and eligible", 1: "Verified, eligibility to confirm", 2: "Not yet verified", 3: "Open, but you appear ineligible", 4: "Closed or likely closed"}


def normalize_weights(w: dict) -> dict:
    if set(w) != set(COMPONENTS) or any((not isinstance(v, (int, float))) or v < 0 for v in w.values()) or sum(w.values()) <= 0:
        raise ValueError("weights need all five components, each >= 0, with a positive total")
    t = sum(w.values())
    out = {k: round(w[k] * 100 / t, 4) for k in COMPONENTS}
    out[COMPONENTS[0]] = round(out[COMPONENTS[0]] + 100 - sum(out.values()), 4)
    return out


def _c(v, why):
    return {"value": None if v is None else round(v, 3), "known": v is not None, "explanation": why}


def group_of(status: str, elig: dict) -> int:
    if status in ("CLOSED", "POSSIBLY_CLOSED"):
        return 4
    if elig.get("VIOLATED"):
        return 3
    if status != "ACTIVE_VERIFIED":
        return 2
    return 1 if elig.get("UNCERTAIN") else 0


def score(match_total: float, status: str, needs_reverify: bool, best_contact: float | None, hr_contacts: int,
          deadline: datetime | None, now: datetime, elig: dict, cfg: dict | None = None) -> dict:
    cfg = cfg or {}
    w = normalize_weights(cfg.get("weights", DEFAULT_WEIGHTS))
    c = {"match": _c(match_total / 100, f"Job Match Score {match_total:.0f}/100.")}
    vv = VERIF.get(status, 0.25) * (0.8 if needs_reverify and status != "CLOSED" else 1)
    c["verification"] = _c(vv, f"Status {status.replace('_', ' ').lower()}" + ("; evidence is stale, re-verify." if needs_reverify else "."))
    if best_contact is not None:
        c["contacts"] = _c(best_contact / 100, f"Best contact scores {best_contact:.0f}/100 for this job.")
    elif hr_contacts:
        c["contacts"] = _c(0.3, f"No LinkedIn connections here, but {hr_contacts} HR contact(s) from your CSV.")
    else:
        c["contacts"] = _c(0.0, "You know nobody at this company (a known fact: apply directly or look for an intro).")
    if deadline is None:
        c["deadline"] = _c(None, "No deadline stated.")
    else:
        days = (deadline - now).days
        c["deadline"] = _c(0.0 if days < 0 else 1.0 if days <= 14 else 0.6 if days <= 30 else 0.3, f"Deadline {deadline:%Y-%m-%d} ({'passed' if days < 0 else f'{days} days'}).")
    ev = 0.0 if elig.get("VIOLATED") else 0.5 if elig.get("UNCERTAIN") else 1.0
    c["eligibility"] = _c(ev, f"Eligibility: {elig.get('SATISFIED', 0)} satisfied, {elig.get('UNCERTAIN', 0)} uncertain, {elig.get('VIOLATED', 0)} violated.")
    total = scoring.combine(c, w, cfg.get("missing_policy", "neutral"))
    return {"version": VERSION, "total": total, "components": c, "group": group_of(status, elig)}


def rank_all(rows: list[dict]) -> list[dict]:
    """rows: {job_id, total, group, title, company}. Adds rank (display), score_only_rank, trade_off."""
    by_score = sorted(rows, key=lambda r: (-r["total"], r["job_id"]))
    sr = {r["job_id"]: i + 1 for i, r in enumerate(by_score)}
    display = sorted(rows, key=lambda r: (r["group"], -r["total"], r["job_id"]))
    out = []
    for i, r in enumerate(display):
        better_group = [x for x in display[:i] if x["total"] < r["total"] and x["group"] < r["group"]]
        t = None
        if better_group:
            x = better_group[0]
            t = (f"Ranked below '{x['title']}' ({x['company']}) despite a higher score because it is "
                 f"{GROUPS[r['group']].lower()}, while that role is {GROUPS[x['group']].lower()}.")
        out.append({**r, "rank": i + 1, "score_only_rank": sr[r["job_id"]], "trade_off": t})
    return out


def next_action(status: str, elig_rows: list[dict], has_contacts: bool, resume_status: str = "not_started", draft_status: str = "not_started") -> str:
    if status in ("CLOSED",):
        return "Skip: the role is closed."
    if status == "POSSIBLY_CLOSED":
        return "Re-verify the posting before doing anything else."
    if any(e["status"] == "VIOLATED" for e in elig_rows):
        return "Check the ineligibility reason; this role may not be open to you."
    unc = [e for e in elig_rows if e["status"] == "UNCERTAIN"]
    if unc:
        return unc[0].get("action") or "Resolve the uncertain eligibility items."
    if status != "ACTIVE_VERIFIED":
        return "Verify the job is still open (or check the posting yourself)."
    if resume_status == "not_started":
        return "Tailor your resume for this role."
    if resume_status == "draft":
        return "Review and approve your tailored resume."
    if has_contacts and draft_status == "not_started":
        return "Review the recommended contacts and draft outreach."
    return "Apply through the official link." if not has_contacts else "Review and approve the outreach drafts."
