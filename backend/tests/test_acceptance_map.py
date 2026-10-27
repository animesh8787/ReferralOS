import ast
from pathlib import Path

from tests.acceptance_map import MAP

HERE = Path(__file__).parent


def _tests(file: str) -> set[str]:
    return {n.name for n in ast.walk(ast.parse((HERE / file).read_text(encoding="utf-8"))) if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")}


def test_all_fourteen_scenarios_are_mapped_to_tests_that_exist():
    assert sorted(MAP) == list(range(1, 15))
    for n, (title, refs) in MAP.items():
        assert title and len(refs) >= 1, n
        for ref in refs:
            f, t = ref.split("::")
            assert (HERE / f).exists() and t in _tests(f), f"scenario {n}: {ref} does not exist (renamed or deleted?)"
