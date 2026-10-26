"""Polite outbound HTTP: honest User-Agent, robots.txt, SSRF guard, backoff, size cap, per-domain concurrency, cache.

Used for user-supplied URLs and public ATS endpoints. Real network is only used when ADAPTER_MODE=real;
mock mode routes everything to adapters.fakes unless a test installs TRANSPORT_OVERRIDE.
"""
import ipaddress
import socket
import threading
import time
from collections import defaultdict
from urllib import robotparser
from urllib.parse import urljoin, urlparse

import httpx

from ..config import get_settings

UA_TOKEN = "ReferralOS"
USER_AGENT = f"{UA_TOKEN}/0.1 (personal job-search tool; honours robots.txt)"
MAX_BYTES = 2 * 1024 * 1024
TRANSPORT_OVERRIDE: httpx.BaseTransport | None = None


class FetchError(Exception):
    pass


class RobotsDisallowed(FetchError):
    pass


class UnsafeUrl(FetchError):
    pass


def make_client() -> httpx.Client:
    from . import fakes
    transport = TRANSPORT_OVERRIDE or (httpx.MockTransport(fakes.handler) if get_settings().adapter_mode == "mock" else None)
    return httpx.Client(transport=transport, headers={"User-Agent": USER_AGENT}, timeout=15, follow_redirects=False)


def _real_resolver(host: str) -> list[str]:
    return [i[4][0] for i in socket.getaddrinfo(host, None)]


def check_public_url(url: str, resolver=None) -> str:
    """Reject non-http(s), credentials, localhost and private/link-local addresses (SSRF)."""
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname or u.username or u.password:
        raise UnsafeUrl("Only plain http(s) URLs are allowed")
    host = u.hostname.lower()
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise UnsafeUrl("Local addresses are not allowed")
    try:
        ips = [host] if ipaddress.ip_address(host) else []
    except ValueError:
        ips = resolver(host) if resolver else []
    for ip in ips:
        a = ipaddress.ip_address(ip)
        if a.is_private or a.is_loopback or a.is_link_local or a.is_reserved or a.is_multicast or a.is_unspecified:
            raise UnsafeUrl("Private or reserved addresses are not allowed")
    return url


class PoliteFetcher:
    def __init__(self, client: httpx.Client | None = None, resolver=None, sleep=time.sleep, per_domain: int = 2,
                 respect_robots: bool = True):
        self.client = client or make_client()
        real = get_settings().adapter_mode == "real" and TRANSPORT_OVERRIDE is None
        self.resolver = resolver or (_real_resolver if real else None)  # mock mode has no DNS
        self.sleep = sleep
        self.respect_robots = respect_robots
        self._robots: dict[str, robotparser.RobotFileParser | None] = {}
        self._cache: dict[str, httpx.Response] = {}
        self._sems = defaultdict(lambda: threading.Semaphore(per_domain))

    def allowed(self, url: str) -> bool:
        u = urlparse(url)
        origin = f"{u.scheme}://{u.netloc}"
        if origin not in self._robots:
            rp = robotparser.RobotFileParser()
            try:
                r = self.client.get(f"{origin}/robots.txt")
                if r.status_code >= 500:
                    rp = None  # robots unreachable -> be conservative
                elif r.status_code >= 400:
                    rp.parse([])  # no robots.txt -> allowed
                else:
                    rp.parse(r.text.splitlines())
            except httpx.HTTPError:
                rp = None
            self._robots[origin] = rp
        rp = self._robots[origin]
        return bool(rp and rp.can_fetch(UA_TOKEN, url))

    def get(self, url: str, headers: dict | None = None, public_only: bool = True) -> httpx.Response:
        if url in self._cache:
            return self._cache[url]
        for _ in range(4):  # follow at most 3 redirects, re-validating each hop
            if public_only:
                check_public_url(url, self.resolver)
            if self.respect_robots and not self.allowed(url):
                raise RobotsDisallowed(f"robots.txt does not allow fetching {urlparse(url).netloc}")
            r = self._request(url, headers)
            if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
                url = urljoin(url, r.headers["location"])
                continue
            if len(r.content) > MAX_BYTES:
                raise FetchError("Response too large")
            self._cache[url] = r
            return r
        raise FetchError("Too many redirects")

    def _request(self, url: str, headers: dict | None) -> httpx.Response:
        host = urlparse(url).netloc
        for attempt in range(3):
            with self._sems[host]:
                try:
                    r = self.client.get(url, headers=headers)
                except httpx.HTTPError as e:
                    if attempt == 2:
                        raise FetchError(f"Network error: {type(e).__name__}") from e
                    self.sleep(2 ** attempt)
                    continue
            if r.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                ra = r.headers.get("retry-after", "")
                self.sleep(min(int(ra), 10) if ra.isdigit() else 2 ** attempt)
                continue
            return r
        return r
