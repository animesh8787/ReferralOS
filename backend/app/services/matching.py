"""Requirement matrix, eligibility constraints and the Job Match Score. All functions are pure.

Principles: a missing keyword is not missing competence (NO_EVIDENCE means "nothing in your profile shows it", not "you lack it");
a JD keyword is never added to the profile; eligibility is judged separately from the score and never assumed when data is
missing; profile facts are never altered to satisfy a constraint.
"""
import re
from datetime import date

from rapidfuzz import fuzz

from . import scoring, taxonomy

MATCH_VERSION = "job-match/1"
MATCH_COMPONENTS = ["technical_skills", "required_qualifications", "role_career", "experience_projects", "location"]
DEFAULT_MATCH_WEIGHTS = {"technical_skills": 35, "required_qualifications": 25, "role_career": 15, "experience_projects": 15, "location": 10}
STATUS_VALUE = {"STRONG_EVIDENCE": 1.0, "PARTIAL_EVIDENCE": 0.5, "NEEDS_VERIFICATION": 0.4, "CONFLICTING_EVIDENCE": 0.2, "NO_EVIDENCE": 0.0}
LEVEL = {"bachelors": 1, "masters": 2, "phd": 3}
RANK = {"USED_PROFESSIONALLY": 4, "USED_IN_PROJECT": 3, "STUDIED": 2, "CLAIMED_ONLY": 1}
PRIORITIZE_AT = 60


# ---------------------------------------------------------------- profile summary
def _months(start: str | None, end: str | None, today: date) -> tuple[int, int] | None:
    def p(s, is_end):
        if not s:
            return None
        if s == "present":
            return today.year * 12 + today.month
        m = re.match(r"(\d{4})(?:-(\d{2}))?$", s)
        if not m:
            return None
        return int(m.group(1)) * 12 + (int(m.group(2)) if m.group(2) else (12 if is_end else 1))
    a, b = p(start, False), p(end, True)
    return (a, b) if a is not None and b is not None and b >= a else None


def _merged_months(spans: list[tuple[int, int]]) -> int:
    merged: list[list[int]] = []
    for a, b in sorted(spans):
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return sum(b - a + 1 for a, b in merged)


def summarize_profile(items: list[dict], today: date) -> dict:
    """items: serialized ProfileItem dicts (section, data, status, verified, evidence_level, flags, id)."""
    act = [i for i in items if i["status"] == "active"]
    sug = [i for i in items if i["status"] == "suggested"]
    skills: dict[str, dict] = {}

    def add(name, level, item, how):
        s = skills.setdefault(name, {"best": None, "suggested": False, "verified": False, "item_ids": [], "conflict": False, "how": []})
        if level == "SUGGESTED":
            s["suggested"] = True
        elif level and RANK[level] > RANK.get(s["best"], 0):
            s["best"] = level
        s["verified"] |= bool(item.get("verified"))
        s["conflict"] |= any(f.get("type") in ("conflict", "date_order") for f in item.get("flags") or [])
        if item["id"] not in s["item_ids"]:
            s["item_ids"].append(item["id"])
        s["how"].append(how)

    for i in act:
        d, sec = i["data"], i["section"]
        if sec == "skill":
            add(taxonomy.normalize(d["name"]) or d["name"], i.get("evidence_level") or "CLAIMED_ONLY", i, "listed in your skills")
        elif sec == "experience":
            for sk in taxonomy.skill_set(" ".join(d.get("bullets", []) + [d.get("title") or ""])):
                add(sk, "USED_PROFESSIONALLY", i, f"used at {d.get('organization')}")
        elif sec == "project":
            for sk in d.get("stack", []):
                add(sk, "USED_IN_PROJECT", i, f"used in project '{d.get('name')}'")
        elif sec == "education":
            for sk in taxonomy.skill_set(" ".join(d.get("coursework", []))):
                add(sk, "STUDIED", i, "studied (coursework)")
    for i in sug:  # GitHub/portfolio suggestions: usable only as "needs verification"
        d = i["data"]
        names = [d["name"]] if i["section"] == "skill" else d.get("stack", []) if i["section"] == "project" else []
        for n in names:
            add(taxonomy.normalize(n) or n, "SUGGESTED", i, f"suggested from {i['source']}")

    spans, by_skill = [], {}
    for i in act:
        if i["section"] == "experience" and not any(f.get("type") == "date_order" for f in i.get("flags") or []):
            m = _months(i["data"].get("start"), i["data"].get("end"), today)
            if m:
                spans.append(m)
                for sk in taxonomy.skill_set(" ".join(i["data"].get("bullets", []) + [i["data"].get("title") or ""])):
                    by_skill.setdefault(sk, []).append(m)
    months = _merged_months(spans)
    skill_months = {sk: _merged_months(v) for sk, v in by_skill.items()}

    degree, expected, grad_year = None, False, None
    for i in act:
        if i["section"] == "education":
            d = i["data"]
            blob = (d.get("degree") or "").lower()
            lvl = "phd" if re.search(r"ph\.?d|doctor", blob) else "masters" if re.search(r"master|m\.?\s?tech|m\.?\s?s\b|m\.?sc|mba", blob) else "bachelors" if blob else None
            if lvl and LEVEL[lvl] >= LEVEL.get(degree, 0):
                degree, expected = lvl, bool(d.get("expected"))
            end = d.get("end")
            if end and re.match(r"\d{4}", end):
                grad_year = max(grad_year or 0, int(end[:4]))
    prefs = next((i["data"] for i in act if i["section"] == "preference"), {})
    if prefs.get("graduation_date"):
        grad_year = int(prefs["graduation_date"][:4])
    return {"skills": skills, "experience_months": months, "skill_months": skill_months, "has_dated_experience": bool(spans), "degree_level": degree, "degree_in_progress": expected,
            "grad_year": grad_year, "prefs": prefs,
            "used_skills": sorted(k for k, v in skills.items() if v["best"] in ("USED_PROFESSIONALLY", "USED_IN_PROJECT"))}


# ---------------------------------------------------------------- requirement matrix
def _skill_row(req: dict, prof: dict) -> dict:
    t = req["term"]
    s = prof["skills"].get(t)
    base = {"requirement": req["text"], "type": "skill", "term": t, "importance": req["importance"]}
    if s and s["conflict"]:
        return {**base, "status": "CONFLICTING_EVIDENCE", "explanation": f"Your profile mentions {t}, but a supporting entry has an unresolved conflict. Resolve it first.", "fact_ids": s["item_ids"]}
    if s and s["best"] in ("USED_PROFESSIONALLY", "USED_IN_PROJECT"):
        return {**base, "status": "STRONG_EVIDENCE", "explanation": f"{t}: " + "; ".join(dict.fromkeys(s["how"][:3])) + ("" if s["verified"] else " (not yet confirmed by you)"), "fact_ids": s["item_ids"]}
    if s and s["best"] == "STUDIED":
        return {**base, "status": "PARTIAL_EVIDENCE", "explanation": f"You studied {t} but no job or project shows using it.", "fact_ids": s["item_ids"]}
    if s and s["best"] == "CLAIMED_ONLY":
        return {**base, "status": "NEEDS_VERIFICATION", "explanation": f"You list {t}, but nothing in your jobs or projects shows it. Add where you used it.", "fact_ids": s["item_ids"]}
    if s and s["suggested"]:
        return {**base, "status": "NEEDS_VERIFICATION", "explanation": f"{t} appears only in suggestions from {', '.join(dict.fromkeys(s['how'][:2]))}. Confirm it to count it.", "fact_ids": s["item_ids"]}
    cat = req.get("category")
    if cat in ("database", "cloud"):
        rel = sorted(k for k, v in prof["skills"].items() if v["best"] in ("USED_PROFESSIONALLY", "USED_IN_PROJECT") and taxonomy.category(k) == cat)
        if rel:
            return {**base, "status": "PARTIAL_EVIDENCE", "explanation": f"Related, not the same: you have used {', '.join(rel[:3])} ({cat}).",
                    "fact_ids": [x for k in rel[:3] for x in prof["skills"][k]["item_ids"]]}
    return {**base, "status": "NO_EVIDENCE", "explanation": f"Nothing in your profile shows {t}. This is absence of evidence, not proof you lack it; add it only if you have it.", "fact_ids": []}


def build_matrix(analysis: dict, prof: dict) -> list[dict]:
    rows = []
    for req in analysis["requirements"]:
        if req["type"] == "skill":
            rows.append(_skill_row(req, prof))
        elif req["type"] == "experience_years":
            need = req["years"]
            terms = [t.strip() for t in req["term"].split(",") if t.strip() in prof["skills"] or t.strip() in taxonomy.SKILLS]
            base = {"requirement": req["text"], "type": "experience_years", "term": req["term"], "importance": req["importance"], "fact_ids": []}
            if terms:  # "3+ years of Python" is measured against Python in your jobs, not your whole career
                have = max(prof["skill_months"].get(t, 0) for t in terms) / 12
                what = f"using {', '.join(terms)} in your jobs (all roles combined: {prof['experience_months'] / 12:.1f})"
            else:
                have, what = prof["experience_months"] / 12, "of dated experience (all roles combined, including internships)"
            if not prof["has_dated_experience"]:
                rows.append({**base, "status": "NEEDS_VERIFICATION", "explanation": f"The role asks {need}+ years; your profile has no dated work experience to measure."})
            elif have >= need:
                rows.append({**base, "status": "STRONG_EVIDENCE", "explanation": f"About {have:.1f} years {what} vs {need}+ asked."})
            elif have >= need * 0.6:
                rows.append({**base, "status": "PARTIAL_EVIDENCE", "explanation": f"About {have:.1f} years {what} vs {need}+ asked."})
            else:
                rows.append({**base, "status": "NO_EVIDENCE", "explanation": f"About {have:.1f} years {what} vs {need}+ asked. Projects and coursework are not counted as years."})
        elif req["type"] == "education":
            lvl, base = req["level"], {"requirement": req["text"], "type": "education", "term": req["level"], "importance": req["importance"], "fact_ids": []}
            have = prof["degree_level"]
            if not have:
                rows.append({**base, "status": "NEEDS_VERIFICATION", "explanation": "No degree in your profile to compare."})
            elif prof["degree_in_progress"]:
                rows.append({**base, "status": "PARTIAL_EVIDENCE", "explanation": f"Your {have} degree is in progress (expected {prof['grad_year'] or 'date not given'})."})
            elif LEVEL[have] >= LEVEL[lvl]:
                rows.append({**base, "status": "STRONG_EVIDENCE", "explanation": f"Your profile shows a {have} degree."})
            elif req.get("or_equivalent"):
                rows.append({**base, "status": "PARTIAL_EVIDENCE", "explanation": f"Posting asks {lvl} or equivalent experience; your profile shows {have}."})
            else:
                rows.append({**base, "status": "NO_EVIDENCE", "explanation": f"Posting asks {lvl}; your profile shows {have}."})
    return rows


# ---------------------------------------------------------------- eligibility
def _auth_kind(txt: str | None) -> str:
    t = (txt or "").lower()
    if not t:
        return "unspecified"
    if re.search(r"sponsor|needs? (a )?visa|require", t) and not re.search(r"no sponsor|not require|no visa", t):
        return "needs_sponsorship"
    if re.search(r"citizen|permanent resident|green card|authori[sz]ed|no sponsor|not require", t):
        return "authorized"
    return "unspecified"


def eligibility(analysis: dict, prof: dict, job: dict, matrix: list[dict]) -> list[dict]:
    """job: work_arrangement, location, employment_type. -> [{key,status,reason,action?}]; status SATISFIED|VIOLATED|UNCERTAIN."""
    h, prefs, out = analysis["hints"], prof["prefs"], []
    if h["graduation_years"]:
        gy = prof["grad_year"]
        ex = next((t for t in analysis["requirements"] if t["type"] == "education"), None)
        if gy is None:
            out.append({"key": "graduation_year", "status": "UNCERTAIN", "reason": f"Posting mentions {', '.join(map(str, h['graduation_years']))}; your graduation date is not in your profile.",
                        "action": "Add your graduation date in Profile > Preferences."})
        elif gy in h["graduation_years"]:
            out.append({"key": "graduation_year", "status": "SATISFIED", "reason": f"Your graduation year {gy} is among those the posting names."})
        else:
            out.append({"key": "graduation_year", "status": "VIOLATED", "reason": f"Posting names {', '.join(map(str, h['graduation_years']))}; your profile says {gy}. (Read from the posting text; please double-check.)"})
    ed = [r for r in matrix if r["type"] == "education" and r["importance"] == "mandatory"]
    if ed:
        r = ed[0]
        st = {"STRONG_EVIDENCE": "SATISFIED", "NO_EVIDENCE": "VIOLATED"}.get(r["status"], "UNCERTAIN")
        out.append({"key": "degree_level", "status": st, "reason": r["explanation"], **({"action": "Add or confirm your degree in your profile."} if st == "UNCERTAIN" and not prof["degree_level"] else {})})
    if h["min_years"]:
        r = next((r for r in matrix if r["type"] == "experience_years" and r["importance"] == "mandatory" and r["requirement"]), None)
        st = {"STRONG_EVIDENCE": "SATISFIED", "NO_EVIDENCE": "VIOLATED"}.get(r["status"], "UNCERTAIN") if r else "UNCERTAIN"
        out.append({"key": "min_experience", "status": st, "reason": r["explanation"] if r else "Minimum experience could not be measured.",
                    **({"action": "Add dates to your experience entries."} if st == "UNCERTAIN" else {})})
    if h["sponsorship"] == "none" or h["citizenship_required"]:
        kind = _auth_kind(prefs.get("work_authorization"))
        what = "citizenship may be required" if h["citizenship_required"] else "no visa sponsorship"
        if kind == "unspecified":
            out.append({"key": "work_authorization", "status": "UNCERTAIN", "reason": f"Posting indicates {what}; you have not stated your work authorisation.", "action": "Optionally add your work authorisation in Preferences (kept private)."})
        elif kind == "needs_sponsorship" and h["sponsorship"] == "none":
            out.append({"key": "work_authorization", "status": "VIOLATED", "reason": "Posting offers no sponsorship and your preferences say you would need it."})
        elif h["citizenship_required"]:
            out.append({"key": "work_authorization", "status": "UNCERTAIN", "reason": "Posting may require citizenship; a stated work authorisation does not settle that. Check the posting."})
        else:
            out.append({"key": "work_authorization", "status": "SATISFIED", "reason": "You state you are authorised to work without sponsorship."})
    if h["clearance"]:
        out.append({"key": "security_clearance", "status": "UNCERTAIN", "reason": "Posting mentions a security clearance; this app cannot judge that.", "action": "Read the clearance requirement in the posting."})
    # location / arrangement
    arr, loc = job.get("work_arrangement"), (job.get("location") or "").lower()
    locs = [l.lower() for l in prefs.get("locations", []) if l]
    if arr == "remote" and not h["onsite_required"]:
        out.append({"key": "location", "status": "SATISFIED", "reason": "Remote role." + (f" Posting location: {job['location']}; check any country restriction." if job.get("location") else "")})
    elif not locs:
        out.append({"key": "location", "status": "UNCERTAIN", "reason": "You have not set preferred locations.", "action": "Add preferred locations in Preferences."})
    elif not loc:
        out.append({"key": "location", "status": "UNCERTAIN", "reason": "The posting does not state a location.", "action": "Check the posting for the location."})
    elif any(l in loc or loc.split(",")[0].strip() in l for l in locs):
        out.append({"key": "location", "status": "SATISFIED", "reason": f"{job['location']} matches your preferred locations."})
    else:
        out.append({"key": "location", "status": "VIOLATED", "reason": f"{job['location']} is outside your preferred locations ({', '.join(prefs['locations'])})."})
    return out


# ---------------------------------------------------------------- Job Match Score
def _mean(rows, weight_by_importance=True):
    num = den = 0.0
    for r in rows:
        w = (2 if r["importance"] == "mandatory" else 1) if weight_by_importance else 1
        num += STATUS_VALUE[r["status"]] * w
        den += w
    return num / den if den else None


def _c(value, why):
    return {"value": None if value is None else round(value, 3), "known": value is not None, "explanation": why}


def normalize_match_weights(w: dict) -> dict:
    if set(w) != set(MATCH_COMPONENTS) or any((not isinstance(v, (int, float))) or v < 0 for v in w.values()) or sum(w.values()) <= 0:
        raise ValueError("weights need all five components, each >= 0, with a positive total")
    t = sum(w.values())
    out = {k: round(w[k] * 100 / t, 4) for k in MATCH_COMPONENTS}
    out[MATCH_COMPONENTS[0]] = round(out[MATCH_COMPONENTS[0]] + 100 - sum(out.values()), 4)
    return out


def match_score(analysis: dict, matrix: list[dict], elig: list[dict], prof: dict, job: dict, cfg: dict | None = None) -> dict:
    cfg = cfg or {}
    w = normalize_match_weights(cfg.get("weights", DEFAULT_MATCH_WEIGHTS))
    prefs, c = prof["prefs"], {}
    skills = [r for r in matrix if r["type"] == "skill"]
    mand = [r for r in matrix if r["importance"] == "mandatory"]
    v = _mean(skills)
    cnt = {s: sum(1 for r in skills if r["status"] == s) for s in STATUS_VALUE}
    c["technical_skills"] = _c(v, f"{len(skills)} skills named: {cnt['STRONG_EVIDENCE']} strong, {cnt['PARTIAL_EVIDENCE']} partial, {cnt['NEEDS_VERIFICATION']} to verify, {cnt['NO_EVIDENCE']} with no evidence." if skills else "The posting names no recognisable technical skills.")
    c["required_qualifications"] = _c(_mean(mand), f"{len(mand)} mandatory requirements; " + (f"{sum(1 for r in mand if r['status'] == 'STRONG_EVIDENCE')} strongly supported." if mand else "none identified."))
    roles = prefs.get("target_roles", [])
    if roles:
        best = max(fuzz.token_set_ratio(job["title"].lower(), r.lower()) for r in roles)
        rv = 1.0 if best >= 80 else 0.7 if best >= 60 else 0.4 if best >= 40 else 0.1
        why = f"Title '{job['title']}' vs your target roles: {best:.0f}% similar."
        et = prefs.get("employment_type", [])
        if et and job.get("employment_type") not in (None, "unknown") and job["employment_type"] not in et:
            rv, why = rv * 0.4, why + f" The role is {job['employment_type'].replace('_', ' ')}, which is not in your preferred types."
        c["role_career"] = _c(rv, why)
    else:
        c["role_career"] = _c(None, "You have not set target roles.")
    jd = {r["term"] for r in skills}
    used = set(prof["used_skills"])
    c["experience_projects"] = _c(len(jd & used) / len(jd) if jd and used else None,
                                  (f"{len(jd & used)} of the {len(jd)} named skills appear in your jobs or projects: {', '.join(sorted(jd & used)) or 'none'}." if jd and used else "Needs both named skills and project/job entries."))
    loc = next((e for e in elig if e["key"] == "location"), None)
    lv = None if not loc or loc["status"] == "UNCERTAIN" else 1.0 if loc["status"] == "SATISFIED" else 0.0
    arr = prefs.get("work_arrangement", [])
    if lv == 1.0 and arr and job.get("work_arrangement") in ("remote", "hybrid", "onsite") and job["work_arrangement"] not in arr:
        lv = 0.5
    c["location"] = _c(lv, loc["reason"] if loc else "No location information.")
    total = scoring.combine(c, w, cfg.get("missing_policy", "neutral"))
    states = {e["status"] for e in elig}
    verdict = "no" if "VIOLATED" in states else "review" if "UNCERTAIN" in states or job.get("status") != "ACTIVE_VERIFIED" else "yes" if total >= PRIORITIZE_AT else "maybe"
    return {"version": MATCH_VERSION, "total": total, "components": c, "prioritize_applying": verdict,
            "aligned_skills": sorted(jd & used), "missing_qualifications": [r["requirement"] for r in mand if r["status"] == "NO_EVIDENCE"],
            "to_verify": [r["term"] for r in matrix if r["status"] == "NEEDS_VERIFICATION"],
            "eligibility_summary": {s: sum(1 for e in elig if e["status"] == s) for s in ("SATISFIED", "UNCERTAIN", "VIOLATED")}}
