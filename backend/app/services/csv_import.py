"""Tolerant CSV reading for LinkedIn connection exports and HR contact lists.

Handles BOMs, common encodings, ; \\t | delimiters, preamble lines before the header (LinkedIn adds a "Notes:" block),
ragged rows and blank lines. Nothing is dropped silently: callers get every row with its number.
"""
import csv
import io
import re

from charset_normalizer import from_bytes

FIELDS = {
    "linkedin": {
        "first_name": ["first name", "firstname", "given name"],
        "last_name": ["last name", "lastname", "surname", "family name"],
        "full_name": ["name", "full name"],
        "linkedin_url": ["url", "linkedin url", "profile url", "linkedin profile", "linkedin", "profile"],
        "email": ["email address", "email", "e-mail", "e mail"],
        "company": ["company", "organization", "organisation", "employer", "current company"],
        "position": ["position", "title", "job title", "current title", "headline"],
        "connected_on": ["connected on", "connection date", "date connected", "connected"],
    },
    "hr": {
        "company": ["company", "organization", "organisation", "employer", "company name"],
        "name": ["contact name", "name", "full name", "contact", "recruiter", "recruiter name"],
        "first_name": ["first name", "firstname", "given name"],
        "last_name": ["last name", "lastname", "surname"],
        "title": ["job title", "title", "position", "role", "designation"],
        "email": ["email", "email address", "e-mail", "mail", "work email"],
        "phone": ["phone", "mobile", "telephone", "phone number", "contact number", "tel", "cell"],
        "linkedin_url": ["linkedin", "linkedin url", "linkedin profile", "profile url", "url"],
        "location": ["location", "city", "country", "region"],
        "notes": ["notes", "note", "comments", "remarks"],
    },
}
REQUIRED = {"linkedin": [], "hr": []}  # mapping completeness is judged per row (see contacts_import)


def decode(data: bytes) -> tuple[str, str, list[str]]:
    """-> (text, encoding, warnings)."""
    warnings = []
    for enc in ("utf-8-sig",):
        try:
            return data.decode(enc), "utf-8", warnings
        except UnicodeDecodeError:
            pass
    best = from_bytes(data).best()
    if best and best.encoding:
        warnings.append(f"File was not UTF-8; decoded as {best.encoding}")
        return str(best), best.encoding, warnings
    warnings.append("Encoding unknown; decoded as latin-1, some characters may be wrong")
    return data.decode("latin-1"), "latin-1", warnings


def _norm_header(h: str) -> str:
    return re.sub(r"\s+", " ", h.strip().lower().replace("_", " "))


def sniff_delimiter(text: str) -> str:
    sample = "\n".join(text.splitlines()[:40])
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        counts = {d: sample.count(d) for d in ",;\t|"}
        return max(counts, key=counts.get) if any(counts.values()) else ","


def read_rows(text: str, delimiter: str) -> list[list[str]]:
    try:
        return list(csv.reader(io.StringIO(text, newline=""), delimiter=delimiter))
    except csv.Error as e:
        raise ValueError(f"Could not read this file as CSV: {e}") from e


def find_header(rows: list[list[str]], kind: str) -> int:
    """Index of the row that looks most like a header (handles preamble lines). 0 if nothing matches."""
    aliases = {a for v in FIELDS[kind].values() for a in v}
    best, best_i = 0, 0
    for i, r in enumerate(rows[:30]):
        score = sum(1 for c in r if _norm_header(c) in aliases)
        if score > best:
            best, best_i = score, i
    return best_i if best >= 2 else 0


def auto_map(headers: list[str], kind: str) -> dict[str, str | None]:
    """field -> header text (or None). First matching column wins; each column is used once."""
    used, out = set(), {}
    norm = [(_norm_header(h), h) for h in headers]
    for field, aliases in FIELDS[kind].items():
        out[field] = None
        for alias in aliases:  # alias order = priority
            hit = next((h for n, h in norm if n == alias and h not in used), None)
            if hit is not None:
                out[field] = hit
                used.add(hit)
                break
    return out


def unmapped(headers: list[str], mapping: dict[str, str | None]) -> list[str]:
    used = {v for v in mapping.values() if v}
    return [h for h in headers if h.strip() and h not in used]


def iter_records(rows: list[list[str]], header_row: int, mapping: dict[str, str | None]):
    """Yield (row_number, raw_dict, values_dict, notes). row_number is 1-based within the file."""
    headers = [h.strip() for h in rows[header_row]]
    idx = {f: headers.index(h.strip()) for f, h in mapping.items() if h and h.strip() in headers}
    for n, r in enumerate(rows[header_row + 1:], start=header_row + 2):
        notes = []
        if not any(c.strip() for c in r):
            yield n, None, None, ["empty_row"]
            continue
        if len(r) != len(headers):
            notes.append("column_count_mismatch")
            r = (r + [""] * len(headers))[: len(headers)]
        raw = {headers[i]: r[i] for i in range(len(headers)) if headers[i]}
        vals = {f: r[i].strip() or None for f, i in idx.items()}
        yield n, raw, vals, notes
