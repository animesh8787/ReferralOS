"""The 14 mandatory acceptance scenarios (spec 15.2) -> the tests that prove them. docs/ACCEPTANCE.md is generated from this."""
MAP = {
    1: ("Relevant open job with a verified current employee -> verified, scored, contact ranked, request drafted, queued for approval", [
        "test_matching_api.py::test_scenario_verified_job_with_verified_employee_is_ranked_first",
        "test_outreach_flow.py::test_generate_makes_a_small_reviewable_batch_and_sends_nothing",
        "test_outreach_flow.py::test_approve_many_requires_restating_count_and_daily_limit"]),
    2: ("Closed job -> marked CLOSED, no outgoing request, existing drafts flagged stale", [
        "test_jobs.py::test_scenario_closed_job_is_marked_closed_and_never_eligible",
        "test_outreach_flow.py::test_scenario_closed_job_gets_no_drafts_and_existing_drafts_become_stale",
        "test_matching_api.py::test_closed_job_is_filtered_to_the_bottom_and_marked_skip"]),
    3: ("Uncertain employment -> contact retained, confidence shown, never called 'verified'", [
        "test_matching_api.py::test_scenario_uncertain_employment_is_retained_and_never_called_verified",
        "test_matching.py::test_unknown_employment_is_not_treated_as_negative_or_verified"]),
    4: ("No public referral info -> route unconfirmed, contacts still considered, wording does not assert a programme", [
        "test_jobs.py::test_scenario_no_public_referral_info_never_asserts_a_programme",
        "test_jobs.py::test_referral_programme_needs_official_page_evidence",
        "test_outreach_drafts.py::test_referral_programme_is_only_mentioned_when_verified"]),
    5: ("Duplicate listings across sources -> canonical job and a single outreach strategy", [
        "test_jobs.py::test_dedup_rules",
        "test_jobs.py::test_scenario_duplicate_listings_across_sources_become_one_job",
        "test_outreach_flow.py::test_scenario_one_person_covering_several_roles_gets_one_message"]),
    6: ("Multiple jobs at one company with multiple connections -> per-job ranking, consolidated, non-repetitive outreach", [
        "test_matching_api.py::test_scenario_multiple_jobs_one_company_per_job_ranking_and_consolidation",
        "test_outreach_flow.py::test_scenario_one_person_covering_several_roles_gets_one_message",
        "test_outreach_flow.py::test_second_generate_never_duplicates_outreach_to_the_same_people"]),
    7: ("Missing eligibility data (e.g. graduation year) -> uncertain, review action, no unsupported claim", [
        "test_matching_api.py::test_scenario_missing_graduation_year_is_uncertain_with_review_action",
        "test_matching.py::test_graduation_year_rules"]),
    8: ("Ambiguous delivery result -> DELIVERY_UNCONFIRMED, no duplicate send, manual reconciliation", [
        "test_outreach_flow.py::test_scenario_ambiguous_result_is_unconfirmed_never_resent_and_can_be_reconciled",
        "test_outreach_flow.py::test_unconfirmed_not_found_requires_a_deliberate_manual_decision",
        "test_outreach_flow.py::test_two_sender_runs_deliver_each_email_once"]),
    9: ("No supported LinkedIn messaging API -> everything works, manual queue, the app never claims auto-sending", [
        "test_outreach_flow.py::test_scenario_linkedin_messages_are_never_sent_by_the_app",
        "test_outreach_flow.py::test_linkedin_adapter_is_a_disabled_stub_and_nothing_references_it"]),
    10: ("HR CSV with mixed-quality rows -> cleaned report, no silent drops, a suppressed address is never emailed", [
        "test_imports.py::test_hr_mixed_quality_cleaned_report_and_suppression",
        "test_imports.py::test_every_row_is_accounted_for",
        "test_outreach_flow.py::test_scenario_suppressed_address_is_never_emailed_even_if_suppressed_after_approval"]),
    11: ("Gmail not connected -> full cold-email drafting and manual mode still work", [
        "test_outreach_flow.py::test_scenario_without_gmail_drafting_and_manual_mode_still_work",
        "test_outreach_flow.py::test_dry_run_executes_everything_but_delivers_nothing"]),
    12: ("Two users with overlapping contacts/companies see only their own data; the shared job cache leaks nothing", [
        "test_isolation.py::test_every_id_route_is_isolated",
        "test_jobs.py::test_shared_job_cache_does_not_leak_between_users",
        "test_outreach_replies.py::test_outreach_is_isolated_between_users",
        "test_scoring.py::test_isolation_for_prospects_and_intelligence"]),
    13: ("Master resume untouched after tailoring several jobs; approved versions immutable", [
        "test_tailoring_api.py::test_scenario_master_untouched_after_tailoring_several_jobs_and_unsupported_tech_never_appears",
        "test_tailoring_api.py::test_edits_create_new_versions_and_approved_versions_are_immutable",
        "test_tailoring.py::test_master_profile_is_untouched_and_no_state_leaks_between_jobs"]),
    14: ("Unsupported JD technology never appears in the resume; missing-metric prompts appear instead of fabricated numbers", [
        "test_tailoring.py::test_unsupported_jd_technology_is_never_added",
        "test_tailoring.py::test_no_invented_numbers_and_missing_metrics_become_questions",
        "test_tailoring_api.py::test_scenario_master_untouched_after_tailoring_several_jobs_and_unsupported_tech_never_appears"]),
}
