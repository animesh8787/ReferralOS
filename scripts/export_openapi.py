"""Writes the API contract to docs/openapi.json. Run:  cd backend && uv run python ../scripts/export_openapi.py
The live, interactive version is served by the API itself at /docs and /openapi.json."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.main import app  # noqa: E402

spec = app.openapi()
(ROOT / "docs/openapi.json").write_text(json.dumps(spec, indent=1), encoding="utf-8")
paths = spec["paths"]
n = sum(len([m for m in v if m in ("get", "post", "put", "patch", "delete")]) for v in paths.values())
print(f"wrote docs/openapi.json: {len(paths)} paths, {n} operations")
