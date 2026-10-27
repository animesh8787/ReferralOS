"""docs/ReferralOS_Test_Guide.pdf: the tests still needed and exactly how to run them.
Run:  cd backend && uv run python ../scripts/make_test_guide.py"""
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (KeepTogether, ListFlowable, ListItem, PageBreak, Paragraph, Preformatted, SimpleDocTemplate, Spacer,
                                Table, TableStyle)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "ReferralOS_Test_Guide.pdf"

ss = getSampleStyleSheet()
H1 = ParagraphStyle("H1", parent=ss["Heading1"], fontSize=18, spaceAfter=6, textColor=colors.HexColor("#111827"))
H2 = ParagraphStyle("H2", parent=ss["Heading2"], fontSize=13.5, spaceBefore=10, spaceAfter=4, textColor=colors.HexColor("#1f2937"))
H3 = ParagraphStyle("H3", parent=ss["Heading3"], fontSize=11, spaceBefore=6, spaceAfter=2, textColor=colors.HexColor("#374151"))
B = ParagraphStyle("B", parent=ss["BodyText"], fontSize=9.5, leading=13, alignment=TA_LEFT)
SMALL = ParagraphStyle("S", parent=B, fontSize=8.5, leading=11, textColor=colors.HexColor("#4b5563"))
CODE = ParagraphStyle("C", fontName="Courier", fontSize=8.3, leading=10.5, backColor=colors.HexColor("#f3f4f6"),
                      borderPadding=4, leftIndent=4, spaceBefore=2, spaceAfter=6)
CELL = ParagraphStyle("cell", parent=B, fontSize=8.5, leading=10.5)


def p(t, s=B):
    return Paragraph(t, s)


def code(t):
    return Preformatted(t.strip("\n"), CODE)


def bullets(items, numbered=False):
    return ListFlowable([ListItem(p(i), leftIndent=12) for i in items], bulletType="1" if numbered else "bullet",
                        start="1" if numbered else None, leftIndent=14, bulletFontSize=8.5)


def box(title, text, color="#fef3c7", border="#d97706"):
    t = Table([[p(f"<b>{title}</b> {text}", CELL)]], colWidths=[170 * mm])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(color)), ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor(border)),
                           ("LEFTPADDING", (0, 0), (-1, -1), 6), ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    return t


def table(rows, widths, header=True):
    data = [[p(str(c), CELL) for c in r] for r in rows]
    t = Table(data, colWidths=[w * mm for w in widths], repeatRows=1 if header else 0)
    st = [("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1d5db")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
          ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4)]
    if header:
        st.append(("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e5e7eb")))
    t.setStyle(TableStyle(st))
    return t


def test(tid, title, goal, prepare, steps, passes, record):
    """One manual test: goal, what to have ready, numbered steps, pass criteria, what to write down."""
    out = [p(f"{tid}  {title}", H3), p(f"<b>Goal:</b> {goal}")]
    if prepare:
        out.append(p(f"<b>Have ready:</b> {prepare}"))
    out += [p("<b>Steps:</b>"), bullets(steps, numbered=True), p("<b>Pass if:</b>"), bullets(passes)]
    if record:
        out.append(p(f"<b>Write down:</b> {record}", SMALL))
    out.append(Spacer(1, 4))
    return out


story = []
# ------------------------------------------------------------------ cover
story += [p("ReferralOS - Test Guide", H1),
          p("What still needs testing, and exactly how to do it", ss["Heading3"]),
          p("Version for the build of 27 Oct 2026 (commit a9f6ef5). Windows commands; paths assume the project is at "
            "<font name='Courier'>C:\\Users\\anime\\Desktop\\Referral Portal</font>."), Spacer(1, 6),
          p("Why this guide exists", H2),
          p("The automated tests prove the logic and the safety rules, but only with <b>fictional data</b> and <b>simulated</b> Gmail/AI. "
            "They cannot tell you whether your real resume is read correctly, whether your real LinkedIn export imports cleanly, whether "
            "the ranking makes sense for your network, or whether a real Gmail account sends. Those are the tests in Part C, and only "
            "you can run them, because they use your own data."),
          table([["Area", "Already verified", "You still need to verify"],
                 ["Backend logic (402 tests)", "Yes, SQLite + PostgreSQL", "Re-run after any change (Part B)"],
                 ["Browser flow (Playwright)", "Yes, with fake data", "Re-run after any change (Part B)"],
                 ["Resume reading", "Synthetic resumes only", "Your real resume (C1)"],
                 ["GitHub / portfolio", "GitHub API once, read-only", "Your account and site (C2)"],
                 ["CSV imports", "Synthetic 11k rows", "Your real LinkedIn export (C3)"],
                 ["Contact ranking", "Rules tested", "Does the order make sense to you (C4)"],
                 ["Job boards", "5 public board APIs, once", "Companies you care about (C5)"],
                 ["Resume tailoring", "Rules tested", "Read the real PDF line by line (C6)"],
                 ["Outreach drafts", "Rules tested", "Read as the recipient (C7)"],
                 ["Gmail sending", "Simulated only - never real", "Dry run, then self-test, then one real (C8)"],
                 ["Privacy / deletion", "Tested", "Export, purge, delete (C9)"],
                 ["docker compose", "Not run", "Optional (Part D)"]], [42, 58, 70]),
          Spacer(1, 8),
          box("Safety rule for the whole guide:", "nothing you do in C1-C7 can send a message. Keep <b>Delivery mode = Manual</b> "
              "(or Dry run) until test C8. Do not connect real Gmail before C1-C7 look right."),
          Spacer(1, 6),
          p("How to use it", H2),
          bullets(["Do Part A once (start the app).", "Do Part B whenever code changes (5-10 minutes, automatic).",
                   "Do Part C in order. Each test lists: goal, what to have ready, numbered steps, <b>Pass if</b>, and what to write down.",
                   "Fill in the results sheet at the end (Part E) and send it back with screenshots of anything wrong (blur personal details)."]),
          PageBreak()]

# ------------------------------------------------------------------ part A
story += [p("Part A - Start the app (once, about 10 minutes)", H2),
          p("<b>You need:</b> Python 3.11 with <font name='Courier'>uv</font>, Node.js 20 or newer, and three terminal windows. "
            "No <font name='Courier'>.env</font> file is needed for local testing: the defaults are SQLite and offline (mock) mode."),
          box("Important:", "do <b>not</b> copy <font name='Courier'>.env.example</font> into <font name='Courier'>backend\\</font>. "
              "That file is for docker compose and points the database at a host called <font name='Courier'>db</font>, which does not exist "
              "outside Docker.", "#fee2e2", "#dc2626"), Spacer(1, 6),
          p("Terminal 1 - the API", H3),
          code('cd "C:\\Users\\anime\\Desktop\\Referral Portal\\backend"\nuv sync\nuv run alembic upgrade head\nuv run uvicorn app.main:app --port 8000'),
          p("Wait for <font name='Courier'>Application startup complete</font>. Check: open http://localhost:8000/docs - the API page loads."),
          p("Terminal 2 - the background worker", H3),
          code('cd "C:\\Users\\anime\\Desktop\\Referral Portal\\backend"\nuv run python -m app.worker'),
          p("Leave it running. Imports, parsing, scoring, matching and sending happen here. If it is not running, those jobs stay \"queued\" forever."),
          p("Terminal 3 - the web app", H3),
          code('cd "C:\\Users\\anime\\Desktop\\Referral Portal\\frontend"\nnpm install\nnpm run dev'),
          p("Open <b>http://localhost:3000</b>."),
          p("Create your account", H3),
          bullets(["Click <b>Sign up</b>, enter your email and a password (at least 10 characters, with a letter and a digit).",
                   "No real email is sent in local mode. Open the newest file in <font name='Courier'>backend\\data\\outbox\\</font>, "
                   "copy the verification link from it, and open it in the browser.",
                   "Sign in. The onboarding wizard opens; you can follow it or skip and use the menu."], numbered=True),
          p("<b>Pass if:</b> you reach the Dashboard signed in. <b>If not:</b> see Troubleshooting (Part F).", B),
          Spacer(1, 4),
          p("Offline vs real mode", H3),
          p("Steps C1, C3, C4, C6, C7 work fully offline. C2 (GitHub/portfolio) and C5 (job boards) need internet: stop Terminal 1 and 2 "
            "(Ctrl+C) and restart them with real mode:"),
          code('$env:ADAPTER_MODE="real"; uv run uvicorn app.main:app --port 8000      # Terminal 1 (PowerShell)\n'
               '$env:ADAPTER_MODE="real"; uv run python -m app.worker                 # Terminal 2 (PowerShell)'),
          p("Real mode only makes read-only requests to public sites and APIs. It still cannot send email without Gmail connected and your approval.", SMALL),
          PageBreak()]

# ------------------------------------------------------------------ part B
story += [p("Part B - Automated tests (run after every code change)", H2),
          p("These need no data from you. Close the app first (Ctrl+C in all three terminals) so ports 3100/8100 are free."),
          p("B1. Backend tests on SQLite (about 4 minutes)", H3),
          code('cd "C:\\Users\\anime\\Desktop\\Referral Portal\\backend"\nuv run pytest -q -p no:warnings'),
          p("<b>Pass if:</b> the last line says <font name='Courier'>402 passed</font> (or more) and <b>0 failed</b>."),
          p("B2. Browser tests (about 2 minutes)", H3),
          code('cd "C:\\Users\\anime\\Desktop\\Referral Portal\\frontend"\nnpx playwright test'),
          p("Starts its own throwaway API (port 8100) and web app (port 3100) with fake data, then clicks through sign-up to account "
            "deletion, checks 20 pages at phone width, and runs an accessibility audit. <b>Pass if:</b> <font name='Courier'>3 passed</font>. "
            "To watch it: <font name='Courier'>npx playwright test --headed</font>. On failure: <font name='Courier'>npx playwright show-report</font>."),
          p("B3. Backend tests on PostgreSQL (optional, about 12 minutes)", H3),
          p("Needed only before running with several users. Requires Docker Desktop to be running."),
          code('docker run -d --name referralos-test-pg -e POSTGRES_USER=referralos -e POSTGRES_PASSWORD=testpw ^\n'
               '  -e POSTGRES_DB=referralos_test -p 55432:5432 postgres:16\n'
               'cd "C:\\Users\\anime\\Desktop\\Referral Portal\\backend"\n'
               '$env:TEST_DATABASE_URL="postgresql+psycopg://referralos:testpw@localhost:55432/referralos_test"\n'
               'uv run pytest -q -p no:warnings\n'
               'Remove-Item Env:TEST_DATABASE_URL; docker rm -f referralos-test-pg'),
          p("(In PowerShell, put the <font name='Courier'>docker run</font> command on one line instead of using <font name='Courier'>^</font>.)", SMALL),
          p("<b>Pass if:</b> 0 failed. Postgres catches things SQLite ignores (text length limits, NUL bytes) - it found two real bugs last time."),
          p("B4. One test only (when something fails)", H3),
          code('uv run pytest -q -p no:warnings tests/test_outreach_flow.py -k linkedin'),
          p("<font name='Courier'>docs/ACCEPTANCE.md</font> lists which test proves each of the 14 required scenarios."),
          PageBreak()]

# ------------------------------------------------------------------ part C
story += [p("Part C - Real-data tests (you run these)", H2),
          p("Do them in order: later tests use what earlier ones created. Allow 2-3 hours in total. Keep a notes file open for the "
            "\"Write down\" items.")]

story += test("C1", "Resume -> profile accuracy",
              "The app reads your real resume correctly and never invents anything.",
              "Your resume as PDF; the DOCX version if you have one; a two-column version if you have one. Offline mode is fine.",
              ["Menu <b>Profile</b> -> upload your PDF. Wait until its status is <b>parsed</b> (the worker must be running).",
               "Click <b>Compare extracted data with your original resume</b>. The original text is shown next to what was extracted.",
               "Go section by section (experience, education, projects, skills). For each entry check: is it there, is it correct, does it point to the right line of the original?",
               "Look specifically for: two jobs merged into one, one job split in two, dates wrong (especially <i>Present</i>), title and company swapped, skills in the wrong group.",
               "Menu <b>Diagnostics</b> -> Resume parsing: note the parser, columns detected, items extracted, mean confidence, items dropped, warnings.",
               "Edit one wrong entry and save. Then open <b>Profile -> versions</b>.",
               "Upload the DOCX and the two-column PDF too, and repeat steps 2-4 for each.",
               "Optional: upload <font name='Courier'>samples\\resumes\\scanned_image_only.pdf</font>."],
              ["Every entry shown can be traced to a line in your original - nothing appears that is not in your resume.",
               "Conflicts and duplicate roles are listed for you to resolve, never merged silently.",
               "The edited entry is marked <i>confirmed by you</i> and a new profile version exists.",
               "The scanned file is reported as image-only (there is no OCR) instead of guessed."],
              "Number of entries in your resume, number that needed correcting (= error rate), and each wrong one with what it should be.")

story += test("C2", "GitHub and portfolio",
              "Public repos become suggestions only; nothing is trusted until you confirm it.",
              "Real mode (Part A). Your GitHub username; your portfolio URL if you have one.",
              ["<b>Settings</b> (or Profile) -> allow GitHub, enter your username, start the import.",
               "Open the suggested projects in <b>Profile</b>.",
               "Allow portfolio, enter one URL, start the import.",
               "Optional: try a site whose robots.txt disallows crawlers."],
              ["Repos appear as <i>suggestions</i>, not confirmed facts.",
               "Forks and tutorial/template repos are flagged <i>possibly not original</i>.",
               "Languages become <i>used in project</i> skill candidates; nothing becomes confirmed until you confirm it.",
               "Private repos never appear. A disallowed site is refused with an explanation."],
              "Any repo flagged wrongly or not flagged when it should be.")

story += test("C3", "Imports and data quality",
              "Your real LinkedIn export imports without silently losing anyone.",
              "LinkedIn <i>Connections.csv</i>: LinkedIn -> Settings &amp; Privacy -> Data privacy -> Get a copy of your data -> "
              "choose <i>Connections</i> -> wait for the email (can take up to a day) -> unzip. Optionally an HR/recruiter list you hold lawfully.",
              ["Menu <b>Imports</b> -> LinkedIn -> upload <i>Connections.csv</i>.",
               "Check the detected encoding, delimiter and header line, the suggested column mapping and the first rows. Fix the mapping if needed, then start.",
               "When done, read the report and check: <b>rows read = valid + duplicate + invalid</b>.",
               "Click <b>Inspect rows</b> for invalid and duplicate rows. Are the reasons right? Are two different people with the same name wrongly called duplicates?",
               "Open <b>Companies</b> -> the match review queue. Do \"Acme Inc.\" and \"Acme\" collapse sensibly? Ambiguous ones must wait for you.",
               "Optional HR list: import it. It must ask where the list came from. Choose <i>self-collected</i> (a purchased/scraped list blocks bulk sending).",
               "Add one address to <b>Do-not-contact</b>, import the same file again, and check that address stays suppressed.",
               "Check <b>Diagnostics -> Imports</b> and the <b>Dashboard</b> percentages (connections with employer and title)."],
              ["The arithmetic adds up and every rejected row has a reason.",
               "No real person is wrongly merged or dropped.",
               "Bad emails are flagged but the person is kept; <font name='Courier'>info@</font> / no-reply addresses are flagged.",
               "The do-not-contact address stays suppressed after re-import."],
              "Rows read / valid / duplicate / invalid; any wrong duplicate or wrong company merge.")

story += test("C4", "Ranking sanity",
              "The people ranked highest are genuinely the best people to ask, and every reason is true.",
              "C3 done. Your target companies and roles.",
              ["<b>Settings</b> -> set your target roles, target companies and any companies to exclude. Save.",
               "Menu <b>Prospects</b> -> press <b>Recalculate</b> and wait.",
               "Open <b>Why?</b> on the top 10, and on 5 people picked at random from the middle of the list.",
               "Change one weight in <b>Settings</b> (e.g. raise company match), press <b>Recalculate</b> again."],
              ["Every explanation quotes a real fact (title, company, connection date) and claims nothing you cannot verify.",
               "Nobody is high who obviously should not be (irrelevant recruiter, someone who left long ago).",
               "Confidence is low where employment information is old or unknown.",
               "Excluded companies disappear; the order changes in the direction of the weight you changed."],
              "Anyone in the top 20 who should not be there, and why.")

story += test("C5", "Jobs and verification evidence",
              "A job marked open really is open, and a closed one is not called open.",
              "Real mode. 3-5 companies you care about; one job you <b>know is closed</b> and one you <b>know is open</b> on the company's own careers site.",
              ["Menu <b>Jobs</b> -> add the companies' job boards (or paste a job link) and run discovery.",
               "Read the <i>coverage of the last run</i>: which boards answered, which companies have no reachable board.",
               "Open the job you know is open and the one you know is closed. Read <b>Why this status</b> and the verification evidence table.",
               "Open the referral-route panel of one job."],
              ["The open job is <font name='Courier'>ACTIVE_VERIFIED</font> only because the company's own board lists it - not just because a page loaded.",
               "The closed job is not shown as active.",
               "The referral route says <i>Unknown</i> until you point it at an official careers/referral page."],
              "Any job whose status disagrees with the company's site.")

story += test("C6", "Resume tailoring and the claim ledger",
              "A tailored resume contains only things you actually did.",
              "C1 done (profile corrected and confirmed). A real job from C5 you would apply to.",
              ["Open the job (or <b>Opportunities</b>) and start tailoring a resume for it. Open the result under <b>Resumes</b>.",
               "Read <b>Claim check</b>: every statement should be marked supported.",
               "Download the <b>PDF</b> and read it line by line against your own resume.",
               "Read <i>Requirements your background does not support yet</i> and <i>Questions for you</i>.",
               "Guard-rail test: edit a bullet to add a technology you have never used. Try to approve. Then undo the edit.",
               "Approve the resume, then change something and look at the versions.",
               "Open the PDF and DOCX in your normal viewer: text selectable, links clickable, one column."],
              ["Nothing on the PDF is something you did not do; no skill appears just because the job asks for it; every number is one you gave.",
               "The fake technology is flagged and approval is blocked.",
               "After approval, a change creates a new version and the approved one stays unchanged."],
              "Any sentence on the PDF that is not true or is exaggerated.")

story += test("C7", "Outreach drafts (still no sending)",
              "Drafts are honest and the safety checks block bad messages.",
              "C3-C6 done. Delivery mode must be <b>Manual</b> or <b>Dry run</b>.",
              ["<b>Outreach -> Settings</b>: enter your name and email, acknowledge the lawful-use statement. Confirm delivery mode is Manual.",
               "<b>Outreach</b> -> <b>Prepare a new batch</b>.",
               "Read every draft as if you were the recipient. Also read <i>Things to know</i> and <i>What this message claims about you</i>.",
               "Guard-rail tests on one draft, one at a time, trying to approve after each: (a) put <font name='Courier'>Re:</font> in the subject; "
               "(b) add \"as we discussed\"; (c) add a technology you do not have; (d) delete the opt-out line. Undo each one.",
               "Edit an already approved message and check its approval state.",
               "Approve several messages; then press <b>Pause all</b>."],
              ["No invented relationship, no promised interview, no referral programme claimed unless the company page said so, an easy way to say no, the real job title and official link, an opt-out line in every email.",
               "Each of (a)-(d) is blocked with a stated reason.",
               "Editing an approved message withdraws its approval.",
               "Approving several asks you to confirm the count and your daily limit; when paused nothing can go out."],
              "Any draft sentence that is untrue, pushy, or claims a relationship you don't have.")

story += test("C8", "Sending (only when C1-C7 all pass)",
              "Real sending works, exactly once, only after approval.",
              "A Google Cloud project with an OAuth client: console.cloud.google.com -> APIs &amp; Services -> enable the <b>Gmail API</b> -> "
              "OAuth consent screen (External, add yourself as a test user) -> Credentials -> <i>Create OAuth client ID</i> -> Web application -> "
              "Authorised redirect URI <font name='Courier'>http://localhost:3000/settings/gmail/callback</font>. Then create "
              "<font name='Courier'>backend\\.env</font> containing only <font name='Courier'>GOOGLE_CLIENT_ID=...</font>, "
              "<font name='Courier'>GOOGLE_CLIENT_SECRET=...</font> and <font name='Courier'>ADAPTER_MODE=real</font>, and restart Terminals 1 and 2.",
              ["<b>Dry run first:</b> Outreach -> Settings -> delivery mode <b>Dry run</b>. Approve one message, press <b>Send approved emails now</b>.",
               "<b>Connect:</b> Outreach -> Settings -> Gmail connection -> tick the consent box -> <b>Connect with Google</b> -> sign in and allow. You return to a page saying <i>Connected as ...</i>.",
               "<b>Self-test:</b> press <b>Send one test email to myself</b>. Check your inbox and your Gmail Sent folder.",
               "<b>One real message:</b> switch delivery to Gmail, approve one message to a contact you are comfortable with, send.",
               "Open <b>Tracking</b>. Then try to send the same message again.",
               "On the sent message's page, paste a reply into <b>Record a reply</b>; on another, paste a bounce notice. Check what happens."],
              ["Dry run reports success and delivers nothing.",
               "The self-test arrives and is in Sent.",
               "The real message arrives once; Tracking shows it only after it was really sent; the repeat send is blocked.",
               "Reply/bounce are classified as described in <font name='Courier'>docs/COLD_EMAIL_COMPLIANCE.md</font>; a reply cancels follow-ups; "
               "an opt-out is only a suggestion until you confirm it."],
              "Whether each step worked; any error message exactly as shown. Gmail is the least-tested part (simulated until now).")

story += test("C9", "Privacy and deletion",
              "You can take all your data out and remove it completely.",
              "Any time after C3.",
              ["<b>Settings -> Privacy</b>: export your data. Open the JSON and search it for <i>password</i>, <i>token</i>, <i>key</i>.",
               "Set a short retention period and press <b>Purge now</b>.",
               "Optional: sign up a second throwaway account in a private window and look for any of the first account's data.",
               "With a throwaway account (not your real one): <b>Settings -> Delete account</b>, then try to sign in."],
              ["The export contains your data and no password hashes, tokens or keys.",
               "After purge the raw CSV files are gone but your contacts remain.",
               "The second account sees nothing of the first.",
               "After deletion, sign-in fails and nothing of that account remains."],
              None)

story += [PageBreak(),
          p("Part D - docker compose (optional, not yet verified)", H2),
          p("Only if you want to run it the way a server would. Docker Desktop must be running."),
          code('cd "C:\\Users\\anime\\Desktop\\Referral Portal"\ncopy .env.example .env      # then edit: set APP_KEK and a real database password\n'
               'docker compose up --build'),
          p("Generate <font name='Courier'>APP_KEK</font> with: "
            "<font name='Courier'>python -c \"import os,base64;print(base64.b64encode(os.urandom(32)).decode())\"</font>"),
          p("<b>Pass if:</b> the four services (db, api, worker, web) start, http://localhost:3000 loads, and you can sign up. "
            "Stop with Ctrl+C, then <font name='Courier'>docker compose down</font>. This has never been run, so problems here are expected and worth reporting."),
          Spacer(1, 6),
          p("Part E - Results sheet", H2),
          table([["Test", "Pass / Fail", "Notes (numbers, what was wrong)"],
                 ["B1 Backend SQLite", "", ""], ["B2 Browser", "", ""], ["B3 Backend Postgres (opt.)", "", ""],
                 ["C1 Resume accuracy", "", "error rate: ___ / ___ entries"], ["C2 GitHub / portfolio", "", ""],
                 ["C3 Imports", "", "read ___ = valid ___ + dup ___ + invalid ___"], ["C4 Ranking", "", ""],
                 ["C5 Job verification", "", ""], ["C6 Tailoring", "", ""], ["C7 Drafts + guard rails", "", ""],
                 ["C8 Sending", "", ""], ["C9 Privacy / deletion", "", ""], ["D docker compose (opt.)", "", ""]],
                [50, 25, 95]),
          Spacer(1, 6),
          p("Send back: this sheet, plus a screenshot or redacted example of every wrong extraction, ranking, status or claim. "
            "Real data that exposes problems can be fixed with re-import, recalculation and re-versioning - nothing is lost.", SMALL),
          Spacer(1, 8),
          KeepTogether([p("Part F - Troubleshooting", H2),
                        table([["Symptom", "Fix"],
                               ["Upload/import stays \"queued\"", "The worker (Terminal 2) is not running. Start it."],
                               ["Web page shows network errors", "The API (Terminal 1) is not running on port 8000."],
                               ["Can't find the verification link", "Newest file in backend\\data\\outbox\\ - open it in a text editor."],
                               ["\"database is locked\"", "SQLite is single-user. Close other copies of the app; for several users use PostgreSQL."],
                               ["Port already in use", "Another copy is running. Close it, or find it: netstat -ano | findstr :8000"],
                               ["Connect with Google fails", "Check the redirect URI is exactly http://localhost:3000/settings/gmail/callback and you are a test user on the consent screen."],
                               ["Job board gives no jobs", "You are in mock mode - restart Terminals 1 and 2 with ADAPTER_MODE=real."],
                               ["Start over with an empty app", "Stop everything and delete backend\\data\\ (this deletes all local data)."]],
                              [55, 115])])]


def footer(c, doc):
    c.saveState()
    c.setFont("Helvetica", 7.5)
    c.setFillColor(colors.HexColor("#6b7280"))
    c.drawString(20 * mm, 10 * mm, "ReferralOS - Test Guide")
    c.drawRightString(190 * mm, 10 * mm, f"Page {doc.page}")
    c.restoreState()


doc = SimpleDocTemplate(str(OUT), pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
                        title="ReferralOS - Test Guide", author="ReferralOS")
doc.build(story, onFirstPage=footer, onLaterPages=footer)
print(f"wrote {OUT.relative_to(ROOT)}")
