"""Create, edit, approve and store tailored resume versions. Every change creates a NEW version; approved rows are never touched."""
import copy
import hashlib
import json
from datetime import date

from sqlalchemy import func
from sqlalchemy.orm import Session

from ... import storage
from ...models.contacts import Company
from ...models.jobs import Job
from ...models.matching import UserJobMatch
from ...models.profile import ProfileItem, ProfileVersion
from ...models.tailoring import TailoredResume
from ...util import utcnow
from .. import jd_analysis, matching, profile as profile_svc, scoring_run
from ..llm import NoLLM, get_provider
from ..matching_run import job_domains
from . import diff, engine, render, score as rscore, validate

EDITABLE = {"bullet"}


def items_for(db: Session) -> list[dict]:
    return [profile_svc.serialize(i) for i in db.query(ProfileItem).filter(ProfileItem.status.in_(("active", "suggested"))).all()]


def resume_status(db: Session, job_id: str) -> dict:
    rows = db.query(TailoredResume.id, TailoredResume.status, TailoredResume.version).filter(TailoredResume.job_id == job_id).order_by(TailoredResume.version.desc()).all()
    appr = next((r for r in rows if r.status == "approved"), None)
    if appr:
        return {"status": "approved", "resume_id": appr.id, "version": appr.version}
    return {"status": "draft", "resume_id": rows[0].id, "version": rows[0].version} if rows else {"status": "not_started", "resume_id": None, "version": None}


def _analysis(db: Session, job: Job) -> dict:
    m = db.query(UserJobMatch).filter(UserJobMatch.job_id == job.id).first()
    dh = hashlib.sha1((job.description or "").encode()).hexdigest()
    return m.analysis if m and m.desc_hash == dh else jd_analysis.analyse(job.description)


def _finish(db: Session, job: Job, content: dict, ledger: list[dict], items: list[dict], analysis: dict, matrix: list[dict], notes: dict,
            questions: list[dict], options: dict, parent: TailoredResume | None) -> TailoredResume:
    node_ids = {cid for cid, _ in engine.render_nodes(content)}
    val = validate.validate_all(ledger, items, node_ids)
    cfg = {"missing_policy": scoring_run.get_config(db)["missing_policy"]}
    sc = rscore.score(content, analysis, matrix, questions, cfg)
    pdf, dx, txt = render.to_pdf(content), render.to_docx(content), render.to_txt(content)
    val["render_check"] = render.check_render(content, pdf, dx)
    changes = diff.vs_master(content, items, notes, matrix)
    last = db.query(func.max(TailoredResume.version)).filter(TailoredResume.job_id == job.id).scalar() or 0
    pv = db.query(ProfileVersion).order_by(ProfileVersion.version.desc()).first()
    row = TailoredResume(job_id=job.id, version=last + 1, parent_id=parent.id if parent else None, status="draft", content=content, ledger=ledger,
                         validation=val, score=sc, changes=changes, questions=questions, options=options, matrix=matrix,
                         profile_version=pv.version if pv else 0, score_total=sc["total"])
    db.add(row)
    db.flush()
    cname = (db.get(Company, job.company_id).name if job.company_id else "") or ""
    files = {
        "resume.pdf": pdf, "resume.docx": dx, "resume.txt": txt.encode(),
        "requirement_matrix.json": json.dumps(matrix, indent=2, default=str).encode(),
        "validation_report.json": json.dumps({**val, "ledger": ledger}, indent=2, default=str).encode(),
        "diff.json": json.dumps(changes, indent=2, default=str).encode(),
        "tailoring_summary.md": _summary_md(job, cname, row, sc, val, changes, questions).encode(),
    }
    for name, data in files.items():
        storage.put_bundle(row.user_id, row.id, name, data)
    row.files = sorted(files)
    return row


def _summary_md(job: Job, company: str, row: TailoredResume, sc: dict, val: dict, ch: dict, qs: list[dict]) -> str:
    L = [f"# Tailored resume: {job.title} at {company}", f"Version {row.version} · created {utcnow():%Y-%m-%d %H:%M} UTC · status {row.status}", "",
         f"**Resume Match Score: {sc['total']:.0f}/100.** {sc['label']}", "", "## Validation",
         f"- {val['validated']} of {val['claims_total']} claims validated against your profile",
         f"- {len(val['needs_confirmation'])} need your confirmation; {len(val['excluded'])} left out; {len(val['unresolved_contradictions'])} unresolved contradictions",
         f"- Render check: {'passed' if val['render_check']['ok'] else 'PROBLEMS: ' + '; '.join(val['render_check']['problems'])}", "", "## Requirements your background does not (yet) support"]
    L += [f"- {r['term']} ({r['importance']}): {r['status'].replace('_', ' ').lower()}" for r in ch["unsupported_requirements"]] or ["- none"]
    L += ["", "## Questions for you"] + ([f"- {q['text']}" for q in qs] or ["- none"])
    L += ["", "Your master profile was not changed. Nothing from the job description was added to your resume without evidence."]
    return "\n".join(L) + "\n"


def create(db: Session, job: Job, options: dict | None = None, parent: TailoredResume | None = None) -> TailoredResume:
    items, analysis = items_for(db), _analysis(db, job)
    prof = matching.summarize_profile(items, date.today())
    matrix = matching.build_matrix(analysis, prof)
    jinfo = {"title": job.title, "company": (db.get(Company, job.company_id).name if job.company_id else None), "employment_type": job.employment_type,
             "domains": job_domains(job, analysis)}
    llm = get_provider()
    built = engine.build(items, analysis, matrix, jinfo, options, llm=None if isinstance(llm, NoLLM) else llm)
    return _finish(db, job, built["content"], built["ledger"], items, analysis, matrix, built["notes"], built["questions"], options or {}, parent)


def edit(db: Session, parent: TailoredResume, bullet_edits: list[dict], exclude_claims: list[str]) -> TailoredResume:
    """User edits produce a new version. Edited text is re-validated against its source facts; anything the facts do not
    contain is flagged needs_confirmation and blocks approval until the user confirms it into the master."""
    job = db.get(Job, parent.job_id)
    content, ledger = copy.deepcopy(parent.content), copy.deepcopy(parent.ledger)
    by = {c["id"]: c for c in ledger}
    for ed in bullet_edits:
        c = by.get(ed["claim_id"])
        if not c or c["kind"] != "bullet":
            raise ValueError(f"Claim {ed['claim_id']} is not an editable bullet")
        text = " ".join(str(ed["text"]).split())[:400]
        if not text:
            raise ValueError("A bullet cannot be empty; exclude it instead")
        c["text"], c["edited"] = text, True
        for sec in ("experience", "projects"):
            for e in content.get(sec, []):
                for b in e["bullets"]:
                    if b["claim_id"] == c["id"]:
                        b["text"] = text
    for cid in exclude_claims:
        if cid not in by:
            raise ValueError(f"Unknown claim {cid}")
        by[cid].update(dropped=True, status="excluded", reasons=["Removed by you."])
        for sec in ("experience", "projects"):
            for e in content.get(sec, []):
                e["bullets"] = [b for b in e["bullets"] if b["claim_id"] != cid]
    items, analysis = items_for(db), _analysis(db, job)
    matrix = matching.build_matrix(analysis, matching.summarize_profile(items, date.today()))
    notes = {"left_out": parent.changes.get("left_out_of_resume", []), "rewrites_used": 0, "rewrites_rejected": []}
    return _finish(db, job, content, [c for c in ledger], items, analysis, matrix, notes, parent.questions, parent.options, parent)


def confirm_claim(db: Session, parent: TailoredResume, claim_id: str) -> TailoredResume:
    """The ONLY path from a resume edit into the master profile, and only on the user's explicit request."""
    c = next((x for x in parent.ledger if x["id"] == claim_id), None)
    if not c or c["status"] != "needs_confirmation" or not c["fact_ids"]:
        raise ValueError("This claim does not need confirmation")
    item = db.query(ProfileItem).filter(ProfileItem.id == c["fact_ids"][0]).first()
    if not item:
        raise ValueError("The supporting profile entry no longer exists")
    data = dict(item.data)
    key = "bullets" if item.section == "experience" else "description"
    data[key] = list(data.get(key) or []) + [c["text"]]
    item.data, item.verified = data, True
    profile_svc.snapshot(db, f"Confirmed claim from tailored resume {parent.version}")
    db.flush()
    job = db.get(Job, parent.job_id)
    content, ledger = copy.deepcopy(parent.content), copy.deepcopy(parent.ledger)
    items, analysis = items_for(db), _analysis(db, job)
    matrix = matching.build_matrix(analysis, matching.summarize_profile(items, date.today()))
    return _finish(db, job, content, ledger, items, analysis, matrix, {"left_out": [], "rewrites_used": 0, "rewrites_rejected": []}, parent.questions, parent.options, parent)


def approve(db: Session, r: TailoredResume) -> TailoredResume:
    if r.status == "approved":
        return r
    if not r.validation["ok_to_approve"]:
        raise ValueError("This version has claims that need your confirmation or unsupported text; resolve them first")
    if not r.validation["render_check"]["ok"]:
        raise ValueError("The generated files failed the render check: " + "; ".join(r.validation["render_check"]["problems"]))
    r.status, r.approved_at = "approved", utcnow()
    return r
