# Cold email: safety and compliance

> **This document is guidance, not legal advice.** Rules differ by country and change. You are responsible for lawful use of this tool. The app helps you honour opt-outs and keep volume low; it cannot make an unlawful email lawful.

## What the app will never do

- Send anything you have not approved, or send LinkedIn messages (there is no authorised API; LinkedIn is manual, see `app/adapters/linkedin_stub.py`).
- Send from an address you do not control, spoof senders, rotate senders or domains, or evade spam filters. Emails come from **your** Gmail (official OAuth) or are sent by you.
- Email the same address a second *initial* cold email, ever; email an address on your do-not-contact list; email about a job that is closed or possibly closed.
- Use open-tracking pixels or link tracking (not built). Replies and bounces are the only tracking, and only if you opt in.
- Call, text or WhatsApp anyone. Phone numbers are stored for your manual reference only; telemarketing rules (e.g. TRAI in India, TCPA in the US) still apply to you.

## Limits (configurable, always capped)

| Setting | Default | Hard maximum | Notes |
|---|---|---|---|
| Emails per day | 20 | 100 | below Gmail's published limits; raising above 20 shows a warning |
| Emails per company per day | 5 | 20 | |
| Introductory (no specific opening) emails per day | 5 | the daily limit | |
| Follow-ups per person | 2 | 3 | minimum 5 business days apart (3-30 configurable), drafts only |
| Pause between sends | random 30-120 s | 0-3600 s | spreads a batch out; it is rate-safety, not evasion |
| Campaign limit | — | can only *lower* the account limit | per-campaign pause too |

Counts use what was actually sent today (UTC), **including unconfirmed deliveries**. "Pause all sending" stops everything immediately.

## The gate: every send passes `services/outreach/preflight.py`

Content rules (checked when you approve *and* again at send time): unresolved `{{placeholders}}` · missing subject/body · deceptive subject (fake `Re:`/`Fwd:`, "urgent", "act now", …) ·
missing opt-out line · missing sender name/address · invalid or no-reply recipient · forbidden claims (invented relationship, "as discussed", promises of an interview, superlatives) ·
statements about you not supported by your profile · attachments that are not a resume you approved for that job (PDF, ≤ 2 MB) · job closed/possibly closed.

Sending rules: approved · delivery mode allows automation and a provider is connected · not paused (account or campaign) · address and domain not suppressed or blocklisted · pair not do-not-contact ·
no earlier initial email to this address · job verified open and verified within 3 days · lawful-use acknowledged · extra acknowledgement for consent regions · not from a purchased/unknown-source list ·
daily / per-company / intro / campaign limits · follow-up cap and spacing. Temporary blocks (limits, pause) leave the message queued; permanent ones (suppressed, duplicate, closed job) mark it blocked.

Every email contains your real name and a plain opt-out line: *"If you'd rather not hear from me, reply 'unsubscribe' and I won't contact you again."*

## Consent, jurisdictions and provenance

- First use requires acknowledging the lawful-use statement. Recipients in regions that usually require prior consent for unsolicited commercial email (UK, EU/EEA, Canada, Australia in the app's table) additionally require an **acknowledgement per region** and show the guidance. Region comes from the contact's country/phone region or the email's country domain; unknown → apply the strictest rules you are subject to.
- Every HR/recruiter import requires a **provenance** answer. Lists marked *purchased or scraped* are excluded from batches and from automated sending; you may only create one-off manual drafts to individuals and send them yourself.
- The do-not-contact list is per user, survives re-imports, and is checked immediately before every send.

## Replies, bounces and follow-ups

Classification is rule-based and correctable. A **hard bounce** (explicit permanent-failure text; the sender "mailer-daemon" alone is never enough) suppresses the address automatically.
An **opt-out request** is only a suggestion until you confirm it, then the address is suppressed everywhere and pending messages are cancelled. A real reply cancels pending follow-ups; out-of-office replies and soft bounces do not.
Follow-ups are **drafted for approval**, never sent silently, and are cancelled by a reply, bounce, opt-out, closed job or pause.

## Ambiguous results

A timeout, a 5xx or an unreadable answer after the request left is **never** treated as a failure to retry. The message becomes `DELIVERY_UNCONFIRMED`, counts toward your limit, is never re-sent automatically,
and you can reconcile it (we search your Sent mail for our own Message-ID, if you granted read access) or decide manually. A definite non-delivery (auth error, invalid request, could not connect) is `failed` and also not retried automatically.

## Verification status

The Gmail adapter, OAuth code exchange and token refresh were verified **only against mock HTTP**. They have never run against Google. Treat the first real use as a test: use dry-run, then "send one test email to myself".
