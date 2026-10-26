"""Email, phone and LinkedIn-URL validation. DNS MX is optional and never probes mailboxes (no SMTP)."""
import re
from urllib.parse import unquote, urlparse

import phonenumbers
from email_validator import EmailNotValidError, validate_email

ROLE_LOCALS = {"info", "hr", "careers", "career", "jobs", "job", "recruiting", "recruitment", "recruiter", "talent", "admin",
               "support", "contact", "hello", "sales", "team", "office", "mail", "help", "press", "privacy", "enquiries",
               "inquiries", "humanresources", "people", "hiring", "apply", "applications"}
NOREPLY = re.compile(r"^(no[-_.]?reply|do[-_.]?not[-_.]?reply|donotreply|mailer-daemon|postmaster)$", re.I)


def check_email(raw: str | None, check_mx: bool = False, mx_resolver=None) -> dict:
    """-> {valid, norm, flags[], error}. Syntax + normalisation only unless check_mx (DNS lookup, no SMTP)."""
    if not raw or not raw.strip():
        return {"valid": False, "norm": None, "flags": [], "error": "missing"}
    try:
        v = validate_email(raw.strip(), check_deliverability=False)
    except EmailNotValidError as e:
        return {"valid": False, "norm": None, "flags": [], "error": str(e)[:120]}
    norm = v.normalized.lower()
    local, domain = norm.rsplit("@", 1)
    flags = []
    if NOREPLY.match(local):
        flags.append("noreply")
    elif local.replace(".", "").replace("-", "").replace("_", "") in ROLE_LOCALS or local in ROLE_LOCALS:
        flags.append("role_account")
    if check_mx and not (mx_resolver or _mx)(domain):
        flags.append("mx_missing")
    return {"valid": True, "norm": norm, "flags": flags, "error": None}


def _mx(domain: str) -> bool:
    import dns.exception
    import dns.resolver
    try:
        return bool(dns.resolver.resolve(domain, "MX", lifetime=4))
    except (dns.exception.DNSException, OSError):
        return False


def check_phone(raw: str | None, region: str = "US") -> dict:
    """Stored for manual reference only; never dialled or messaged by the app."""
    if not raw or not raw.strip():
        return {"valid": False, "e164": None, "country": None}
    try:
        n = phonenumbers.parse(raw, region)
    except phonenumbers.NumberParseException:
        return {"valid": False, "e164": None, "country": None}
    if not phonenumbers.is_valid_number(n):
        return {"valid": False, "e164": None, "country": phonenumbers.region_code_for_number(n)}
    return {"valid": True, "e164": phonenumbers.format_number(n, phonenumbers.PhoneNumberFormat.E164),
            "country": phonenumbers.region_code_for_number(n)}


_LI = re.compile(r"^/in/([^/]+)/?$", re.I)


def linkedin_identity(raw: str | None) -> tuple[str | None, str | None]:
    """-> (clean_url, key). Only linkedin.com/in/<slug> profile URLs are identities."""
    if not raw or not raw.strip():
        return None, None
    s = raw.strip()
    if not re.match(r"^https?://", s, re.I):
        s = "https://" + s
    try:
        u = urlparse(s)
    except ValueError:
        return None, None
    host = (u.hostname or "").lower()
    if not (host == "linkedin.com" or host.endswith(".linkedin.com")):
        return None, None
    m = _LI.match(u.path)
    if not m:
        return None, None
    slug = unquote(m.group(1)).lower()
    return f"https://www.linkedin.com/in/{slug}", slug
