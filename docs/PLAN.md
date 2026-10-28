# ReferralOS — Build Plan

## Context
The user wants ReferralOS built from scratch in `C:\Users\anime\Desktop\Referral Portal` (currently **empty**). It is a multi-user job-search platform. Each user can upload a resume, add GitHub and portfolio links, and import LinkedIn connections and HR contact CSVs. The app builds a Master Career Profile, finds and verifies jobs, scores matches, tailors resumes using a claim ledger, ranks contacts, drafts honest referral requests and cold emails, sends Gmail only after approval, and tracks outcomes. The spec (v2, Sections 0–20) is the source of truth. This plan sets the stack, the architecture and the order of work so the build can run on its own through Phase 12 and end in a working app, tests, docs and a handoff report.

## Environment (inspected)
- Windows 11, 12 cores, 15.7 GB RAM, about 160 GB free disk.
- Installed:
  - Python 3.11.9 and `uv`, with FastAPI 0.116, SQLAlchemy 2.0, Alembic, Pydantic 2.11, pdfplumber, PyMuPDF, pypdf, python-docx, reportlab, openpyxl, pandas, RapidFuzz, scikit-learn, httpx, cryptography and pytest.
  - Node 24 with npm 11.
  - Playwright Chromium browsers.
  - git, with identity `Animesh` already configured.
- Docker Desktop is installed, but its engine is **not running**. There is no local Postgres, Redis, Tesseract, LibreOffice or pandoc.
- User decisions:
  - **git init plus one local commit per phase**, using the existing git identity. Never push.
  - **I start Docker Desktop myself** when I reach the Postgres/compose verification step.

## Key technical decisions (each goes into `docs/DECISIONS.md`)
| Area | Decision | Why |
|---|---|---|
| Backend | FastAPI + SQLAlchemy 2.0 + Alembic + Pydantic v2 in `backend/.venv` (uv) | Spec stack; mostly installed already |
| DB | SQLite for local dev and default tests; Postgres in docker-compose; the same Alembic migrations run on both | No local Postgres; spec allows SQLite single-user |
| Job queue | **DB-backed queue** (`background_tasks` table) and a `python -m app.worker` process. Postgres claims jobs with `FOR UPDATE SKIP LOCKED`; SQLite uses an atomic `UPDATE…WHERE status='queued'`. Supports retries with a limit, progress, a checkpoint JSON, failure reports and resume-on-restart. Tests run tasks inline. | No Redis, RQ does not work on Windows, and the DB doubles as the broker. Compose therefore needs no separate broker. |
| Auth | argon2-cffi (Argon2id); server-side sessions (hashed token, HttpOnly + SameSite=Lax cookie, Secure when on HTTPS); double-submit CSRF (`csrf` cookie + `X-CSRF-Token` header); email-verify and reset tokens stored hashed; dev mailer writes to `data/outbox/`; Google sign-in is an OAuth+PKCE adapter that stays disabled until configured | Simple and standard |
| Rate limit | In-process sliding window keyed by user/IP and route group (auth, uploads, exports, send) | `shortcut: per-process memory, move to DB/Redis for multi-instance` |
| Crypto | Envelope encryption with AES-GCM: a per-record DEK wrapped by a KEK from `APP_KEK` env. Used for OAuth tokens, user LLM keys and SMTP creds. A redacting log filter covers emails, phone numbers and tokens. | Spec 2.4 |
| Storage | `Storage` interface with a `LocalStorage` implementation at `data/users/{uid}/…`. Paths are built from IDs only, which blocks path traversal. S3 is documented as an extension point and is not implemented. | Smallest version that meets the spec; S3 is optional |
| Frontend | Next.js (App Router) + TypeScript + Tailwind + Radix primitives (accessible). Next rewrites `/api/*` to FastAPI, so cookies are same-origin. SWR handles data fetching. The funnel chart is plain CSS bars, with no chart library. | Spec stack; avoids CORS/cookie trouble |
| E2E | `@playwright/test` uses the installed Chromium, with the backend in `ADAPTER_MODE=mock` | Spec 15.1 |
| LLM | `LLMProvider` protocol with `NoLLM` (the deterministic default), `MockLLM` (tests) and `AnthropicLLM` (user's own key, encrypted, budget-capped, fields redacted before sending). LLM output always goes through validation. | Spec 2.6 |
| External APIs | Every adapter has a real implementation over httpx plus a fake that uses `httpx.MockTransport`: GitHub REST, Gmail API (OAuth+PKCE, `gmail.send` scope, plus `gmail.readonly` only when reply tracking is opted in), Greenhouse/Lever/Ashby/Workable/SmartRecruiters public boards, and schema.org `JobPosting` JSON-LD. Outbound HTTP goes through one polite fetcher: robots.txt check, honest User-Agent, backoff, a per-domain concurrency limit and a cache. | Spec 5.1, 15.4 |
| New deps | backend: `argon2-cffi`, `pydantic-settings`, `python-multipart`, `email-validator` (brings `dnspython` for the optional MX check), `phonenumbers`, `charset-normalizer`; frontend: next, react, tailwind, radix, swr, @playwright/test | Smallest set |
| Not available | OCR: Tesseract is missing, so image-only PDFs are detected and flagged with a manual-entry prompt. DOCX render checks run by reopening the file with python-docx and checking hyperlinks; PDF checks render pages with PyMuPDF and extract text and links. | Documented limitation |

## Repo layout
```
backend/  app/{main,config,db,security,crypto,ratelimit,audit,tasks,worker,storage}.py
          app/models/{core,profile,contacts,jobs,matching,tailoring,outreach}.py
          app/api/{auth,me,profile,resumes,imports,contacts,companies,jobs,matches,opportunities,tailoring,outreach,campaigns,settings,diagnostics,admin}.py
          app/services/  resume_parse, profile, github, portfolio, csv_import, contacts, companies,
                         email_validate, phone, taxonomy(+data/skills.json), scoring, jobs/{sources,dedup,verify,referral_route},
                         jd_analysis, eligibility, match, tailoring/{engine,ledger,render,check}, outreach/{templates,drafts,preflight,send,followups,replies,compliance}, exports, privacy
          app/adapters/  http (polite fetcher), llm, gmail, mailer, github_api, ats/*
          migrations/  tests/{unit,integration,acceptance,security}  pyproject.toml
frontend/ src/app/(auth)/… src/app/(app)/{onboarding,dashboard,profile,imports,jobs,opportunities,resumes,contacts,companies,outreach,tracking,settings,guide,diagnostics,privacy}
          src/components/{DataTable,ColumnMapper,ScoreBreakdown,ProvenanceBadge,StatusBadge,States,ConfirmDialog,…}  src/lib/api.ts  e2e/
scripts/  gen_synthetic.py  make_sample_resumes.py  perf.py  export_openapi.py
docs/     PLAN DECISIONS PROGRESS + Section 16 docs + VERIFICATION_CHECKLIST + HANDOFF
docker-compose.yml (postgres, api, worker, web)  .env.example  .gitignore  README.md
```

## Core mechanisms (written once, reused everywhere)
1. **Tenancy (central).** A `UserScoped` mixin (`user_id` FK, indexed, non-null) plus a SQLAlchemy `do_orm_execute` hook that applies `with_loader_criteria(UserScoped, user_id == session.info["user_id"])` to every SELECT in a request session. A `before_flush` hook stamps `user_id` on inserts and rejects mismatches. `get_owned_or_404()` is the only by-ID lookup helper. Shared tables (`companies`, `company_aliases`, `jobs`, `job_sources`, `job_verifications`, `referral_routes`) are not `UserScoped`. Per-user data about them lives in user-scoped tables. A generic isolation test walks every OpenAPI route with path IDs, plus list, export and file endpoints, and runs them as user B against user A's IDs.
2. **Provenance.** Every fact or derived field carries `source`, `source_ref`, `confidence`, `verified`, `observed_at`/`updated_at`. Source rows (import rows, original uploads) stay immutable. Derived columns and tables are kept separate.
3. **Scores.** Pure functions `score(inputs, weights) -> {total, components, explanations, confidence}`. Every score row stores `scoring_version` and a `config_snapshot` JSON, so it can be reproduced. Unknown is not negative: the missing-data policy (`neutral` by default, or `exclude`) is applied in one place, and its effect on confidence is recorded.
4. **Job verification.** A pure function `next_status(evidence[]) -> status` for the five statuses and the rules in 5.3. Every attempt becomes a `job_verifications` row. Re-verification is required before a draft if the last check is older than the staleness window (default 3 days).
5. **Claim ledger.** Tailoring and messaging both build `[{claim_text, fact_ids, status}]` first. Any claim without facts is dropped. Any claim that rests on a conflicted fact is blocked. Tech names and numbers in the output must appear in the linked facts. LLM rewrites that fail this check fall back to the original bullet.
6. **Send gate.** One `preflight(message) -> [blocking_reasons]` function is used by every send path. It checks approval, suppression and do-not-contact, an earlier initial email, the domain blocklist, job active, unresolved `{{placeholders}}`, sender identity, attachments, daily/per-company/introductory limits under hard maximums, global and campaign pause, jurisdiction/provenance blocks and the opt-out line. The worker sends with random pacing. A timeout or unclear response becomes `DELIVERY_UNCONFIRMED` and is never retried automatically. Reconciliation searches the Sent folder by our own `Message-ID`, when read scope is granted.
7. **CSV import (shared by LinkedIn and HR).** It detects encoding (charset-normalizer), delimiter (`csv.Sniffer`) and preamble lines, auto-maps columns with manual override, and runs as a background task with progress. The import report covers read/valid/duplicate/invalid/missing counts and the reason for every rejected row, so nothing is dropped silently. Suppression entries are keyed by normalised email and outlive re-imports.

## Execution phases (each ends runnable + tests green + PROGRESS.md updated + one local commit)
1. **Plan.** `git init` and `.gitignore` (data/, .env*, uploads, outbox, synthetic outputs, .venv, node_modules), plus `docs/PLAN.md` (one page), `DECISIONS.md` and `PROGRESS.md`.
2. **Foundation.** Backend skeleton, config, DB with tenancy hooks, Alembic baseline, auth (signup, verify, login, logout, reset, sessions, CSRF), rate limits, audit log, DB task queue and worker, storage, crypto, `/api/admin/health`, `/api/me/export` and `/api/me/delete` (generic over all UserScoped models plus files). Also the Next.js shell with login/signup and the API wrapper, and compose and `.env.example`. **Tests:** auth, CSRF, isolation walker, task retries/resume, delete completeness.
3. **Profile.** PDF parsing (PyMuPDF blocks with column-aware ordering, pdfplumber fallback), DOCX parsing, image-only detection, section heuristics with text-span traceability, facts, versions and conflicts, the completeness meter and questions. GitHub (repos, languages, topics, README, fork/boilerplate flags; suggestions need confirmation) and portfolio (robots-respecting text and link extraction). Profile editor UI with an extracted-vs-original view. **Tests:** synthetic PDF/DOCX/multi-column/empty/malformed/image-only files, mocked GitHub cases (404, rate limit, fork, private).
4. **Contacts.** LinkedIn and HR importers, the mapping UI, company normalisation (suffix rules, alias table, RapidFuzz with a high threshold, a review queue), dedup (URL key, or conservative name+company, never name alone), email validation (syntax, role accounts, optional MX; no SMTP probing), E.164 phone numbers, the required provenance question, the suppression list, `email_contacts` with an optional link to the matching connection. **Tests:** every import case in 15.1.
5. **Scoring core.** Role category and seniority classifiers, Referral Priority Score plus confidence, tiers (100/400/500, no duplicates, tie-breakers), weight normalisation, and CSV and Excel exports (openpyxl, with frozen headers, filters and a summary sheet). Includes the contacts and companies UI.
6. **Jobs.** The 5 ATS adapters plus JSON-LD and manual add, suggestions for ATS boards from a company's careers URL or slug (a suggestion is never trusted until the user confirms it), canonical dedup, the verification state machine, referral-route detection from official pages, and the jobs UI. **Tests:** hand-built fixtures that follow each documented schema (labelled as such), dedup, all five statuses.
7. **Matching.** JD analysis (mandatory vs preferred, using a taxonomy with synonyms), the requirement matrix, eligibility constraints, Job Match Score, the job-specific contact score with recommendations for the top 1–3 per company, consolidation, Opportunity Priority Score with the trade-off shown, and the opportunities UI.
8. **Tailoring.** Engine (project ranking, skill reordering, section order by role type, summary built from facts only, questions about missing metrics), the ledger and validation report, Resume Match Score, PDF/DOCX/TXT output plus `requirement_matrix.json`, `validation_report.json`, `tailoring_summary.md` and the diff, render and link checks, immutable approved versions. Includes the workspace UI.
9. **Outreach.** Referral templates (6 role types, plus tone, length, internship vs full-time and referral-vs-guidance ask; a 300-character LinkedIn note version), the 4 cold-email types, subject options and A/B variants, compliance (jurisdiction from location or ccTLD, acknowledgements, purchased-list block), batch review, the send gate, Gmail/Mock/Manual (`.eml`, `mailto:`, CSV) adapters with SMTP off by default, a disabled LinkedIn stub, the worker sender, reply/bounce classification, follow-up drafts (never sent automatically) and the pair status pipeline.
10. **Frontend integration.** All 12 pages wired to real APIs, the onboarding wizard, the dashboard funnel, settings, guide, privacy, diagnostics, dry-run mode and "send test email to myself", with loading, empty and error states and keyboard navigation.
11. **Synthetic validation.** `gen_synthetic.py` produces fictional people at fictional companies, `example.com`/`.test` addresses and a `synthetic=true` flag: 11k LinkedIn rows, 5k HR rows, 500 jobs and 3 users. Covers the 14 acceptance tests, the Playwright end-to-end flow, `perf.py` (only measured numbers are reported), and **starting Docker Desktop** to run pytest plus compose against Postgres. Fix bugs and run again.
12. **Docs and handoff.** All docs from Section 16, `openapi.json`, the test report (real vs mocked, stated plainly), `VERIFICATION_CHECKLIST.md` and `HANDOFF.md`.

## Honesty and safety guardrails during the build
- No real email or message is sent at any point. Gmail and GitHub run against mocks unless the user provides credentials. A public read-only GitHub or ATS call may be run once for a smoke check, and the report states whether it ran.
- Synthetic data uses only reserved domains and invented names. No real people, and no hiring claims about real companies.
- The report marks every integration as verified-real, mock-only or untested.

## Verification
- `cd backend && uv run pytest` (SQLite). With `TEST_DATABASE_URL` pointing at the Postgres container, the same suite runs against Postgres.
- `cd frontend && npx playwright test`: the full flow from sign-up to account deletion, with mock adapters.
- `python scripts/perf.py` writes measured throughput and latency to `docs/TEST_REPORT.md`.
- `docker compose up` starts postgres, api, worker and web, and the health endpoint responds.
- Manual: start both servers and click through onboarding to batch review in the browser.

## After approval
- Check `PROGRESS.md` at the start of every phase. That file is where work resumes after context compaction.
