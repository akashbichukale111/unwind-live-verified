"""The zero-model boundary inside `evolution/`.

This package deliberately has BOTH kinds of module, so the guarantee here is
split rather than blanket -- a single rule over the whole package would
either be vacuous or would forbid the one module that legitimately needs a
model.

  SCORING side -- `schema.py`, `criteria.py`, `trajectory.py`. These decide
                 what a number IS. They must not be able to reach a model
                 client OR `google.adk` even transitively, by the same strict
                 rule `tests/test_warrant_zero_model.py` applies to
                 `warrant/`. If scoring could call a model, a score would stop
                 being recomputable and every number in
                 `docs/evaluation-report.md` would become unreproducible.

  ROSTER side  -- `versions.py`, `policy.py`. Model-FREE in themselves, but
                 they deliberately read the live fleet definition:
                 `seed_versions()` takes version 1 from the instruction text
                 `fleet/roles.py` is actually serving, and
                 `plan_step_ceiling()` reads `fleet/planner.py`'s hard cap so
                 a policy can only ever narrow it. Both imports are the
                 reason those functions are honest -- copying the strings here
                 instead would let the seed drift from production -- and
                 `fleet/` reaches `google.adk` through `tower/registry.py`.
                 So these two get the NARROWER guarantee that
                 `tests/test_tower_zero_model.py` uses: no DIRECT model
                 import. Asserting the strict rule here would force a copy of
                 production text into this package, which is a worse property
                 than the one it would buy.

  MODEL side  -- `propose.py` alone. Writing a better instruction from a
                 failure analysis is a judgement call over prose, which is
                 what a model is for. It is asserted to be the ONLY module
                 permitted to reach one, so the boundary cannot quietly widen
                 by someone adding an import to `criteria.py`.

  I/O side    -- `store.py`, `promote.py`, `replay.py`. Not model-free by
                 construction (`replay.py` runs the real planner, which may
                 call Gemini), and not asserted to be.

The transitive-closure walk is the same one `tests/test_zero_model.py`,
`tests/test_tower_zero_model.py` and `tests/test_warrant_zero_model.py`
already use, reused rather than reinvented.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EVOLUTION = REPO / "evolution"

#: Strict set, matching `tests/test_warrant_zero_model.py`.
FORBIDDEN_MODULES = {
    "lib.vertex",
    "google.genai",
    "google.adk",
    "vertexai",
    "openai",
    "anthropic",
}

#: Must not reach a model directly OR transitively.
SCORING_MODULES = ("schema.py", "criteria.py", "trajectory.py")

#: Must not import a model DIRECTLY. Reach one transitively via `fleet/`,
#: deliberately, because they read the live roster rather than a copy of it.
ROSTER_MODULES = ("versions.py", "policy.py")

#: The one module allowed to.
MODEL_FACING = "propose.py"


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


def _reachable_forbidden(source: Path) -> list[str]:
    start = _module_name(source)
    offenders: list[str] = []
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
            local = _local_module_path(imported)
            if local is not None and imported not in seen:
                stack.append((imported, local, [*chain, imported]))
    return offenders


def test_the_scoring_side_cannot_reach_a_model_or_adk() -> None:
    """A score that could call a model is a score nobody can recompute."""
    offenders: list[str] = []
    for name in SCORING_MODULES:
        source = EVOLUTION / name
        assert source.is_file(), f"{name} is missing; update SCORING_MODULES"
        offenders.extend(_reachable_forbidden(source))
    assert not offenders, "model client reachable from the scoring side:\n" + "\n".join(offenders)


def test_the_roster_side_imports_no_model_client_directly() -> None:
    """The narrower guarantee, and the reason it is narrower is stated in this
    module's docstring: these two read the LIVE fleet definition on purpose."""
    offenders: list[str] = []
    for name in ROSTER_MODULES:
        source = EVOLUTION / name
        assert source.is_file(), f"{name} is missing; update ROSTER_MODULES"
        offenders.extend(
            f"{name} -> {imported}"
            for imported in sorted(_direct_imports(source))
            if _is_forbidden(imported)
        )
    assert not offenders, "direct model import on the roster side:\n" + "\n".join(offenders)


def test_the_roster_sides_only_route_to_adk_is_the_fleet_registry() -> None:
    """Pins WHY the roster side is exempt, so the exemption cannot silently
    grow to cover a new and unrelated dependency."""
    for name in ROSTER_MODULES:
        for chain in _reachable_forbidden(EVOLUTION / name):
            assert "fleet." in chain, (
                f"{name} reaches a model by a route other than the fleet roster: {chain}"
            )


def test_only_one_module_in_the_package_is_model_facing() -> None:
    """Pins the boundary's WIDTH, not just its existence.

    Without this, someone could add a model import to `criteria.py` and the
    test above would fail with no explanation of what the rule was supposed
    to be. This states it.
    """
    model_facing = [
        source.name
        for source in sorted(EVOLUTION.glob("*.py"))
        if any(_is_forbidden(imported) for imported in _direct_imports(source))
    ]
    assert model_facing == [MODEL_FACING], (
        f"expected exactly {MODEL_FACING!r} to import a model client, found {model_facing}"
    )


def test_the_pure_side_is_importable_with_no_credentials_configured() -> None:
    """A cold clone with no GCP account must still be able to score a
    mission. This is the property that makes the eval harness runnable in
    CI."""
    import importlib

    for name in (*SCORING_MODULES, *ROSTER_MODULES):
        importlib.import_module(f"evolution.{name[:-3]}")
