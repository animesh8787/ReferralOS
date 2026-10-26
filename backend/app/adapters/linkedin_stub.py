"""LinkedIn messaging adapter: DISABLED BY DESIGN and not wired to anything.

Why it is off
- LinkedIn offers no documented, authorised API for a member to send messages to other members on their own behalf.
  (Its partner messaging APIs are for approved partners and do not cover this use.)
- Automating a member's account (scraping, session cookies, headless browsers, unofficial endpoints) breaks LinkedIn's terms and
  this project forbids it. We never ask for LinkedIn credentials, cookies or tokens.

What happens instead: referral requests are drafted, reviewed and approved here, then the user copies the text and opens the
recipient's profile link to send it themselves ("manual send queue"). The pre-send gate also blocks any attempt to treat a
LinkedIn message as sendable (code CHANNEL_NOT_SENDABLE).

If LinkedIn ever publishes an authorised API for this, implement send() below, keep `enabled = False` until it has been verified
against the real service, and put it behind the same approval, limits and audit rules as email.
"""


class LinkedInMessaging:
    enabled = False
    reason = "No documented, authorised LinkedIn API exists for member-to-member messaging; manual send only."

    def send(self, *args, **kwargs):
        raise NotImplementedError(self.reason)
