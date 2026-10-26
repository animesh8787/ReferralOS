"""Claim-ledger validation. A claim is {id, kind, text, fact_ids, status, reasons}. It is `validated` only when
  1. it cites at least one existing, ACTIVE profile fact (suggestions the user has not confirmed do not count),
  2. none of those facts carries an unresolved conflict / date-order problem, and
  3. every technology and every number in the text also appears in the cited facts.
Anything else is `excluded` (no usable support) or `needs_confirmation` (the user wrote or implied something the facts
do not contain). The same function checks generated text, user edits and LLM rewrites.
"""
import re

from .. import taxonomy

NUM = re.compile(r"\d+(?:[.,]\d+)?%?")
BLOCKING = {"conflict", "date_order"}


def strings(obj) -> list[str]:
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, dict):
        return [s for v in obj.values() for s in strings(v)]
    if isinstance(obj, (list, tuple)):
        return [s for v in obj for s in strings(v)]
    return []


def fact_text(items_by_id: dict, ids: list[str]) -> str:
    return " \n ".join(s for i in ids if i in items_by_id for s in strings(items_by_id[i]["data"]))


def ungrounded(text: str, facts: str) -> dict:
    """Technologies and numbers present in `text` but absent from `facts` (synonyms normalised via the taxonomy)."""
    return {"tech": sorted(taxonomy.skill_set(text) - taxonomy.skill_set(facts)),
            "numbers": sorted(set(NUM.findall(text)) - set(NUM.findall(facts)))}


def validate_claim(claim: dict, items_by_id: dict) -> tuple[str, list[str]]:
    ids = claim.get("fact_ids") or []
    facts = [items_by_id[i] for i in ids if i in items_by_id]
    if not facts:
        return "excluded", ["No supporting fact in your profile."]
    if any(f["status"] != "active" for f in facts):
        return "excluded", ["The supporting fact is only a suggestion you have not confirmed."]
    bad = [f for f in facts if any(fl.get("type") in BLOCKING for fl in f.get("flags") or [])]
    if bad:
        return "excluded", ["The supporting fact has an unresolved conflict. Resolve it in your profile first."]
    if claim["kind"] == "skill":
        return "validated", []
    g = ungrounded(claim["text"], fact_text(items_by_id, ids))
    reasons = []
    if g["tech"]:
        reasons.append("Mentions technology not found in the supporting facts: " + ", ".join(g["tech"]))
    if g["numbers"]:
        reasons.append("Contains numbers not found in the supporting facts: " + ", ".join(g["numbers"]))
    return ("needs_confirmation", reasons) if reasons else ("validated", [])


def validate_all(ledger: list[dict], items: list[dict], content_ids: set[str] | None = None) -> dict:
    """Re-validates every claim in place and returns the report. content_ids: claims actually present in the resume."""
    by_id = {i["id"]: i for i in items}
    for c in ledger:
        if c.get("dropped"):  # the user removed it; it stays excluded, never silently comes back
            continue
        c["status"], c["reasons"] = validate_claim(c, by_id)
    inc = [c for c in ledger if content_ids is None or c["id"] in content_ids]
    present_excluded = [c["id"] for c in inc if c["status"] == "excluded" and not c.get("dropped")]
    contradictions = [{"item_id": i["id"], "section": i["section"], "flags": [f for f in i.get("flags") or [] if f.get("type") in BLOCKING]}
                      for i in items if i["status"] == "active" and any(f.get("type") in BLOCKING for f in i.get("flags") or [])]
    return {"claims_total": len(inc), "validated": sum(1 for c in inc if c["status"] == "validated"),
            "needs_confirmation": [{"claim_id": c["id"], "text": c["text"], "reasons": c["reasons"]} for c in inc if c["status"] == "needs_confirmation"],
            "excluded": [{"claim_id": c["id"], "text": c["text"], "reasons": c["reasons"]} for c in ledger if c["status"] == "excluded"],
            "unresolved_contradictions": contradictions, "excluded_claims_in_resume": present_excluded,
            "ok_to_approve": not any(c["status"] == "needs_confirmation" for c in inc) and not present_excluded}


def check_rewrite(original: str, rewritten: str) -> list[str]:
    """Reasons to REJECT an LLM rewrite of an existing bullet. Empty list = acceptable."""
    why = []
    g = ungrounded(rewritten, original)
    if g["tech"]:
        why.append("adds technology: " + ", ".join(g["tech"]))
    if g["numbers"]:
        why.append("adds numbers: " + ", ".join(g["numbers"]))
    orig_words = {w.lower() for w in re.findall(r"[A-Za-z][\w'-]*", original)}
    new_caps = [w for w in re.findall(r"(?<!^)(?<![.!?] )\b[A-Z][a-zA-Z]+\b", rewritten) if w.lower() not in orig_words]
    if new_caps:
        why.append("adds names/terms: " + ", ".join(sorted(set(new_caps))))
    if len(rewritten) > max(260, int(len(original) * 1.5)):
        why.append("is much longer than the original")
    return why
