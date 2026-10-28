"""Regressions found with a real resume: a 'RESEARCH EXPERIENCE' heading, skill-table labels on their own line, parenthesised lists,
wrapped lines, wrapped achievement bullets and header hyperlinks. All text here is fictional."""
import httpx

from app.adapters import mailer
from app.config import get_settings
from app.services import resume_parse as rp
from tests import synth_resumes as sr

LINES = """JORDAN SAMPLE
City, Country | +1 555 010 0000
Email | LinkedIn | GitHub | Portfolio
SUMMARY
Student who builds small services.
EDUCATION
Example Institute of Technology
2023 - 2027
Bachelor of Engineering in Computer Science
TECHNICAL SKILLS
Languages
C++, Python, C, SQL
CS Fundamentals
Data structures, algorithms, graph algorithms,
dynamic programming
Distributed Systems
AWS (Lambda, SQS, S3), event-
driven architecture, WebSockets
Databases & Backend
DynamoDB (single-table design), PostgreSQL, FastAPI, REST
APIs, React
PROJECTS
Queue Runner - Job Dispatcher    AWS, SQS
• Built a dispatcher on SQS and Lambda that retries failed jobs.
RESEARCH EXPERIENCE
Research Intern, Example Institute of Technology Jun 2024 - Jul 2024
• Benchmarked three models on 40,000 images and deployed the best.
ACHIEVEMENTS
• Solved 300+ practice problems across many types, strengthening skills in core data structures and
algorithms; completed a certified course.
• Placed in the top 6% of a national challenge.""".split("\n")


def pdf_with_links() -> bytes:
    import fitz
    doc = fitz.open()
    page = doc.new_page()
    y = 50
    for line in LINES:
        page.insert_text((50, y), line, fontsize=9)
        y += 13
    page.insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(50, 55, 90, 66), "uri": "mailto:jordan.sample@example.com"})
    page.insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(100, 55, 140, 66), "uri": "https://github.com/jordan-sample"})
    return doc.tobytes()


def parsed():
    text, _ = rp.extract_text(pdf_with_links(), "r.pdf")
    items, report = rp.structure(text)
    return items, report


def by(items, section):
    return [i for i in items if i.section == section]


def test_research_experience_is_experience_not_a_project():
    items, _ = parsed()
    exp = by(items, "experience")
    assert [(e.data["title"], e.data["start"], e.data["end"]) for e in exp] == [("Research Intern", "2024-06", "2024-07")]
    assert [p.data["name"] for p in by(items, "project")] == ["Queue Runner"]


def test_skill_labels_wrapped_lines_and_parentheses():
    names = [s.data["name"] for s in by(parsed()[0], "skill")]
    for label in ("Languages", "CS Fundamentals", "Distributed Systems", "Databases & Backend"):
        assert label not in names
    assert {"C++", "Python", "AWS", "Lambda", "SQS", "S3", "event-driven architecture", "WebSockets", "DynamoDB", "REST APIs", "React"} <= set(names)
    assert not any(n.endswith("(") or n.startswith("(") or n.endswith("-") or "(Lambda" in n for n in names)
    assert len(names) == len(set(n.lower() for n in names))


def test_wrapped_achievement_is_one_award():
    awards = [a.data["name"] for a in by(parsed()[0], "award")]
    assert len(awards) == 2 and awards[0].endswith("certified course.") and "core data structures and algorithms" in awards[0]


def test_header_hyperlinks_are_read():
    p = by(parsed()[0], "personal")[0].data
    assert p["email"] == "jordan.sample@example.com" and "https://github.com/jordan-sample" in p["links"]


def test_skill_evidence_uses_the_projects_own_words():
    skills = {s.data["name"]: s.evidence_level for s in by(parsed()[0], "skill")}
    assert skills["SQS"] == "USED_IN_PROJECT" and skills["Python"] == "CLAIMED_ONLY"


def test_skill_questions_collapse_into_one(env, mk):
    a = mk("a@example.com")
    a.upload(pdf_with_links())
    qs = [q for q in a.get("/api/profile").json()["questions"] if q["type"] == "unsupported_skill"]
    assert len(qs) == 1 and "Python" in qs[0]["text"]


def test_resume_without_links_still_parses():
    items, _ = rp.structure(rp.extract_text(sr.pdf_single(), "r.pdf")[0])
    assert by(items, "personal")


# ---------------------------------------------------------------- system mail
def test_mail_goes_to_outbox_without_a_key(env, mk):
    mk("a@example.com")
    body = [__import__("json").loads(f.read_text()) for f in (env / "outbox").glob("*.json")][-1]["body"]
    assert get_settings().app_url + "/verify?token=" in body and "Verification token: " in body


def test_resend_is_used_when_a_key_is_set(env, monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
    get_settings.cache_clear()
    seen = {}

    def fake_post(url, **kw):
        seen.update(url=url, **kw)
        return httpx.Response(200, json={"id": "x"}, request=httpx.Request("POST", url))

    monkeypatch.setattr(mailer.httpx, "post", fake_post)
    mailer.send_system_mail("to@example.com", "Hi", "Body")
    assert seen["url"] == "https://api.resend.com/emails" and seen["json"]["to"] == ["to@example.com"]
    assert seen["headers"]["Authorization"] == "Bearer re_test_key" and not list((env / "outbox").glob("*.json"))


def test_resend_failure_falls_back_to_outbox_and_signup_survives(env, monkeypatch, mk):
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
    get_settings.cache_clear()
    monkeypatch.setattr(mailer.httpx, "post", lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectError("down")))
    mk("a@example.com")  # sign-up must not fail when the mail provider is down
    assert list((env / "outbox").glob("*.json"))


def test_resend_verification_only_for_unverified_and_rate_limited(env, mk):
    a = mk("a@example.com")  # mk signs up and verifies
    assert a.post("/api/auth/resend-verification", {}).status_code == 409
