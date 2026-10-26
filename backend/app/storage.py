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


def delete_user(user_id: str) -> None:
    shutil.rmtree(user_dir(user_id), ignore_errors=True)
