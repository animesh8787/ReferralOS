# Decisions

See the "Key technical decisions" table in PLAN.md. Additions are appended below with dates.

- 2026-10-26: Git: local commit per phase, plain messages, no push, no AI attribution (user instruction).
- 2026-10-26: Docker engine was not running at start; Postgres verification is deferred to Phase 11 (I will start Docker Desktop then).
- 2026-10-26: Profile stored at item level (one row per job/project/skill) with provenance per item, not per field; edits replace the item's data and snapshot a version.
- 2026-10-26: Task claiming is optimistic UPDATE (atomic on SQLite and Postgres) rather than FOR UPDATE SKIP LOCKED.
- 2026-10-26: Re-importing a resume never overwrites; differing data under the same key becomes a flagged 'suggested' conflict.
- 2026-10-26: GitHub token support deferred until encrypted per-user settings exist; only public data is read.
