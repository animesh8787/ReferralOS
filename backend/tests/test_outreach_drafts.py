import re
from datetime import datetime

import pytest

from app.services import jd_analysis, matching
from app.services.outreach import drafts
from tests.test_tailoring import JD_A, TODAY, base_items

ITEMS = base_items()
A = jd_analysis.analyse(JD_A + "\n" + "x" * 120)
MATRIX = matching.build_matrix(A, matching.summarize_profile(ITEMS, TODAY))
FACTS = drafts.sender_facts(ITEMS, MATRIX, "Alex Example")
JOB = {"title": "Backend Engineer", "company": "Acme Test Co", "apply_url": "https://boards.greenhouse.io/acme-test/jobs/1001", "employment_type": "full_time"}
CT = {"first": "Sam", "position": "Staff Engineer", "role_category": "engineer", "seniority": "staff_principal", "relationship_note": None}
OPTS = {"tone": "conversational", "length": "short", "ask": "referral", "variant": "A"}


def ref(ct=None, job=None, route=None, **o):
    return drafts.referral_message(FACTS, {**CT, **(ct or {})}, job or JOB, route, {**OPTS, **o})


# ---------------------------------------------------------------- referral requests (LinkedIn, manual send)
def test_referral_contains_the_required_parts():
    m = ref()
    b = m["body"]
    assert b.startswith("Hi Sam,") and "Backend Engineer" in b and JOB["apply_url"] in b and "Acme Test Co" in b
    assert "please feel free to decline" in b and "not eligible to refer" in b           # may decline / may not be eligible
    assert "I'm Alex Example, a B.Tech student in Computer Science." in b
    assert "Python" in b and "overlaps with what the role asks for" in b                  # honest, matrix-backed alignment
    assert b.rstrip().endswith("Alex Example") and m["channel"] == "linkedin" and m["subject"] is None
    assert len(b) <= drafts.LINKEDIN_BODY_MAX and len(m["connect_note"]) <= drafts.CONNECT_NOTE_MAX


def test_never_invents_relationships_promises_or_superlatives():
    for ct in ({}, {"role_category": "recruiter"}, {"role_category": "eng_manager"}, {"position": None, "role_category": None}):
        for tone in ("formal", "conversational"):
            for ask in ("referral", "guidance"):
                for variant in ("A", "B"):
                    for length in ("short", "medium"):
                        b = ref(ct, tone=tone, ask=ask, variant=variant, length=length)["body"]
                        assert drafts.forbidden_hits(b) == [], (ct, tone, ask, variant, drafts.forbidden_hits(b))
                        assert drafts.unresolved(b) == []
                        assert not re.search(r"interview|hire you|job offer|know each other|mutual", b, re.I)


@pytest.mark.parametrize("text", ["As we discussed last week", "We met at the career fair", "our mutual connection Sam", "it was great meeting you", "I guarantee an interview",
                                  "I'm a perfect fit", "proven track record", "remember me?", "following up on our call"])
def test_forbidden_claim_detector(text):
    assert drafts.forbidden_hits(text)
    assert drafts.forbidden_hits("I'd value your advice on the role.") == []


def test_referral_programme_is_only_mentioned_when_verified():
    plain = ref(route=None)["body"]
    unconfirmed = ref(route={"status": "REFERRAL_ROUTE_UNCONFIRMED", "evidence_url": None})["body"]
    none = ref(route={"status": "NO_PUBLIC_EVIDENCE", "evidence_url": None})["body"]
    verified = ref(route={"status": "VERIFIED_REFERRAL_PROGRAM", "evidence_url": "https://acme-test.example.com/refer"})["body"]
    for b in (plain, unconfirmed, none):
        assert "referral program" not in b.lower() and "If you're able to refer candidates" in b  # asks whether it's possible
    assert "employee referral program (https://acme-test.example.com/refer)" in verified


def test_templates_by_contact_type_and_options():
    assert drafts.contact_type("recruiter", None, "Technical Recruiter", None) == "recruiter"
    assert drafts.contact_type("eng_manager", "manager", "Engineering Manager", None) == "eng_manager"
    assert drafts.contact_type("engineer", "senior", "Senior Engineer", None) == "senior_engineer"
    assert drafts.contact_type("engineer", "mid", "Tech Lead", None) == "senior_engineer"
    assert drafts.contact_type("engineer", "mid", "Software Engineer", None) == "engineer"
    assert drafts.contact_type("product", None, "PM", None) == "low_context"
    assert drafts.contact_type("engineer", "mid", "Engineer", "I read your talk on tracing") == "established"
    rec = ref({"role_category": "recruiter", "position": "Technical Recruiter"})["body"]
    assert "whether a referral is possible" in rec and "I see you're listed as" not in rec
    eng = ref({"role_category": "engineer"})["body"]
    assert "I see you're listed as Staff Engineer at Acme Test Co" in eng      # 'listed as': employment is never asserted as verified
    guide = ref(ask="guidance")["body"]
    assert "point me to the best way to apply" in guide and "refer" not in guide.split("Please feel free")[0].lower().split("role")[-1]
    assert ref(tone="formal")["body"].startswith("Hello Sam,") and "Best regards" in ref(tone="formal")["body"]
    assert "internship" in ref(job={**JOB, "employment_type": "internship"})["body"]
    assert "I've also built Job Tracker." in ref(length="medium")["body"] and "I've also built" not in ref()["body"]
    assert ref(variant="A")["body"] != ref(variant="B")["body"]


def test_relationship_note_is_used_verbatim_or_not_at_all():
    note = "I attended your talk on tracing at PyCon."
    est = ref({"relationship_note": note})
    assert note in est["body"] and est["uses_relationship_note"] and est["contact_type"] == "established"
    assert note not in ref()["body"] and ref()["uses_relationship_note"] is False
    assert "talk" not in ref()["body"] and "attended" not in ref()["body"]


def test_missing_data_becomes_a_visible_placeholder_never_a_guess():
    no_link = ref(job={**JOB, "apply_url": None})["body"]
    assert "{{job_link}}" in no_link and drafts.unresolved(no_link) == ["{{job_link}}"]
    nameless = drafts.referral_message(drafts.sender_facts(ITEMS, MATRIX, None, None) | {"name": None, "first": None}, CT, JOB, None, OPTS)
    assert "{{your_name}}" in nameless["body"]
    no_skills = drafts.referral_message(drafts.sender_facts(ITEMS, [], "Alex Example"), CT, JOB, None, OPTS)["body"]
    assert "overlaps with what the role asks" not in no_skills  # no matrix evidence: no alignment claim at all


def test_alignment_only_names_skills_the_matrix_marks_strong():
    strong = {r["term"] for r in MATRIX if r["status"] == "STRONG_EVIDENCE"}
    assert set(FACTS["skills"]) <= strong and "Terraform" not in FACTS["skills"] and "Kubernetes" not in FACTS["skills"]
    claims = drafts.check_claims(ref()["ledger"], ITEMS)
    assert claims and all(c["status"] == "validated" for c in claims) and all(c["fact_ids"] for c in claims if c["label"] != "x")
    bad = drafts.check_claims([("alignment", "I've worked with Kubernetes and Terraform serving 5000 users.", ["e1"])], ITEMS)
    assert bad[0]["status"] == "needs_confirmation"


def test_connect_note_fits_and_drops_optional_parts_not_words():
    long_job = {**JOB, "title": "Senior Staff Principal Backend Platform Reliability Engineer", "company": "Extraordinarily Long Company Name Incorporated Holdings",
                "apply_url": "https://boards.greenhouse.io/acme-test/jobs/1001?gh_src=" + "x" * 80}
    n = ref(job=long_job)["connect_note"]
    assert len(n) <= 300 and not n.endswith(" ") and "Alex Example" in n


# ---------------------------------------------------------------- cold emails
TO = {"first": "Pat", "name": "Pat Recruiter", "email": "pat@acme-test.example.com"}


def email(kind="cold_job", **o):
    return drafts.cold_email(kind, FACTS, TO, JOB if kind == "cold_job" else None, "Acme Test Co", {**OPTS, **o}, "alex.example@example.com", o.pop("attached", False))


def test_job_email_is_honest_complete_and_has_the_opt_out():
    m = email()
    b = m["body"]
    assert b.startswith("Hi Pat,") and JOB["apply_url"] in b and drafts.OPT_OUT in b and "Alex Example" in b and "alex.example@example.com" in b
    assert len(m["subject_options"]) >= 3 and m["subject"] == m["subject_options"][0]
    from app.services.outreach.compliance import DECEPTIVE_SUBJECT
    assert not any(DECEPTIVE_SUBJECT.search(s) for s in m["subject_options"]) and all(not s.lower().startswith(("re:", "fwd:")) for s in m["subject_options"])
    assert drafts.forbidden_hits(b) == [] and drafts.unresolved(b) == [] and "attached" not in b


def test_resume_is_mentioned_only_when_an_approved_one_is_attached():
    assert "I've attached my resume." not in drafts.cold_email("cold_job", FACTS, TO, JOB, "Acme Test Co", OPTS, "a@example.com", False)["body"]
    assert "I've attached my resume." in drafts.cold_email("cold_job", FACTS, TO, JOB, "Acme Test Co", OPTS, "a@example.com", True)["body"]


def test_intro_email_never_pretends_an_opening_exists():
    m = drafts.cold_email("cold_intro", FACTS, TO, None, "Acme Test Co", OPTS, "a@example.com", False)
    b = m["body"]
    assert "not writing about a specific posting" in b and "whether Acme Test Co has roles" in b and drafts.OPT_OUT in b
    assert "Backend Engineer" not in b and "http" not in b and not re.search(r"opening|vacanc|position you (posted|advertis)", b, re.I)
    assert all("Question" in s or "Introduction" in s or "Who should" in s for s in m["subject_options"]) and len(b) < len(email()["body"]) + 200


def test_follow_up_and_thank_you():
    f = drafts.follow_up(FACTS, TO, "Question about the Backend Engineer role", datetime(2026, 5, 4), JOB, "Acme Test Co", OPTS, "a@example.com", 1)
    assert f["subject"] == "Follow-up: Question about the Backend Engineer role" and "04 May 2026" in f["body"] and drafts.OPT_OUT in f["body"]
    assert not re.search(r"urgent|last chance|final", f["body"], re.I) and not f["subject"].lower().startswith("re:")
    t = drafts.thank_you(FACTS, TO, "Thanks for pointing me to the careers page.", "Question about the role", OPTS, "a@example.com")
    assert "Thanks for pointing me to the careers page." in t["body"] and t["subject"].startswith("Thank you:")


def test_variants_are_choices_not_blasts():
    a, b = email(variant="A"), email(variant="B")
    assert a["body"] != b["body"] and drafts.OPT_OUT in a["body"] and drafts.OPT_OUT in b["body"]


def test_extra_roles_line_consolidates_one_person_across_roles():
    extra = "I'm also interested in the Platform Engineer role (https://x.example.com/2) at Acme Test Co."
    assert extra in email(extra=extra)["body"] and extra in ref(extra=extra)["body"]
