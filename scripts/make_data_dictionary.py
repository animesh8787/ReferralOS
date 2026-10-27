"""Generates docs/DATA_DICTIONARY.md from the SQLAlchemy models, so the documentation cannot drift from the schema.
Run:  cd backend && uv run python ../scripts/make_data_dictionary.py"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import app.models  # noqa: E402,F401
from app.db import Base, UserScoped  # noqa: E402
from app.services.privacy import SECRET_COLS  # noqa: E402

GROUPS = {
    "Accounts, sessions and system": ["users", "auth_sessions", "email_tokens", "audit_logs", "background_tasks", "user_settings", "llm_usage"],
    "Master Career Profile": ["resumes", "profile_items", "profile_versions"],
    "Contacts and imports": ["imports", "import_rows", "contacts", "email_contacts", "suppression_entries", "companies", "user_company_aliases", "company_reviews"],
    "Scoring": ["contact_scores"],
    "Jobs (shared public data + per-user views)": ["jobs", "job_sources", "job_verifications", "user_boards", "user_jobs", "discovery_runs", "referral_routes"],
    "Matching": ["user_job_matches", "job_contact_scores"],
    "Tailored resumes": ["tailored_resumes"],
    "Outreach": ["campaigns", "outreach_batches", "outreach_pairs", "outreach_messages", "email_events", "oauth_tokens"],
}
NOTES = {
    "users": "Account. password_hash is Argon2id; never exported or returned.", "auth_sessions": "Server-side sessions; only a SHA-256 of the cookie token is stored.",
    "email_tokens": "Verification / reset tokens, hashed, single use.", "audit_logs": "Per-user audit trail. Metadata only: no message text, emails or tokens.",
    "background_tasks": "DB-backed job queue: progress, checkpoint (resume), retries, redacted failure report.",
    "user_settings": "Key/value JSON per user: consents ('consent.*'), scoring/matching/outreach config, sources, notifications, encrypted LLM key (never exported).",
    "resumes": "Immutable uploaded originals (file stored separately under data/users/<id>/resumes).", "profile_items": "One fact group per row with provenance (source, source_ref, source_span, verified, confidence, flags).",
    "profile_versions": "Immutable snapshot of active profile entries after each change.", "imports": "One CSV upload (LinkedIn or HR), mapping, provenance, report.",
    "import_rows": "Source records, verbatim (raw JSON), status and reasons for every row. Purged by retention settings.", "contacts": "LinkedIn connections. Employment is inferred unless the user verified it.",
    "email_contacts": "HR/recruiter contacts, separate from connections; flags, E.164 phone, provenance, bulk_send_blocked.", "suppression_entries": "Per-user do-not-contact list (emails/domains); survives re-imports.",
    "companies": "SHARED reference data (public company names). Which user knows a company is only visible through that user's own contacts.", "user_company_aliases": "The user's own resolutions of ambiguous company names.",
    "company_reviews": "Ambiguous fuzzy company matches awaiting user review.", "contact_scores": "General Referral Priority Score with components, confidence, inputs and config snapshot (reproducible).",
    "jobs": "SHARED canonical public postings. Pasted/private jobs carry owner_user_id and are never merged or listed for others.", "job_sources": "Every place a canonical job was seen.",
    "job_verifications": "Append-only timestamped evidence for the open/closed decision.", "user_boards": "ATS boards the user wants searched.", "user_jobs": "Which jobs a user sees (and hides).",
    "discovery_runs": "Coverage report per discovery run.", "referral_routes": "Per user+company: programme status with evidence; never assumed.", "user_job_matches": "Per user+job: requirement matrix, eligibility, match score, opportunity priority.",
    "job_contact_scores": "Job-specific contact scores (top few per job).", "tailored_resumes": "Versioned tailored resumes with claim ledger, validation report, score and diff. Approved versions are immutable.",
    "campaigns": "Optional grouping with its own (lower) daily limit and pause.", "outreach_batches": "A reviewed set of drafts; records the count+limit confirmation.",
    "outreach_pairs": "Job-contact (or company-contact) pipeline status.", "outreach_messages": "Drafts and sent messages (LinkedIn manual, email), approval and send state, risk flags, claim ledger.",
    "email_events": "SENT, DELIVERY_UNCONFIRMED, BOUNCED_*, REPLIED, UNSUBSCRIBE_REQUESTED, ... with user-correctable labels.", "oauth_tokens": "Gmail OAuth tokens, envelope-encrypted; never returned or exported.",
    "llm_usage": "Per-call token and estimated cost metadata only.",
}


def col(c):
    flags = [("PK" if c.primary_key else ""), ("FK→" + next(iter(c.foreign_keys)).column.table.name if c.foreign_keys else ""), ("unique" if c.unique else ""), ("indexed" if c.index else ""),
             ("not null" if not c.nullable and not c.primary_key else ""), ("SECRET" if c.name in SECRET_COLS else "")]
    return f"| `{c.name}` | {str(c.type)} | {', '.join(x for x in flags if x)} |"


def main():
    tables = {t.name: t for t in Base.metadata.sorted_tables}
    scoped = {m.__tablename__ for m in Base.registry.mappers if False} | {mp.class_.__tablename__ for mp in Base.registry.mappers if issubclass(mp.class_, UserScoped)}
    seen, out = set(), ["# Data dictionary", "", "Generated from the SQLAlchemy models by `scripts/make_data_dictionary.py` (do not edit by hand).", "",
                        "**Tenancy.** Tables marked *user-scoped* have a non-null, indexed `user_id`; every query in a request is filtered centrally by it, inserts are stamped and mismatches rejected. "
                        "*Shared* tables hold only public reference data. Source data (import rows, original uploads) is kept separate from derived data (scores, matches, drafts).", ""]
    for group, names in GROUPS.items():
        out += [f"## {group}", ""]
        for n in names:
            t = tables[n]
            seen.add(n)
            kind = "user-scoped" if n in scoped else "shared" if n in ("companies", "jobs", "job_sources", "job_verifications") else "per-user (explicit user_id)"
            out += [f"### `{n}` ({kind})", NOTES.get(n, ""), "", "| Column | Type | Notes |", "|---|---|---|"] + [col(c) for c in t.columns]
            idx = [f"`{i.name}` ({', '.join(c.name for c in i.columns)})" for i in t.indexes]
            uq = [f"({', '.join(c.name for c in u.columns)})" for u in t.constraints if u.__class__.__name__ == "UniqueConstraint" and len(u.columns) > 1]
            if idx:
                out.append(f"\nIndexes: {'; '.join(idx)}")
            if uq:
                out.append(f"\nUnique together: {'; '.join(uq)}")
            out.append("")
    missing = set(tables) - seen
    assert not missing, f"tables missing from the dictionary groups: {missing}"
    (ROOT / "docs/DATA_DICTIONARY.md").write_text("\n".join(out), encoding="utf-8")
    print(f"wrote docs/DATA_DICTIONARY.md for {len(seen)} tables")


if __name__ == "__main__":
    main()
