"""The zero-model guarantee, enforced by walking the import graph.

This is the whole point of Task 2, so it is not tested by convention or by a
comment. `spine/` is a package boundary: if any module in it can reach a model
client through any chain of imports, this test fails and says which chain.

It also runs the full cascade with `UNWIND_VERTEX_DISABLED=1`, which closes the
single door to a model, and asserts the cascade completes anyway. A "degraded
mode" that has never been executed is not a guarantee.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SPINE = REPO / "spine"

#: Anything that can reach Vertex, Gemini, or an LLM SDK. `lib.vertex` is the
#: single door; the rest are the doors it would open.
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
            if node.level:  # relative import within the package
                continue
            if node.module:
                found.add(node.module)
    return found


def _is_forbidden(module: str) -> bool:
    """Match the module itself and anything beneath it.

    Exact matching alone is not enough: `google.genai` is forbidden, and
    `google.genai.types` is the same dependency by another name.
    """
    return any(
        module == forbidden or module.startswith(forbidden + ".") for forbidden in FORBIDDEN_MODULES
    )


def _local_module_path(module: str) -> Path | None:
    candidate = REPO / Path(*module.split(".")).with_suffix(".py")
    if candidate.is_file():
        return candidate
    package = REPO / Path(*module.split(".")) / "__init__.py"
    return package if package.is_file() else None


def test_no_spine_module_can_reach_a_model_client() -> None:
    """Transitive closure over first-party imports, starting from every spine module."""
    offenders: list[str] = []

    for source in sorted(SPINE.glob("*.py")):
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

    assert not offenders, "spine/ can reach a model client:\n" + "\n".join(offenders)


def test_spine_modules_import_cleanly_with_vertex_disabled() -> None:
    """Importing the spine must not construct anything that needs credentials."""
    env = {**os.environ, "UNWIND_VERTEX_DISABLED": "1", "UNWIND_OTEL_CONSOLE": "0"}
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import spine.cascade, spine.debt, spine.regimes, spine.authority; print('ok')",
        ],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout


def test_full_cascade_completes_with_vertex_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """The headline guarantee. Vertex off, whole cascade, zero model calls."""
    monkeypatch.setenv("UNWIND_VERTEX_DISABLED", "1")
    from lib.config import get_config, reset_config_cache
    from lib.vertex import VertexDisabledError, get_vertex_client, reset_vertex_client

    reset_config_cache()
    reset_vertex_client()
    assert get_config().vertex_disabled is True
    with pytest.raises(VertexDisabledError):
        get_vertex_client()  # the door really is shut

    from spine.cascade import CorpusStore, run_cascade

    result = run_cascade(
        store=CorpusStore.from_repo(REPO),
        claim_id="clm_000000",
        source_id="src_supplier_K",
        new_value=20,
        reason="regression test",
        triggered_at=datetime(2026, 7, 6, 9, 0, tzinfo=UTC),
    )

    # The radius is mapped and scored with no model. The AUTHORISATION half of
    # the gate then withholds permission, because a 2,594-node unwind on a single
    # uncorroborated source needs a signature -- which is a decision, not a
    # failure, and it is reached without Vertex either.
    assert result.status.value == "awaiting_authorisation"
    assert result.decision_state == "ask_human"
    assert result.model_calls == 0
    assert len(result.radius) > 2000
    assert result.tier_reached == "T1"

    reset_config_cache()
    reset_vertex_client()


def test_the_forbidden_list_is_not_vacuous() -> None:
    """A guard that would pass against anything is not a guard.

    `agents/` legitimately imports ADK, so the same walk applied there must find
    something. If it does not, the detector is broken rather than the code clean.
    """
    workflow = REPO / "agents" / "cascade" / "workflow.py"
    imports = _direct_imports(workflow)
    assert any(_is_forbidden(i) for i in imports), (
        "the import detector found nothing in a file known to import ADK, so it "
        "would not have caught a real violation either"
    )
