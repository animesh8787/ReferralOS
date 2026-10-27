# Data dictionary

Generated from the SQLAlchemy models by `scripts/make_data_dictionary.py` (do not edit by hand).

**Tenancy.** Tables marked *user-scoped* have a non-null, indexed `user_id`; every query in a request is filtered centrally by it, inserts are stamped and mismatches rejected. *Shared* tables hold only public reference data. Source data (import rows, original uploads) is kept separate from derived data (scores, matches, drafts).

## Accounts, sessions and system

### `users` (per-user (explicit user_id))
Account. password_hash is Argon2id; never exported or returned.

| Column | Type | Notes |
|---|---|---|
| `email` | VARCHAR(320) | unique, indexed, not null |
| `password_hash` | VARCHAR(255) | not null, SECRET |
| `role` | VARCHAR(16) | not null |
| `email_verified` | BOOLEAN | not null |
| `display_name` | VARCHAR(200) | not null |
| `id` | VARCHAR(32) | PK |
| `created_at` | DATETIME | not null |

Indexes: `ix_users_email` (email)

### `auth_sessions` (per-user (explicit user_id))
Server-side sessions; only a SHA-256 of the cookie token is stored.

| Column | Type | Notes |
|---|---|---|
| `user_id` | VARCHAR(32) | FK→users, indexed, not null |
| `token_hash` | VARCHAR(64) | unique, not null, SECRET |
| `csrf_token` | VARCHAR(64) | not null, SECRET |
| `expires_at` | DATETIME | not null |
| `id` | VARCHAR(32) | PK |
| `created_at` | DATETIME | not null |

Indexes: `ix_auth_sessions_user_id` (user_id)

### `email_tokens` (per-user (explicit user_id))
Verification / reset tokens, hashed, single use.

| Column | Type | Notes |
|---|---|---|
| `user_id` | VARCHAR(32) | FK→users, indexed, not null |
| `kind` | VARCHAR(16) | not null |
| `token_hash` | VARCHAR(64) | unique, not null, SECRET |
| `expires_at` | DATETIME | not null |
| `used` | BOOLEAN | not null |
| `id` | VARCHAR(32) | PK |
| `created_at` | DATETIME | not null |

Indexes: `ix_email_tokens_user_id` (user_id)

### `audit_logs` (per-user (explicit user_id))
Per-user audit trail. Metadata only: no message text, emails or tokens.

| Column | Type | Notes |
|---|---|---|
| `user_id` | VARCHAR(32) | FK→users, indexed |
| `action` | VARCHAR(64) | indexed, not null |
| `detail` | JSON | not null |
| `id` | VARCHAR(32) | PK |
| `created_at` | DATETIME | not null |

Indexes: `ix_audit_logs_user_id` (user_id); `ix_audit_logs_action` (action)

### `background_tasks` (user-scoped)
DB-backed job queue: progress, checkpoint (resume), retries, redacted failure report.

| Column | Type | Notes |
|---|---|---|
| `kind` | VARCHAR(64) | indexed, not null |
| `status` | VARCHAR(16) | indexed, not null |
| `payload` | JSON | not null |
| `progress` | FLOAT | not null |
| `checkpoint` | JSON | not null |
| `attempts` | INTEGER | not null |
| `max_attempts` | INTEGER | not null |
| `error` | TEXT |  |
| `result` | JSON |  |
| `heartbeat_at` | DATETIME |  |
| `finished_at` | DATETIME |  |
| `id` | VARCHAR(32) | PK |
| `created_at` | DATETIME | not null |
| `user_id` | VARCHAR(32) | FK→users, indexed, not null |

Indexes: `ix_background_tasks_kind` (kind); `ix_background_tasks_status` (status); `ix_background_tasks_user_id` (user_id)

### `user_settings` (user-scoped)
Key/value JSON per user: consents ('consent.*'), scoring/matching/outreach config, sources, notifications, encrypted LLM key (never exported).

| Column | Type | Notes |
|---|---|---|
| `key` | VARCHAR(100) | not null |
| `value` | JSON | not null |
| `id` | VARCHAR(32) | PK |
| `created_at` | DATETIME | not null |
| `user_id` | VARCHAR(32) | FK→users, indexed, not null |

Indexes: `ix_user_settings_user_id` (user_id)

Unique together: (user_id, key)

### `llm_usage` (user-scoped)
Per-call token and estimated cost metadata only.

| Column | Type | Notes |
|---|---|---|
| `kind` | VARCHAR(30) | not null |
| `model` | VARCHAR(60) | not null |
| `input_tokens` | INTEGER | not null |
| `output_tokens` | INTEGER | not null |
| `est_cost_usd` | FLOAT | not null |
| `id` | VARCHAR(32) | PK |
| `created_at` | DATETIME | not null |
| `user_id` | VARCHAR(32) | FK→users, indexed, not null |

Indexes: `ix_llm_usage_user_id` (user_id)

## Master Career Profile

### `resumes` (user-scoped)
Immutable uploaded originals (file stored separately under data/users/<id>/resumes).

| Column | Type | Notes |
|---|---|---|
| `filename` | VARCHAR(255) | not null |
| `ext` | VARCHAR(8) | not null |
| `size` | INTEGER | not null |
| `sha256` | VARCHAR(64) | not null |
| `status` | VARCHAR(16) | not null |
| `raw_text` | TEXT |  |
| `parse_info` | JSON | not null |
| `id` | VARCHAR(32) | PK |
| `created_at` | DATETIME | not null |
| `user_id` | VARCHAR(32) | FK→users, indexed, not null |

Indexes: `ix_resumes_user_id` (user_id)

### `profile_items` (user-scoped)
One fact group per row with provenance (source, source_ref, source_span, verified, confidence, flags).

| Column | Type | Notes |
|---|---|---|
| `section` | VARCHAR(24) | indexed, not null |
| `data` | JSON | not null |
| `status` | VARCHAR(12) | indexed, not null |
| `source` | VARCHAR(16) | not null |
| `source_ref` | VARCHAR(255) |  |
| `source_span` | JSON |  |
| `verified` | BOOLEAN | not null |
| `confidence` | FLOAT | not null |
| `evidence_level` | VARCHAR(24) |  |
| `flags` | JSON | not null |
| `updated_at` | DATETIME | not null |
| `id` | VARCHAR(32) | PK |
| `created_at` | DATETIME | not null |
| `user_id` | VARCHAR(32) | FK→users, indexed, not null |

Indexes: `ix_profile_items_status` (status); `ix_profile_items_user_id` (user_id); `ix_profile_items_section` (section)

### `profile_versions` (user-scoped)
Immutable snapshot of active profile entries after each change.

| Column | Type | Notes |
|---|---|---|
| `version` | INTEGER | not null |
| `reason` | VARCHAR(120) | not null |
| `snapshot` | JSON | not null |
| `id` | VARCHAR(32) | PK |
| `created_at` | DATETIME | not null |
| `user_id` | VARCHAR(32) | FK→users, indexed, not null |

Indexes: `ix_profile_versions_user_id` (user_id)

## Contacts and imports

### `imports` (user-scoped)
One CSV upload (LinkedIn or HR), mapping, provenance, report.

| Column | Type | Notes |
|---|---|---|
| `kind` | VARCHAR(12) | not null |
| `filename` | VARCHAR(255) | not null |
| `status` | VARCHAR(12) | not null |
| `provenance` | VARCHAR(24) |  |
| `provenance_note` | VARCHAR(300) |  |
| `encoding` | VARCHAR(24) | not null |
| `delimiter` | VARCHAR(2) | not null |
| `header_row` | INTEGER | not null |
| `mapping` | JSON | not null |
| `report` | JSON | not null |
| `region` | VARCHAR(2) | not null |
| `id` | VARCHAR(32) | PK |
| `created_at` | DATETIME | not null |
| `user_id` | VARCHAR(32) | FK→users, indexed, not null |

Indexes: `ix_imports_user_id` (user_id)

### `import_rows` (user-scoped)
Source records, verbatim (raw JSON), status and reasons for every row. Purged by retention settings.

| Column | Type | Notes |
|---|---|---|
| `import_id` | VARCHAR(32) | FK→imports, indexed, not null |
| `row_number` | INTEGER | not null |
| `raw` | JSON | not null |
| `status` | VARCHAR(10) | not null |
| `reasons` | JSON | not null |
| `id` | VARCHAR(32) | PK |
| `created_at` | DATETIME | not null |
| `user_id` | VARCHAR(32) | FK→users, indexed, not null |

Indexes: `ix_import_rows_user_id` (user_id); `ix_import_rows_import_status` (import_id, status); `ix_import_rows_import_id` (import_id)

### `contacts` (user-scoped)
LinkedIn connections. Employment is inferred unless the user verified it.

| Column | Type | Notes |
|---|---|---|
| `source` | VARCHAR(12) | not null |
| `import_id` | VARCHAR(32) | FK→imports |
| `first_name` | VARCHAR(120) | not null |
| `last_name` | VARCHAR(120) | not null |
| `name_norm` | VARCHAR(250) | not null |
| `linkedin_url` | VARCHAR(300) |  |
| `linkedin_key` | VARCHAR(200) |  |
| `email` | VARCHAR(320) |  |
| `company_raw` | VARCHAR(300) |  |
| `company_id` | VARCHAR(32) | FK→companies |
| `position` | VARCHAR(300) |  |
| `connected_on` | DATE |  |
| `role_category` | VARCHAR(24) |  |
| `seniority` | VARCHAR(16) |  |
| `employment_status` | VARCHAR(20) | not null |
| `employment_verified_at` | DATETIME |  |
| `dedup_fallback` | VARCHAR(300) |  |
| `id` | VARCHAR(32) | PK |
| `created_at` | DATETIME | not null |
| `user_id` | VARCHAR(32) | FK→users, indexed, not null |

Indexes: `ix_contacts_user_id` (user_id); `ix_contacts_user_company` (user_id, company_id); `ix_contacts_user_name` (user_id, name_norm)

Unique together: (user_id, linkedin_key)

### `email_contacts` (user-scoped)
HR/recruiter contacts, separate from connections; flags, E.164 phone, provenance, bulk_send_blocked.

| Column | Type | Notes |
|---|---|---|
| `import_id` | VARCHAR(32) | FK→imports |
| `contact_id` | VARCHAR(32) | FK→contacts |
| `name` | VARCHAR(250) |  |
| `title` | VARCHAR(300) |  |
| `company_raw` | VARCHAR(300) |  |
| `company_id` | VARCHAR(32) | FK→companies |
| `email_raw` | VARCHAR(320) |  |
| `email_norm` | VARCHAR(320) |  |
| `email_valid` | BOOLEAN | not null |
| `email_flags` | JSON | not null |
| `phone_raw` | VARCHAR(60) |  |
| `phone_e164` | VARCHAR(20) |  |
| `linkedin_url` | VARCHAR(300) |  |
| `location` | VARCHAR(200) |  |
| `notes` | TEXT |  |
| `provenance` | VARCHAR(24) | not null |
| `country_hint` | VARCHAR(2) |  |
| `bulk_send_blocked` | BOOLEAN | not null |
| `id` | VARCHAR(32) | PK |
| `created_at` | DATETIME | not null |
| `user_id` | VARCHAR(32) | FK→users, indexed, not null |

Indexes: `ix_email_contacts_user_id` (user_id); `ix_ec_user_company` (user_id, company_id)

Unique together: (user_id, email_norm)

### `suppression_entries` (user-scoped)
Per-user do-not-contact list (emails/domains); survives re-imports.

| Column | Type | Notes |
|---|---|---|
| `kind` | VARCHAR(8) | not null |
| `value` | VARCHAR(320) | not null |
| `reason` | VARCHAR(20) | not null |
| `source` | VARCHAR(20) | not null |
| `id` | VARCHAR(32) | PK |
| `created_at` | DATETIME | not null |
| `user_id` | VARCHAR(32) | FK→users, indexed, not null |

Indexes: `ix_suppression_entries_user_id` (user_id)

Unique together: (user_id, kind, value)

### `companies` (shared)
SHARED reference data (public company names). Which user knows a company is only visible through that user's own contacts.

| Column | Type | Notes |
|---|---|---|
| `id` | VARCHAR(32) | PK |
| `key` | VARCHAR(200) | unique, indexed, not null |
| `name` | VARCHAR(200) | not null |
| `created_at` | DATETIME | not null |

Indexes: `ix_companies_key` (key)

### `user_company_aliases` (user-scoped)
The user's own resolutions of ambiguous company names.

| Column | Type | Notes |
|---|---|---|
| `alias_key` | VARCHAR(200) | not null |
| `company_id` | VARCHAR(32) | FK→companies, not null |
| `id` | VARCHAR(32) | PK |
| `created_at` | DATETIME | not null |
| `user_id` | VARCHAR(32) | FK→users, indexed, not null |

Indexes: `ix_user_company_aliases_user_id` (user_id)

Unique together: (user_id, alias_key)

### `company_reviews` (user-scoped)
Ambiguous fuzzy company matches awaiting user review.

| Column | Type | Notes |
|---|---|---|
| `raw_name` | VARCHAR(200) | not null |
| `company_id` | VARCHAR(32) | FK→companies, not null |
| `candidate_id` | VARCHAR(32) | FK→companies, not null |
| `score` | FLOAT | not null |
| `status` | VARCHAR(12) | not null |
| `id` | VARCHAR(32) | PK |
| `created_at` | DATETIME | not null |
| `user_id` | VARCHAR(32) | FK→users, indexed, not null |

Indexes: `ix_company_reviews_user_id` (user_id)

## Scoring

### `contact_scores` (user-scoped)
General Referral Priority Score with components, confidence, inputs and config snapshot (reproducible).

| Column | Type | Notes |
|---|---|---|
| `contact_id` | VARCHAR(32) | FK→contacts, unique, indexed, not null |
| `total` | FLOAT | not null |
| `confidence` | FLOAT | not null |
| `rank` | INTEGER | not null |
| `tier` | INTEGER |  |
| `excluded` | BOOLEAN | not null |
| `components` | JSON | not null |
| `confidence_parts` | JSON | not null |
| `inputs` | JSON | not null |
| `scoring_version` | VARCHAR(40) | not null |
| `config_snapshot` | JSON | not null |
| `computed_at` | DATETIME | not null |
| `id` | VARCHAR(32) | PK |
| `created_at` | DATETIME | not null |
| `user_id` | VARCHAR(32) | FK→users, indexed, not null |

Indexes: `ix_contact_scores_contact_id` (contact_id); `ix_cs_user_rank` (user_id, rank); `ix_contact_scores_user_id` (user_id)

## Jobs (shared public data + per-user views)

### `jobs` (shared)
SHARED canonical public postings. Pasted/private jobs carry owner_user_id and are never merged or listed for others.

| Column | Type | Notes |
|---|---|---|
| `id` | VARCHAR(32) | PK |
| `company_id` | VARCHAR(32) | FK→companies, indexed, not null |
| `owner_user_id` | VARCHAR(32) | indexed |
| `title` | VARCHAR(300) | not null |
| `canonical_key` | VARCHAR(400) | not null |
| `location` | VARCHAR(300) |  |
| `work_arrangement` | VARCHAR(10) | not null |
| `employment_type` | VARCHAR(12) | not null |
| `description` | TEXT |  |
| `apply_url` | VARCHAR(600) |  |
| `posted_at` | VARCHAR(40) |  |
| `deadline` | DATETIME |  |
| `status` | VARCHAR(20) | indexed, not null |
| `status_reasons` | JSON | not null |
| `first_discovered` | DATETIME | not null |
| `last_verified` | DATETIME |  |

Indexes: `ix_jobs_owner_user_id` (owner_user_id); `ix_jobs_company_id` (company_id); `ix_jobs_status` (status); `ix_jobs_company_key` (company_id, canonical_key)

### `job_sources` (shared)
Every place a canonical job was seen.

| Column | Type | Notes |
|---|---|---|
| `id` | VARCHAR(32) | PK |
| `job_id` | VARCHAR(32) | FK→jobs, indexed, not null |
| `source_type` | VARCHAR(16) | not null |
| `board_token` | VARCHAR(80) | not null |
| `source_job_id` | VARCHAR(200) | not null |
| `source_url` | VARCHAR(600) |  |
| `apply_url` | VARCHAR(600) |  |
| `first_seen` | DATETIME | not null |
| `last_seen` | DATETIME | not null |

Indexes: `ix_job_sources_job_id` (job_id)

Unique together: (source_type, board_token, source_job_id)

### `job_verifications` (shared)
Append-only timestamped evidence for the open/closed decision.

| Column | Type | Notes |
|---|---|---|
| `id` | VARCHAR(32) | PK |
| `job_id` | VARCHAR(32) | FK→jobs, indexed, not null |
| `checked_at` | DATETIME | indexed, not null |
| `source_type` | VARCHAR(16) | not null |
| `kind` | VARCHAR(20) | not null |
| `detail` | JSON | not null |

Indexes: `ix_job_verifications_job_id` (job_id); `ix_job_verifications_checked_at` (checked_at)

### `user_boards` (user-scoped)
ATS boards the user wants searched.

| Column | Type | Notes |
|---|---|---|
| `company_id` | VARCHAR(32) | FK→companies, not null |
| `ats` | VARCHAR(16) | not null |
| `token` | VARCHAR(80) | not null |
| `careers_url` | VARCHAR(400) |  |
| `confirmed` | BOOLEAN | not null |
| `added_from` | VARCHAR(12) | not null |
| `last_run_at` | DATETIME |  |
| `last_status` | VARCHAR(200) |  |
| `jobs_found` | INTEGER | not null |
| `id` | VARCHAR(32) | PK |
| `created_at` | DATETIME | not null |
| `user_id` | VARCHAR(32) | FK→users, indexed, not null |

Indexes: `ix_user_boards_user_id` (user_id)

Unique together: (user_id, ats, token)

### `user_jobs` (user-scoped)
Which jobs a user sees (and hides).

| Column | Type | Notes |
|---|---|---|
| `job_id` | VARCHAR(32) | FK→jobs, indexed, not null |
| `origin` | VARCHAR(10) | not null |
| `hidden` | BOOLEAN | not null |
| `id` | VARCHAR(32) | PK |
| `created_at` | DATETIME | not null |
| `user_id` | VARCHAR(32) | FK→users, indexed, not null |

Indexes: `ix_user_jobs_job_id` (job_id); `ix_user_jobs_user_id` (user_id)

Unique together: (user_id, job_id)

### `discovery_runs` (user-scoped)
Coverage report per discovery run.

| Column | Type | Notes |
|---|---|---|
| `status` | VARCHAR(10) | not null |
| `coverage` | JSON | not null |
| `summary` | JSON | not null |
| `id` | VARCHAR(32) | PK |
| `created_at` | DATETIME | not null |
| `user_id` | VARCHAR(32) | FK→users, indexed, not null |

Indexes: `ix_discovery_runs_user_id` (user_id)

### `referral_routes` (user-scoped)
Per user+company: programme status with evidence; never assumed.

| Column | Type | Notes |
|---|---|---|
| `company_id` | VARCHAR(32) | FK→companies, not null |
| `status` | VARCHAR(28) | not null |
| `source` | VARCHAR(14) | not null |
| `evidence_url` | VARCHAR(600) |  |
| `evidence_excerpt` | VARCHAR(300) |  |
| `checked_at` | DATETIME |  |
| `id` | VARCHAR(32) | PK |
| `created_at` | DATETIME | not null |
| `user_id` | VARCHAR(32) | FK→users, indexed, not null |

Indexes: `ix_referral_routes_user_id` (user_id)

Unique together: (user_id, company_id)

## Matching

### `user_job_matches` (user-scoped)
Per user+job: requirement matrix, eligibility, match score, opportunity priority.

| Column | Type | Notes |
|---|---|---|
| `job_id` | VARCHAR(32) | FK→jobs, indexed, not null |
| `desc_hash` | VARCHAR(40) | not null |
| `analysis` | JSON | not null |
| `matrix` | JSON | not null |
| `eligibility` | JSON | not null |
| `match_total` | FLOAT | not null |
| `match_components` | JSON | not null |
| `match_extra` | JSON | not null |
| `priority_total` | FLOAT | not null |
| `priority_components` | JSON | not null |
| `readiness_group` | INTEGER | not null |
| `rank` | INTEGER | not null |
| `score_only_rank` | INTEGER | not null |
| `trade_off` | TEXT |  |
| `next_action` | VARCHAR(300) | not null |
| `profile_version` | INTEGER |  |
| `config_snapshot` | JSON | not null |
| `computed_at` | DATETIME | not null |
| `id` | VARCHAR(32) | PK |
| `created_at` | DATETIME | not null |
| `user_id` | VARCHAR(32) | FK→users, indexed, not null |

Indexes: `ix_user_job_matches_job_id` (job_id); `ix_ujm_user_rank` (user_id, rank); `ix_user_job_matches_user_id` (user_id)

Unique together: (user_id, job_id)

### `job_contact_scores` (user-scoped)
Job-specific contact scores (top few per job).

| Column | Type | Notes |
|---|---|---|
| `job_id` | VARCHAR(32) | FK→jobs, indexed, not null |
| `contact_id` | VARCHAR(32) | FK→contacts, indexed, not null |
| `total` | FLOAT | not null |
| `components` | JSON | not null |
| `employment_label` | VARCHAR(20) | not null |
| `rank_in_job` | INTEGER | not null |
| `recommended` | BOOLEAN | not null |
| `also_fits_jobs` | JSON | not null |
| `config_snapshot` | JSON | not null |
| `id` | VARCHAR(32) | PK |
| `created_at` | DATETIME | not null |
| `user_id` | VARCHAR(32) | FK→users, indexed, not null |

Indexes: `ix_job_contact_scores_job_id` (job_id); `ix_job_contact_scores_contact_id` (contact_id); `ix_job_contact_scores_user_id` (user_id)

Unique together: (user_id, job_id, contact_id)

## Tailored resumes

### `tailored_resumes` (user-scoped)
Versioned tailored resumes with claim ledger, validation report, score and diff. Approved versions are immutable.

| Column | Type | Notes |
|---|---|---|
| `job_id` | VARCHAR(32) | FK→jobs, not null |
| `version` | INTEGER | not null |
| `parent_id` | VARCHAR(32) |  |
| `status` | VARCHAR(10) | not null |
| `content` | JSON | not null |
| `ledger` | JSON | not null |
| `validation` | JSON | not null |
| `score` | JSON | not null |
| `changes` | JSON | not null |
| `questions` | JSON | not null |
| `options` | JSON | not null |
| `matrix` | JSON | not null |
| `profile_version` | INTEGER |  |
| `files` | JSON | not null |
| `approved_at` | DATETIME |  |
| `score_total` | FLOAT | not null |
| `id` | VARCHAR(32) | PK |
| `created_at` | DATETIME | not null |
| `user_id` | VARCHAR(32) | FK→users, indexed, not null |

Indexes: `ix_tr_user_job` (user_id, job_id); `ix_tailored_resumes_user_id` (user_id)

Unique together: (user_id, job_id, version)

## Outreach

### `campaigns` (user-scoped)
Optional grouping with its own (lower) daily limit and pause.

| Column | Type | Notes |
|---|---|---|
| `name` | VARCHAR(120) | not null |
| `goal` | VARCHAR(300) | not null |
| `channel` | VARCHAR(10) | not null |
| `paused` | BOOLEAN | not null |
| `daily_limit` | INTEGER |  |
| `id` | VARCHAR(32) | PK |
| `created_at` | DATETIME | not null |
| `user_id` | VARCHAR(32) | FK→users, indexed, not null |

Indexes: `ix_campaigns_user_id` (user_id)

### `outreach_batches` (user-scoped)
A reviewed set of drafts; records the count+limit confirmation.

| Column | Type | Notes |
|---|---|---|
| `summary` | JSON | not null |
| `approved_at` | DATETIME |  |
| `approval_confirmation` | JSON |  |
| `id` | VARCHAR(32) | PK |
| `created_at` | DATETIME | not null |
| `user_id` | VARCHAR(32) | FK→users, indexed, not null |

Indexes: `ix_outreach_batches_user_id` (user_id)

### `outreach_pairs` (user-scoped)
Job-contact (or company-contact) pipeline status.

| Column | Type | Notes |
|---|---|---|
| `job_id` | VARCHAR(32) | FK→jobs, indexed |
| `contact_id` | VARCHAR(32) | FK→contacts, indexed |
| `email_contact_id` | VARCHAR(32) | FK→email_contacts, indexed |
| `company_id` | VARCHAR(32) | FK→companies |
| `channel` | VARCHAR(10) | not null |
| `status` | VARCHAR(24) | not null |
| `match_score` | FLOAT |  |
| `contact_score` | FLOAT |  |
| `resume_id` | VARCHAR(32) |  |
| `follow_up_at` | DATETIME |  |
| `note` | TEXT |  |
| `evidence` | TEXT |  |
| `updated_at` | DATETIME | not null |
| `id` | VARCHAR(32) | PK |
| `created_at` | DATETIME | not null |
| `user_id` | VARCHAR(32) | FK→users, indexed, not null |

Indexes: `ix_outreach_pairs_user_id` (user_id); `ix_outreach_pairs_contact_id` (contact_id); `ix_outreach_pairs_email_contact_id` (email_contact_id); `ix_outreach_pairs_job_id` (job_id); `ix_pairs_user_status` (user_id, status)

### `outreach_messages` (user-scoped)
Drafts and sent messages (LinkedIn manual, email), approval and send state, risk flags, claim ledger.

| Column | Type | Notes |
|---|---|---|
| `pair_id` | VARCHAR(32) | FK→outreach_pairs, indexed, not null |
| `batch_id` | VARCHAR(32) | FK→outreach_batches, indexed |
| `campaign_id` | VARCHAR(32) | FK→campaigns |
| `parent_id` | VARCHAR(32) |  |
| `job_id` | VARCHAR(32) |  |
| `covers_job_ids` | JSON | not null |
| `channel` | VARCHAR(10) | not null |
| `kind` | VARCHAR(16) | not null |
| `is_initial` | BOOLEAN | not null |
| `to_name` | VARCHAR(250) |  |
| `to_email` | VARCHAR(320) |  |
| `to_linkedin_url` | VARCHAR(300) |  |
| `subject` | VARCHAR(300) |  |
| `body` | TEXT | not null |
| `connect_note` | VARCHAR(320) |  |
| `subject_options` | JSON | not null |
| `variants` | JSON | not null |
| `options` | JSON | not null |
| `attach_resume_id` | VARCHAR(32) |  |
| `ledger` | JSON | not null |
| `risk_flags` | JSON | not null |
| `approval_state` | VARCHAR(24) | not null |
| `send_state` | VARCHAR(22) | not null |
| `approved_at` | DATETIME |  |
| `scheduled_at` | DATETIME |  |
| `sent_at` | DATETIME |  |
| `rfc_message_id` | VARCHAR(200) |  |
| `provider_message_id` | VARCHAR(200) |  |
| `provider_thread_id` | VARCHAR(200) |  |
| `last_block` | JSON | not null |
| `id` | VARCHAR(32) | PK |
| `created_at` | DATETIME | not null |
| `user_id` | VARCHAR(32) | FK→users, indexed, not null |

Indexes: `ix_outreach_messages_user_id` (user_id); `ix_outreach_messages_pair_id` (pair_id); `ix_outreach_messages_batch_id` (batch_id); `ix_msg_user_state` (user_id, approval_state, send_state)

### `email_events` (user-scoped)
SENT, DELIVERY_UNCONFIRMED, BOUNCED_*, REPLIED, UNSUBSCRIBE_REQUESTED, ... with user-correctable labels.

| Column | Type | Notes |
|---|---|---|
| `message_id` | VARCHAR(32) | FK→outreach_messages, indexed, not null |
| `type` | VARCHAR(28) | not null |
| `detail` | JSON | not null |
| `label` | VARCHAR(24) |  |
| `confirmed` | BOOLEAN |  |
| `id` | VARCHAR(32) | PK |
| `created_at` | DATETIME | not null |
| `user_id` | VARCHAR(32) | FK→users, indexed, not null |

Indexes: `ix_email_events_user_id` (user_id); `ix_email_events_message_id` (message_id)

### `oauth_tokens` (user-scoped)
Gmail OAuth tokens, envelope-encrypted; never returned or exported.

| Column | Type | Notes |
|---|---|---|
| `provider` | VARCHAR(16) | not null |
| `account_email` | VARCHAR(320) | not null |
| `encrypted_access` | TEXT | not null, SECRET |
| `encrypted_refresh` | TEXT | SECRET |
| `expires_at` | DATETIME |  |
| `scopes` | JSON | not null |
| `id` | VARCHAR(32) | PK |
| `created_at` | DATETIME | not null |
| `user_id` | VARCHAR(32) | FK→users, indexed, not null |

Indexes: `ix_oauth_tokens_user_id` (user_id)
