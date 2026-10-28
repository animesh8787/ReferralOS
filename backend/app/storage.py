"""Per-user file storage with two backends: local disk (default) and Supabase Storage (when SUPABASE_URL is set).

Keys are built only from validated ids, so no traversal. Missing files raise FileNotFoundError on both backends.
shortcut: whole files are read into memory (resumes, CSVs up to 25 MB); stream them if uploads get much larger.
"""
import re
import shutil
from pathlib import Path

import httpx

from .config import get_settings

_ID = re.compile(r"^[a-f0-9]{32}$")
_CAT = {"resumes", "generated", "imports", "exports"}
_EXT = re.compile(r"^\.[a-z0-9]{1,5}$")
BUNDLE_FILES = {"resume.pdf", "resume.docx", "resume.txt", "requirement_matrix.json", "validation_report.json", "tailoring_summary.md", "diff.json"}
TRANSPORT: httpx.BaseTransport | None = None  # tests inject a MockTransport


def _user_prefix(user_id: str) -> str:
    if not _ID.match(user_id):
        raise ValueError("bad user id")
    return f"users/{user_id}"


def _key(user_id: str, category: str, file_id: str, ext: str = "") -> str:
    if category not in _CAT or not _ID.match(file_id) or (ext and not _EXT.match(ext)):
        raise ValueError("bad storage key")
    return f"{_user_prefix(user_id)}/{category}/{file_id}{ext}"


def _bundle_key(user_id: str, version_id: str, name: str) -> str:
    """generated/<version id>/<fixed file name>: one directory per tailored version, names from a whitelist."""
    if not _ID.match(version_id) or name not in BUNDLE_FILES:
        raise ValueError("bad bundle key")
    return f"{_user_prefix(user_id)}/generated/{version_id}/{name}"


# ---------------------------------------------------------------- backends
def _supabase() -> bool:
    return bool(get_settings().supabase_url)


def _sb(method: str, path: str, **kw) -> httpx.Response:
    s = get_settings()
    h = {"Authorization": f"Bearer {s.supabase_service_key}", "apikey": s.supabase_service_key, **kw.pop("headers", {})}
    with httpx.Client(transport=TRANSPORT, timeout=30) as c:
        return c.request(method, f"{s.supabase_url.rstrip('/')}/storage/v1/{path}", headers=h, **kw)


def _write(key: str, data: bytes) -> None:
    if _supabase():
        _sb("POST", f"object/{get_settings().storage_bucket}/{key}", content=data, headers={"x-upsert": "true", "Content-Type": "application/octet-stream"}).raise_for_status()
        return
    p = get_settings().data_dir / key
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)


def _read(key: str) -> bytes:
    if _supabase():
        r = _sb("GET", f"object/{get_settings().storage_bucket}/{key}")
        if r.status_code in (400, 404):
            raise FileNotFoundError(key)
        r.raise_for_status()
        return r.content
    return (get_settings().data_dir / key).read_bytes()


def _remove(key: str) -> None:
    if _supabase():
        _sb("DELETE", f"object/{get_settings().storage_bucket}", json={"prefixes": [key]}).raise_for_status()
        return
    (get_settings().data_dir / key).unlink(missing_ok=True)


def _remove_tree(prefix: str) -> None:
    if not _supabase():
        shutil.rmtree(get_settings().data_dir / prefix, ignore_errors=True)
        return
    bucket, keys, stack = get_settings().storage_bucket, [], [prefix]
    while stack:  # Supabase lists one folder level at a time; entries without an id are folders
        cur = stack.pop()
        r = _sb("POST", f"object/list/{bucket}", json={"prefix": cur, "limit": 1000})
        r.raise_for_status()
        for e in r.json():
            (keys.append(f"{cur}/{e['name']}") if e.get("id") else stack.append(f"{cur}/{e['name']}"))
    for i in range(0, len(keys), 100):
        _sb("DELETE", f"object/{bucket}", json={"prefixes": keys[i:i + 100]}).raise_for_status()


# ---------------------------------------------------------------- public API
def put(user_id: str, category: str, file_id: str, data: bytes, ext: str = "") -> None:
    _write(_key(user_id, category, file_id, ext), data)


def get(user_id: str, category: str, file_id: str, ext: str = "") -> bytes:
    return _read(_key(user_id, category, file_id, ext))


def delete(user_id: str, category: str, file_id: str, ext: str = "") -> None:
    _remove(_key(user_id, category, file_id, ext))


def put_bundle(user_id: str, version_id: str, name: str, data: bytes) -> None:
    _write(_bundle_key(user_id, version_id, name), data)


def get_bundle(user_id: str, version_id: str, name: str) -> bytes:
    return _read(_bundle_key(user_id, version_id, name))


def delete_user(user_id: str) -> None:
    _remove_tree(_user_prefix(user_id))
