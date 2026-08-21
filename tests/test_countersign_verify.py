"""Card 3: Countersign -- the collusion guard, the parse, and the wiring
into `warrant/ledger.py`'s minting gate.

Split like `tests/test_warrant_ledger.py`: PURE tests need no Firestore and
no Vertex; PERSISTED tests (the DISAGREE -> CHALLENGE wiring) need the
Firestore emulator and run with `UNWIND_COUNTERSIGN_SIMULATED=1` so they
need no live Gemma call either -- the mechanism, not the model, is what
these prove.
"""

from __future__ import annotations

import os
import socket
import uuid

import pytest

from countersign.verify import (
    CollusionError,
    assert_independent,
    run_countersign,
)
from lib.config import GEMMA_MODEL, MODEL_DEEP, MODEL_FAST

# ===========================================================================
# PURE section -- no Firestore, no Vertex.
# ===========================================================================


def test_same_family_countersign_rejected() -> None:
    """Adversary: collusion by family. Different exact string, same root."""
    with pytest.raises(CollusionError):
        assert_independent(
            countersign_family=MODEL_DEEP,
            countersign_principal="countersign::gemma",
            judging_family=MODEL_FAST,
            judging_principal="agent::extractor",
        )


def test_same_principal_countersign_rejected() -> None:
    """Adversary: collusion by principal, even with an independent family."""
    with pytest.raises(CollusionError):
        assert_independent(
            countersign_family=GEMMA_MODEL,
            countersign_principal="agent::extractor",
            judging_family=MODEL_DEEP,
            judging_principal="agent::extractor",
        )


def test_independent_family_and_principal_pass() -> None:
    """Vacuity check: the guard does not fire on a genuinely independent pair."""
    assert_independent(
        countersign_family=GEMMA_MODEL,
        countersign_principal="countersign-gemma@0.1.0",
        judging_family=MODEL_DEEP,
        judging_principal="agent::extractor",
    )


def test_family_root_normalizes_versions() -> None:
    from warrant.ledger import family_root

    assert family_root(MODEL_DEEP) == "gemini"
    assert family_root(MODEL_FAST) == "gemini"
    assert family_root(GEMMA_MODEL) == "gemma"
    assert family_root("GEMMA-3-27B-IT") == "gemma"


def test_simulated_countersign_is_labelled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulated flag off by default, labelled when on -- checked at the
    call site, not just documented."""
    monkeypatch.delenv("UNWIND_COUNTERSIGN_SIMULATED", raising=False)
    monkeypatch.setenv("UNWIND_VERTEX_DISABLED", "1")
    off = run_countersign("c1", {}, judging_family=MODEL_DEEP, judging_principal="agent::x")
    assert off.simulated is False
    assert off.available is False  # Vertex disabled, not simulated -- honest UNAVAILABLE

    monkeypatch.setenv("UNWIND_COUNTERSIGN_SIMULATED", "1")
    on = run_countersign(
        "c1", {"class": "clean"}, judging_family=MODEL_DEEP, judging_principal="agent::x"
    )
    assert on.simulated is True
    # The family name changed from "gemma-simulated" to
    # "zero-model-challenger" when the marker-lookup stand-in was replaced by
    # a real evidence-based challenger. What must hold is the PROPERTY, not
    # the string: the family must be independent of the judging side, and it
    # must not be Gemini-family, or `warrant.ledger.mint` would accept it as
    # independent verification when it is not.
    from warrant.ledger import family_root

    assert family_root(on.family) != family_root(MODEL_DEEP)
    assert not family_root(on.family).startswith("gemini")


def test_simulated_countersign_disagrees_on_adversarial_material(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("UNWIND_COUNTERSIGN_SIMULATED", "1")
    clean = run_countersign(
        "c1", {"class": "clean"}, judging_family=MODEL_DEEP, judging_principal="agent::x"
    )
    assert clean.agrees is True

    adversarial = run_countersign(
        "c2",
        {"class": "adversarial"},
        judging_family=MODEL_DEEP,
        judging_principal="agent::x",
    )
    assert adversarial.agrees is False


def test_simulated_countersign_still_enforces_collusion_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A simulated run is a rehearsal of the real guard, not a bypass of it."""
    monkeypatch.setenv("UNWIND_COUNTERSIGN_SIMULATED", "1")
    with pytest.raises(CollusionError):
        run_countersign(
            "c1",
            {},
            judging_family=MODEL_DEEP,
            judging_principal="agent::x",
            principal="agent::x",  # collides on principal
        )


def test_countersign_agent_is_a_real_single_turn_agent_tool() -> None:
    """Novelty test: not plain code wearing a comment. `countersign_tool` is
    a real `google.adk.tools.agent_tool.AgentTool`, and the agent it wraps
    is configured `mode="single_turn"` -- inspectable, not asserted."""
    from google.adk.tools.agent_tool import AgentTool

    from countersign.agent import countersign_agent, countersign_tool

    assert isinstance(countersign_tool, AgentTool)
    assert countersign_tool.agent is countersign_agent
    assert countersign_agent.mode == "single_turn"


def test_parse_verdict_raises_rather_than_guesses() -> None:
    from countersign.verify import _parse_verdict

    with pytest.raises(ValueError):
        _parse_verdict("I have thoughts about this case but no clear verdict.")

    agrees, ground = _parse_verdict("VERDICT: AGREE\nGROUND: the evidence supports it.")
    assert agrees is True
    assert "evidence" in ground

    agrees2, ground2 = _parse_verdict("verdict: disagree\nground: numbers do not match.")
    assert agrees2 is False


# ===========================================================================
# PERSISTED section -- Firestore emulator, SIMULATED countersign (no Vertex).
# ===========================================================================


def _emulator_up() -> bool:
    host = os.environ.get("FIRESTORE_EMULATOR_HOST", "localhost:8080")
    hostname, _, port = host.partition(":")
    try:
        with socket.create_connection((hostname, int(port or 8080)), timeout=1.0):
            return True
    except OSError:
        return False


requires_emulator = pytest.mark.skipif(
    not _emulator_up(), reason="Firestore emulator not running; start it with `make emulator`"
)


@pytest.fixture(scope="module", autouse=True)
def _emulator_project():
    if not _emulator_up():
        yield
        return
    os.environ.setdefault("FIRESTORE_EMULATOR_HOST", "localhost:8080")
    os.environ["UNWIND_PROJECT_ID"] = "unwind-countersign-test"
    from lib import firestore as fs
    from lib.config import reset_config_cache

    reset_config_cache()
    fs.reset_client()
    yield
    fs.reset_client()
    reset_config_cache()


def _fresh_agent(agent_id: str, **overrides):
    from tower.registry import make_entry

    defaults = dict(
        capabilities=["extract"],
        max_budget=1000,
        authority_scope=["claim.read"],
        risk_class_thresholds={"LOW": 1000, "HIGH": 100},
        warrant_mint_schedule={"LOW": 500, "HIGH": 50},
        warrant_spend_schedule={"LOW": 100, "HIGH": 100},
    )
    defaults.update(overrides)
    return make_entry(agent_id, **defaults)


@requires_emulator
def test_agree_lets_mint_proceed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UNWIND_COUNTERSIGN_SIMULATED", "1")
    from countersign.verify import verify_and_record
    from warrant.ledger import mint, record_human_concurrence, reset_for_test

    agent = _fresh_agent(f"cs_agree_{uuid.uuid4().hex[:6]}")
    reset_for_test(principal=agent.principal)
    case_id = f"case_{uuid.uuid4().hex[:8]}"
    record_human_concurrence(case_id, principal="human::alice", note="ok")

    outcome = verify_and_record(
        case_id=case_id,
        material={"class": "clean"},
        agent=agent,
        capability="extract",
        risk_class="LOW",
        judging_family=MODEL_DEEP,
        judging_principal="agent::some_extractor",
    )
    assert outcome.available and outcome.agrees

    event = mint(agent=agent, capability="extract", risk_class="LOW", case_id=case_id, reason="ok")
    assert event.amount_bp == 500


@requires_emulator
def test_disagree_freezes_minting_with_challenge(monkeypatch: pytest.MonkeyPatch) -> None:
    """DISAGREE -> CHALLENGE event, minting frozen for that case."""
    monkeypatch.setenv("UNWIND_COUNTERSIGN_SIMULATED", "1")
    from countersign.verify import verify_and_record
    from warrant.ledger import CaseChallengedError, mint, record_human_concurrence, reset_for_test

    agent = _fresh_agent(f"cs_disagree_{uuid.uuid4().hex[:6]}")
    reset_for_test(principal=agent.principal)
    case_id = f"case_{uuid.uuid4().hex[:8]}"
    record_human_concurrence(case_id, principal="human::alice", note="ok")

    outcome = verify_and_record(
        case_id=case_id,
        material={"class": "adversarial"},
        agent=agent,
        capability="extract",
        risk_class="LOW",
        judging_family=MODEL_DEEP,
        judging_principal="agent::some_extractor",
    )
    assert outcome.available and not outcome.agrees

    with pytest.raises(CaseChallengedError):
        mint(agent=agent, capability="extract", risk_class="LOW", case_id=case_id, reason="frozen")


@requires_emulator
def test_unavailable_countersign_writes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """UNAVAILABLE never fabricates a record -- mint() refuses for lack of
    one, same as if Countersign had never been attempted."""
    monkeypatch.delenv("UNWIND_COUNTERSIGN_SIMULATED", raising=False)
    monkeypatch.setenv("UNWIND_VERTEX_DISABLED", "1")
    from countersign.verify import verify_and_record
    from warrant.ledger import MintPreconditionError, mint, record_human_concurrence, reset_for_test

    agent = _fresh_agent(f"cs_unavail_{uuid.uuid4().hex[:6]}")
    reset_for_test(principal=agent.principal)
    case_id = f"case_{uuid.uuid4().hex[:8]}"
    record_human_concurrence(case_id, principal="human::alice", note="ok")

    outcome = verify_and_record(
        case_id=case_id,
        material={"class": "clean"},
        agent=agent,
        capability="extract",
        risk_class="LOW",
        judging_family=MODEL_DEEP,
        judging_principal="agent::some_extractor",
    )
    assert outcome.available is False

    with pytest.raises(MintPreconditionError):
        mint(agent=agent, capability="extract", risk_class="LOW", case_id=case_id, reason="x")
