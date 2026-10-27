"""docs/ACCEPTANCE.md from tests/acceptance_map.py (a test fails if any referenced test disappears).
Run:  cd backend && uv run python ../scripts/make_acceptance_doc.py"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from tests.acceptance_map import MAP  # noqa: E402

out = ["# Acceptance scenarios", "", "The 14 mandatory scenarios from the specification, each with the automated tests that prove it. "
       "`backend/tests/test_acceptance_map.py` fails if a referenced test is renamed or removed.", "",
       "Run one with e.g. `cd backend && uv run pytest -p no:warnings tests/test_outreach_flow.py::test_scenario_linkedin_messages_are_never_sent_by_the_app`.", ""]
for n, (title, refs) in MAP.items():
    out += [f"## {n}. {title}", ""] + [f"- `backend/tests/{r.split('::')[0]}` → `{r.split('::')[1]}`" for r in refs] + [""]
out += ["## Caveat", "", "These pass against **synthetic data and mock integrations**. They prove the logic and the guard rails, not that a real posting is open, a real Gmail account accepts a send, or a real resume layout is parsed correctly. See `VERIFICATION_CHECKLIST.md`."]
(ROOT / "docs/ACCEPTANCE.md").write_text("\n".join(out) + "\n", encoding="utf-8")
print("wrote docs/ACCEPTANCE.md")
