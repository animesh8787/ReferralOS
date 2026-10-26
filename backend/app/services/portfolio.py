"""Portfolio page ingestion: fetch only the URL the user supplied, extract text and links. Low confidence by design."""
import re
from html.parser import HTMLParser
from urllib.parse import urljoin

from . import taxonomy
from .resume_parse import Item


class _Text(HTMLParser):
    BLOCK = {"p", "div", "li", "ul", "ol", "br", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "table"}

    def __init__(self):
        super().__init__()
        self.title, self.parts, self.links, self._skip, self._in_title = "", [], [], 0, False

    def handle_starttag(self, tag, attrs):
        if tag in self.BLOCK:
            self.parts.append("\n")  # block tags add newline parts so line structure survives
        if tag in ("script", "style", "noscript"):
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)

    def handle_endtag(self, tag):
        if tag in self.BLOCK:
            self.parts.append("\n")
        if tag in ("script", "style", "noscript"):
            self._skip = max(0, self._skip - 1)
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip and data.strip():
            self.parts.append(data.strip())


def text_with_lines(parts: list[str]) -> str:
    """Join parsed pieces: spaces between inline text, one newline per block boundary."""
    text = re.sub(r"[ \t]*\n[ \t]*", "\n", " ".join(parts))
    return re.sub(r"\n{2,}", "\n", text).strip()


def parse_html(html: str, base_url: str) -> dict:
    p = _Text()
    p.feed(html)
    links = sorted({urljoin(base_url, h) for h in p.links if not h.startswith(("javascript:", "#", "mailto:"))})
    return {"title": p.title.strip(), "text": text_with_lines(p.parts)[:6000], "links": links}


_REPO = re.compile(r"^https://github\.com/([\w.-]+)/([\w.-]+)/?$", re.I)


def to_items(page: dict) -> list[Item]:
    items = []
    for u in page["links"]:
        m = _REPO.match(u)
        if m:
            items.append(Item("project", {"name": m.group(2), "description": [], "stack": [], "repo_url": u, "demo_url": None,
                                          "contribution": None, "outcomes": []}, (0, 0), 0.4))
    for s in sorted(taxonomy.skill_set(page["text"])):
        items.append(Item("skill", {"name": s, "category": taxonomy.category(s), "raw": s}, (0, 0), 0.4,
                          evidence_level="CLAIMED_ONLY"))
    return items
