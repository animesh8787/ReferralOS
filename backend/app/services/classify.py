"""Deterministic role / seniority / domain classification from a job title. Pure functions, keyword rules.

Titles are inputs we were given, so the result is an *inference*; callers keep the matched keyword for explanations.
"""
import re

_R = lambda p: re.compile(p, re.I)  # noqa: E731
RECRUITER = _R(r"recruit|talent acquisition|talent partner|talent sourc|sourcer|\bhr\b|human resources|people (partner|operations|ops)|staffing|\bta (partner|lead|manager)\b")
ENG_MANAGER = _R(r"(engineering|software|development|data|ml|machine learning|platform|infrastructure|technical|devops) (manager|lead manager)|manager,? (of )?(engineering|software|platform)|head of engineering|\bem\b")
LEADERSHIP = _R(r"\b(cto|ceo|coo|vp|vice president|chief|director|head of|founder|co-founder|cofounder|president|partner)\b")
PRODUCT = _R(r"product (manager|owner|lead)|program manager|project manager|\bpm\b|\btpm\b")
ENGINEER = _R(r"engineer|developer|\bswe\b|\bsde\b|programmer|architect|devops|\bsre\b|scientist|researcher|tech(nical)? lead|machine learning|\bml\b|software|backend|frontend|full.?stack")

DOMAINS = {
    "backend": _R(r"back.?end|server|\bapi\b|distributed|microservice|java\b|golang|\bgo\b|python"),
    "frontend": _R(r"front.?end|\bui\b|\bux\b|web developer|react|angular|vue"),
    "fullstack": _R(r"full.?stack"),
    "ml_ai": _R(r"machine learning|\bml\b|\bai\b|artificial intelligence|deep learning|nlp|computer vision|data scientist|llm|research scientist|applied scientist"),
    "data": _R(r"\bdata\b|analytics|etl|big data|warehouse|\bbi\b"),
    "platform_cloud": _R(r"platform|infrastructure|devops|\bsre\b|reliability|cloud|kubernetes|aws|gcp|azure|systems"),
    "mobile": _R(r"android|\bios\b|mobile|flutter|react native"),
    "security": _R(r"security|appsec|infosec|cyber"),
}


def role_category(position: str | None) -> tuple[str, str | None]:
    """-> (category, matched keyword). Order matters: recruiter > eng_manager > leadership > product > engineer."""
    if not position or not position.strip():
        return "unknown", None
    for cat, rx in (("recruiter", RECRUITER), ("eng_manager", ENG_MANAGER), ("leadership", LEADERSHIP),
                    ("product", PRODUCT), ("engineer", ENGINEER)):
        m = rx.search(position)
        if m:
            return cat, m.group(0).lower()
    return "other", None


def seniority(position: str | None, category: str) -> tuple[str, str | None]:
    if not position:
        return "unknown", None
    p = position.lower()
    for level, rx in (("intern", r"\bintern(ship)?\b|trainee|apprentice"), ("director_plus", r"\b(director|vp|vice president|chief|cto|ceo|president|founder|co-founder)\b|head of"),
                      ("staff_principal", r"\b(staff|principal|distinguished|fellow)\b"), ("manager", r"manager"),
                      ("senior", r"\b(senior|sr\.?|lead)\b|\bsde\s?(iii|3)\b|\b(iii|3)\b"),
                      ("junior", r"\b(junior|jr\.?|graduate|entry)\b|\b(associate)\b|\bsde\s?(i|1)\b|engineer (i|1)\b")):
        m = re.search(rx, p)
        if m:
            return level, m.group(0)
    if category == "engineer":
        return "mid", None  # plain "Software Engineer": a typical mid-level title; marked as inferred by the missing keyword
    return "unknown", None


def domain_tags(text: str | None) -> set[str]:
    return {t for t, rx in DOMAINS.items() if text and rx.search(text)}


def classify(position: str | None) -> dict:
    cat, kw = role_category(position)
    sen, skw = seniority(position, cat)
    return {"role_category": cat, "role_keyword": kw, "seniority": sen, "seniority_keyword": skw, "domains": sorted(domain_tags(position))}
