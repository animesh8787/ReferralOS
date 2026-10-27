# ReferralOS

A multi-user, **job-first** referral, resume-tailoring and outreach platform. Anyone can sign up, add a resume (and optionally GitHub, a portfolio, their LinkedIn connections export and an HR contact list), and the system builds a
sourced career profile, finds and **verifies** open jobs, matches them, tailors an honest resume per job, ranks the few people most worth contacting, drafts referral requests and cold emails, **waits for your approval**,
and tracks everything through to applications and outcomes.

It is built around three promises: **never invent** (every resume or message claim is checked against facts you confirmed), **never act without approval** (nothing is sent, ever, until you approve it), and **say "unknown" instead of guessing**.

> Status: all twelve build phases are complete and tested. What was and was not verified against real services is in [`docs/HANDOFF.md`](docs/HANDOFF.md) and [`docs/TEST_REPORT.md`](docs/TEST_REPORT.md). Please read those before trusting an integration.

## What works fully offline (no accounts, no keys)
Resume parsing (PDF/DOCX), profile with provenance, LinkedIn/HR CSV import and cleaning, ranking and scoring, job analysis and requirement matrices, resume tailoring and PDF/DOCX/TXT output, drafting, review/approval, manual sending (`.eml`, `mailto:`, copy buttons), tracking, export, deletion.
A deterministic mock mode (`ADAPTER_MODE=mock`, the default) simulates GitHub, job boards and Gmail so the whole workflow can be tried without touching any real service.

## What needs something outside
| Feature | Needs |
|---|---|
| GitHub / portfolio import, real job discovery | internet; `ADAPTER_MODE=real` |
| Sending through Gmail | a Google Cloud OAuth client (`GOOGLE_CLIENT_ID/SECRET`), `ADAPTER_MODE=real`, HTTPS in production |
| AI rewording of resume bullets (optional) | your own Anthropic API key (Settings) |
| Multi-user production | PostgreSQL, a worker process, TLS in front, `APP_KEK` from a secrets manager |

## Run it locally (Windows, macOS or Linux)

Requirements: Python 3.11+, [`uv`](https://docs.astral.sh/uv/), Node 20+.

```bash
# 1. API (http://localhost:8000, interactive docs at /docs)
cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --port 8000

# 2. Background worker, in a second terminal (imports, scoring, discovery, matching, sending)
cd backend
uv run python -m app.worker

# 3. Web app (http://localhost:3000)
cd frontend
npm install
npm run dev
```

Open http://localhost:3000/signup. In development the verification email is written to `data/outbox/*.json` (the `body` holds the token; paste it at `/verify`).
To run without a worker process (development only; tasks then run inside the request and sending pacing is not realistic), start the API with `TASKS_INLINE=1`.

### With Docker (PostgreSQL + API + worker + web)
```bash
cp .env.example .env     # fill in placeholders; set APP_KEK (see the file)
docker compose up --build
```
Production notes: persistent volumes for `pgdata` and `userdata` (uploads and generated files), at least one `worker`, TLS at a reverse proxy, `COOKIE_SECURE=true`, a real `APP_KEK` from a secrets manager, and replace the development mailer before exposing sign-up publicly.

## Configuration (`.env`, placeholders only in `.env.example`)
`DATABASE_URL` (SQLite by default, PostgreSQL for multi-user) · `DATA_DIR` · `APP_KEK` · `COOKIE_SECURE` · `ADAPTER_MODE` (`mock`/`real`) · `CORS_ORIGINS` · `GOOGLE_CLIENT_ID/SECRET` · `TASKS_INLINE` · `HARD_MAX_DAILY_EMAILS`, `HARD_MAX_PER_COMPANY_DAILY`.

## Using it (the guided setup at `/onboarding` walks through this)
1. **Profile** — upload a PDF/DOCX resume (or enter details by hand). Compare what was extracted with the original, confirm or fix entries. Optionally allow and fetch GitHub/portfolio suggestions (they stay *suggestions* until you confirm them).
2. **Career goals** — roles, companies, locations, graduation date, optional work authorisation (Settings).
3. **Import contacts** — *LinkedIn:* Settings & Privacy → Data privacy → Get a copy of your data → Connections, then upload the CSV. *HR/recruiters:* a CSV with company, name, title, email, phone (columns are auto-detected and mappable); you must say where the list came from. Every rejected row is kept with its reason (Imports → Inspect rows).
4. **Jobs** — add a company's public job board (Greenhouse/Lever/Ashby/Workable/SmartRecruiters URL) and press *Find jobs*; or paste a job link/description. Each job shows its verification evidence.
5. **Opportunities** — requirement matrix, eligibility checks, who to contact first, next action.
6. **Resumes** — tailor per job, check the claim report, edit, approve. Approved versions never change.
7. **Outreach** — *Prepare a new batch*, review every message and its risks, approve (approving several asks you to confirm the count and your daily limit), then send/copy. LinkedIn messages are copied and sent by you. Mark replies and outcomes in **Tracking**.
8. **Your data** — Settings → Privacy: export everything, set retention, or delete the account and all data.

## Tests
```bash
cd backend && uv run pytest -p no:warnings                 # 380+ tests, SQLite by default
TEST_DATABASE_URL=postgresql+psycopg://user:pw@localhost:5432/db uv run pytest   # same suite on PostgreSQL
cd frontend && npm run e2e                                  # browser tests (Playwright): full journey, phone layouts, accessibility audit
```
Measured results and what was mocked: [`docs/TEST_REPORT.md`](docs/TEST_REPORT.md). Performance: [`docs/PERFORMANCE.md`](docs/PERFORMANCE.md).

## Documentation
[`HANDOFF`](docs/HANDOFF.md) · [`VERIFICATION_CHECKLIST`](docs/VERIFICATION_CHECKLIST.md) (use this with your real data) · [`SCORING`](docs/SCORING.md) · [`JOB_VERIFICATION`](docs/JOB_VERIFICATION.md) · [`TAILORING`](docs/TAILORING.md) ·
[`COLD_EMAIL_COMPLIANCE`](docs/COLD_EMAIL_COMPLIANCE.md) · [`PRIVACY`](docs/PRIVACY.md) · [`SECURITY`](docs/SECURITY.md) · [`DATA_DICTIONARY`](docs/DATA_DICTIONARY.md) · [`ACCEPTANCE`](docs/ACCEPTANCE.md) · [`openapi.json`](docs/openapi.json) ·
[`DECISIONS`](docs/DECISIONS.md) · [`PLAN`](docs/PLAN.md) · [`PROGRESS`](docs/PROGRESS.md). Sample data (all fictional) is in `samples/`; large synthetic datasets come from `scripts/gen_synthetic.py`.

## Layout
`backend/` FastAPI + SQLAlchemy + Alembic (+ worker) · `frontend/` Next.js · `scripts/` sample/synthetic data, OpenAPI export, data dictionary, performance harness, real-service check · `docs/` · `samples/` · `docker-compose.yml`.
