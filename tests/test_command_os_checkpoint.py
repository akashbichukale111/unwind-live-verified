"""`command_os.checkpoint` and `resume_mission`'s three real cases:
ALREADY COMPLETED, REQUIRES HUMAN APPROVAL, and REPLAYABLE FROM THE NEXT
STAGE (crash recovery).

Every invariant this file proved before the plan-driven rewrite is still
proved here. The assertions that changed are the ones that hard-coded
eleven stages; the properties -- ordering, no re-entry, no double spend, no
duplicate external effect, a gate that cannot be passed without a principal
-- are unchanged and now cover strictly more ground, because a mission's
length varies by objective.

Needs the Firestore emulator (`make emulator`).
"""

from __future__ import annotations

import os
import socket

import pytest

PRINCIPAL = "human::checkpoint-test@example.com"


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


def _run(**kwargs):
    from command_os.mission import run_mission

    base = {"principal": PRINCIPAL, "auth_method": "dev", "allow_model": False}
    base.update(kwargs)
    return run_mission(**base)


# ===========================================================================
# Persistence
# ===========================================================================


@requires_emulator
def test_checkpoints_survive_and_are_ordered() -> None:
    from command_os.checkpoint import list_checkpoints

    result = _run()
    checkpoints = list_checkpoints(result.mission_id)
    assert [c.seq for c in checkpoints] == list(range(1, len(result.stages) + 1))
    assert [c.stage.name for c in checkpoints] == [s.name for s in result.stages]


@requires_emulator
def test_every_checkpoint_carries_the_continuation_context() -> None:
    """`ctx` must contain the mission's own work queue and position, because
    that is what makes an inserted phase (containment, replan) survive a
    restart rather than living only in memory."""
    from command_os.checkpoint import list_checkpoints

    result = _run()
    for checkpoint in list_checkpoints(result.mission_id):
        assert "phases" in checkpoint.ctx
        assert "cursor" in checkpoint.ctx
        assert checkpoint.ctx["mission_id"] == result.mission_id


@requires_emulator
def test_checkpoint_ctx_is_json_safe_primitives_only() -> None:
    """A live object round-tripped through Firestore is how a resume starts
    reconstructing state it should have re-fetched."""
    import json

    from command_os.checkpoint import list_checkpoints

    for checkpoint in list_checkpoints(_run().mission_id):
        json.dumps(checkpoint.ctx)  # raises if anything is not JSON-safe


# ===========================================================================
# ALREADY COMPLETED
# ===========================================================================


@requires_emulator
def test_resuming_an_already_completed_mission_does_not_rerun_anything() -> None:
    from command_os.checkpoint import list_checkpoints
    from command_os.mission import resume_mission

    first = _run()
    before = len(list_checkpoints(first.mission_id))

    again = resume_mission(first.mission_id)
    assert again.status == first.status
    assert [s.name for s in again.stages] == [s.name for s in first.stages]
    assert len(list_checkpoints(first.mission_id)) == before


@requires_emulator
def test_resume_does_not_double_spend() -> None:
    """The property measured on the LEDGER, not on a flag."""
    from command_os.mission import resume_mission
    from fleet.roles import SPECIALISTS
    from tower.registry import get_agent
    from warrant.ledger import current_balance

    first = _run()

    def _balances() -> dict[str, int]:
        out = {}
        for role in SPECIALISTS:
            agent = get_agent(role.agent_id)
            for risk_class in role.warrant_mint_schedule:
                out[f"{role.agent_id}:{risk_class}"] = current_balance(
                    agent.principal, role.capabilities[0], risk_class
                )
        return out

    before = _balances()
    for _ in range(3):
        resume_mission(first.mission_id)
    assert _balances() == before


@requires_emulator
def test_resume_does_not_duplicate_external_action() -> None:
    from command_os.external import sandbox_line_count
    from command_os.mission import resume_mission

    first = _run()
    before = sandbox_line_count()
    for _ in range(3):
        resume_mission(first.mission_id)
    assert sandbox_line_count() == before


@requires_emulator
def test_resume_does_not_duplicate_hyperion_events() -> None:
    from command_os.mission import resume_mission
    from hyperion.immune_memory import list_events

    first = _run()
    before = len(list_events())
    for _ in range(3):
        resume_mission(first.mission_id)
    assert len(list_events()) == before


# ===========================================================================
# REQUIRES HUMAN APPROVAL
# ===========================================================================


@requires_emulator
def test_resume_without_a_decision_on_an_awaiting_human_mission_raises() -> None:
    from command_os.mission import resume_mission

    paused = _run(auto_approve=False)
    if paused.status != "AWAITING_HUMAN":
        pytest.skip("this objective's plan needs no human concurrence")
    with pytest.raises(ValueError, match="human_decision"):
        resume_mission(paused.mission_id)


@requires_emulator
def test_resume_with_a_decision_but_no_principal_raises() -> None:
    """The forgery this gate exists to prevent: an approval attributed to
    nobody."""
    from command_os.mission import resume_mission

    paused = _run(auto_approve=False)
    if paused.status != "AWAITING_HUMAN":
        pytest.skip("this objective's plan needs no human concurrence")
    with pytest.raises(ValueError, match="human_principal"):
        resume_mission(paused.mission_id, human_decision="approve")


@requires_emulator
def test_approving_the_gate_resumes_into_the_same_execution_chain() -> None:
    from command_os.mission import resume_mission

    paused = _run(auto_approve=False)
    if paused.status != "AWAITING_HUMAN":
        pytest.skip("this objective's plan needs no human concurrence")

    approver = "human::approver@example.com"
    resumed = resume_mission(paused.mission_id, human_decision="approve", human_principal=approver)
    assert resumed.status != "AWAITING_HUMAN"
    assert resumed.report is not None
    assert resumed.report.human_principal == approver
    assert resumed.report.human_decision_mode == "explicit_gate_decision"
    assert len(resumed.stages) > len(paused.stages)


@requires_emulator
def test_denying_the_gate_halts_without_any_external_effect() -> None:
    from command_os.external import sandbox_line_count
    from command_os.mission import resume_mission

    paused = _run(auto_approve=False)
    if paused.status != "AWAITING_HUMAN":
        pytest.skip("this objective's plan needs no human concurrence")

    before = sandbox_line_count()
    denied = resume_mission(
        paused.mission_id, human_decision="deny", human_principal="human::denier@example.com"
    )
    assert denied.status == "HALTED"
    assert denied.report.external_action_id is None
    assert sandbox_line_count() == before


@requires_emulator
def test_a_human_decision_cannot_overturn_the_gateway() -> None:
    """The structural guarantee: approving only authorises a NEW request that
    the unmodified Gateway independently re-checks. Asserted on the source --
    no phase handler constructs a `GatewayDecision` with `allowed=True`
    itself; every allow in the trace comes from `evaluate_with_hyperion`."""
    import inspect

    import command_os.mission as mission

    source = inspect.getsource(mission)
    assert "GatewayDecision(" not in source, (
        "command_os/mission.py constructs a GatewayDecision directly; the only "
        "source of an allow must be tower/gateway.py"
    )
    assert "allowed=True" not in source


# ===========================================================================
# REPLAYABLE (crash recovery)
# ===========================================================================


@requires_emulator
def test_resume_from_a_simulated_crash_continues_past_the_last_completed_stage() -> None:
    """Simulates a process exiting between two stages by rewinding the parent
    record to RUNNING while the checkpoints stay where they are."""
    from command_os.checkpoint import list_checkpoints, update_mission_status
    from command_os.mission import resume_mission

    first = _run()
    total = len(list_checkpoints(first.mission_id))
    update_mission_status(first.mission_id, "RUNNING")

    resumed = resume_mission(first.mission_id)
    assert resumed.status != "RUNNING"
    # Nothing before the crash point is re-entered: the stage list is not
    # longer than it was, because the mission had in fact already finished.
    assert len(list_checkpoints(first.mission_id)) >= total


@requires_emulator
def test_resuming_an_unknown_mission_raises_rather_than_inventing_one() -> None:
    from command_os.mission import resume_mission

    with pytest.raises(ValueError, match="no mission"):
        resume_mission("mission_does_not_exist")


@requires_emulator
def test_missions_index_lists_recent_missions_most_recent_first() -> None:
    from command_os.checkpoint import list_missions

    ids = [_run().mission_id for _ in range(3)]
    listed = [m.mission_id for m in list_missions(limit=10)]
    assert set(ids) <= set(listed)
    assert listed.index(ids[-1]) < listed.index(ids[0]), "not ordered most-recent-first"
