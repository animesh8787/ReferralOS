# Privacy and data handling

> Guidance for the person running and using this software, not legal advice.

## What is stored, where, and for how long

Everything is stored on the server you run it on: a SQL database (SQLite for single-user, PostgreSQL for multi-user) and a per-user folder of files (`data/users/<id>/`: uploaded resumes, imported CSVs,
generated resume bundles). Nothing is sent to a third party unless you turn a feature on:

| Feature | Leaves the server? | Needs your consent |
|---|---|---|
| Resume/CSV parsing, scoring, matching, tailoring, drafting | **No** | — |
| GitHub import | public GitHub REST API (username only) | `github` |
| Portfolio import | the URL you give, with robots.txt respected | `portfolio` |
| Job discovery | public job-board APIs / pages for companies *you* add | — (you choose the boards) |
| Gmail sending | Gmail API, from your own account, only for messages you approved | `gmail` (+ `reply_tracking` for read access) |
| AI rewording (optional) | one resume bullet + job skill names, emails/phones/links removed, to the provider you chose with your own key | `llm` |

Each consent is opt-in, listed in Settings, revocable at any time, and recorded in your audit log. **Complete contact lists are never sent to an AI service.**
Logs never contain personal content: every log record is passed through a redactor (emails, phone numbers, token/password values) and audit entries hold metadata only (tested).

## Your controls

- **Export** everything as JSON (`/api/me/export`, Settings → Privacy). Secrets (password hash, OAuth tokens, your AI key) are never included.
- **Delete** your account and all your data (Settings → Privacy, password required): rows in every table that carries your id, your files, your tokens and sessions. Tested for completeness.
- **Retention**: choose to auto-delete raw import files and verbatim CSV values after N days (derived contacts stay). The worker applies it hourly; "Purge now" does it immediately.
- **Audit log** of your own sensitive actions (sign-ins, imports, exports, approvals, sends, consent changes, deletions): Outreach → Activity.
- **Do-not-contact list**: yours alone, kept across imports.

## Other people's data

Imported connections and HR contacts are **other people's personal data**. You are responsible for having a lawful reason to hold and contact them, for honouring opt-outs, and for deleting what you no longer need.
The app records where an HR list came from (required), restricts purchased/unknown-source lists, and never scrapes or contacts anyone by itself. Sensitive or protected characteristics are not inferred, stored or used for ranking.

## Multi-user separation

Each user's data is isolated in code and verified by tests (see `SECURITY.md`). Only public, non-personal reference data is shared across users (company names; public job postings and their verification
evidence). Scores, matches, contacts, drafts and files are never shared. An admin role exists but sees only aggregate health counts, not personal data.
