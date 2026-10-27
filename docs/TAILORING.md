# Resume tailoring and claim validation

## Principle

Tailoring **selects, orders and groups what your Master Career Profile already says**. It never invents. Bullets are copied verbatim, education and dates are copied exactly,
skills come only from your active profile entries, and a keyword in a job description is never added without evidence.

## What the engine does (`services/tailoring/engine.py`)

| Section | Rule |
|---|---|
| Summary | built from facts with fixed templates: your degree (student vs graduate, expected date), the ≤3 JD-relevant skills you have **used** (job or project), the names of ≤2 included projects. No durations, no superlatives. If there are not enough facts, there is **no summary** rather than filler. |
| Skills | only active skills; JD-relevant first; used skills before listed-only; studied-only skills kept in a separate "Studied" group; never added because a posting mentions them. |
| Experience | most recent first, duplicates dropped; the most relevant bullets kept (default 4) **in their original order and wording**. |
| Projects | ranked by overlap with the posting's skills (ties keep your own order); stack lists are copied, never extended; links only if you supplied them. |
| Education / certifications / awards | copied exactly. |
| Section order | early-career or internship → education/skills/projects first; experienced → skills/experience first; AI/ML role with ML projects and < 3 years → projects before experience. Overridable. |
| Left out | entries with an unresolved conflict or date problem, duplicates, unconfirmed GitHub/portfolio suggestions. All are listed in the change report. |
| Missing numbers | become **questions** ("Do you have a number for …?"), never numbers. |

## The claim ledger and the one validator (`services/tailoring/validate.py`)

Every text node (summary sentence, bullet, role line, skill, project, education entry, header) carries a claim id; the ledger maps each claim to the profile facts that support it.
A claim is **validated** only if it cites at least one existing **active** fact; none of its facts has an unresolved conflict or date-order problem;
and **every technology and every number in the text also appears in the cited facts** (synonyms normalised). Otherwise it is `excluded` (no usable support) or `needs_confirmation`.
The same function checks generated text, **your edits**, and **language-model proposals**. A version cannot be approved while any claim needs confirmation or an excluded claim is present.

Editing a bullet and adding something the facts do not contain (a new technology, a number) flags it. The only route from a resume edit into your master profile is the explicit
**"This is true: add to my profile"** action, which records a new confirmed fact and a new profile version. Tailoring never modifies the master.

## Optional language model

Off by default (everything works without it). If you consent, add your own key and set a monthly budget, a model may *propose a rewording of one existing bullet*; it is accepted only if
`check_rewrite` finds no new technology, number or proper noun and no large growth, otherwise the original stands. Only the bullet and the job's skill names are sent, with emails,
phone numbers and links stripped first; the call stops at the budget; only token counts and an estimated cost are logged. *Verified against mock HTTP only.*

## Output and verification

Per version: `resume.pdf`, `resume.docx`, `resume.txt`, `requirement_matrix.json`, `validation_report.json` (with the ledger), `tailoring_summary.md`, `diff.json`, plus a zip bundle.
One document model renders all three formats, so they cannot drift. ATS-readable by construction: single column, standard headings, no tables or images, selectable text, standard fonts.
After rendering, the generator **reopens the files**: pages exist, text is selectable and complete, hyperlinks survive in the PDF and DOCX, the DOCX has no table. A version whose render check fails cannot be approved.
Known limit: the built-in PDF fonts cover Latin-1; other scripts are replaced with `?` until a font is bundled. There is no spell-checker: text is your own wording or fixed templates.

## Versions

Every edit, regeneration or confirmation creates a **new version** with a parent link. Approving locks a version: it is never modified afterwards (tested). Outreach drafts can attach only a version you approved for that job.
