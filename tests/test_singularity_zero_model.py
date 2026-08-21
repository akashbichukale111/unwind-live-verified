"""The zero-model guarantee, extended to Singularity-Mesh's two decision
engines. Same broad forbidden-import walk `tests/test_hyperion_zero_model.py`
already runs for `hyperion/risk.py`.

`singularity/mesh_memory.py`, `singularity/fleet.py`, and
`singularity/lifecycle.py` are deliberately NOT walked here:
`mesh_memory.py` imports `lib.firestore`, which is infrastructure, not
model-adjacent reasoning, and `fleet.py`/`lifecycle.py` are inert data
modules with no logic to protect from a model dependency in the first
place.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SINGULARITY_DECISION_MODULES = [
    REPO / "singularity" / "genome.py",
    REPO / "singularity" / "behavior.py",
]

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


def test_singularity_decision_engines_cannot_reach_a_model_client() -> None:
    offenders: list[str] = []

    for source in SINGULARITY_DECISION_MODULES:
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
