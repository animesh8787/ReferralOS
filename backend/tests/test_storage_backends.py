"""The Supabase backend is exercised with a mock transport: request shapes and the missing-file contract."""
import httpx
import pytest

from app import storage
from app.config import get_settings

UID, FID = "a" * 32, "b" * 32


@pytest.fixture
def sb(env, monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "service-key")
    get_settings.cache_clear()
    files, calls = {}, []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append((req.method, req.url.path, dict(req.headers)))
        path = req.url.path.removeprefix("/storage/v1/")
        if req.method == "POST" and path.startswith("object/list/"):
            import json
            prefix = json.loads(req.content)["prefix"] + "/"
            rel = {k[len(prefix):] for k in files if k.startswith(prefix)}
            out = {r.split("/")[0]: ("/" in r) for r in rel}
            return httpx.Response(200, json=[{"name": n, "id": None if folder else "id"} for n, folder in out.items()])
        if req.method == "POST":
            files[path.removeprefix("object/referralos/")] = req.content
            return httpx.Response(200, json={})
        if req.method == "GET":
            k = path.removeprefix("object/referralos/")
            return httpx.Response(200, content=files[k]) if k in files else httpx.Response(400, json={"error": "not found"})
        import json
        for k in json.loads(req.content)["prefixes"]:
            files.pop(k, None)
        return httpx.Response(200, json=[])

    monkeypatch.setattr(storage, "TRANSPORT", httpx.MockTransport(handler))
    return files, calls


def test_put_get_delete_round_trip_with_auth_headers(sb):
    files, calls = sb
    storage.put(UID, "resumes", FID, b"data", ".pdf")
    assert files == {f"users/{UID}/resumes/{FID}.pdf": b"data"}
    assert calls[0][2]["authorization"] == "Bearer service-key" and calls[0][2]["x-upsert"] == "true"
    assert storage.get(UID, "resumes", FID, ".pdf") == b"data"
    storage.delete(UID, "resumes", FID, ".pdf")
    with pytest.raises(FileNotFoundError):
        storage.get(UID, "resumes", FID, ".pdf")


def test_bundle_and_whole_user_deletion(sb):
    files, _ = sb
    storage.put_bundle(UID, FID, "resume.pdf", b"pdf")
    storage.put(UID, "imports", FID, b"csv", ".csv")
    storage.put("c" * 32, "resumes", FID, b"other", ".pdf")
    assert storage.get_bundle(UID, FID, "resume.pdf") == b"pdf"
    storage.delete_user(UID)
    assert list(files) == [f"users/{'c' * 32}/resumes/{FID}.pdf"]


def test_keys_are_validated_on_every_backend(sb):
    for bad in (lambda: storage.get(UID, "../x", FID), lambda: storage.get_bundle(UID, FID, "../../etc/passwd"), lambda: storage.get("../evil", "resumes", FID)):
        with pytest.raises(ValueError):
            bad()
