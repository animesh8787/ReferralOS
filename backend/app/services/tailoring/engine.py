"""Resume tailoring. SELECT, ORDER and GROUP what the Master Career Profile already says; never invent.

- Bullets are kept verbatim unless an LLM proposes a rewording that passes validate.check_rewrite (default: no LLM, no rewording).
- Skills come only from active profile skill/experience/project entries. A JD keyword is never added to the resume.
- Education and dates are copied exactly. Entries with unresolved conflicts are left out and reported.
- Missing numbers become questions to the user, never numbers.
Every text node carries a claim id; the ledger maps each claim to the profile facts that support it.
"""
import re
from datetime import date

from .. import taxonomy
from ..classify import domain_tags
from ..matching import summarize_profile
from . import validate

CAT_LABEL = {"language": "Languages", "framework": "Frameworks", "database": "Databases", "cloud": "Cloud", "infrastructure": "Infrastructure & DevOps",
             "ai_ml": "AI / ML", "data": "Data", "tool": "Tools", "methodology": "Practices", "concept": "Concepts", "other": "Other"}
SECTIONS = ["summary", "skills", "experience", "projects", "education", "certifications", "awards"]
ORDERS = {"early": ["summary", "education", "skills", "projects", "experience", "certifications", "awards"],
          "ai_projects": ["summary", "skills", "projects", "experience", "education", "certifications", "awards"],
          "experienced": ["summary", "skills", "experience", "projects", "education", "certifications", "awards"]}
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
BLOCK = validate.BLOCKING


def fmt_date(s: str | None) -> str:
    if not s:
        return ""
    if s == "present":
        return "Present"
    m = re.match(r"(\d{4})-(\d{2})$", s)
    return f"{MONTHS[int(m.group(2)) - 1]} {m.group(1)}" if m and 1 <= int(m.group(2)) <= 12 else s


def _blocked(i: dict) -> bool:
    return any(f.get("type") in BLOCK for f in i.get("flags") or [])


class Ledger:
    def __init__(self):
        self.claims: list[dict] = []

    def add(self, kind: str, section: str, text: str, fact_ids: list[str]) -> str:
        cid = f"c{len(self.claims) + 1:03d}"
        self.claims.append({"id": cid, "kind": kind, "section": section, "text": text, "fact_ids": list(dict.fromkeys(fact_ids)), "status": "validated", "reasons": []})
        return cid


def role_type(job: dict, prof: dict, items: list[dict]) -> str:
    if job.get("employment_type") == "internship" or (prof["degree_in_progress"] and prof["experience_months"] < 24):
        return "early"
    def is_ml(i):
        stack = i["data"].get("stack", [])
        return any(taxonomy.category(s) == "ai_ml" for s in stack) or "ml_ai" in domain_tags(" ".join(stack + [i["data"].get("name") or ""]))
    ml_projects = [i for i in items if i["section"] == "project" and i["status"] == "active" and is_ml(i)]
    if "ml_ai" in job.get("domains", []) and ml_projects and prof["experience_months"] < 36:
        return "ai_projects"
    return "experienced"


def _weights(analysis: dict) -> dict[str, float]:
    return {r["term"]: (2.0 if r["importance"] == "mandatory" else 1.0) for r in analysis["requirements"] if r["type"] == "skill"}


def _rel(text: str, w: dict[str, float]) -> float:
    return sum(w.get(s, 0) for s in taxonomy.skill_set(text)) + (0.1 if re.search(r"\d", text) else 0)


def build(items: list[dict], analysis: dict, matrix: list[dict], job: dict, options: dict | None = None, today: date | None = None, llm=None) -> dict:
    """items: serialized ProfileItems. job: title, company, employment_type, domains. -> {content, ledger, questions, notes}"""
    o = {"max_projects": 3, "max_bullets": 4, "excluded_item_ids": [], "section_order": None, **(options or {})}
    today = today or date.today()
    act = [i for i in items if i["status"] == "active" and i["id"] not in set(o["excluded_item_ids"])]
    usable = [i for i in act if not _blocked(i)]
    prof = summarize_profile(items, today)
    w, led, notes = _weights(analysis), Ledger(), {"left_out": [], "rewrites_rejected": [], "rewrites_used": 0}
    for i in act:
        if _blocked(i):
            notes["left_out"].append({"item_id": i["id"], "section": i["section"], "why": "unresolved conflict or date problem in your profile"})
    jd_terms = sorted(w, key=lambda t: -w[t])
    rtype = role_type(job, prof, items)
    content: dict = {"role_type": rtype}

    # header
    pers = next((i for i in usable if i["section"] == "personal"), None)
    if pers:
        d = pers["data"]
        hdr = [d.get(k) for k in ("name", "email", "phone")] + list(d.get("links") or [])
        content["header"] = {"name": d.get("name"), "email": d.get("email"), "phone": d.get("phone"), "links": list(d.get("links") or []),
                             "claim_id": led.add("header", "header", " | ".join(x for x in hdr if x), [pers["id"]])}

    # experience: most recent first, duplicates dropped, bullets selected by relevance but kept verbatim and in original order
    def end_key(i):
        e = i["data"].get("end")
        return "9999" if e == "present" else (e or "0000")
    seen, exp_out = set(), []
    for i in sorted([x for x in usable if x["section"] == "experience"], key=end_key, reverse=True):
        d = i["data"]
        key = ((d.get("title") or "").lower(), (d.get("organization") or "").lower(), d.get("start"))
        if key in seen:
            notes["left_out"].append({"item_id": i["id"], "section": "experience", "why": "duplicate of another entry"})
            continue
        seen.add(key)
        bullets = d.get("bullets") or []
        pick = sorted(sorted(range(len(bullets)), key=lambda k: -_rel(bullets[k], w))[: o["max_bullets"]])
        out_b = []
        for k in pick:
            text = bullets[k]
            if llm is not None and jd_terms:
                prop = llm.rewrite_bullet(text, jd_terms)
                if prop:
                    why = validate.check_rewrite(text, prop)
                    if why:
                        notes["rewrites_rejected"].append({"original": text, "proposed": prop, "why": why})
                    else:
                        text, notes["rewrites_used"] = prop, notes["rewrites_used"] + 1
            out_b.append({"claim_id": led.add("bullet", "experience", text, [i["id"]]), "text": text, "source_index": k})
        role_txt = f"{d.get('title')}, {d.get('organization')}, {fmt_date(d.get('start'))} - {fmt_date(d.get('end'))}"
        exp_out.append({"item_id": i["id"], "title": d.get("title"), "organization": d.get("organization"), "start": fmt_date(d.get("start")), "end": fmt_date(d.get("end")),
                        "claim_id": led.add("role", "experience", role_txt, [i["id"]]), "bullets": out_b, "omitted_bullets": len(bullets) - len(pick)})
    content["experience"] = exp_out

    # projects: ranked by relevance; the user's stack lists are copied, never extended
    projs = [i for i in usable if i["section"] == "project"]
    def prel(i):
        d = i["data"]
        return sum(w.get(s, 0) for s in set(d.get("stack", [])) | taxonomy.skill_set(" ".join(d.get("description", []))))
    order = {i["id"]: n for n, i in enumerate(projs)}  # ties keep the user's own order
    ranked = sorted(projs, key=lambda i: (-prel(i), not i["verified"], order[i["id"]]))
    chosen = [i for i in ranked if prel(i) > 0][: o["max_projects"]] or ranked[:2]
    proj_out = []
    for i in chosen:
        d = i["data"]
        links = [u for u in (d.get("repo_url"), d.get("demo_url")) if u]
        head = f"{d.get('name')} {' '.join(d.get('stack', []))} {' '.join(links)}".strip()
        desc = [t for t in d.get("description", []) if t] + [t for t in d.get("outcomes", []) if t]
        pick = sorted(sorted(range(len(desc)), key=lambda k: -_rel(desc[k], w))[: o["max_bullets"]])
        proj_out.append({"item_id": i["id"], "name": d.get("name"), "links": links, "stack": list(d.get("stack", [])),
                         "claim_id": led.add("project", "projects", head, [i["id"]]),
                         "bullets": [{"claim_id": led.add("bullet", "projects", desc[k], [i["id"]]), "text": desc[k], "source_index": k} for k in pick]})
    content["projects"] = proj_out
    notes["left_out"] += [{"item_id": i["id"], "section": "project", "why": "less relevant to this role (still in your profile)"} for i in projs if i not in chosen]

    # skills (only what the profile supports; JD-relevant first; studied-only kept apart)
    groups: dict[str, list[tuple]] = {}
    for name, s in prof["skills"].items():
        if s["conflict"] or s["best"] is None:
            continue
        ids = [x for x in s["item_ids"] if x in {u["id"] for u in usable}]
        if not ids:
            continue
        label = "Studied" if s["best"] == "STUDIED" else CAT_LABEL.get(taxonomy.category(name), "Other")
        evrank = {"USED_PROFESSIONALLY": 0, "USED_IN_PROJECT": 1, "STUDIED": 2, "CLAIMED_ONLY": 3}[s["best"]]
        groups.setdefault(label, []).append((-w.get(name, 0), evrank, name, ids))
    skills_out = []
    for label, rows in sorted(groups.items(), key=lambda kv: (min(r[0] for r in kv[1]), kv[0] == "Studied", kv[0])):
        rows.sort()
        skills_out.append({"group": label, "items": [{"claim_id": led.add("skill", "skills", n, ids), "name": n} for _, _, n, ids in rows]})
    content["skills"] = skills_out

    # education / certifications / awards: copied exactly
    edu_out = []
    for i in usable:
        if i["section"] == "education":
            d = i["data"]
            txt = f"{d.get('institution')}, {d.get('degree')}, {fmt_date(d.get('start'))} - {fmt_date(d.get('end'))}" + (f", {d['gpa']}" if d.get("gpa") else "")
            edu_out.append({"item_id": i["id"], "institution": d.get("institution"), "degree": d.get("degree"), "start": fmt_date(d.get("start")), "end": fmt_date(d.get("end")),
                            "expected": bool(d.get("expected")), "gpa": d.get("gpa"), "coursework": d.get("coursework") or [], "claim_id": led.add("education", "education", txt, [i["id"]])})
    content["education"] = edu_out
    for sec, key in (("certification", "certifications"), ("award", "awards")):
        content[key] = [{"claim_id": led.add(sec, key, i["data"].get("name") or "", [i["id"]]), "name": i["data"].get("name")} for i in usable if i["section"] == sec and i["data"].get("name")]

    # summary: facts only, no durations, no superlatives
    content["summary"] = _summary(prof, usable, job, exp_out, proj_out, w, led)
    order = o["section_order"] if o["section_order"] and sorted(o["section_order"]) == sorted(SECTIONS) else ORDERS[rtype]
    content["section_order"] = order

    questions = []
    for e in exp_out + proj_out:
        for b in e["bullets"]:
            if not re.search(r"\d", b["text"]) and len(questions) < 3:
                questions.append({"type": "missing_metric", "item_id": e["item_id"], "text": f"Do you have a number for “{b['text'][:90]}” (users, speed, size, time saved)? Add it to your profile and it can be included."})
    for r in matrix:
        if r["type"] == "skill" and r["status"] == "NEEDS_VERIFICATION" and len(questions) < 6:
            questions.append({"type": "verify_skill", "item_id": None, "text": f"The role asks for {r['term']}. If you have used it, add where (a job or project) so it can be featured; otherwise it stays off the resume's highlights."})
    return {"content": content, "ledger": led.claims, "questions": questions, "notes": notes, "role_type": rtype, "jd_terms": jd_terms}


def _list(xs: list[str]) -> str:
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1]


def _summary(prof: dict, usable: list[dict], job: dict, exp_out: list, proj_out: list, w: dict, led: Ledger) -> dict | None:
    edu = next((i for i in usable if i["section"] == "education" and i["data"].get("degree")), None)
    ids, lead = [], None
    if edu:
        d = edu["data"]
        base = f"{d['degree']} student" if d.get("expected") else f"{d['degree']} graduate"
        if d.get("discipline"):
            base += f" in {d['discipline']}"
        if d.get("expected") and d.get("end") and re.match(r"\d{4}-\d{2}$", d["end"]):
            base += f" (expected {fmt_date(d['end'])})"
        lead, ids = base, [edu["id"]]
    elif exp_out and exp_out[0]["title"]:
        lead, ids = exp_out[0]["title"], [exp_out[0]["item_id"]]
    used = [(w.get(n, 0), n, s) for n, s in prof["skills"].items() if s["best"] in ("USED_PROFESSIONALLY", "USED_IN_PROJECT") and not s["conflict"] and w.get(n)]
    used.sort(key=lambda t: (-t[0], t[1]))
    top = used[:3]
    sents = []
    if lead and top:
        names = [n for _, n, _ in top]
        fids = ids + [x for _, _, s in top for x in s["item_ids"]]
        sents.append((f"{lead} with hands-on experience using {_list(names)}.", fids))
    elif lead:
        sents.append((f"{lead}.", ids))
    if proj_out:
        pn = [p["name"] for p in proj_out[:2] if p["name"]]
        if pn:
            sents.append((f"Built projects including {_list(pn)}.", [p["item_id"] for p in proj_out[:2]]))
    if not sents:
        return None
    return {"sentences": [{"claim_id": led.add("summary", "summary", t, f), "text": t} for t, f in sents]}


def render_nodes(content: dict) -> list[tuple[str, str]]:
    """(claim_id, text) for every textual node in the resume: used to prove the ledger is complete."""
    out = []
    h = content.get("header")
    if h:
        out.append((h["claim_id"], ""))
    for s in (content.get("summary") or {}).get("sentences", []):
        out.append((s["claim_id"], s["text"]))
    for g in content.get("skills", []):
        out += [(i["claim_id"], i["name"]) for i in g["items"]]
    for e in content.get("experience", []):
        out.append((e["claim_id"], e["title"] or ""))
        out += [(b["claim_id"], b["text"]) for b in e["bullets"]]
    for p in content.get("projects", []):
        out.append((p["claim_id"], p["name"] or ""))
        out += [(b["claim_id"], b["text"]) for b in p["bullets"]]
    out += [(e["claim_id"], e["institution"] or "") for e in content.get("education", [])]
    for k in ("certifications", "awards"):
        out += [(c["claim_id"], c["name"]) for c in content.get(k, [])]
    return out
