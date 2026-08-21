"""Card 3: the countersign/spine boundary, and the Gemma model singleton.

`tests/test_zero_model.py` proves `spine/` cannot reach a model client at
all; `tests/test_tower_zero_model.py` extends the same walk to `tower/`'s
authority-deciding modules. `countersign/` is different again -- it EXISTS
to make a model call, so "zero model calls" is not the claim here. What
must still hold, the same one-hop boundary check
`tests/test_tower_zero_model.py::test_tower_cannot_be_reached_from_spine`
already runs for `tower/`, is that `spine/` never imports it: a T0/T1 path
that quietly grew a Countersign dependency would no longer survive a total
Vertex outage, which is exactly the guarantee `tests/test_zero_model.py`
exists to protect.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _direct_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                continue
            if node.module:
                found.add(node.module)
    return found


def test_spine_cannot_reach_countersign() -> None:
    """countersign/ must be unreachable from spine/ -- the boundary this
    prompt's invariants explicitly name."""
    spine_dir = REPO / "spine"
    offenders = []
    for source in sorted(spine_dir.glob("*.py")):
        imports = _direct_imports(source)
        if any(i == "countersign" or i.startswith("countersign.") for i in imports):
            offenders.append(str(source.relative_to(REPO)))
    assert not offenders, f"spine/ modules importing countersign/: {offenders}"


def test_countersign_does_not_import_spine() -> None:
    """The boundary works both directions, the same discipline
    `tests/test_warrant_separation.py` applies to warrant/<->settle/."""
    offenders = []
    for source in sorted((REPO / "countersign").glob("*.py")):
        imports = _direct_imports(source)
        if any(i == "spine" or i.startswith("spine.") for i in imports):
            offenders.append(str(source.relative_to(REPO)))
    assert not offenders, f"countersign/ modules importing spine/: {offenders}"


def test_the_boundary_check_is_not_vacuous() -> None:
    """A guard that would pass against anything is not a guard: confirm the
    detector actually finds SOMETHING when countersign/ imports tower/,
    which it legitimately does (record_countersign lives in tower.memory
    via warrant.ledger)."""
    offenders = []
    for source in sorted((REPO / "countersign").glob("*.py")):
        imports = _direct_imports(source)
        if any(i == "warrant" or i.startswith("warrant.") for i in imports):
            offenders.append(str(source.relative_to(REPO)))
    assert offenders, (
        "the import detector found nothing in countersign/ importing warrant/, "
        "so it would not have caught a real spine/ violation either"
    )


# ---------------------------------------------------------------------------
# The Gemma model string: same singleton discipline as Gemini's.
# `tests/test_config_singleton.py` is frozen and only greps `gemini-\d`, so
# it does not (and structurally cannot, without editing a frozen file) cover
# GEMMA_MODEL. This is the same rule, voluntarily extended to the new string.
# ---------------------------------------------------------------------------

SKIP_DIRS = {
    ".git",
    ".venv",
    ".cache",
    "node_modules",
    ".next",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
}


def _tracked_text_files() -> list[Path]:
    import subprocess

    out = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=False)
    if out.returncode == 0 and out.stdout.strip():
        paths = [REPO / line for line in out.stdout.splitlines() if line]
    else:
        paths = [p for p in REPO.rglob("*") if p.is_file()]
    result = []
    for path in paths:
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if not path.is_file() or path.suffix in {".jsonl", ".sha256", ".eml"}:
            continue
        result.append(path)
    return result


def test_gemma_model_string_appears_only_in_config() -> None:
    pattern = re.compile(r"gemma-\d")
    offenders: list[str] = []
    for path in _tracked_text_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if not pattern.search(text):
            continue
        rel = path.relative_to(REPO).as_posix()
        if rel in {"lib/config.py", "tests/test_countersign_boundary.py"}:
            continue
        if path.suffix == ".md":
            continue  # prose is exempt, the same rule test_config_singleton.py uses
        # Evidence artefacts are exempt for the same reason -- and only
        # recorded output, never source. See the fuller note in
        # `tests/test_config_singleton.py`.
        if rel.startswith("evidence/") and path.suffix in {".log", ".json", ".txt"}:
            continue
        offenders.append(rel)
    assert not offenders, f"gemma model string found outside lib/config.py: {offenders}"
