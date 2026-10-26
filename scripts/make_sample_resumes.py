"""Writes clearly fake sample resumes + small sample CSVs into ./samples (committed). Run from the repo root:
    cd backend && uv run python ../scripts/make_sample_resumes.py
Everything here is invented: person, employers and links use reserved/example domains."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from tests import synth_contacts as sc  # noqa: E402
from tests import synth_resumes as sr  # noqa: E402

OUT = ROOT / "samples"

EXPERIENCED = sr.HEADER + [
    "EDUCATION", "Example State University - B.Tech in Computer Science    Aug 2014 - May 2018", "CGPA: 8.4/10",
    "EXPERIENCE",
    "Senior Backend Engineer - Initech Sample    Jan 2021 - Present",
    "- Built REST APIs in Python backed by PostgreSQL for an internal tools service used by several teams.",
    "- Added Docker based CI checks and pytest suites that caught regressions before release.",
    "- Cut report generation time by 30% by adding Redis caching.",
    "Backend Engineer - Acme Test Co    Jul 2018 - Dec 2020",
    "- Developed Python and Flask services that process job applications.",
    "- Migrated services to Docker and deployed them on AWS.",
    "PROJECTS", "Job Tracker - github.com/alex-example/job-tracker",
    "- Built a Flask and Redis service that tracks job applications.",
    "SKILLS", "Languages: Python, Java, SQL", "Cloud: AWS, Docker", "Tools: Git, Postgres, Redis",
]


def main():
    (OUT / "resumes").mkdir(parents=True, exist_ok=True)
    (OUT / "contacts").mkdir(parents=True, exist_ok=True)
    (OUT / "resumes" / "alex_student_single_column.pdf").write_bytes(sr.pdf_single())
    (OUT / "resumes" / "alex_student_two_column.pdf").write_bytes(sr.pdf_two_column())
    (OUT / "resumes" / "alex_student.docx").write_bytes(sr.docx_single())
    (OUT / "resumes" / "alex_experienced.pdf").write_bytes(sr.pdf_single(EXPERIENCED))
    (OUT / "resumes" / "scanned_image_only.pdf").write_bytes(sr.pdf_image_only())
    acme = [["Alex", "Banson", "https://www.linkedin.com/in/synthetic-00001", "", "Acme Test Co", "Senior Backend Engineer", "01 Jun 2026"],
            ["Sam", "Koson", "https://www.linkedin.com/in/synthetic-00002", "", "Acme Test Co", "Technical Recruiter", "01 Mar 2026"],
            ["Jordan", "Renson", "https://www.linkedin.com/in/synthetic-00003", "", "Acme Test Co", "Engineering Manager", "01 Feb 2026"],
            ["Taylor", "Talson", "https://www.linkedin.com/in/synthetic-00004", "", "Acme Test Co", "Product Manager", "01 Feb 2026"],
            ["Quinn", "Vason", "https://www.linkedin.com/in/synthetic-00005", "", "Acme Test Co", "Frontend Engineer", "01 Jan 2020"],
            ["Robin", "Mason", "https://www.linkedin.com/in/synthetic-00006", "", "Acme Test Co", "Staff Engineer", ""]]
    rows = acme + list(sc.li_rows(54, start=100))
    (OUT / "contacts" / "linkedin_connections_sample.csv").write_bytes(sc.to_csv(sc.LI_HEADER, rows))
    hr = [["Acme Test Co", "Pat Recruiter", "Technical Recruiter", "pat@acme-test.example.com", "+1 415 555 0134", "", "Remote", "synthetic"],
          ["Acme Test Co", "Lee Talent", "Recruiter", "lee@acme-test.example.com", "", "", "", ""],
          ["Acme Test Co", "Dup Person", "Recruiter", "PAT@acme-test.example.com", "", "", "", "duplicate of Pat (case differs)"],
          ["Globex Example", "Bad Mail", "HR", "not-an-email", "", "", "", "invalid email, kept for review"],
          ["Globex Example", "", "", "info@globex-example.example.com", "", "", "", "role account"],
          ["Initech Sample", "No Reply", "", "noreply@initech-sample.example.com", "", "", "", "no-reply address"],
          ["", "", "", "", "", "", "", ""]] + list(sc.hr_rows(20, start=0))
    (OUT / "contacts" / "hr_contacts_sample.csv").write_bytes(sc.to_csv(sc.HR_HEADER, hr))
    print("wrote", sorted(str(p.relative_to(ROOT)) for p in OUT.rglob("*") if p.is_file()))


if __name__ == "__main__":
    main()
