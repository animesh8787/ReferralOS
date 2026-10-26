"""shortcut: per-process sliding window; move to DB/Redis before running several API instances."""
import time
from collections import defaultdict, deque

from fastapi import HTTPException

_hits: dict[str, deque] = defaultdict(deque)


def check(key: str, limit: int, window_s: int) -> None:
    now, q = time.monotonic(), _hits[key]
    while q and now - q[0] > window_s:
        q.popleft()
    if len(q) >= limit:
        raise HTTPException(429, "Too many requests, slow down")
    q.append(now)


def reset() -> None:
    _hits.clear()
