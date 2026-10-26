# Progress

| Phase | Status |
|---|---|
| 1 Plan | done |
| 2 Foundation | done (compose/Docker written, NOT yet run: verified in Phase 11) |
| 3 Profile | done |
| 4 Contacts | done |
| 5 Scoring core | done |
| 6 Jobs | done |
| 7 Matching | done |
| 8 Tailoring | done |
| 9 Outreach | next |
| 10-12 | pending |

Tests: backend 257 passing (`cd backend && uv run pytest -p no:warnings`).
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

Phase 5 covers: role/seniority/domain classifier, General Referral Priority Score (6 weighted components, configurable weights
normalised to 100, neutral|exclude missing-data policy) with a SEPARATE confidence score (completeness/source/freshness/
consistency/verified-vs-inferred), tiers 100/400/500 with deterministic tie-breakers and no duplicates, stored config snapshot +
inputs so every score is reproducible (tested), company intelligence endpoint, CSV (formula-injection-safe) and Excel exports,
Prospects + Companies UI (build only, not browser-tested).
Measured (SQLite, synthetic): scoring 11,000 contacts 9.4s (~1,170/s); prospects page query (filtered, offset 4,900) 842ms;
xlsx export of 11,000 rows 7.9s; LinkedIn import 11,000 rows 17.4s including the automatic scoring follow-up.
Known gaps: employment status is inferred from connection age only (never verified); hiring relevance has no open-role input until
Phase 6; role keyword rules are English-only and untested on real titles.

Phase 6 covers: Greenhouse/Lever/Ashby/Workable/SmartRecruiters adapters + schema.org JobPosting parser, user-confirmed boards
(suggestions are candidates only, with sample titles), discovery task with honest coverage report (reachable boards, companies you
know people at that have no reachable board), canonical dedup (same source id -> same apply URL -> same company + similar title/
compatible place; private pasted jobs never merged across users), verification state machine (all 5 statuses, 21 table cases incl.
200-is-not-proof, 404-alone-is-not-closed, stale evidence, contradictory same-time evidence resolves conservatively), referral-route
discovery (programme can only be VERIFIED from an official page; absence = NO_PUBLIC_EVIDENCE; unreadable = UNKNOWN), Jobs UI.
INTEGRATION STATUS: all five ATS adapters were written from vendor docs and tested ONLY against hand-built fixtures (app/adapters/
fake_ats.py). They have never been run against live services; payload-shape mistakes are possible. Planned: one read-only smoke
check per ATS in Phase 11 if network access is allowed.
Known gaps: no job-detail fetch for SmartRecruiters descriptions (list endpoint has none); location compatibility is city-string based.
Perf numbers vary by run (SQLite, synthetic): 11k LinkedIn import 7.8-17.4s incl. auto-scoring; scoring 11k 5.2-9.4s.

Phase 7 covers: deterministic JD analyser (mandatory vs preferred, skills via taxonomy synonyms, years/degree/graduation/
sponsorship/citizenship/clearance hints; short descriptions reported, never invented), requirement matrix (5 statuses, honest
"no evidence != lacks skill" wording, skill-specific years, related-skill partials), eligibility constraints (SATISFIED/VIOLATED/
UNCERTAIN + review actions, profile never edited), Job Match Score (5 weighted components, configurable, shared missing-data
policy), job-specific contact score (employment is inferred unless the USER verifies it; recommend 1-5 per job; one person fitting
several jobs is linked via also_fits_jobs), Opportunity Priority Score with readiness groups (verified+eligible first;
closed last) and explicit trade-off text, next-action rules, Opportunities UI (build only).
Acceptance scenarios covered by API tests: 1 (verified job + verified contact), 3 (uncertain employment), 6 (several jobs,
consolidated contacts), 7 (missing graduation data), plus closed-job ranking and per-user isolation.
Bugs found by tests and fixed this phase: "be" inside prose matched as a B.E. degree; short one-paragraph postings were not split into
sentences; legacy single-byte CSVs were mis-detected (now UTF-8 -> UTF-16 BOM -> Windows-1252 -> detector).
Known gaps: job-specific contact scores are computed for the 40 best general-ranked contacts per company (top 10 stored);
JD heuristics are English-only and unproven on real postings; work-authorisation matching is keyword-based.

Phase 8 covers: tailoring engine that only SELECTS/ORDERS/GROUPS existing profile facts (bullets verbatim; skills only from
active profile entries; education/dates copied exactly; conflicted entries left out and reported; suggestions never used),
claim ledger (every text node has a claim id -> supporting fact ids) with a single validator that also checks user edits and LLM
rewrites (no new technologies/numbers/names), missing metrics become questions not numbers, Resume Match Score (internal estimate,
labelled as not an ATS score) with only-if-true improvement hints, PDF/DOCX/TXT rendered from one document model with a post-render
check (reopen files, selectable text, hyperlinks survive, no tables), 7-file bundle per version (+zip), version history, approve
(blocked while claims need confirmation or render check fails), approved versions immutable (edits/regeneration create new versions),
explicit confirm-claim path into the master (new profile version), compare, workspace UI (build only, not browser-tested).
Acceptance 13 and 14 covered by API tests.
Known gaps: no spell/grammar checker (text is verbatim user text or fixed templates); no hosted LLM client (interface + validation
only; NoLLM default); PDF fonts are Latin-1 only (other scripts become '?'); role-type layouts are heuristic.
