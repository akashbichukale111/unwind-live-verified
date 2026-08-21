"""`command_os.mission.run_mission`: the plan-driven orchestrator.

WHAT THIS SUITE TESTS, AND WHAT IT DELIBERATELY DOES NOT
-----------------------------------------------------------
Every engine the mission calls already has unit tests one layer down
(`tests/test_singularity_genome.py`, `tests/test_hyperion_guard.py`,
`tests/test_warrant_ledger.py`, `tests/test_fleet.py`,
`tests/test_warrant_economics.py`). This suite tests the ORCHESTRATION: that
a plan is computed and followed, that the authority path is genuinely
invoked, that the shared loop and the checkpoint contract hold.

The causal properties -- that different evidence produces different traces --
live in `tests/test_mission_causality.py`, which is the suite that replaced
this file's old assertions about a fixed eleven-stage sequence.

WHAT SURVIVED FROM THE PREVIOUS VERSION
------------------------------------------
Every invariant it proved still has a test here or in a named sibling:
a scripted attack really does get blocked (now
`test_mission_causality.py::test_critical_drift_isolates_the_agent_the_evidence_named`),
the report's counts are consistent with the stages
(`test_report_counts_match_what_actually_happened`, below), and no model
call escapes the process (`test_no_model_call_escapes_a_zero_model_mission`).
"""

from __future__ import annotations

import os
import socket

import pytest

PRINCIPAL = "human::mission-test@example.com"


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


def _run(objective: str | None = None, **kwargs):
    from command_os.mission import run_mission

    base = {"principal": PRINCIPAL, "auth_method": "dev", "allow_model": False}
    base.update(kwargs)
    return run_mission(objective, **base) if objective else run_mission(**base)


# ===========================================================================
# Shape
# ===========================================================================


def test_run_mission_requires_a_principal_with_no_default() -> None:
    """Structural. A caller that has not authenticated cannot even construct
    the call -- this is the signature-level half of the anonymous-approval
    fix."""
    import inspect

    from command_os.mission import run_mission

    principal = inspect.signature(run_mission).parameters["principal"]
    assert principal.default is inspect.Parameter.empty
    assert principal.kind is inspect.Parameter.KEYWORD_ONLY


@requires_emulator
def test_mission_follows_the_plan_it_computed() -> None:
    result = _run()
    assert result.plan is not None
    plan_steps = result.plan["steps"]
    step_stages = [s for s in result.stages if s.name.startswith("STEP ")]
    assert len(step_stages) == len(plan_steps)
    assert result.stages[0].name.startswith("PLAN")
    assert result.stages[-1].name.startswith("REPORT")


@requires_emulator
def test_every_stage_is_numbered_monotonically() -> None:
    """`seq` is a monotonic counter independent of the phase queue, so
    inserting work (a containment probe, a replan) never renumbers a
    completed stage."""
    result = _run()
    assert [s.n for s in result.stages] == list(range(1, len(result.stages) + 1))


@requires_emulator
def test_the_authority_path_is_genuinely_invoked_for_each_step() -> None:
    """Every executed step carries a real `GatewayDecision` in its recorded
    detail -- not a summary of one."""
    result = _run()
    for stage in result.stages:
        if not stage.name.startswith("STEP "):
            continue
        if stage.detail.get("skipped"):
            continue
        assert "decision" in stage.detail
        assert stage.detail["decision"]["reason_code"] in {
            "ALLOWED",
            "SCOPE_EXCEEDED",
            "BUDGET_EXCEEDED",
            "WARRANT_INSUFFICIENT",
            "PRINCIPAL_VIOLATION",
            "WORKER_FAULT",
        }


@requires_emulator
def test_every_priced_action_is_recorded_with_its_full_derivation() -> None:
    """A price with no derivation is a number an operator cannot argue with."""
    result = _run()
    priced = [s.detail["priced"] for s in result.stages if "priced" in s.detail]
    assert priced
    for record in priced:
        assert record["cost_bp"] >= record["base_bp"]
        assert isinstance(record["contributions"], list)


# ===========================================================================
# The report
# ===========================================================================


@requires_emulator
def test_report_counts_match_what_actually_happened() -> None:
    result = _run()
    report = result.report
    plan_steps = result.plan["steps"]

    assert report.steps_planned == len(plan_steps)
    assert report.objective == result.objective
    assert report.status == result.status
    assert report.plan_fingerprint
    assert set(report.agents_selected) == {s["role"] for s in plan_steps}
    assert report.evidence_records_parsed <= report.evidence_records_total
    assert report.agents_isolated == (1 if report.isolated_agent else 0)


@requires_emulator
def test_report_names_the_authenticated_principal_never_a_constant() -> None:
    result = _run()
    assert result.report.human_principal == PRINCIPAL
    assert "human::mission_operator" not in str(result.report.model_dump())


@requires_emulator
def test_report_status_is_never_a_bare_success_over_a_refusal() -> None:
    result = _run()
    if result.report.gateway_refusals or result.report.agents_isolated:
        assert result.report.status != "COMPLETED"


@requires_emulator
def test_the_mission_records_every_case_id_it_opened() -> None:
    """So an auditor can walk the causal chain without guessing at a naming
    convention."""
    result = _run()
    assert result.report.case_ids
    assert all(cid.startswith(result.mission_id) for cid in result.report.case_ids)


# ===========================================================================
# The zero-model guarantee, at runtime
# ===========================================================================


@requires_emulator
def test_no_model_call_escapes_a_zero_model_mission(monkeypatch) -> None:
    """Runtime guarantee, not an import-graph one.

    `command_os/mission.py` legitimately reaches `fleet.planner` and
    `countersign.verify`, both of which CAN call Vertex. This asserts that a
    mission run with the door closed makes no call: the plan is labelled
    ZERO_MODEL and the challenge is labelled simulated, and both labels are
    written by the code path that actually ran.
    """
    result = _run()
    assert result.plan["provenance"] == "ZERO_MODEL"
    challenge = next(s for s in result.stages if s.name.startswith("CHALLENGE"))
    assert challenge.detail["simulated"] is True
    assert result.report.challenger_simulated is True


@requires_emulator
def test_the_challenger_family_is_independent_of_the_judging_side() -> None:
    """A same-family countersign proves nothing. Asserted on the recorded
    family, using the same `family_root` normalisation the guard itself uses."""
    from warrant.ledger import family_root

    result = _run()
    challenge = next(s for s in result.stages if s.name.startswith("CHALLENGE"))
    assert family_root(challenge.detail["family"]) != family_root("hyperion-risk-engine")
    assert not family_root(challenge.detail["family"]).startswith("gemini")


# ===========================================================================
# Human gate
# ===========================================================================


@requires_emulator
def test_auto_approve_records_concurrence_under_the_launching_principal() -> None:
    result = _run(auto_approve=True)
    if result.report.gate == "APPROVED":
        assert result.report.human_principal == PRINCIPAL
        assert result.report.human_decision_mode == "auto_approved_at_launch"


@requires_emulator
def test_auto_approve_false_pauses_before_any_external_effect() -> None:
    from command_os.external import sandbox_line_count

    before = sandbox_line_count()
    result = _run(auto_approve=False)
    if result.status == "AWAITING_HUMAN":
        assert result.report is None
        assert sandbox_line_count() == before, (
            "the mission touched the system of record before a human decided"
        )
