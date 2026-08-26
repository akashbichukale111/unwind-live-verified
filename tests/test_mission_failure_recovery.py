"""What the mission does when a worker misbehaves, in every way it can.

Each test names ONE failure mode and asserts the mission's response to it:
that it noticed, that it recorded WHICH failure, that it did not act on the
bad result, and that it finished rather than hanging or crashing.

The emulator-backed tests run a real mission; the rest are pure.
"""

from __future__ import annotations

import os
import socket
import time

import pytest

from command_os import mission as mission_mod
from command_os.mission import (
    MAX_MISSION_PHASES,
    MAX_TOOL_ATTEMPTS,
    TOOL_TIMEOUT_SECONDS,
    _append_phase,
    _run_tool,
)


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


def _ctx() -> dict:
    return {"mission_id": "mission_test", "phases": ["PLAN"], "cursor": 0, "seq": 1}


# ===========================================================================
# 1. WORKER TIMEOUT
# ===========================================================================


def test_a_hung_worker_does_not_hang_the_mission(monkeypatch: pytest.MonkeyPatch) -> None:
    """The supervisor stops waiting. That is the guarantee, and it is the only
    one available: CPython cannot kill the thread, so the assertion is about
    the SUPERVISOR's wall clock, not the worker's.

    The timeout is lowered for the test rather than making the fake worker
    sleep for the production ceiling -- a test that takes twenty seconds to
    prove a timeout works is a test people stop running.
    """
    monkeypatch.setattr(mission_mod, "TOOL_TIMEOUT_SECONDS", 0.15)
    monkeypatch.setattr(mission_mod, "MAX_TOOL_ATTEMPTS", 2)

    def _hung(ctx, tool):
        return lambda: time.sleep(30) or {}

    monkeypatch.setattr(mission_mod, "_tool_thunk", _hung)

    started = time.monotonic()
    output, calls = _run_tool(_ctx(), "recon.extract_claims")
    elapsed = time.monotonic() - started

    assert output["__failed__"] is True
    assert output["failure"] == "TIMED_OUT"
    assert len(calls) == 2, "the timeout must be retried within the retry budget, then given up"
    assert all(c["failure"] == "TIMED_OUT" for c in calls)
    # Two attempts at 0.15s each, plus overhead. The 30s sleep is still
    # running; the mission is not waiting for it.
    assert elapsed < 5.0, f"the supervisor waited {elapsed:.1f}s for a hung worker"


def test_the_timeout_ceiling_is_actually_read_from_the_constant() -> None:
    """Guards the exact defect this suite was written for: a declared
    `TOOL_TIMEOUT_SECONDS` that nothing enforced. Asserting the constant
    exists proves nothing; asserting the module READS it does."""
    import inspect

    source = inspect.getsource(mission_mod._run_tool)
    assert "TOOL_TIMEOUT_SECONDS" in source


# ===========================================================================
# 2. WORKER RAISES -- bounded retries, then a structured failure
# ===========================================================================


def test_a_raising_worker_is_retried_exactly_the_budget_and_no_more(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = {"n": 0}

    def _boom(ctx, tool):
        def _run():
            attempts["n"] += 1
            raise RuntimeError("backend refused the connection")

        return _run

    monkeypatch.setattr(mission_mod, "_tool_thunk", _boom)
    output, calls = _run_tool(_ctx(), "risk.probe")

    assert attempts["n"] == MAX_TOOL_ATTEMPTS
    assert output["__failed__"] is True
    assert output["failure"] == "RAISED"
    assert "backend refused" in output["error"]
    assert [c["attempt"] for c in calls] == list(range(1, MAX_TOOL_ATTEMPTS + 1))


def test_a_transient_failure_that_recovers_on_the_retry_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A retry budget that can never succeed is a delay, not a recovery."""
    attempts = {"n": 0}
    good = {
        "escalations": [],
        "hypotheses": [],
        "verdict": "NO_ESCALATION_FOUND",
    }

    def _flaky(ctx, tool):
        def _run():
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise OSError("transient")
            return good

        return _run

    monkeypatch.setattr(mission_mod, "_tool_thunk", _flaky)
    output, calls = _run_tool(_ctx(), "risk.probe")

    assert output == good
    assert attempts["n"] == 2
    assert [c["ok"] for c in calls] == [False, True]


def test_an_unknown_tool_is_not_retried() -> None:
    """A closed vocabulary miss is not transient. Retrying it burns the budget
    on something that cannot become true."""
    output, calls = _run_tool(_ctx(), "definitely.not.a.tool")
    assert output["failure"] == "UNKNOWN_TOOL"
    assert len(calls) == 1


# ===========================================================================
# 3. HALLUCINATED OUTPUT -- right shape, wrong contents
# ===========================================================================


def test_a_structurally_plausible_lie_is_rejected_before_it_reaches_ctx(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The result below is a dict with every required key. It claims perfect
    coverage over counts that contradict it, and that number is what prices
    the next action. It must never be returned as usable output."""
    forged = {
        "claims": [],
        "requests": [],
        "contradictions": [],
        "anomalies": [],
        "parsed": 99,
        "total": 3,
        "completeness": 1.0,
        "newest_age_seconds": 0.0,
    }
    monkeypatch.setattr(mission_mod, "_tool_thunk", lambda ctx, tool: lambda: forged)
    output, calls = _run_tool(_ctx(), "recon.extract_claims")

    assert output["__failed__"] is True
    assert output["failure"] == "CONTRACT"
    assert output["violations"], "the rejection must name what was wrong, not just fail"
    assert any(v["check"] == "SELF_CONSISTENCY" for v in output["violations"])
    assert len(calls) == MAX_TOOL_ATTEMPTS, "a contract failure is retried once, then given up"


@requires_emulator
def test_a_faulted_step_leaves_the_mission_visibly_failed_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End to end: the fault reaches the report, names its kind, and the
    status is never a bare success."""
    from command_os.mission import STATUS_FAILED_SAFE, reset_for_test, run_mission

    reset_for_test()

    real_thunk = mission_mod._tool_thunk

    def _break_risk(ctx, tool):
        if tool == "risk.probe":
            return lambda: {"escalations": "not a list", "hypotheses": [], "verdict": "BOGUS"}
        return real_thunk(ctx, tool)

    monkeypatch.setattr(mission_mod, "_tool_thunk", _break_risk)
    result = run_mission(principal="human::test", auth_method="test", allow_model=False)

    assert result.status == STATUS_FAILED_SAFE
    assert result.report.worker_faults >= 1
    assert "CONTRACT" in result.report.worker_fault_kinds
    faulted = [s for s in result.stages if "WORKER FAULT" in s.name]
    assert faulted, "the fault must be a visible stage, not a silent skip"
    assert faulted[0].detail["contract_violations"], "the violations must be in the checkpoint"
    # And the orchestrator replanned rather than stopping dead.
    assert any(s.name.startswith("REPLAN") for s in result.stages)


@requires_emulator
def test_a_rejected_result_never_reaches_the_mission_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The property that matters more than the fault being recorded: the
    fabricated coverage figure must not have priced anything."""
    from command_os.mission import reset_for_test, run_mission

    reset_for_test()
    real_thunk = mission_mod._tool_thunk

    def _forge_recon(ctx, tool):
        if tool == "recon.extract_claims":
            return lambda: {
                "claims": [],
                "requests": [],
                "contradictions": [],
                "anomalies": [],
                "parsed": 99,
                "total": 3,
                "completeness": 1.0,
                "newest_age_seconds": 0.0,
            }
        return real_thunk(ctx, tool)

    monkeypatch.setattr(mission_mod, "_tool_thunk", _forge_recon)
    result = run_mission(principal="human::test", auth_method="test", allow_model=False)

    # The forged numbers appear NOWHERE in the mission's own record except
    # inside the violation that rejected them.
    import json

    for stage in result.stages:
        blob = json.dumps(stage.detail, default=str)
        if "contract_violations" in stage.detail and stage.detail["contract_violations"]:
            continue  # the rejection itself is allowed to quote what it rejected
        assert '"parsed": 99' not in blob, f"the forged output reached stage {stage.name!r}"

    # The report's coverage is the DEFAULT (nothing was ever parsed), never
    # the forged 99-of-3.
    assert result.report.evidence_records_total == 0
    assert result.report.evidence_records_parsed == 0
    assert result.report.evidence_completeness == 1.0  # the untouched default, not a measurement
    assert "CONTRACT" in result.report.worker_fault_kinds


# ===========================================================================
# 4. LOOP BOUND -- a mission that can extend itself needs a ceiling
# ===========================================================================


def test_the_phase_queue_has_a_ceiling_and_refuses_past_it() -> None:
    ctx = _ctx()
    ctx["phases"] = ["PLAN"]
    added = 0
    for _ in range(MAX_MISSION_PHASES * 2):
        if _append_phase(ctx, "CONTAIN"):
            added += 1
    assert len(ctx["phases"]) == MAX_MISSION_PHASES
    assert added == MAX_MISSION_PHASES - 1
    assert ctx["phase_budget_exhausted"] is True
    assert ctx["refused_phases"], "a refused append must be recorded, not silently dropped"


def test_the_ceiling_is_far_above_a_real_mission() -> None:
    """A bound that a normal mission brushes against is a bug generator. The
    longest committed plan produces well under half the ceiling."""
    from fleet.planner import MAX_PLAN_STEPS

    # plan + steps + the five terminal phases + room for CONTAIN, REPLAN,
    # RECONCILE and CONSEQUENCE.
    worst_case = 1 + MAX_PLAN_STEPS + 5 + 4
    assert worst_case <= MAX_MISSION_PHASES


def test_an_unknown_phase_raises_rather_than_being_skipped() -> None:
    """Silently skipping an unexecutable queue entry would drop mission work
    while reporting success."""
    with pytest.raises(KeyError):
        mission_mod._handler_for("NOT_A_PHASE")


# ===========================================================================
# 5. THE TIMEOUT AND RETRY CONSTANTS ARE SANE
# ===========================================================================


def test_the_retry_budget_is_bounded_and_small() -> None:
    assert 1 < MAX_TOOL_ATTEMPTS <= 3
    assert 0 < TOOL_TIMEOUT_SECONDS <= 30
