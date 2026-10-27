# Acceptance scenarios

The 14 mandatory scenarios from the specification, each with the automated tests that prove it. `backend/tests/test_acceptance_map.py` fails if a referenced test is renamed or removed.

Run one with e.g. `cd backend && uv run pytest -p no:warnings tests/test_outreach_flow.py::test_scenario_linkedin_messages_are_never_sent_by_the_app`.

## 1. Relevant open job with a verified current employee -> verified, scored, contact ranked, request drafted, queued for approval

- `backend/tests/test_matching_api.py` → `test_scenario_verified_job_with_verified_employee_is_ranked_first`
- `backend/tests/test_outreach_flow.py` → `test_generate_makes_a_small_reviewable_batch_and_sends_nothing`
- `backend/tests/test_outreach_flow.py` → `test_approve_many_requires_restating_count_and_daily_limit`

## 2. Closed job -> marked CLOSED, no outgoing request, existing drafts flagged stale

- `backend/tests/test_jobs.py` → `test_scenario_closed_job_is_marked_closed_and_never_eligible`
- `backend/tests/test_outreach_flow.py` → `test_scenario_closed_job_gets_no_drafts_and_existing_drafts_become_stale`
- `backend/tests/test_matching_api.py` → `test_closed_job_is_filtered_to_the_bottom_and_marked_skip`

## 3. Uncertain employment -> contact retained, confidence shown, never called 'verified'

- `backend/tests/test_matching_api.py` → `test_scenario_uncertain_employment_is_retained_and_never_called_verified`
- `backend/tests/test_matching.py` → `test_unknown_employment_is_not_treated_as_negative_or_verified`

## 4. No public referral info -> route unconfirmed, contacts still considered, wording does not assert a programme

- `backend/tests/test_jobs.py` → `test_scenario_no_public_referral_info_never_asserts_a_programme`
- `backend/tests/test_jobs.py` → `test_referral_programme_needs_official_page_evidence`
- `backend/tests/test_outreach_drafts.py` → `test_referral_programme_is_only_mentioned_when_verified`

## 5. Duplicate listings across sources -> canonical job and a single outreach strategy

- `backend/tests/test_jobs.py` → `test_dedup_rules`
- `backend/tests/test_jobs.py` → `test_scenario_duplicate_listings_across_sources_become_one_job`
- `backend/tests/test_outreach_flow.py` → `test_scenario_one_person_covering_several_roles_gets_one_message`

## 6. Multiple jobs at one company with multiple connections -> per-job ranking, consolidated, non-repetitive outreach

- `backend/tests/test_matching_api.py` → `test_scenario_multiple_jobs_one_company_per_job_ranking_and_consolidation`
- `backend/tests/test_outreach_flow.py` → `test_scenario_one_person_covering_several_roles_gets_one_message`
- `backend/tests/test_outreach_flow.py` → `test_second_generate_never_duplicates_outreach_to_the_same_people`

## 7. Missing eligibility data (e.g. graduation year) -> uncertain, review action, no unsupported claim

- `backend/tests/test_matching_api.py` → `test_scenario_missing_graduation_year_is_uncertain_with_review_action`
- `backend/tests/test_matching.py` → `test_graduation_year_rules`

## 8. Ambiguous delivery result -> DELIVERY_UNCONFIRMED, no duplicate send, manual reconciliation

- `backend/tests/test_outreach_flow.py` → `test_scenario_ambiguous_result_is_unconfirmed_never_resent_and_can_be_reconciled`
- `backend/tests/test_outreach_flow.py` → `test_unconfirmed_not_found_requires_a_deliberate_manual_decision`
- `backend/tests/test_outreach_flow.py` → `test_two_sender_runs_deliver_each_email_once`

## 9. No supported LinkedIn messaging API -> everything works, manual queue, the app never claims auto-sending

- `backend/tests/test_outreach_flow.py` → `test_scenario_linkedin_messages_are_never_sent_by_the_app`
- `backend/tests/test_outreach_flow.py` → `test_linkedin_adapter_is_a_disabled_stub_and_nothing_references_it`

## 10. HR CSV with mixed-quality rows -> cleaned report, no silent drops, a suppressed address is never emailed

- `backend/tests/test_imports.py` → `test_hr_mixed_quality_cleaned_report_and_suppression`
- `backend/tests/test_imports.py` → `test_every_row_is_accounted_for`
- `backend/tests/test_outreach_flow.py` → `test_scenario_suppressed_address_is_never_emailed_even_if_suppressed_after_approval`

## 11. Gmail not connected -> full cold-email drafting and manual mode still work

- `backend/tests/test_outreach_flow.py` → `test_scenario_without_gmail_drafting_and_manual_mode_still_work`
- `backend/tests/test_outreach_flow.py` → `test_dry_run_executes_everything_but_delivers_nothing`

## 12. Two users with overlapping contacts/companies see only their own data; the shared job cache leaks nothing

- `backend/tests/test_isolation.py` → `test_every_id_route_is_isolated`
- `backend/tests/test_jobs.py` → `test_shared_job_cache_does_not_leak_between_users`
- `backend/tests/test_outreach_replies.py` → `test_outreach_is_isolated_between_users`
- `backend/tests/test_scoring.py` → `test_isolation_for_prospects_and_intelligence`

## 13. Master resume untouched after tailoring several jobs; approved versions immutable

- `backend/tests/test_tailoring_api.py` → `test_scenario_master_untouched_after_tailoring_several_jobs_and_unsupported_tech_never_appears`
- `backend/tests/test_tailoring_api.py` → `test_edits_create_new_versions_and_approved_versions_are_immutable`
- `backend/tests/test_tailoring.py` → `test_master_profile_is_untouched_and_no_state_leaks_between_jobs`

## 14. Unsupported JD technology never appears in the resume; missing-metric prompts appear instead of fabricated numbers

- `backend/tests/test_tailoring.py` → `test_unsupported_jd_technology_is_never_added`
- `backend/tests/test_tailoring.py` → `test_no_invented_numbers_and_missing_metrics_become_questions`
- `backend/tests/test_tailoring_api.py` → `test_scenario_master_untouched_after_tailoring_several_jobs_and_unsupported_tech_never_appears`

## Caveat

These pass against **synthetic data and mock integrations**. They prove the logic and the guard rails, not that a real posting is open, a real Gmail account accepts a send, or a real resume layout is parsed correctly. See `VERIFICATION_CHECKLIST.md`.
