import pytest

from app.services import resume_parse as rp
from app.services import taxonomy
from tests import synth_resumes as sr


def by(items, section):
    return [i for i in items if i.section == section]


def run(data, name):
    text, info = rp.extract_text(data, name)
    items, report = rp.structure(text)
    return text, info, items, report


def check_standard(items):
    p = by(items, "personal")[0].data
    assert p["name"] == "Alex Example" and p["email"] == "alex.example@example.com"
    assert any("github.com/alex-example" in l for l in p["links"])
    exp = by(items, "experience")[0].data
    assert exp["title"] == "Backend Engineering Intern" and exp["organization"] == "Acme Test Co"
    assert (exp["start"], exp["end"]) == ("2024-06", "2024-08") and len(exp["bullets"]) == 2
    edu = by(items, "education")[0].data
    assert edu["institution"] == "Example State University" and edu["expected"] and edu["end"] == "2026-05"
    assert edu["gpa"].lower().startswith("cgpa")
    proj = by(items, "project")[0].data
    assert proj["name"] == "Job Tracker" and {"Flask", "Redis", "Docker", "AWS"} <= set(proj["stack"])
    assert proj["repo_url"] and "job-tracker" in proj["repo_url"]
    skills = {s.data["name"]: s for s in by(items, "skill")}
    assert {"Python", "Java", "SQL", "AWS", "Docker", "Kubernetes", "PostgreSQL", "Git", "Rust"} <= set(skills)  # aliases normalised


def test_pdf_single_column():
    _, info, items, report = run(sr.pdf_single(), "r.pdf")
    assert info["parser"] == "pymupdf" and not info["image_only"] and report["rejected"] == []
    check_standard(items)


def test_pdf_two_column_reading_order():
    text, info, items, _ = run(sr.pdf_two_column(), "r.pdf")
    assert info["columns"] == 2
    assert text.index("Backend Engineering") < text.index("SKILLS") < text.index("Job Tracker")  # left col, then right col
    exp = by(items, "experience")[0].data
    assert exp["organization"] == "Acme Test Co" and by(items, "education") and by(items, "project")


def test_docx_and_table_layout():
    check_standard(run(sr.docx_single(), "r.docx")[2])
    _, info, items, _ = run(sr.docx_table_layout(), "r.docx")
    assert by(items, "experience") and by(items, "skill")


def test_image_only_pdf_is_flagged_not_crashed():
    text, info = rp.extract_text(sr.pdf_image_only(), "scan.pdf")
    assert info["image_only"] and "OCR" in info["warnings"][0]
    assert rp.structure(text)[0] == []


@pytest.mark.parametrize("data,name", [(b"", "a.pdf"), (b"%PDF-1.4 garbage", "a.pdf"), (b"PK\x03\x04junk", "a.docx"),
                                       (b"hello", "a.txt"), (b"x" * (6 * 1024 * 1024), "a.pdf")],
                         ids=["empty", "bad-pdf", "bad-docx", "wrong-type", "oversized"])
def test_malformed_empty_or_oversized_raise_parse_error(data, name):
    with pytest.raises(rp.ParseError):
        rp.extract_text(data, name)


def test_every_item_traces_to_source_text_and_span():
    text, _, items, _ = run(sr.pdf_single(), "r.pdf")
    for it in items:
        assert 0 <= it.span[0] <= it.span[1] <= len(text)
        assert rp.traceable(it, text)


def test_untraceable_extraction_is_rejected():
    it = rp.Item("experience", {"title": "CTO", "organization": "Invented Corp"}, (0, 5))
    assert not rp.traceable(it, "Alex Example\nBackend Intern at Acme Test Co")


def test_skill_evidence_levels():
    text = ("Alex Example\nEXPERIENCE\nBackend Engineer — Acme Test Co  Jan 2023 - Present\n- Built services in Python.\n"
            "PROJECTS\nSide App\n- Used Rust for the parser.\nSKILLS\nPython, Rust, Kubernetes\n")
    lvl = {i.data["name"]: i.evidence_level for i in rp.structure(text)[0] if i.section == "skill"}
    assert lvl == {"Python": "USED_PROFESSIONALLY", "Rust": "USED_IN_PROJECT", "Kubernetes": "CLAIMED_ONLY"}


def test_date_order_and_duplicate_roles_are_flagged_not_resolved():
    text = ("Alex Example\nEXPERIENCE\nBackend Engineer — Acme Test Co  Jun 2024 - Jan 2023\n- x\n"
            "Backend Engineer — Acme Test Co  Jun 2020 - Jan 2021\n- y\n")
    exp = by(rp.structure(text)[0], "experience")
    kinds = {f["type"] for e in exp for f in e.flags}
    assert kinds == {"date_order", "duplicate"} and len(exp) == 2  # both kept for user review


def test_missing_sections_do_not_crash():
    items, _ = rp.structure("Alex Example\nalex@example.com\nSKILLS\nPython")
    assert {i.section for i in items} == {"personal", "skill"}


def test_taxonomy_aliases():
    assert taxonomy.normalize("Postgres") == "PostgreSQL" and taxonomy.normalize("k8s") == "Kubernetes"
    assert taxonomy.skill_set("we use go and c in prose, golang services, Node.js") == {"Go", "Node.js"}
    assert taxonomy.skill_set("C++ and C#") == {"C++", "C#"}
