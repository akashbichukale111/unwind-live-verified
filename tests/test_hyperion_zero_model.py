"""The zero-model guarantee, extended to Hyperion's scoring path.

`hyperion/risk.py` needs no framework at all -- unlike `tower/registry.py`
and `tower/gateway.py`, which legitimately import `google.adk` for their
router graph, scoring a closed six-value enum is table lookup with no graph
to route. So this walks `hyperion/risk.py` against the SAME broad forbidden
set `tests/test_zero_model.py` uses for `spine/`, including `google.adk`
itself -- the narrower `tests/test_tower_zero_model.py` set does not apply
here because there is no legitimate ADK import to exempt.

`hyperion/guard.py` and `hyperion/immune_memory.py` are deliberately NOT
walked here: `guard.py` imports `tower.gateway`, which legitimately imports
`google.adk` for the Gateway's router graph one layer down, the same
exception `tests/test_tower_zero_model.py`'s own docstring documents for
that module. Walking `guard.py` against the broad set would fail on an
import that is supposed to be there.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
HYPERION_SCORING_MODULES = [REPO / "hyperion" / "risk.py"]

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


def test_hyperion_scoring_path_cannot_reach_a_model_client() -> None:
    offenders: list[str] = []

    for source in HYPERION_SCORING_MODULES:
        start = _module_name(source)
        seen: set[str] = set()
        stack: list[tuple[str, Path, list[str]]] = [(start, source, [start])]

        while stack:
            module, path, chain = stack.pop()
            if module in seen:
                continue
            seen.add(module)

            for imp in _direct_imports(path):
                if _is_forbidden(imp):
                    offenders.append(f"{' -> '.join(chain)} -> {imp}")
                    continue
                local = _local_module_path(imp)
                if local is not None and imp not in seen:
                    stack.append((imp, local, [*chain, imp]))

    assert not offenders, "forbidden model-client import reachable:\n" + "\n".join(offenders)
