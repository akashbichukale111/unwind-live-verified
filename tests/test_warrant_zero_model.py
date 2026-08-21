"""The zero-model guarantee, extended to Card 0's ledger.

`tests/test_zero_model.py` walks `spine/` and forbids `google.adk` itself
(spine/ has no framework dependency at all); `tests/test_tower_zero_model.py`
walks `tower/registry.py` and `tower/gateway.py` with a NARROWER forbidden
set that allows `google.adk` (the router graph legitimately needs it) but
still forbids a real model client.

`warrant/ledger.py` is stricter than either: it has NO reason to import
`google.adk` -- the FunctionNode that wraps `spend_or_refuse` lives in
`tower/gateway.py`, not here (see `warrant/DESIGN.md`). So this file reuses
`tests/test_zero_model.py`'s STRICT forbidden set (model clients AND
`google.adk` itself), the same guarantee `spine/` gets, applied to `warrant/`.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WARRANT = REPO / "warrant"

#: Strict set: warrant/ has no legitimate reason to import ANY of these,
#: unlike tower/gateway.py which needs google.adk for its router graph.
FORBIDDEN_MODULES = {
    "lib.vertex",
    "google.genai",
    "google.adk",
    "vertexai",
    "openai",
    "anthropic",
}


def _module_name(path: Path) -> str:
    return ".".join(path.relative_to(REPO).with_suffix("").parts)


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


def _is_forbidden(module: str) -> bool:
    return any(
        module == forbidden or module.startswith(forbidden + ".") for forbidden in FORBIDDEN_MODULES
    )


def _local_module_path(module: str) -> Path | None:
    candidate = REPO / Path(*module.split(".")).with_suffix(".py")
    if candidate.is_file():
        return candidate
    package = REPO / Path(*module.split(".")) / "__init__.py"
    return package if package.is_file() else None


def test_no_warrant_module_can_reach_a_model_client_or_adk() -> None:
    """Transitive closure over first-party imports, starting from every
    module in warrant/. Includes google.adk itself, unlike tower/'s own
    version of this test -- warrant/ never needs the framework at all.
    """
    offenders: list[str] = []

    for source in sorted(WARRANT.glob("*.py")):
        start = _module_name(source)
        seen: set[str] = set()
        stack: list[tuple[str, Path, list[str]]] = [(start, source, [start])]

        while stack:
            module, path, chain = stack.pop()
            if module in seen:
                continue
            seen.add(module)

            for imported in sorted(_direct_imports(path)):
                if _is_forbidden(imported):
                    offenders.append(" -> ".join([*chain, imported]))
                    continue
                nested = _local_module_path(imported)
                if nested is not None:
                    stack.append((imported, nested, [*chain, imported]))

    assert not offenders, "warrant/ can reach a model client or ADK:\n" + "\n".join(offenders)


def test_warrant_modules_import_cleanly_with_vertex_disabled() -> None:
    """Importing the ledger must not construct anything that needs credentials."""
    import os
    import subprocess
    import sys

    env = {**os.environ, "UNWIND_VERTEX_DISABLED": "1", "UNWIND_OTEL_CONSOLE": "0"}
    result = subprocess.run(
        [sys.executable, "-c", "import warrant.ledger; print('ok')"],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout


def test_the_forbidden_list_is_not_vacuous_for_warrant() -> None:
    """A guard that would pass against anything is not a guard. tower/gateway.py
    is known to import google.adk; confirm the detector would actually catch
    that shape if it appeared inside warrant/ (it does not today)."""
    gateway = REPO / "tower" / "gateway.py"
    imports = _direct_imports(gateway)
    assert any(_is_forbidden(i) for i in imports), (
        "the import detector found nothing in a file known to import ADK, so it "
        "would not have caught a real violation inside warrant/ either"
    )


def test_warrant_ledger_does_not_import_google_adk_directly() -> None:
    """The specific claim `tower/gateway.py`'s docstring makes: the atomic
    SPEND-or-refuse FunctionNode is built THERE, wrapping a plain function
    defined HERE. If warrant/ledger.py ever imports google.adk directly, that
    claim is false and this is the one test that would catch it fastest.
    """
    ledger_imports = _direct_imports(WARRANT / "ledger.py")
    assert not any(i == "google.adk" or i.startswith("google.adk.") for i in ledger_imports)
