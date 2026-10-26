"""Jurisdiction-aware GUIDANCE for cold email. This is not legal advice and is not exhaustive; the user is responsible for lawful use.

Regions where unsolicited commercial email generally needs prior consent (or a narrow B2B exception) get an extra acknowledgement.
"""
import re

LAWFUL_USE_TEXT = ("I will only email people I have a legitimate reason to contact, I will honour opt-outs immediately, I will not send "
                   "misleading messages, and I understand I am responsible for complying with the laws that apply to me and to my recipients.")
NOT_LEGAL_ADVICE = "This is general guidance, not legal advice. Rules differ by country and change; check them for your situation."

EU = {"AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE", "IS", "LI", "NO"}
CONSENT_REGIONS = {"GB": "UK PECR/UK GDPR: unsolicited marketing email to individuals needs consent; B2B corporate-subscriber rules differ. Job-seeking emails to a named person still involve personal data.",
                   "CA": "Canada CASL: commercial electronic messages generally need consent (with limited exceptions) and an unsubscribe mechanism.",
                   "AU": "Australia Spam Act: commercial email needs consent and a functional unsubscribe.", **{c: "EU/EEA ePrivacy + GDPR: contacting a named person needs a lawful basis and a clear way to object; consent is the safe default." for c in EU}}
GUIDANCE = {"US": "US CAN-SPAM: no deceptive headers or subjects; include a working opt-out; honour it within 10 business days. Individual job-seeking emails are rarely 'commercial' but keep the opt-out anyway.",
            "IN": "India DPDP Act 2023: personal data of the recipient needs a lawful purpose and an easy way to withdraw. Phone calls/SMS are regulated by TRAI (DND/Do-Not-Disturb): this app never calls or texts."}
CCTLD = {"uk": "GB", "de": "DE", "fr": "FR", "es": "ES", "it": "IT", "nl": "NL", "ie": "IE", "in": "IN", "ca": "CA", "au": "AU", "se": "SE", "pl": "PL",
         "be": "BE", "at": "AT", "dk": "DK", "fi": "FI", "pt": "PT", "ch": "CH", "no": "NO", "us": "US"}


def region_of(email: str | None, country_hint: str | None) -> str | None:
    if country_hint:
        return country_hint.upper()
    if email and "@" in email:
        return CCTLD.get(email.rsplit(".", 1)[-1].lower())
    return None


def guidance_for(region: str | None) -> dict:
    r = (region or "").upper()
    return {"region": r or None, "requires_extra_ack": r in CONSENT_REGIONS,
            "text": CONSENT_REGIONS.get(r) or GUIDANCE.get(r) or "Region unknown. Apply the strictest rules you are subject to.", "disclaimer": NOT_LEGAL_ADVICE}


def needs_region_ack(region: str | None, cfg: dict) -> bool:
    return bool(region) and region.upper() in CONSENT_REGIONS and region.upper() not in cfg.get("region_acks", {})


DECEPTIVE_SUBJECT = re.compile(r"^\s*(re|fwd?|fw)\s*:|urgent|act now|last chance|final notice|immediate(ly)?\b|!!|\bfree\b|guarantee|congratulations|you('ve| have) won", re.I)
