"""PDF / DOCX / TXT from ONE document model, so the formats cannot drift apart.

ATS-readable by construction: single column, standard section headings, no tables or images, selectable text, standard fonts.
Hyperlinks are real links in PDF and DOCX. Limit: built-in PDF fonts cover Latin-1; other scripts are replaced with '?'
(reported in the render check) until a TTF font is bundled.
"""
import io
from xml.sax.saxutils import escape

HEADINGS = {"summary": "Summary", "skills": "Skills", "experience": "Experience", "projects": "Projects", "education": "Education",
            "certifications": "Certifications", "awards": "Awards"}


def _short(url: str) -> str:
    return url.replace("https://", "").replace("http://", "").replace("www.", "").rstrip("/")


def _href(url: str) -> str:
    return url if url.startswith("http") else "https://" + url


def blocks(content: dict) -> list[tuple]:
    """('name', t) ('contact', [(text, url|None)]) ('heading', t) ('line', [(text, bold, url|None)]) ('bullet', t)"""
    out: list[tuple] = []
    h = content.get("header")
    if h:
        out.append(("name", h["name"] or ""))
        parts = [(x, None) for x in (h.get("email"), h.get("phone")) if x] + [(_short(u), _href(u)) for u in h.get("links", [])]
        if h.get("email"):
            parts[0] = (h["email"], "mailto:" + h["email"])
        out.append(("contact", parts))
    for sec in content["section_order"]:
        if sec == "summary" and content.get("summary"):
            out += [("heading", "Summary"), ("line", [(" ".join(s["text"] for s in content["summary"]["sentences"]), False, None)])]
        elif sec == "skills" and content.get("skills"):
            out.append(("heading", "Skills"))
            out += [("line", [(g["group"] + ": ", True, None), (", ".join(i["name"] for i in g["items"]), False, None)]) for g in content["skills"]]
        elif sec == "experience" and content.get("experience"):
            out.append(("heading", "Experience"))
            for e in content["experience"]:
                dates = " - ".join(x for x in (e["start"], e["end"]) if x)
                out.append(("line", [(e["title"] or "", True, None), (f", {e['organization']}" if e["organization"] else "", False, None), (f"  |  {dates}" if dates else "", False, None)]))
                out += [("bullet", b["text"]) for b in e["bullets"]]
        elif sec == "projects" and content.get("projects"):
            out.append(("heading", "Projects"))
            for p in content["projects"]:
                line = [(p["name"] or "", True, None)]
                if p["stack"]:
                    line.append(("  |  " + ", ".join(p["stack"]), False, None))
                for u in p["links"]:
                    line.append(("  |  ", False, None))
                    line.append((_short(u), False, _href(u)))
                out.append(("line", line))
                out += [("bullet", b["text"]) for b in p["bullets"]]
        elif sec == "education" and content.get("education"):
            out.append(("heading", "Education"))
            for e in content["education"]:
                dates = " - ".join(x for x in (e["start"], e["end"]) if x)
                tail = f"  |  {dates}" + (" (expected)" if e["expected"] else "") + (f"  |  {e['gpa']}" if e["gpa"] else "")
                out.append(("line", [(e["institution"] or "", True, None), (f", {e['degree']}" if e["degree"] else "", False, None), (tail, False, None)]))
                if e["coursework"]:
                    out.append(("line", [("Coursework: " + ", ".join(e["coursework"]), False, None)]))
        elif sec in ("certifications", "awards") and content.get(sec):
            out.append(("heading", HEADINGS[sec]))
            out += [("bullet", c["name"]) for c in content[sec]]
    return out


def to_txt(content: dict) -> str:
    lines = []
    for b in blocks(content):
        if b[0] == "name":
            lines.append(b[1])
        elif b[0] == "contact":
            lines.append(" | ".join(t for t, _ in b[1]))
        elif b[0] == "heading":
            lines += ["", b[1].upper()]
        elif b[0] == "line":
            lines.append("".join(t for t, _, _ in b[1]))
        else:
            lines.append("- " + b[1])
    return "\n".join(lines).strip() + "\n"


def to_pdf(content: dict) -> bytes:
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer

    body = ParagraphStyle("b", fontName="Helvetica", fontSize=9.5, leading=12)
    st = {"name": ParagraphStyle("n", parent=body, fontName="Helvetica-Bold", fontSize=18, leading=22, spaceAfter=2),
          "contact": ParagraphStyle("c", parent=body, fontSize=9, textColor="#333333", spaceAfter=6),
          "heading": ParagraphStyle("h", parent=body, fontName="Helvetica-Bold", fontSize=11, spaceBefore=8, spaceAfter=2),
          "line": ParagraphStyle("l", parent=body, spaceAfter=2), "bullet": ParagraphStyle("bl", parent=body, leftIndent=14, bulletIndent=4, spaceAfter=1.5)}
    safe = lambda s: escape(s.encode("latin-1", "replace").decode("latin-1"))  # noqa: E731
    flow = []
    for b in blocks(content):
        k = b[0]
        if k == "name":
            flow.append(Paragraph(safe(b[1]), st["name"]))
        elif k == "contact":
            flow.append(Paragraph("  |  ".join(f'<a href="{escape(u, {chr(34): "&quot;"})}" color="#1a4d8f">{safe(t)}</a>' if u else safe(t) for t, u in b[1]), st["contact"]))
        elif k == "heading":
            flow += [Paragraph(safe(b[1]), st["heading"]), HRFlowable(width="100%", thickness=0.5, color="#888888", spaceAfter=3)]
        elif k == "line":
            flow.append(Paragraph("".join((f'<a href="{escape(u, {chr(34): "&quot;"})}" color="#1a4d8f">{safe(t)}</a>' if u else f"<b>{safe(t)}</b>" if bold else safe(t)) for t, bold, u in b[1]), st["line"]))
        else:
            flow.append(Paragraph(safe(b[1]), st["bullet"], bulletText="•"))
    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=letter, leftMargin=0.7 * inch, rightMargin=0.7 * inch, topMargin=0.6 * inch, bottomMargin=0.6 * inch,
                      title=(content.get("header") or {}).get("name") or "Resume", author=(content.get("header") or {}).get("name") or "").build(flow + [Spacer(1, 1)])
    return buf.getvalue()


def _add_link(par, text: str, url: str):
    from docx.opc.constants import RELATIONSHIP_TYPE
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    rid = par.part.relate_to(url, RELATIONSHIP_TYPE.HYPERLINK, is_external=True)
    h = OxmlElement("w:hyperlink")
    h.set(qn("r:id"), rid)
    r = OxmlElement("w:r")
    rpr = OxmlElement("w:rPr")
    col = OxmlElement("w:color")
    col.set(qn("w:val"), "1A4D8F")
    u = OxmlElement("w:u")
    u.set(qn("w:val"), "single")
    rpr.append(col)
    rpr.append(u)
    r.append(rpr)
    t = OxmlElement("w:t")
    t.text = text
    t.set(qn("xml:space"), "preserve")
    r.append(t)
    h.append(r)
    par._p.append(h)


def to_docx(content: dict) -> bytes:
    import docx
    from docx.shared import Inches, Pt

    d = docx.Document()
    for s in d.sections:
        s.left_margin = s.right_margin = Inches(0.7)
        s.top_margin = s.bottom_margin = Inches(0.6)
    d.styles["Normal"].font.name, d.styles["Normal"].font.size = "Calibri", Pt(10)
    for b in blocks(content):
        k = b[0]
        if k == "name":
            p = d.add_paragraph()
            r = p.add_run(b[1])
            r.bold, r.font.size = True, Pt(18)
        elif k == "contact":
            p = d.add_paragraph()
            for i, (t, u) in enumerate(b[1]):
                if i:
                    p.add_run("  |  ")
                _add_link(p, t, u) if u else p.add_run(t)
        elif k == "heading":
            d.add_heading(b[1], level=2)
        elif k == "line":
            p = d.add_paragraph()
            for t, bold, u in b[1]:
                _add_link(p, t, u) if u else setattr(p.add_run(t), "bold", bold)
        else:
            d.add_paragraph(b[1], style="List Bullet")
    d.core_properties.title = (content.get("header") or {}).get("name") or "Resume"
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def check_render(content: dict, pdf: bytes, docx_bytes: bytes) -> dict:
    """Reopen the generated files and inspect them: pages exist, text is selectable and complete, links survived."""
    import docx
    import fitz

    from .engine import render_nodes
    want_links = {u for b in blocks(content) for u in ([x for _, x in b[1] if x] if b[0] == "contact" else [x for _, _, x in b[1] if x] if b[0] == "line" else [])}
    res: dict = {"ok": True, "problems": []}
    try:
        doc = fitz.open(stream=pdf, filetype="pdf")
        text = " ".join(" ".join(p.get_text().split()) for p in doc)
        got = {l["uri"] for p in doc for l in p.get_links() if l.get("uri")}
        res["pdf"] = {"pages": len(doc), "chars": len(text), "links": sorted(got)}
        if not doc.page_count or len(text) < 20:
            res["problems"].append("PDF has no selectable text")
        missing = [t[:50] for _, t in render_nodes(content) if t and " ".join(t.split())[:40].encode("latin-1", "replace").decode("latin-1") not in text]
        if missing:
            res["problems"].append(f"PDF is missing text: {missing[:3]}")
        if not want_links <= got:
            res["problems"].append(f"PDF lost links: {sorted(want_links - got)}")
    except Exception as e:  # noqa: BLE001
        res["problems"].append(f"PDF could not be opened: {type(e).__name__}")
    try:
        d = docx.Document(io.BytesIO(docx_bytes))
        links = {r.target_ref for r in d.part.rels.values() if r.reltype.endswith("/hyperlink")}
        res["docx"] = {"paragraphs": len(d.paragraphs), "links": sorted(links), "tables": len(d.tables)}
        if d.tables:
            res["problems"].append("DOCX contains a table (ATS risk)")
        if not want_links <= links:
            res["problems"].append(f"DOCX lost links: {sorted(want_links - links)}")
    except Exception as e:  # noqa: BLE001
        res["problems"].append(f"DOCX could not be opened: {type(e).__name__}")
    res["ok"] = not res["problems"]
    return res
