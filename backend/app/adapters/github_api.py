"""GitHub REST adapter (public data only). Tokens are intentionally not supported yet: private repos are never read.

shortcut: no dependency-file skill inference (needs extra API calls); languages and topics only.
"""
import re

import httpx

from ..services import taxonomy
from ..services.resume_parse import Item

API = "https://api.github.com"
_USER = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
_BOILER = re.compile(r"tutorial|course|bootcamp|template|boilerplate|starter|followalong|follow-along|clone|learning", re.I)


class GitHubError(Exception):
    pass


class NotFound(GitHubError):
    pass


class RateLimited(GitHubError):
    pass


def parse_username(s: str) -> str:
    s = s.strip().rstrip("/")
    m = re.match(r"(?:https?://)?(?:www\.)?github\.com/([^/\s]+)", s, re.I)
    name = m.group(1) if m else s.lstrip("@")
    if not _USER.match(name):
        raise GitHubError("That doesn't look like a GitHub username")
    return name


class GitHubClient:
    def __init__(self, client: httpx.Client):
        self.c = client

    def _get(self, path: str, **kw) -> httpx.Response:
        r = self.c.get(API + path, headers={"Accept": kw.pop("accept", "application/vnd.github+json")}, **kw)
        if r.status_code in (403, 429) and r.headers.get("x-ratelimit-remaining") == "0":
            raise RateLimited("GitHub rate limit reached; try again later")
        if r.status_code == 404:
            raise NotFound(path)
        if r.status_code >= 400:
            raise GitHubError(f"GitHub returned {r.status_code}")
        return r

    def repos(self, username: str, max_pages: int = 3) -> list[dict]:
        self._get(f"/users/{username}")  # distinguishes unknown user (404) from empty
        out = []
        for page in range(1, max_pages + 1):
            batch = self._get(f"/users/{username}/repos", params={"per_page": 100, "sort": "pushed", "page": page}).json()
            out += [r for r in batch if not r.get("private")]
            if len(batch) < 100:
                break
        return out

    def readme(self, full_name: str) -> str | None:
        try:
            return self._get(f"/repos/{full_name}/readme", accept="application/vnd.github.raw").text[:4000]
        except NotFound:
            return None


def to_items(repos: list[dict], readmes: dict[str, str | None]) -> list[Item]:
    """Suggestions only. Forks/tutorial repos are flagged 'possibly not original'; skills are USED_IN_PROJECT candidates."""
    items, langs = [], {}
    for r in repos:
        flags = []
        if r.get("fork"):
            flags.append({"type": "possibly_not_original", "note": "This repository is a fork"})
        if _BOILER.search(r["name"]) or any(_BOILER.search(t) for t in r.get("topics", [])):
            flags.append({"type": "possibly_not_original", "note": "Looks like a tutorial, template or course project"})
        readme = readmes.get(r["full_name"]) or ""
        stack = {taxonomy.normalize(x) or None for x in [r.get("language")] + r.get("topics", [])}
        stack |= taxonomy.skill_set(readme)
        stack = sorted(s for s in stack if s)
        if r.get("language") and (c := taxonomy.normalize(r["language"])):
            langs[c] = langs.get(c, 0) + 1
        items.append(Item("project", {
            "name": r["name"], "description": [r["description"]] if r.get("description") else [], "stack": stack,
            "repo_url": r["html_url"], "demo_url": None, "contribution": None, "outcomes": [],
            "stars": r.get("stargazers_count", 0), "pushed_at": r.get("pushed_at"), "readme_excerpt": readme[:500],
        }, (0, 0), 0.5, flags))
    for lang in langs:
        items.append(Item("skill", {"name": lang, "category": taxonomy.category(lang), "raw": lang}, (0, 0), 0.5,
                          evidence_level="USED_IN_PROJECT"))
    return items
