# Verification checklist: checking ReferralOS against your real data

Everything so far was tested with **synthetic** data and **mock** integrations. This list is how you verify it on the real thing. Work top to bottom; every item says what to upload and what to look at.
Nothing in this checklist sends a real message: keep **Delivery mode = Manual** or **Dry run** until the final step.

Start the app with `ADAPTER_MODE=mock` for steps 1-6 if you want to avoid network use; switch to `real` for steps 7-8.

## 1. Resume → profile accuracy
- **Upload:** your real resume (PDF and, if you have one, the DOCX). Try a two-column layout version too.
- **Inspect:** *Profile → "Compare extracted data with your original resume"*. For every section, is each entry present, correct and attributed to the right line of the original? Look for: merged or split jobs, dates read wrongly (e.g. `Present`), titles/companies swapped, skills that appear in the wrong group.
- **Inspect:** *Diagnostics → Resume parsing*: parser, columns detected, items extracted, mean confidence, items dropped as untraceable, warnings. An image-only/scanned PDF is reported (there is no OCR) rather than guessed.
- **Judge:** how many of your jobs/projects/skills needed correcting? Report the rate; if it is high, send me the (redacted) layout so the heuristics can be extended.
- **Check:** flagged conflicts and duplicate roles are shown for you to resolve, never merged silently. Editing an entry makes it "confirmed by you" and creates a profile version.

## 2. GitHub and portfolio
- **Do:** allow GitHub, enter your username; allow portfolio and give one URL.
- **Inspect:** repositories appear only as *suggestions*; forks and tutorial-style repos are flagged "possibly not original work"; languages become *used in project* skill candidates; nothing is confirmed until you confirm it. Private repos are never read.
- **Check:** a portfolio that disallows crawlers in `robots.txt` is refused with an explanation.

## 3. Imports and data quality
- **Upload:** your real LinkedIn *Connections.csv* (LinkedIn → Settings & Privacy → Data privacy → Get a copy of your data → Connections) and one HR/recruiter list you hold lawfully.
- **Inspect (Imports):** detected encoding/delimiter/header line; the column mapping suggestion; the first rows. Then *Diagnostics → Imports*: columns not used, fields without a column, why rows were flagged.
- **Check the arithmetic:** *rows read = valid + duplicate + invalid*. Open *Inspect rows* for "invalid" and "duplicate": are the reasons right? Are real people wrongly called duplicates (same name, different person)? Do company names collapse sensibly ("Acme Inc." = "Acme")? Review the company match queue; ambiguous merges are never automatic.
- **Check:** HR import demands where the list came from; a "purchased/scraped" answer blocks bulk sending; a bad email is flagged but the person is kept; role mailboxes (`info@`) and no-reply addresses are flagged; add one address to *Do-not-contact* and re-import: it stays suppressed.
- **Dashboard:** "connections imported" and "with employer and title" percentages: how usable is your export?

## 4. Ranking sanity
- **Inspect (Prospects):** open *Why?* on the top 10 and a few at random from the middle. Do the explanations quote real facts (title, company, connection date)? Do they ever claim something you cannot verify? Is anyone high who should not be (a recruiter at an irrelevant company, someone long gone)? Is "confidence" low where employment is old or unknown?
- **Try:** set target companies and excluded companies, change a weight (Settings), press Recalculate: the order changes accordingly and excluded companies drop out.

## 5. Jobs and verification evidence
- **Do:** add the job boards of 3-5 companies you really care about (or paste a job link) and run discovery.
- **Inspect (Jobs):** *coverage of the last run* (which boards answered; which companies you know people at have no reachable board). Open several jobs: *Why this status* and the *Verification evidence* table. Pick one job you **know is closed** and one you **know is open** on the company's own site and compare. `ACTIVE_VERIFIED` should mean the company's own board lists it; a page that merely loads must not.
- **Check:** the referral-route panel says *Unknown* until you point it at an official careers/referral page.

## 6. Resume tailoring and the claim ledger
- **Do:** tailor a resume for a job you would really apply to.
- **Inspect:** *Claim check*: every statement supported; read the **PDF** against your master resume line by line. Is anything on it you did not do? Are skills from the job description appearing that you do not have (they must not)? Is the summary accurate and free of puffery? Are numbers only ones you supplied?
- **Inspect:** *Requirements your background does not support yet* and *Questions for you* (missing metrics). **Try:** edit a bullet to add a technology you did not use: it must be flagged and block approval; then undo.
- **Check:** open the downloaded PDF and DOCX in your usual viewer (selectable text, links work, one column). Approve, then change something: a new version appears and the approved one is unchanged.

## 7. Outreach drafts (still no sending)
- **Do:** set your name and email (Outreach → Settings), acknowledge the lawful-use statement, then *Prepare a new batch*.
- **Inspect:** each LinkedIn and email draft in the *Review* table and the message page. Read them as the recipient: no invented relationship, no promised interview, no claim a referral programme exists unless the company page said so, an easy way to decline, the real job title and official link, an opt-out line in every email. Check *Things to know* (risk flags) and *What this message claims about you*.
- **Try the guard rails:** put `Re:` in a subject; add "as we discussed"; add a technology you do not have; remove the opt-out line: each is blocked with a reason. Edit an approved message: approval is withdrawn.
- **Check limits:** approve several: you are asked to confirm the count and your daily limit. Pause all sending and confirm nothing goes.

## 8. Sending (only when you are ready)
1. Switch to **Dry run**, approve one message, press *Send approved emails now*: it should report a dry run and deliver nothing.
2. Connect Gmail (Settings → Outreach; needs a Google OAuth client; the first real use of this adapter), then **Send one test email to myself**. Confirm it arrives and appears in your Sent folder.
3. Only then send one real, approved message to a contact you are comfortable with. Check Tracking shows it only after it was really sent, and that a repeat send is blocked.
4. Record a reply and a bounce (paste text) and check the classification, suppression suggestion and follow-up cancellation behave as described in `COLD_EMAIL_COMPLIANCE.md`.

## 9. Privacy and deletion
- *Settings → Privacy*: export your data and open the JSON (no password hashes, no tokens). Set a retention period and *Purge now*: the raw CSVs disappear, the contacts remain.
- Optional: create a throwaway second account and confirm it cannot see anything of the first.
- Finally, delete a test account and confirm sign-in fails and nothing remains.

## Report back
For each section: what matched, what did not, and a screenshot or redacted example of any wrong extraction, ranking or claim. If real data exposes schema or ranking problems the system supports **re-import, recalculation and re-versioning without data loss** (profile versions, tailored versions, re-run matching/scoring).
