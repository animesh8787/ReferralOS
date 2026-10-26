"""Message drafting: LinkedIn referral requests (manual send) and cold emails. Pure functions over supplied facts.

Rules enforced here and re-checked by tests:
- only supplied facts: name, degree/role, skills that the requirement matrix marks STRONG, the job title/company/official link;
- never invent a relationship, mutual connection, prior conversation, interview promise or referral programme;
- a referral programme is mentioned ONLY when the company's route is VERIFIED_REFERRAL_PROGRAM;
- every message states that the person may decline / may not be eligible;
- anything that cannot be filled in stays as a visible {{placeholder}} so the pre-send check blocks it, never a guess.
"""
import re

from ..tailoring import validate

OPT_OUT = "If you'd rather not hear from me, reply 'unsubscribe' and I won't contact you again."
LINKEDIN_BODY_MAX, CONNECT_NOTE_MAX = 1900, 300
PLACEHOLDER = re.compile(r"\{\{[^}]+\}\}")
FORBIDDEN = [re.compile(p, re.I) for p in (
    r"\bwe (met|spoke|talked|worked together)\b", r"as (we )?discussed", r"\bmutual (connection|friend|acquaintance)s?\b", r"\bour (conversation|chat|call|meeting)\b",
    r"\bi know you\b", r"\byou know me\b", r"following up on our", r"guarantee", r"\binterview (is )?(guaranteed|assured|promised)\b",
    r"\bperfect fit\b", r"\bexpert\b", r"\bproven track record\b", r"\bit was great (meeting|talking)\b", r"\bremember me\b")]


def forbidden_hits(text: str) -> list[str]:
    return [m.group(0) for rx in FORBIDDEN if (m := rx.search(text))]


def unresolved(text: str) -> list[str]:
    return PLACEHOLDER.findall(text or "")


def first_name(full: str | None) -> str | None:
    return full.split()[0].strip(",.") if full and full.split() else None


def contact_type(role_category: str | None, seniority: str | None, position: str | None, relationship_note: str | None) -> str:
    if relationship_note and relationship_note.strip():
        return "established"
    if role_category == "recruiter":
        return "recruiter"
    if role_category == "eng_manager":
        return "eng_manager"
    if role_category == "engineer":
        return "senior_engineer" if seniority in ("senior", "staff_principal") or "lead" in (position or "").lower() else "engineer"
    return "low_context"


# ---------------------------------------------------------------- facts about the sender
def sender_facts(items: list[dict], matrix: list[dict], sender_name: str | None, prof: dict | None = None) -> dict:
    """Facts a message may use. Everything here comes from active profile entries; claims carry the ids that support them."""
    act = {i["id"]: i for i in items if i["status"] == "active" and not any(f.get("type") in ("conflict", "date_order") for f in i.get("flags") or [])}
    pers = next((i for i in act.values() if i["section"] == "personal"), None)
    name = sender_name or (pers["data"].get("name") if pers else None)
    edu = next((i for i in act.values() if i["section"] == "education" and i["data"].get("degree")), None)
    exp = next((i for i in sorted([x for x in act.values() if x["section"] == "experience"], key=lambda x: x["data"].get("end") == "present", reverse=True)), None)
    intro, intro_ids = None, []
    if edu:
        d = edu["data"]
        intro = f"a {d['degree']} student" if d.get("expected") else f"a {d['degree']} graduate"
        intro += (f" in {d['discipline']}" if d.get("discipline") else "")
        intro_ids = [edu["id"]]
    elif exp:
        intro, intro_ids = f"a {exp['data'].get('title')}", [exp["id"]]
    strong = [r for r in matrix if r["type"] == "skill" and r["status"] == "STRONG_EVIDENCE" and r["fact_ids"] and all(f in act for f in r["fact_ids"])]
    strong.sort(key=lambda r: r["importance"] != "mandatory")
    skills = [r["term"] for r in strong[:3]]
    ev_ids = [f for r in strong[:3] for f in r["fact_ids"] if f in act]
    if not matrix and prof:  # no specific job (intro email): fall back to what the profile shows you have actually used
        used = sorted((n for n, v in prof["skills"].items() if v["best"] in ("USED_PROFESSIONALLY", "USED_IN_PROJECT") and not v["conflict"]),
                      key=lambda n: ({"USED_PROFESSIONALLY": 0, "USED_IN_PROJECT": 1}[prof["skills"][n]["best"]], n))[:3]
        skills = used
        ev_ids = [f for n in used for f in prof["skills"][n]["item_ids"] if f in act]
    where = None
    for f in ev_ids:
        it = act[f]
        if it["section"] == "experience" and it["data"].get("organization"):
            where = f"my work at {it['data']['organization']}"
            break
        if it["section"] == "project" and it["data"].get("name"):
            where = f"my project {it['data']['name']}"
            break
    proj = next((i for i in act.values() if i["section"] == "project" and i["data"].get("name")), None)
    return {"name": name, "first": first_name(name), "intro": intro, "intro_ids": intro_ids, "skills": skills, "skill_ids": ev_ids, "where": where, "project": proj}


def _join(xs: list[str]) -> str:
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1]


def alignment(f: dict) -> tuple[str | None, list[str]]:
    if not f["skills"]:
        return None, []
    s = f"I've worked with {_join(f['skills'])}" + (f" in {f['where']}" if f["where"] else "") + ", which overlaps with what the role asks for."
    return s, list(dict.fromkeys(f["skill_ids"]))


def intro_sentence(f: dict) -> tuple[str, list[str]]:
    if f["intro"]:
        return f"I'm {f['name'] or '{{your_name}}'}, {f['intro']}.", f["intro_ids"]
    return f"I'm {f['name'] or '{{your_name}}'}.", []


def _greet(tone: str, first: str | None) -> str:
    return (f"Hello {first}," if first else "Hello,") if tone == "formal" else (f"Hi {first}," if first else "Hello,")


def _close(tone: str, name: str | None, variant: str = "A") -> str:
    n = name or "{{your_name}}"
    if tone == "formal":
        return f"Thank you for your time and consideration.\n\nBest regards,\n{n}"
    return (f"Thanks so much,\n{n}" if variant == "A" else f"Thank you either way,\n{n}")


def _job_line(job: dict, kind: str) -> str:
    link = job.get("apply_url") or "{{job_link}}"
    noun = "internship" if job.get("employment_type") == "internship" else "role"
    return f"I'm interested in the {job['title']} {noun} at {job['company']} ({link})."


def _ask(ask: str, company: str, route: dict | None, ctype: str, variant: str) -> str:
    verified = bool(route and route.get("status") == "VERIFIED_REFERRAL_PROGRAM")
    if ask == "guidance":
        return ("Would you be willing to point me to the best way to apply, or share any advice about the role? "
                "Please feel free to decline; I realise you're busy.")
    if ctype == "recruiter":
        base = "Could you let me know the best way to be considered for it, and whether a referral is possible?"
    elif verified:
        base = f"I understand {company} has an employee referral program ({route.get('evidence_url')}). If you're able to refer me for this role, I'd be grateful."
    else:
        base = ("If you're able to refer candidates for this role, I'd be grateful for a referral." if variant == "A"
                else "If referrals are something you can do for this role, I'd really appreciate your help.")
    return base + " I understand if you can't, or if you're not eligible to refer; please feel free to decline."


# ---------------------------------------------------------------- LinkedIn referral request (manual send)
def referral_message(f: dict, ct: dict, job: dict, route: dict | None, o: dict) -> dict:
    """ct: first, position, role_category, seniority, relationship_note. o: tone, length, ask(referral|guidance), variant."""
    tone, variant, length = o.get("tone", "conversational"), o.get("variant", "A"), o.get("length", "short")
    ctype = o.get("contact_type") or contact_type(ct.get("role_category"), ct.get("seniority"), ct.get("position"), ct.get("relationship_note"))
    ledger = []
    intro, iids = intro_sentence(f)
    ledger.append(("intro", intro, iids))
    lines = [_greet(tone, ct.get("first"))]
    if ctype == "established":
        lines.append(f"I wanted to reach out about something specific. {ct['relationship_note'].strip()}")  # the user's own words, verbatim
    elif ct.get("position") and ctype in ("engineer", "senior_engineer", "eng_manager"):
        lines.append(f"I see you're listed as {ct['position']} at {job['company']}.")
    lines.append(intro)
    lines.append(_job_line(job, "referral"))
    al, aids = alignment(f)
    if al:
        lines.append(al)
        ledger.append(("alignment", al, aids))
    if length == "medium" and f.get("project"):
        pj = f"I've also built {f['project']['data']['name']}."
        lines.append(pj)
        ledger.append(("project", pj, [f["project"]["id"]]))
    if o.get("extra"):
        lines.append(o["extra"])  # other roles at the same company this person could help with: ONE message per person
    lines.append(_ask(o.get("ask", "referral"), job["company"], route, ctype, variant))
    lines.append(_close(tone, f["name"], variant))
    body = "\n\n".join(lines)
    # connection note: tiny, honest, <= 300 chars; drop optional parts rather than cutting words
    first = ct.get("first")
    parts = [f"Hi {first}," if first else "Hi,", f"I'm {f['name'] or '{{your_name}}'}" + (f", {f['intro']}" if f["intro"] else "") + ".",
             f"I'm interested in the {job['title']} role at {job['company']} and would value your advice.", (job.get("apply_url") or "")]
    note = " ".join(p for p in parts if p)
    for drop in (3, 1):
        if len(note) <= CONNECT_NOTE_MAX:
            break
        parts[drop] = ""
        note = " ".join(p for p in parts if p)
    return {"channel": "linkedin", "kind": "referral", "subject": None, "body": body, "connect_note": note[:CONNECT_NOTE_MAX], "contact_type": ctype,
            "ledger": ledger, "uses_relationship_note": ctype == "established"}


# ---------------------------------------------------------------- cold emails
def _sig(f: dict, sender_email: str | None) -> str:
    return f"{f['name'] or '{{your_name}}'}" + (f"\n{sender_email}" if sender_email else "")


def subject_options(kind: str, f: dict, job: dict | None, company: str) -> list[str]:
    n = f["name"] or "{{your_name}}"
    if kind == "cold_intro":
        return [f"Question about engineering opportunities at {company}", f"Introduction from {n}: engineering at {company}", f"Who should I ask about roles at {company}?"]
    return [f"{job['title']} at {company}: interested candidate", f"Question about the {job['title']} role", f"{job['title']} role at {company} ({n})"]


def cold_email(kind: str, f: dict, to: dict, job: dict | None, company: str, o: dict, sender_email: str | None, resume_attached: bool) -> dict:
    """kind: cold_job (a real, verified opening) | cold_intro (no specific opening: clearly says so)."""
    tone, variant = o.get("tone", "conversational"), o.get("variant", "A")
    ledger = []
    intro, iids = intro_sentence(f)
    ledger.append(("intro", intro, iids))
    lines = [_greet(tone, to.get("first")), intro]
    if kind == "cold_job":
        lines.append(_job_line(job, "cold") + (" I'm writing to ask whether the team is still reviewing applications." if variant == "A" else " Could you tell me whether it's still open to new applicants?"))
    else:
        lines.append(f"I'm not writing about a specific posting. I'm trying to find out whether {company} has roles that could suit my background, or who the right person to ask would be.")
    al, aids = alignment(f)
    if al:
        lines.append(al)
        ledger.append(("alignment", al, aids))
    if o.get("extra"):
        lines.append(o["extra"])
    if resume_attached:
        lines.append("I've attached my resume.")
    lines.append("If there's nothing suitable right now, I'd appreciate being pointed to the right place. Thank you for your time." if kind == "cold_intro"
                 else "I'd welcome the chance to be considered, and I understand if the timing isn't right.")
    lines.append(OPT_OUT)
    lines.append(("Best regards," if tone == "formal" else "Thanks,") + "\n" + _sig(f, sender_email))
    subs = subject_options(kind, f, job, company)
    return {"channel": "email", "kind": kind, "subject": subs[0], "subject_options": subs, "body": "\n\n".join(lines), "connect_note": None,
            "ledger": ledger, "uses_relationship_note": False}


def follow_up(f: dict, to: dict, original_subject: str, original_sent_at, job: dict | None, company: str, o: dict, sender_email: str | None, n: int) -> dict:
    tone = o.get("tone", "conversational")
    when = original_sent_at.strftime("%d %b %Y") if original_sent_at else "{{original_date}}"
    what = f"the {job['title']} role at {company}" if job else f"opportunities at {company}"
    lines = [_greet(tone, to.get("first")),
             f"I'm following up on my email of {when} about {what}. I know inboxes get busy, so a one-line reply is plenty, even if the answer is that there's nothing right now.",
             OPT_OUT, ("Best regards," if tone == "formal" else "Thanks,") + "\n" + _sig(f, sender_email)]
    return {"channel": "email", "kind": "follow_up", "subject": f"Follow-up: {original_subject}"[:200], "subject_options": [], "body": "\n\n".join(lines), "connect_note": None,
            "ledger": [], "uses_relationship_note": False, "follow_up_number": n}


def thank_you(f: dict, to: dict, user_text: str, original_subject: str, o: dict, sender_email: str | None) -> dict:
    """The user's own words, wrapped with a greeting and signature. Nothing is added to the substance."""
    lines = [_greet(o.get("tone", "conversational"), to.get("first")), user_text.strip(), OPT_OUT, "Thanks,\n" + _sig(f, sender_email)]
    return {"channel": "email", "kind": "thank_you", "subject": f"Thank you: {original_subject}"[:200], "subject_options": [], "body": "\n\n".join(lines), "connect_note": None,
            "ledger": [], "uses_relationship_note": False}


def check_claims(ledger: list[tuple], items: list[dict]) -> list[dict]:
    """Validate each claim against the profile (same rules as resumes). -> ledger dicts with status."""
    by = {i["id"]: i for i in items}
    out = []
    for n, (kind, text, ids) in enumerate(ledger, 1):
        c = {"id": f"m{n:02d}", "kind": "bullet", "label": kind, "text": text, "fact_ids": ids}
        c["status"], c["reasons"] = validate.validate_claim(c, by) if ids else ("validated", [])  # no facts cited = no factual claim made
        out.append(c)
    return out
