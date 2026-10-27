# Job discovery and verification methodology

## Sources (each an adapter; each can be switched off in Settings → Job sources)

| Source | How | Status of verification |
|---|---|---|
| Greenhouse, Lever, Ashby, Workable, SmartRecruiters | the vendors' **public job-board APIs**, using a board token the user supplies or confirms | written from vendor documentation; tested against hand-built fixtures that follow the documented shapes; see `docs/REAL_SERVICE_CHECK.md` for what was exercised live |
| schema.org `JobPosting` (JSON-LD) | a page URL the user supplies; `robots.txt` respected | fixtures |
| Manual add | a pasted description (stays private to the user and `UNKNOWN`) or a URL | tests |

Crawler etiquette (all outbound fetches go through one `PoliteFetcher`): honest `User-Agent`, `robots.txt` honoured for pages, SSRF guard (no private/loopback addresses, re-checked on every redirect, ≤3 redirects),
exponential back-off with a `Retry-After` cap, response size cap, per-domain concurrency, in-run caching. Board APIs are documented public JSON endpoints; page fetches always respect robots.
**No LinkedIn scraping, no search-engine evidence, no unofficial endpoints.**

Board discovery is *suggest-and-confirm*: a guessed token can belong to a different company, so candidates show sample job titles and are only used after the user confirms them.
Every run records **coverage honestly** — boards reachable vs not, and how many of the companies you know people at have *no reachable board* (those jobs are simply not covered).

## Canonical jobs and de-duplication

One position seen on several sources becomes one `Job` with several `JobSource` rows, so there is one outreach strategy per job. Matching order: same `(source, board, source id)` → same apply URL →
same company with an equal canonical key or a very similar title (≥ 92 token-set similarity) and a compatible location. A job of another company, another city, or another owner's *private* pasted job is never merged.

## Statuses and the rules (`services/job_verify.py::decide`, a pure function)

Evidence kinds (append-only, timestamped, shown on the job page): `api_listed` (the company's board API lists it) · `api_absent` · `page_gone` (404/410) · `page_closed_text` ("no longer accepting applications", "position has been filled", …) ·
`page_ok` (HTTP 200) · `jsonld_valid` · `inaccessible` (network error, 5xx, robots-blocked). A search-engine hit is **not** an evidence kind.

| Status | When |
|---|---|
| `ACTIVE_VERIFIED` | the latest decisive evidence is a **fresh** (≤ 3 days) `api_listed` and the deadline has not passed |
| `ACTIVE_UNCONFIRMED` | listed but stale, or listed with a passed deadline; or only a loading page / structured data |
| `POSSIBLY_CLOSED` | any negative signal newer than the last listing that does not amount to closed; or a passed deadline with no listing |
| `CLOSED` | the official listing is gone/closed **and** the job is absent from the board API, both fresh, with no later listing |
| `UNKNOWN` | nothing conclusive (including pasted jobs and unreachable sources) |

Consequences that are enforced and tested: **HTTP 200 alone is not proof**; a 404 alone or an absence alone is only `POSSIBLY_CLOSED`; an inaccessible page or board **never** closes a job;
contradictory evidence at the same instant resolves to the cautious side; only `ACTIVE_VERIFIED` jobs enter the default outreach queue; `CLOSED`/`POSSIBLY_CLOSED` jobs get no drafts and existing drafts are flagged stale
and cannot be approved; stale evidence (> 3 days) is re-verified before drafts are prepared.

## Referral route (per company, per user)

`VERIFIED_REFERRAL_PROGRAM` only when an **official page the user points us at** matches a referral-programme phrase (the page URL and an excerpt are stored); `NO_PUBLIC_EVIDENCE` when pages were read and nothing was found;
`UNKNOWN` when pages could not be read; `REFERRAL_ROUTE_UNCONFIRMED` / `NOT_APPLICABLE` can be set by the user, but a user cannot self-declare a verified programme.
Message wording may mention a programme **only** when it is verified; otherwise it asks whether a referral is possible.
