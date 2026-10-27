# Test report
Synthetic data (fictional people, example.com) and mock integrations unless stated.

| Suite | Result |
|---|---|
| Backend, SQLite | 402 passed |
| Backend, PostgreSQL 16.14 | 401 passed on the second full run; the one failure was a test doing json.loads on a JSON column (Postgres returns a dict). Test fixed and passes on both DBs; the full Postgres suite was not re-run after that fix. |
| Browser (Playwright) | Full journey, phone-width layout, axe audit (0 serious/critical). Re-run after the final fixes: 3 passed. |
| 14 acceptance scenarios | Mapped to tests in ACCEPTANCE.md |

## Bugs found during validation (fixed)
1. Postgres only: outreach_messages.approval_state was varchar(16), "awaiting_approval" is 17 chars (migration 0010). 60 tests failed only on Postgres.
2. Postgres only: NUL byte in a query string caused a 500; now 422.
3. Log redaction did not cover child loggers.
4. Real GitHub API: repos with language=null crashed the importer (found only by the real-service check; regression test added).

## Real services
Read-only public GETs to GitHub and the Greenhouse, Lever, Ashby, Workable, SmartRecruiters board APIs worked (REAL_SERVICE_CHECK.md). Gmail, OAuth and the LLM were never contacted (mock only).

## Not verified
Real, messy resumes; docker compose end to end; SQLite with several simultaneous heavy writers.
5. Log redaction collapsed log args, which made uvicorn's access logger raise "Logging error" on every request (seen in the browser-test server output); it now redacts each argument in place.
