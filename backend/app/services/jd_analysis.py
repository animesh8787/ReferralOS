"""Deterministic job-description analysis. No LLM; every output string is a span of the posting or a taxonomy term.

Mandatory != preferred: requirements under 'Requirements/Qualifications' headings, or containing must/required/minimum cues,
are mandatory; 'nice to have / bonus / preferred / plus' are preferred. Anything we cannot classify is kept as 'other', never
promoted. A missing or very short description yields an explicit "insufficient description" result (we never invent text).
"""
import re

from . import taxonomy

H_MAND = re.compile(r"^(minimum |basic |required )?(requirements?|qualifications?)$|what you.?ll need|what we.?re looking for|must.?haves?|you have|about you|your (skills|background)|skills( and experience)?$|who you are|you bring|what you bring", re.I)
H_PREF = re.compile(r"preferred|nice.?to.?haves?|bonus|a plus|desired|desirable|ideal(ly)?|extra credit|good to have|great if", re.I)
H_RESP = re.compile(r"responsibilit|what you.?ll do|the role|your impact|day.?to.?day|duties|in this role|you will", re.I)
H_IGNORE = re.compile(r"about (us|the company|the team)|benefits|perks|compensation|salary|equal opportunity|our (mission|values)|why join|how to apply|what we offer", re.I)
CUE_PREF = re.compile(r"preferred|nice to have|bonus|a plus|\bplus\b|ideally|desirable|good to have|familiarity|exposure to|is a (big )?plus", re.I)
CUE_MAND = re.compile(r"required|must|minimum|need to|proficien|experience (with|in|using)|knowledge of|strong|solid|expertise|\b\d+\+?\s*years?\b|ability to|degree|fluen", re.I)
CUE_RESP = re.compile(r"^(build|design|develop|own|lead|collaborate|maintain|write|ship|work|create|implement|drive|deliver|improve|manage|support|mentor|partner|contribute|participate|analy[sz]e|operate|monitor|debug|optimi[sz]e)\b", re.I)
COLLAB = re.compile(r"collaborat|cross.?functional|partner with|work(ing)? (closely )?with|mentor|stakeholder|communicat|team player", re.I)
YEARS = re.compile(r"(\d{1,2})\s*\+?\s*(?:-\s*\d{1,2}\s*)?years?", re.I)
# (level, case-insensitive words, case-sensitive abbreviations): "BE" / "MS" must not match the words "be" / "ms" in prose
DEGREE = [("phd", re.compile(r"ph\.?d|doctorate|doctoral", re.I), None),
          ("masters", re.compile(r"master'?s|master of", re.I), re.compile(r"(?:M\.?S\.?|MSc|M\.?Tech|MBA)(?![A-Za-z])")),
          ("bachelors", re.compile(r"bachelor'?s?|undergraduate degree|university degree|degree", re.I), re.compile(r"(?:B\.?E\.?|B\.?S\.?|BSc|B\.?Tech)(?![A-Za-z])"))]
DOMAINS = ["fintech", "payments", "healthcare", "e-commerce", "ecommerce", "adtech", "ad tech", "gaming", "logistics", "cybersecurity", "security",
           "edtech", "saas", "telecom", "automotive", "robotics", "bioinformatics", "supply chain", "insurance", "banking", "real-time", "iot"]
GRAD = re.compile(r"(?:graduat\w*|class of|degree)[^.\n]{0,60}?\b(20\d{2})(?:\s*(?:,|or|and|/|-|to)\s*(20\d{2}))?|\b(20\d{2})\s+graduates?", re.I)
NO_SPONSOR = re.compile(r"(no|not (able|available|offer|provide))\W+(visa )?sponsorship|unable to sponsor|cannot sponsor|without (the need for )?sponsorship|sponsorship (is )?not (available|offered|provided)", re.I)
SPONSOR_OK = re.compile(r"(visa )?sponsorship (is )?(available|offered|provided)|we (do )?sponsor|will sponsor", re.I)
CITIZEN = re.compile(r"(u\.?s\.?|us)\s*citizen|citizens? (only|of)|citizenship (is )?required|must be a (u\.?s\.?|us)? ?citizen", re.I)
CLEARANCE = re.compile(r"security clearance|secret clearance|ts/sci|top secret", re.I)
ONSITE_ONLY = re.compile(r"on.?site (only|required)|must (be able to )?(work|be) (on.?site|in[- ]office)|relocation required|in[- ]office (\d|five|four|three)", re.I)
MIN_LEN = 120


def _clean(line: str) -> str:
    return re.sub(r"\s+", " ", line.strip().lstrip("-•*·▪●◦–— ").strip())


def _blocks(text: str) -> list[tuple[str | None, str]]:
    """-> [(section, item)] where section in mand|pref|resp|ignore|None (None = decide per item)."""
    lines = [l for l in re.split(r"\r?\n", text) if l.strip()]
    if len(lines) <= 3 and max((len(l) for l in lines), default=0) > 160:  # one paragraph blob: split into sentences
        lines = [s for s in re.split(r"(?<=[.;!?])\s+(?=[A-Z0-9])", text) if s.strip()]
    out, sec = [], None
    for l in lines:
        c = _clean(l)
        if not c:
            continue
        head = re.sub(r"[:\-–]+$", "", c).strip()
        is_head = len(head) < 60 and (c.endswith(":") or head.isupper() or len(head.split()) <= 5 and not c.endswith("."))
        if is_head and H_PREF.search(head):
            sec = "pref"
        elif is_head and H_IGNORE.search(head):
            sec = "ignore"
        elif is_head and H_RESP.search(head):
            sec = "resp"
        elif is_head and H_MAND.search(head):
            sec = "mand"
        elif is_head and not CUE_MAND.search(head) and c.endswith(":"):
            sec = None  # unknown heading: classify items by their own cues
        else:
            out.append((sec, c))
    return out


def analyse(description: str | None) -> dict:
    text = (description or "").strip()
    res = {"description_ok": len(text) >= MIN_LEN, "requirements": [], "responsibilities": [], "collaboration": [], "concepts": [], "domain": [],
           "education": [], "keywords": [], "other": [], "hints": {"graduation_years": [], "sponsorship": None, "citizenship_required": False,
                                                                   "clearance": False, "onsite_required": False, "min_years": None},
           "disqualifier_flags": []}
    if not res["description_ok"]:
        res["note"] = "The description is missing or too short to analyse. Paste the full posting to get a requirement matrix."
        return res
    seen: dict[tuple[str, str], dict] = {}
    for sec, item in _blocks(text):
        if sec == "ignore":
            continue
        kind = sec
        if kind is None:
            kind = "pref" if CUE_PREF.search(item) else "mand" if CUE_MAND.search(item) else "resp" if CUE_RESP.search(item) else "other"
        if kind == "mand" and CUE_PREF.search(item) and re.search(r"preferred|nice to have|bonus|a plus", item, re.I):
            kind = "pref"  # a preferred cue inside a requirements list wins for that line
        if COLLAB.search(item):
            res["collaboration"].append(item[:200])
        if kind == "resp":
            res["responsibilities"].append(item[:240])
        if kind == "other":
            res["other"].append(item[:200])
        if kind not in ("mand", "pref"):
            for s in {c for c, _ in taxonomy.find_skills(item)}:  # skills mentioned in duties are context, not requirements
                if s not in res["keywords"]:
                    res["keywords"].append(s)
            continue
        imp = "mandatory" if kind == "mand" else "preferred"
        for skill in sorted({c for c, _ in taxonomy.find_skills(item)}):
            cat = taxonomy.category(skill)
            if cat in ("concept", "methodology"):
                if skill not in res["concepts"]:
                    res["concepts"].append(skill)
            prev = seen.get(("skill", skill))
            if prev is None or (prev["importance"] == "preferred" and imp == "mandatory"):
                seen[("skill", skill)] = {"type": "skill", "term": skill, "importance": imp, "text": item[:240], "category": cat}
        m = YEARS.search(item)
        if m and re.search(r"experience|year", item, re.I):
            n = int(m.group(1))
            hint = sorted({c for c, _ in taxonomy.find_skills(item)})
            seen[("years", f"{n}:{hint}:{imp}")] = {"type": "experience_years", "years": n, "importance": imp, "text": item[:240], "term": ", ".join(hint) or "professional experience"}
        for level, rx, abbr in DEGREE:
            if rx.search(item) or (abbr and abbr.search(item)):
                equiv = bool(re.search(r"or equivalent|equivalent (practical )?experience", item, re.I))
                seen[("edu", level)] = {"type": "education", "level": level, "importance": imp, "text": item[:240], "term": level, "or_equivalent": equiv}
                res["education"].append(item[:200])
                break
    res["requirements"] = list(seen.values())
    low = text
    for d in DOMAINS:
        if re.search(rf"\b{re.escape(d)}\b", low, re.I) and d not in res["domain"]:
            res["domain"].append(d)
    for s, _ in taxonomy.find_skills(low):
        if s not in res["keywords"]:
            res["keywords"].append(s)
    for k in res["keywords"]:  # engineering concepts can appear in duties as well as requirements
        if taxonomy.category(k) in ("concept", "methodology") and k not in res["concepts"]:
            res["concepts"].append(k)
    h = res["hints"]
    years = set()
    for m in GRAD.finditer(low):
        years |= {int(g) for g in m.groups() if g}
    h["graduation_years"] = sorted(years)
    h["sponsorship"] = "none" if NO_SPONSOR.search(low) else "offered" if SPONSOR_OK.search(low) else None
    h["citizenship_required"] = bool(CITIZEN.search(low))
    h["clearance"] = bool(CLEARANCE.search(low))
    h["onsite_required"] = bool(ONSITE_ONLY.search(low))
    mand_years = [r["years"] for r in res["requirements"] if r["type"] == "experience_years" and r["importance"] == "mandatory"]
    h["min_years"] = max(mand_years) if mand_years else None
    flags = res["disqualifier_flags"]
    if h["sponsorship"] == "none":
        flags.append("No visa sponsorship offered")
    if h["citizenship_required"]:
        flags.append("Citizenship may be required")
    if h["clearance"]:
        flags.append("Security clearance mentioned")
    if h["onsite_required"]:
        flags.append("On-site presence required")
    if h["graduation_years"]:
        flags.append("Graduation year constraint: " + ", ".join(map(str, h["graduation_years"])))
    return res
