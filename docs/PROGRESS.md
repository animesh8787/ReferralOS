# Progress

| Phase | Status |
|---|---|
| 1 Plan | done |
| 2 Foundation | done (compose/Docker written, NOT yet run: verified in Phase 11) |
| 3 Profile | done |
| 4 Contacts | next |
| 5-12 | pending |

Tests: backend 76 passing (`cd backend && uv run pytest -p no:warnings`).
Phase 3 covers: PDF/DOCX parsing (single/two-column/table/image-only/corrupt), span-traceable extraction, skill evidence levels,
conflict/duplicate/date-order flags, profile versions, completeness + questions, GitHub + portfolio import against fakes
(404, rate limit, fork, tutorial flag, robots, SSRF), polite fetcher, consents, isolation walker over all id routes.
Frontend: profile pages build + typecheck; NOT exercised in a browser yet (E2E in Phase 10/11).
Known gaps: GitHub token support (needs encrypted settings, Phase 10); GitHub/portfolio never run against real network;
no OCR (Tesseract absent); parser is heuristic/English-only, tested on synthetic resumes only (real-resume accuracy unknown until user verification).
Resume rule: read this file first, continue from the first non-done phase.
