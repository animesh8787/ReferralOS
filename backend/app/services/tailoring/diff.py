"""What changed relative to the master profile, and which requirements the background does not support."""
import difflib

from . import render


def vs_master(content: dict, items: list[dict], notes: dict, matrix: list[dict]) -> dict:
    act = {i["id"]: i for i in items if i["status"] == "active"}
    exp = []
    for e in content.get("experience", []):
        total = len(act[e["item_id"]]["data"].get("bullets") or []) if e["item_id"] in act else 0
        kept = [b["source_index"] for b in e["bullets"]]
        omitted = [t for k, t in enumerate(act[e["item_id"]]["data"].get("bullets") or []) if k not in kept] if e["item_id"] in act else []
        exp.append({"role": f"{e['title']}, {e['organization']}", "bullets_kept": len(kept), "bullets_in_master": total, "omitted": omitted,
                    "reworded": [b["text"] for b in e["bullets"] if e["item_id"] in act and b["text"] not in (act[e["item_id"]]["data"].get("bullets") or [])]})
    shown = {p["item_id"] for p in content.get("projects", [])}
    projects = [i for i in act.values() if i["section"] == "project"]
    first_skills = [i["name"] for g in content.get("skills", []) for i in g["items"]][:8]
    return {
        "master_unchanged": True,  # tailoring only reads the profile; edits to facts happen elsewhere, by explicit confirmation
        "summary": "added" if content.get("summary") else "not generated (not enough supported facts)",
        "section_order": content["section_order"], "role_type": content.get("role_type"),
        "skills_listed_first": first_skills, "experience": exp,
        "projects_included": [p["name"] for p in content.get("projects", [])],
        "projects_left_out": [i["data"].get("name") for i in projects if i["id"] not in shown],
        "left_out_of_resume": notes.get("left_out", []),
        "unsupported_requirements": [{"term": r["term"], "type": r["type"], "importance": r["importance"], "status": r["status"], "why": r["explanation"]}
                                     for r in matrix if r["status"] in ("NO_EVIDENCE", "NEEDS_VERIFICATION", "CONFLICTING_EVIDENCE")],
        "llm_rewrites": {"used": notes.get("rewrites_used", 0), "rejected": notes.get("rewrites_rejected", [])},
    }


def text_diff(a_content: dict, b_content: dict) -> str:
    a, b = render.to_txt(a_content).splitlines(), render.to_txt(b_content).splitlines()
    return "\n".join(difflib.unified_diff(a, b, "version A", "version B", lineterm="", n=1))
