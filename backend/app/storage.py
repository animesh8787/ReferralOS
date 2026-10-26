"""Per-user local file storage. Paths are built only from validated ids, so no traversal."""
import re
import shutil
from pathlib import Path

from .config import get_settings

_ID = re.compile(r"^[a-f0-9]{32}$")
_CAT = {"resumes", "generated", "imports", "exports"}
_EXT = re.compile(r"^\.[a-z0-9]{1,5}$")


def user_dir(user_id: str) -> Path:
    if not _ID.match(user_id):
        raise ValueError("bad user id")
    return get_settings().data_dir / "users" / user_id


def path_for(user_id: str, category: str, file_id: str, ext: str = "") -> Path:
    if category not in _CAT or not _ID.match(file_id) or (ext and not _EXT.match(ext)):
        raise ValueError("bad storage key")
    return user_dir(user_id) / category / f"{file_id}{ext}"


def put(user_id: str, category: str, file_id: str, data: bytes, ext: str = "") -> Path:
    p = path_for(user_id, category, file_id, ext)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def get(user_id: str, category: str, file_id: str, ext: str = "") -> bytes:
    return path_for(user_id, category, file_id, ext).read_bytes()


BUNDLE_FILES = {"resume.pdf", "resume.docx", "resume.txt", "requirement_matrix.json", "validation_report.json", "tailoring_summary.md", "diff.json"}


def bundle_path(user_id: str, version_id: str, name: str) -> Path:
    """generated/<version id>/<fixed file name>: one directory per tailored version, names from a whitelist."""
    if not _ID.match(version_id) or name not in BUNDLE_FILES:
        raise ValueError("bad bundle key")
    return user_dir(user_id) / "generated" / version_id / name


def put_bundle(user_id: str, version_id: str, name: str, data: bytes) -> Path:
    p = bundle_path(user_id, version_id, name)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def delete_user(user_id: str) -> None:
    shutil.rmtree(user_dir(user_id), ignore_errors=True)
