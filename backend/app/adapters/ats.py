"""Public ATS job-board adapters (Greenhouse, Lever, Ashby, Workable, SmartRecruiters) + schema.org JobPosting.

Only documented public job-board endpoints are used; tokens are validated and placed in the path of fixed hosts
(no user-controlled hostnames). Each adapter maps its payload to RawJob.

STATUS: written from the vendors' public documentation and exercised ONLY against hand-built fixtures that follow
those documented shapes (app/adapters/fake_ats.py). They have not been run against the live services.
"""
import html
import json
import re
from dataclasses import dataclass
from urllib.parse import urljoin

from ..services.portfolio import _Text, text_with_lines

TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,59}$")
ATS_TYPES = ("greenhouse", "lever", "ashby", "workable", "smartrecruiters")


class AtsError(Exception):
    pass


class BoardNotFound(AtsError):
    pass


@dataclass
class RawJob:
    source_type: str
    board_token: str
    source_job_id: str
    title: str
    location: str | None = None
    remote: bool | None = None
    employment_type: str | None = None
    description: str = ""
    apply_url: str | None = None
    source_url: str | None = None
    posted_at: str | None = None
    deadline: str | None = None
    company_name: str | None = None  # only known for JSON-LD pages
    workplace: str | None = None  # remote|hybrid|onsite when the source states it explicitly


def html_to_text(s: str | None) -> str:
    if not s:
        return ""
    p = _Text()
    p.feed(html.unescape(s) if "&lt;" in s else s)
    return re.sub(r"[ \t]+", " ", text_with_lines(p.parts))  # one item per line: the analyser reads headings and bullets


def check_token(token: str) -> str:
    if not TOKEN_RE.match(token or ""):
        raise AtsError("Invalid board token")
    return token


def _get(fetcher, url: str) -> dict | list:
    r = fetcher.get(url, public_only=False)
    if r.status_code == 404:
        raise BoardNotFound(url)
    if r.status_code >= 400:
        raise AtsError(f"HTTP {r.status_code}")
    try:
        return r.json()
    except ValueError as e:
        raise AtsError("Response was not JSON") from e


# ---------------------------------------------------------------- Greenhouse
def greenhouse_list(f, token: str) -> list[RawJob]:
    data = _get(f, f"https://boards-api.greenhouse.io/v1/boards/{check_token(token)}/jobs?content=true")
    return [RawJob("greenhouse", token, str(j["id"]), j["title"], (j.get("location") or {}).get("name"), None, None,
                   html_to_text(j.get("content")), j.get("absolute_url"), j.get("absolute_url"), j.get("updated_at"))
            for j in data.get("jobs", [])]


# ---------------------------------------------------------------- Lever
def lever_list(f, token: str) -> list[RawJob]:
    data = _get(f, f"https://api.lever.co/v0/postings/{check_token(token)}?mode=json")
    out = []
    for j in data:
        cat = j.get("categories") or {}
        wp = (j.get("workplaceType") or "").replace("-", "").lower() or None
        out.append(RawJob("lever", token, j["id"], j["text"], cat.get("location"), (wp == "remote") or None,
                          cat.get("commitment"), j.get("descriptionPlain") or html_to_text(j.get("description")), j.get("applyUrl"),
                          j.get("hostedUrl"), str(j.get("createdAt")) if j.get("createdAt") else None, workplace=wp if wp in ("remote", "hybrid", "onsite") else None))
    return out


# ---------------------------------------------------------------- Ashby
def ashby_list(f, token: str) -> list[RawJob]:
    data = _get(f, f"https://api.ashbyhq.com/posting-api/job-board/{check_token(token)}")
    return [RawJob("ashby", token, j["id"], j["title"], j.get("location"), j.get("isRemote"), j.get("employmentType"),
                   j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml")), j.get("applyUrl"), j.get("jobUrl"), j.get("publishedAt"))
            for j in data.get("jobs", []) if j.get("isListed", True)]


# ---------------------------------------------------------------- Workable
def workable_list(f, token: str) -> list[RawJob]:
    data = _get(f, f"https://apply.workable.com/api/v1/widget/accounts/{check_token(token)}?details=true")
    out = []
    for j in data.get("jobs", []):
        loc = ", ".join(x for x in (j.get("city"), j.get("state"), j.get("country")) if x) or None
        out.append(RawJob("workable", token, j["shortcode"], j["title"], loc, j.get("telecommuting"), j.get("employment_type"),
                          html_to_text(j.get("description")), j.get("application_url") or j.get("url"), j.get("url"), j.get("published_on")))
    return out


# ---------------------------------------------------------------- SmartRecruiters
def smartrecruiters_list(f, token: str) -> list[RawJob]:
    data = _get(f, f"https://api.smartrecruiters.com/v1/companies/{check_token(token)}/postings")
    out = []
    for j in data.get("content", []):
        loc = j.get("location") or {}
        place = ", ".join(x for x in (loc.get("city"), loc.get("region"), loc.get("country")) if x) or None
        out.append(RawJob("smartrecruiters", token, j["id"], j["name"], place, loc.get("remote"), (j.get("typeOfEmployment") or {}).get("label"),
                          "", j.get("applyUrl") or j.get("ref"), j.get("ref"), j.get("releasedDate")))
    return out


LISTERS = {"greenhouse": greenhouse_list, "lever": lever_list, "ashby": ashby_list, "workable": workable_list, "smartrecruiters": smartrecruiters_list}


def list_jobs(fetcher, ats: str, token: str) -> list[RawJob]:
    if ats not in LISTERS:
        raise AtsError(f"Unsupported ATS '{ats}'")
    return LISTERS[ats](fetcher, token)


def board_from_url(url: str) -> tuple[str, str] | None:
    """Recognise a public job-board URL and return (ats, token). Nothing is fetched."""
    for ats, rx in (("greenhouse", r"(?:boards|job-boards)\.greenhouse\.io/([\w.-]+)"), ("lever", r"jobs\.lever\.co/([\w.-]+)"),
                    ("ashby", r"jobs\.ashbyhq\.com/([\w.-]+)"), ("workable", r"apply\.workable\.com/([\w.-]+)"),
                    ("smartrecruiters", r"(?:careers|jobs)\.smartrecruiters\.com/([\w.-]+)")):
        m = re.search(rx, url, re.I)
        if m and TOKEN_RE.match(m.group(1)):
            return ats, m.group(1)
    return None


# ---------------------------------------------------------------- schema.org JobPosting (JSON-LD)
def parse_jsonld(html_text: str, base_url: str) -> list[RawJob]:
    out = []
    for m in re.finditer(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html_text, re.S | re.I):
        try:
            data = json.loads(m.group(1))
        except ValueError:
            continue
        nodes = data if isinstance(data, list) else data.get("@graph", [data]) if isinstance(data, dict) else []
        for n in nodes:
            if not isinstance(n, dict) or "JobPosting" not in str(n.get("@type")):
                continue
            loc = n.get("jobLocation")
            loc = loc[0] if isinstance(loc, list) and loc else loc
            addr = (loc or {}).get("address", {}) if isinstance(loc, dict) else {}
            place = ", ".join(x for x in (addr.get("addressLocality"), addr.get("addressRegion"), addr.get("addressCountry") if isinstance(addr.get("addressCountry"), str) else None) if x) or None
            org = n.get("hiringOrganization")
            ident = n.get("identifier")
            jid = str(ident.get("value") if isinstance(ident, dict) else ident or n.get("url") or n.get("title"))
            out.append(RawJob("jsonld", "", jid, str(n.get("title") or ""), place, "TELECOMMUTE" in str(n.get("jobLocationType", "")) or None,
                              str(n.get("employmentType") or "") or None, html_to_text(n.get("description")), n.get("url") or base_url,
                              n.get("url") or base_url, n.get("datePosted"), n.get("validThrough"),
                              (org.get("name") if isinstance(org, dict) else str(org or "")) or None))
    return [j for j in out if j.title]
