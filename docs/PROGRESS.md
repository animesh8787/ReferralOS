# Progress

| Phase | Status |
|---|---|
| 1 Plan | done |
| 2 Foundation | done (compose/Docker written, NOT yet run: verified in Phase 11) |
| 3 Profile | done |
| 4 Contacts | done |
| 5 Scoring core | next |
| 6-12 | pending |

Tests: backend 102 passing (`cd backend && uv run pytest -p no:warnings`).
Phase 3 covers: PDF/DOCX parsing (single/two-column/table/image-only/corrupt), span-traceable extraction, skill evidence levels,
conflict/duplicate/date-order flags, profile versions, completeness + questions, GitHub + portfolio import against fakes
(404, rate limit, fork, tutorial flag, robots, SSRF), polite fetcher, consents, isolation walker over all id routes.
Frontend: profile pages build + typecheck; NOT exercised in a browser yet (E2E in Phase 10/11).
Known gaps: GitHub token support (needs encrypted settings, Phase 10); GitHub/portfolio never run against real network;
no OCR (Tesseract absent); parser is heuristic/English-only, tested on synthetic resumes only (real-resume accuracy unknown until user verification).
Resume rule: read this file first, continue from the first non-done phase.

Phase 4 covers: LinkedIn + HR CSV import (encoding/delimiter/preamble detection, column mapping, resumable background task, verbatim
source rows, per-row reasons, import report that always sums), conservative company normalisation + review queue, URL/name dedup
(never name alone), email validation (role/noreply flags, optional MX not exercised), E.164 phones, required HR provenance with
purchased-list bulk block, per-user suppression list (survives re-import), HR<->LinkedIn linking, retention purge, paginated APIs,
Imports/Contacts/Do-not-contact UI (build + typecheck only; not driven in a browser yet).
Measured (SQLite, this machine, 1 worker, synthetic data): 11,000 LinkedIn rows in 7.8s (~1,400 rows/s); 5,000 HR rows in 6.1s
(~820 rows/s); search+page query over ~16k contacts 294ms. Not yet measured on Postgres.
Known gaps: MX check path only unit-tested via injected resolver; role/seniority classifiers arrive in Phase 5; 'Connected On'
parser tries a fixed list of formats (ambiguous dd/mm vs mm/dd is read as mm/dd).
