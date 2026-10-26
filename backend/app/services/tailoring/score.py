"""Resume Match Score (0-100): an INTERNAL ALIGNMENT ESTIMATE, not an ATS score; it guarantees nothing about screening.

Components (weights configurable): technical skills 30, relevant experience & projects 30, mandatory qualification coverage 20,
responsibilities alignment 10, natural keyword coverage & readability 10. Suggestions only ever point at things the profile
could support (confirm a skill you used, add a number you have) or say plainly that nothing supports a requirement.
"""
import re

from rapidfuzz import fuzz

from .. import matching, scoring, taxonomy
from .engine import render_nodes

VERSION = "resume-match/1"
COMPONENTS = ["technical_skills", "experience_projects", "mandatory_coverage", "responsibilities", "keywords_readability"]
DEFAULT_WEIGHTS = {"technical_skills": 30, "experience_projects": 30, "mandatory_coverage": 20, "responsibilities": 10, "keywords_readability": 10}
LABEL = "Internal alignment estimate. This is not an ATS score and does not predict whether a resume passes screening."


def normalize_weights(w: dict) -> dict:
    if set(w) != set(COMPONENTS) or any((not isinstance(v, (int, float))) or v < 0 for v in w.values()) or sum(w.values()) <= 0:
        raise ValueError("weights need all five components, each >= 0, with a positive total")
    t = sum(w.values())
    out = {k: round(w[k] * 100 / t, 4) for k in COMPONENTS}
    out[COMPONENTS[0]] = round(out[COMPONENTS[0]] + 100 - sum(out.values()), 4)
    return out


def _c(v, why):
    return {"value": None if v is None else round(v, 3), "known": v is not None, "explanation": why}


def score(content: dict, analysis: dict, matrix: list[dict], questions: list[dict], cfg: dict | None = None) -> dict:
    cfg = cfg or {}
    w = normalize_weights(cfg.get("weights", DEFAULT_WEIGHTS))
    reqs = [r for r in analysis["requirements"] if r["type"] == "skill"]
    exp, proj = content.get("experience", []), content.get("projects", [])
    bullets = [b["text"] for e in exp + proj for b in e["bullets"]]
    shown = taxonomy.skill_set(" ".join(bullets + [s for p in proj for s in p["stack"]] + [e["title"] or "" for e in exp]))
    listed = {i["name"]: g["group"] for g in content.get("skills", []) for i in g["items"]}
    c = {}
    num = den = 0.0
    per_skill = {}
    for r in reqs:
        wt = 2.0 if r["importance"] == "mandatory" else 1.0
        v = 1.0 if r["term"] in shown else 0.5 if r["term"] in listed else 0.0
        per_skill[r["term"]] = v
        num, den = num + v * wt, den + wt
    c["technical_skills"] = _c(num / den if den else None, f"{sum(1 for v in per_skill.values() if v == 1)} of {len(reqs)} named skills are shown in your jobs/projects, {sum(1 for v in per_skill.values() if v == 0.5)} only listed." if reqs else "The posting names no recognisable technical skills.")
    jd = {r["term"] for r in reqs}
    entries = [taxonomy.skill_set(" ".join([e.get("title") or e.get("name") or ""] + [b["text"] for b in e["bullets"]] + e.get("stack", []))) for e in exp + proj]
    c["experience_projects"] = _c(sum(min(1.0, len(s & jd) / 3) for s in entries) / len(entries) if entries and jd else None,
                                  f"{sum(1 for s in entries if s & jd)} of {len(entries)} included jobs/projects touch the role's skills." if entries and jd else "Needs included jobs/projects and named skills.")
    mand = [r for r in matrix if r["importance"] == "mandatory"]
    c["mandatory_coverage"] = _c(matching._mean(mand), f"{sum(1 for r in mand if r['status'] == 'STRONG_EVIDENCE')} of {len(mand)} mandatory requirements are strongly supported by your profile." if mand else "No mandatory requirements identified.")
    resp = analysis.get("responsibilities", [])
    if resp and bullets:
        vals = [min(1.0, max(fuzz.token_set_ratio(r.lower(), b.lower()) for b in bullets) / 70) for r in resp]
        c["responsibilities"] = _c(sum(vals) / len(vals), f"Your bullets resemble {sum(1 for v in vals if v >= 0.8)} of {len(resp)} listed duties.")
    else:
        c["responsibilities"] = _c(None, "Needs listed duties and bullets to compare.")
    text = " ".join(t for _, t in render_nodes(content) if t)
    kws = sorted(jd | {k for k in analysis.get("keywords", []) if taxonomy.category(k) not in ("concept",)})
    if kws:
        low = text.lower()
        cov = sum(1 for k in kws if k.lower() in low) / len(kws)
        stuffed = [k for k in kws if low.count(k.lower()) > 5]
        read = sum(1 for b in bullets if 30 <= len(b) <= 230) / len(bullets) if bullets else 0.0
        c["keywords_readability"] = _c((0.7 * cov * (0.8 if stuffed else 1.0)) + 0.3 * read,
                                       f"{sum(1 for k in kws if k.lower() in low)} of {len(kws)} posting keywords appear naturally; {round(read * 100)}% of bullets are a readable length." + (f" Repeated too often: {', '.join(stuffed)}." if stuffed else ""))
    else:
        c["keywords_readability"] = _c(None, "No posting keywords to compare.")
    total = scoring.combine(c, w, cfg.get("missing_policy", "neutral"))
    tw = sum(2.0 if r["importance"] == "mandatory" else 1.0 for r in reqs) or 1.0
    tips = []
    for r in matrix:
        if r["type"] != "skill" or per_skill.get(r["term"], 1.0) == 1.0:
            continue
        gain = round(w["technical_skills"] * (2.0 if r["importance"] == "mandatory" else 1.0) / tw * (1.0 - per_skill[r["term"]]), 1)
        if r["status"] == "NEEDS_VERIFICATION":
            tips.append({"type": "confirm_skill", "term": r["term"], "est_gain": gain, "action": f"If you have used {r['term']}, add the job or project where you did, then regenerate."})
        elif r["status"] in ("NO_EVIDENCE", "CONFLICTING_EVIDENCE"):
            tips.append({"type": "no_support", "term": r["term"], "est_gain": 0.0,
                         "action": f"Nothing in your profile supports {r['term']}. Add it only if you genuinely have the experience; it is not added automatically."})
    tips += [{"type": "add_number", "term": None, "est_gain": 0.0, "action": q["text"]} for q in questions if q["type"] == "missing_metric"]
    return {"version": VERSION, "total": total, "components": c, "label": LABEL, "improvements": tips}
