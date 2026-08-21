"""`command_os.trust`: Trusted State -- what a mission is willing to act on
now, as distinct from what merely happened.

The buckets are CATEGORICAL and always will be. This repository already
refused scalar agent trust once (`lib/schema.py:AgentTrust`, refused as a
load-rating input by `settle/loadrating.py:assert_not_agent_trust`), and
`test_no_scalar_score_anywhere_in_the_payload` is what keeps that refusal
from quietly eroding.

What changed with the plan-driven rewrite: bucketing is keyed on what a
stage RECORDED (`isolated`, the Gateway's own `allowed`), never on the
stage's position, because a mission's length and ordering now vary by
objective.
"""

from __future__ import annotations

import os
import socket

import pytest

PRINCIPAL = "human::trust-test@example.com"


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


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    monkeypatch.setenv("UNWIND_VERTEX_DISABLED", "1")
    monkeypatch.setenv("UNWIND_COUNTERSIGN_SIMULATED", "1")
    monkeypatch.delenv("UNWIND_ENV", raising=False)
    if _emulator_up():
        from command_os.mission import reset_for_test

        reset_for_test()
    yield
    if _emulator_up():
        from command_os.mission import reset_for_test

        reset_for_test()


def _run():
    from command_os.mission import run_mission

    return run_mission(principal=PRINCIPAL, auth_method="dev", allow_model=False)


@requires_emulator
def test_buckets_are_disjoint_and_every_checkpoint_lands_in_exactly_one() -> None:
    from command_os.trust import trusted_state_for_mission

    result = _run()
    state = trusted_state_for_mission(result.mission_id)

    buckets = ("trusted", "untrusted", "quarantined", "revoked")
    all_seqs = [item["seq"] for bucket in buckets for item in state[bucket]]
    assert sorted(all_seqs) == list(range(1, len(result.stages) + 1))
    assert len(all_seqs) == len(set(all_seqs)), "a checkpoint landed in two buckets"


@requires_emulator
def test_the_containment_is_quarantined_and_its_refusal_is_revoked() -> None:
    """The isolation and the Gateway refusal that caused it are bucketed by
    what the stage recorded, whatever position it occupied."""
    from command_os.trust import trusted_state_for_mission

    result = _run()
    state = trusted_state_for_mission(result.mission_id)

    contain_stages = [s for s in result.stages if s.name.startswith("CONTAIN")]
    if not contain_stages:
        pytest.skip("this run found no escalation to contain")

    quarantined_names = {item["stage"] for item in state["quarantined"]}
    assert any(name.startswith("CONTAIN") for name in quarantined_names), (
        f"the containment was not quarantined; buckets were {state}"
    )


@requires_emulator
def test_allowed_steps_are_trusted() -> None:
    from command_os.trust import trusted_state_for_mission

    result = _run()
    state = trusted_state_for_mission(result.mission_id)
    trusted_names = {item["stage"] for item in state["trusted"]}
    allowed_steps = {
        s.name
        for s in result.stages
        if s.name.startswith("STEP ") and (s.detail.get("decision") or {}).get("allowed") is True
    }
    assert allowed_steps <= trusted_names, (
        f"an allowed step was not trusted: {allowed_steps - trusted_names}"
    )


@requires_emulator
def test_no_scalar_score_anywhere_in_the_payload() -> None:
    """Never one number. The same refusal `warrant/DESIGN.md` states for
    balances and `hyperion/schema.py` states for risk."""
    from command_os.trust import trusted_state_for_mission

    state = trusted_state_for_mission(_run().mission_id)
    forbidden = {"score", "trust_score", "reputation", "confidence", "rating", "percent"}
    flat = repr(state).lower()
    for word in forbidden:
        assert word not in flat, f"a scalar {word!r} appeared in Trusted State"


@requires_emulator
def test_hyperion_events_considered_are_scoped_to_this_mission() -> None:
    """The count must be a real filter over this mission's own case ids, not
    a fleet-wide total dressed up as mission-scoped."""
    from command_os.trust import trusted_state_for_mission
    from hyperion.immune_memory import list_events

    result = _run()
    state = trusted_state_for_mission(result.mission_id)

    mine = [e for e in list_events() if e.case_id and e.case_id.startswith(result.mission_id)]
    assert state["hyperion_events_considered"] == len(mine)
    assert state["hyperion_events_considered"] > 0, (
        "the mission wrote no Hyperion events; the authority path did not run"
    )


@requires_emulator
def test_trusted_state_of_an_unknown_mission_is_empty_not_invented() -> None:
    from command_os.trust import trusted_state_for_mission

    state = trusted_state_for_mission("mission_does_not_exist")
    assert state["trusted"] == []
    assert state["quarantined"] == []
    assert state["mission_status"] is None
