"""Synthetic contact data. Every person and company is invented; emails use reserved example domains.
LinkedIn-style URLs carry a 'synthetic-' slug so they can never match a real profile."""
import csv
import io

FIRST = ["Alex", "Sam", "Jordan", "Taylor", "Riley", "Casey", "Morgan", "Jamie", "Quinn", "Avery", "Robin", "Drew", "Kai", "Noor", "Ravi", "Mei"]
SYL = ["ba", "ko", "ren", "tal", "vi", "mar", "so", "lin", "der", "fa", "gu", "han", "ji", "lo", "mu", "nel", "or", "pa", "qui", "ru", "sen", "tu", "va", "wen", "xi", "yo", "zel"]
COMPANIES = ["Acme Test Co", "Northwind Labs", "Globex Example", "Initech Sample", "Umbrella Demo", "Hooli Fixture", "Stark Mockworks",
             "Wayne Placeholder", "Wonka Synthetic", "Soylent Testing", "Tyrell Samples", "Cyberdyne Fake"]
SUFFIX = ["", " Inc.", " LLC", " Ltd", " Pvt Ltd", ", Inc"]
TITLES = ["Software Engineer", "Senior Software Engineer", "Engineering Manager", "Technical Recruiter", "Staff Engineer",
          "Data Scientist", "Talent Acquisition Partner", "Product Manager", "Backend Developer", "ML Engineer", "Director of Engineering"]
LI_HEADER = ["First Name", "Last Name", "URL", "Email Address", "Company", "Position", "Connected On"]
PREAMBLE = 'Notes:\n"When exporting your connection data, you may notice that some of the email addresses are missing."\n\n'


def person(i: int) -> tuple[str, str]:
    return FIRST[i % len(FIRST)], (SYL[(i // len(FIRST)) % len(SYL)] + SYL[(i // (len(FIRST) * len(SYL))) % len(SYL)]).capitalize() + "son"


def li_rows(n: int, start: int = 0):
    for i in range(start, start + n):
        f, l = person(i)
        yield [f, l, f"https://www.linkedin.com/in/synthetic-{i:05d}", f"{f.lower()}.{l.lower()}@example.com" if i % 5 == 0 else "",
               COMPANIES[i % len(COMPANIES)] + SUFFIX[i % len(SUFFIX)], TITLES[i % len(TITLES)], f"{1 + i % 28:02d} Mar 2023"]


def to_csv(header, rows, delimiter=",", preamble="", encoding="utf-8") -> bytes:
    buf = io.StringIO()
    buf.write(preamble)
    w = csv.writer(buf, delimiter=delimiter, lineterminator="\n")
    w.writerow(header)
    w.writerows(rows)
    return buf.getvalue().encode(encoding)


def linkedin_csv(n=20, **kw) -> bytes:
    return to_csv(LI_HEADER, li_rows(n), preamble=kw.pop("preamble", PREAMBLE), **kw)


HR_HEADER = ["Company", "Contact Name", "Job Title", "Email", "Phone", "LinkedIn", "Location", "Notes"]


def hr_rows(n: int, start: int = 0):
    for i in range(start, start + n):
        f, l = person(i + 500)
        yield [COMPANIES[i % len(COMPANIES)], f"{f} {l}", "Technical Recruiter", f"{f.lower()}.{l.lower()}@hr{i % 7}.example.com",
               f"+1 415 555 {i % 10000:04d}", f"linkedin.com/in/synthetic-{i + 500:05d}", "Remote", ""]
