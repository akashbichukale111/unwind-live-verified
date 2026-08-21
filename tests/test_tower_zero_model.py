"""The zero-model guarantee, extended to Card 2's deterministic authority path.

`tests/test_zero_model.py` walks `spine/`'s import graph and forbids
`google.adk` itself, because `spine/` must have no framework dependency at
all. `tower/` is different: it legitimately imports ADK for the Gateway's
router graph (`tower/gateway.py`) and the durable runtime tool
(`tower/runtime.py`), the same way `agents/cascade/workflow.py` legitimately
imports ADK one layer below `spine/`. What must still be forbidden, in both
places, is a MODEL CLIENT -- `lib.vertex`, `google.genai`, `vertexai`,
`openai`, `anthropic`. This file walks `tower/registry.py` and
`tower/gateway.py` (the modules that make authority decisions: eligibility,
principal/scope/budget/warrant checks) against that narrower forbidden set.

`tower/memory.py` and `tower/runtime.py` are infrastructure (storage,
pause/resume), not authority decisions, and are deliberately NOT walked here
-- they hold no branch a forged input could steer.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TOWER_AUTHORITY_MODULES = [REPO / "tower" / "registry.py", REPO / "tower" / "gateway.py"]

#: Deliberately narrower than tests/test_zero_model.py's set: google.adk is
#: EXPECTED here (the router graph is ADK), so it is not forbidden. Only an
#: actual model client is.
FORBIDDEN_MODULES = {
    "lib.vertex",
    "google.genai",
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


def test_tower_authority_path_cannot_reach_a_model_client() -> None:
    offenders: list[str] = []

    for source in TOWER_AUTHORITY_MODULES:
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

    assert not offenders, "tower/'s authority path can reach a model client:\n" + "\n".join(
        offenders
    )


def test_tower_cannot_be_reached_from_spine() -> None:
    """The boundary works both directions: spine/ must never import tower/,
    or a future edit to tower/ (which IS allowed to touch ADK/models) could
    smuggle a model call into the tier that must never make one.
    `tests/test_zero_model.py` already forbids spine/ from reaching
    google.adk directly; this asserts the specific one-hop case explicitly
    so the intent is not just an emergent property of a broader rule.
    """
    spine_dir = REPO / "spine"
    offenders = []
    for source in sorted(spine_dir.glob("*.py")):
        imports = _direct_imports(source)
        if any(i == "tower" or i.startswith("tower.") for i in imports):
            offenders.append(_module_name(source))
    assert not offenders, f"spine/ modules importing tower/: {offenders}"


def test_the_forbidden_list_is_not_vacuous_for_tower() -> None:
    """`tower/gateway.py` and `tower/registry.py` both legitimately import
    `google.adk`, which is NOT in this file's forbidden set (unlike
    `tests/test_zero_model.py`'s). Confirm that directly, so a reader knows
    the omission is deliberate rather than an oversight -- and confirm
    separately that `lib.vertex` (a real forbidden entry) is not present
    either, which is the actual guarantee this file exists to check.
    """
    gateway_imports = _direct_imports(REPO / "tower" / "gateway.py")
    assert any(i == "google.adk" or i.startswith("google.adk.") for i in gateway_imports), (
        "tower/gateway.py no longer imports ADK -- if the Gateway stopped being "
        "a real Workflow, the module docstring's ADK claim is now false too"
    )
    assert not any(_is_forbidden(i) for i in gateway_imports)
