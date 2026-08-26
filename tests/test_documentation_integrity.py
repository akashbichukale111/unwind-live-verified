"""Every pointer this repository makes at its own evidence must resolve.

WHY THIS IS A TEST AND NOT A REVIEW HABIT
--------------------------------------------
This codebase argues for itself in its docstrings: a module explains what it
guarantees and names the test that proves it. That is a good habit right up
until a test is renamed, at which point the docstring becomes a confident
citation of something that does not exist -- which is strictly worse than no
citation, because a reader who checks one and finds it missing has to
re-verify every other one by hand.

So the citations are checked mechanically. A `tests/test_x.py::test_y`
reference in any Python module or Markdown document must name a file that
exists and, when a node id is given, a test function that exists in it.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

#: Directories whose contents are historical records, not live claims.
#: `evidence/` is an append-only log of what was run at a point in time; a
#: reference in it names the test as it existed THEN and must not be
#: rewritten to match today's tree.
_SKIP_DIRS = {".git", ".venv", "node_modules", ".cache", "evidence", "submission"}

#: `tests/test_foo.py` optionally followed by `::test_bar` (and optionally a
#: class in between, which this repository does not currently use).
_REFERENCE = re.compile(r"tests/(test_[A-Za-z0-9_]+\.py)(?:::([A-Za-z0-9_]+))?")


def _source_files() -> list[Path]:
    out: list[Path] = []
    for path in REPO.rglob("*"):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        # This file's own docstring uses `tests/test_x.py::test_y` as an
        # ILLUSTRATION of the pattern being checked. Scanning itself would
        # require inventing those files to satisfy the scan.
        if path.resolve() == Path(__file__).resolve():
            continue
        if path.suffix in (".py", ".md") and path.is_file():
            out.append(path)
    return sorted(out)


def _test_functions(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
    }


def _references() -> list[tuple[Path, str, str | None]]:
    found: list[tuple[Path, str, str | None]] = []
    for path in _source_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in _REFERENCE.finditer(text):
            found.append((path, match.group(1), match.group(2)))
    return found


def test_the_reference_scan_is_not_vacuous() -> None:
    """A guard that finds nothing to guard passes for the wrong reason."""
    references = _references()
    assert len(references) > 20, f"only {len(references)} citations found; the regex is wrong"
    assert any(node for _, _, node in references), "no node-id citations found"


@pytest.mark.parametrize(
    "path,filename,node",
    [
        pytest.param(p, f, n, id=f"{p.relative_to(REPO)}->{f}::{n or ''}")
        for p, f, n in _references()
    ],
)
def test_every_cited_test_exists(path: Path, filename: str, node: str | None) -> None:
    target = REPO / "tests" / filename
    assert target.is_file(), f"{path.relative_to(REPO)} cites {filename}, which does not exist"
    if node is None:
        return
    functions = _test_functions(target)
    assert node in functions, (
        f"{path.relative_to(REPO)} cites tests/{filename}::{node}, which does not exist. "
        f"Nearest names: {sorted(f for f in functions if f[:20] == node[:20]) or 'none'}"
    )
