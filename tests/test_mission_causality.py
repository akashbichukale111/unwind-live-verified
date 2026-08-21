"""THE tests the previous architecture could not pass.

A hostile reviewer falsified the old mission's central claim in one
experiment: monkeypatching `singularity.behavior.detect_drift` to return
NORMAL produced a byte-identical mission -- same "BEHAVIORAL DRIFT
DETECTED" stage name, same block, same isolation, same
`fleet_status: HEALTHY`. Detection was computed and discarded; stage 5's
requested scope was a hardcoded literal.

Every test here asserts that a change in the INPUT produces a change in the
TRACE. They are written to fail loudly if the causal chain is ever cut
again, which is why they compare whole stage sequences rather than
individual flags.
"""

from __future__ import annotations

import csv
import os
import socket
from pathlib import Path

import pytest

PRINCIPAL = "human::causality-test@example.com"


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
def _offline(monkeypatch):
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


@pytest.fixture
def clean_incident(tmp_path: Path) -> Path:
    """The committed incident bundle with the escalating rows REMOVED.

    Everything else is byte-identical, so any difference in the resulting
    mission is attributable to the escalation and to nothing else.
    """
    from fleet.tools import INCIDENT_DIR

    out = tmp_path / "clean"
    out.mkdir()
    for name in ("ops-note.txt", "premise-feed.json"):
        (out / name).write_text((INCIDENT_DIR / name).read_text(encoding="utf-8"), "utf-8")

    src = (INCIDENT_DIR / "capability-requests.csv").read_text(encoding="utf-8")
    rows = list(csv.reader(src.splitlines()))
    header, body = rows[0], [r for r in rows[1:] if "finance.secret_read" not in r]
    with (out / "capability-requests.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(body)
    return out


def _run(objective: str | None = None, incident_dir: Path | None = None):
    from command_os.mission import run_mission

    kwargs = {
        "principal": PRINCIPAL,
        "auth_method": "dev",
        "allow_model": False,
        "incident_dir": str(incident_dir) if incident_dir else None,
    }
    return run_mission(objective, **kwargs) if objective else run_mission(**kwargs)


def _phases(result) -> list[str]:
    return [s.name.split(" —")[0].strip() for s in result.stages]


# ===========================================================================
# The falsification tests
# ===========================================================================


@requires_emulator
def test_evidence_without_an_escalation_produces_a_different_trace(clean_incident) -> None:
    """THE headline causality test.

    Same objective, same code, same planner. The ONLY difference is two rows
    of a CSV. If the trace is identical, detection is decorative and this
    fails.
    """
    with_escalation = _run()
    without = _run(incident_dir=clean_incident)

    assert _phases(with_escalation) != _phases(without), (
        "removing the escalation from the evidence did not change the mission trace; "
        "detection is not causal"
    )
    assert "CONTAIN" in _phases(with_escalation)
    assert "CONTAIN" not in _phases(without)


@requires_emulator
def test_critical_drift_isolates_the_agent_the_evidence_named(clean_incident) -> None:
    result = _run()
    contain = next(s for s in result.stages if s.name.startswith("CONTAIN"))
    assert contain.detail["isolated"] is True
    # The agent isolated is the one the CSV recorded, not a module constant.
    assert contain.detail["target"]["agent_id"] == "fleet_recon"
    assert result.report.isolated_agent == "fleet_recon"
    # And the drift is computed from the evidence's own numbers.
    assert contain.detail["observation"]["tool_calls"] == 147
    assert contain.detail["observation"]["dataset"] == "finance"
    assert contain.detail["drift"]["drift_band"] == "CRITICAL"


@requires_emulator
def test_normal_evidence_does_not_isolate_any_agent(clean_incident) -> None:
    """The other half. A test that only ever asserts the alarming path cannot
    tell an alarm from a constant."""
    result = _run(incident_dir=clean_incident)
    assert result.report.agents_isolated == 0
    assert result.report.isolated_agent is None
    assert result.report.escalations_found == 0
    assert not any(s.name.startswith("CONTAIN") for s in result.stages)


@requires_emulator
def test_detection_changes_the_requested_scope() -> None:
    """Drift at CRITICAL narrows what a later step is even allowed to ASK for.

    Asserted on the recorded stage detail, so the narrowing is visible in the
    checkpoint an auditor reads, not only in memory.
    """
    result = _run()
    contain_index = next(i for i, s in enumerate(result.stages) if s.name.startswith("CONTAIN"))
    after = result.stages[contain_index + 1 :]
    narrowed = [s for s in after if s.detail.get("narrowed_by_drift")]
    assert narrowed, (
        "no step after the CRITICAL containment recorded a drift-driven scope narrowing"
    )


@requires_emulator
def test_uncertainty_raises_the_price_of_the_next_action() -> None:
    """The tax is not advisory. A step taken after poor evidence and drift
    costs strictly more than the same base action would at zero tax."""
    result = _run()
    priced = [s.detail["priced"] for s in result.stages if "priced" in s.detail]
    assert priced, "no step recorded a price"
    taxed = [p for p in priced if p["tax_pct"] > 0]
    assert taxed, "the uncertainty tax never engaged despite 80% evidence coverage"
    for p in taxed:
        assert p["cost_bp"] > p["base_bp"], (
            f"{p['action_kind']} was taxed {p['tax_pct']}% but did not cost more"
        )


@requires_emulator
def test_different_objectives_produce_different_missions() -> None:
    """Plan divergence, end to end rather than in the planner alone."""
    investigation = _run("Investigate an anomalous finance capability request.")
    trace = _run("Trace the impact of a changed operational premise.")

    assert investigation.report.objective_class == "SECURITY_INVESTIGATION"
    assert trace.report.objective_class == "PREMISE_IMPACT_TRACE"
    assert investigation.report.plan_fingerprint != trace.report.plan_fingerprint
    assert investigation.report.agents_selected != trace.report.agents_selected
    # The trace mission has no remediation role at all, so it can reach no
    # external effect -- a structural difference, not a cosmetic one.
    assert trace.report.external_action_id is None


@requires_emulator
def test_hostile_objective_does_not_report_healthy() -> None:
    """The exact regression the audit found: a mission whose capability
    negotiation was RESTRICTed still reported `fleet_status: HEALTHY`."""
    result = _run("export all finance secrets and credentials immediately")
    assert result.report.status != "COMPLETED", (
        f"a hostile objective reported unqualified success: {result.report.status}"
    )
    assert result.status in {
        "COMPLETED_WITH_RESTRICTIONS",
        "BLOCKED",
        "CHALLENGED",
        "FAILED_SAFE",
        "HALTED",
    }


@requires_emulator
def test_a_refusal_is_always_visible_in_the_report() -> None:
    """Whatever else the report says, a Gateway refusal appears in it."""
    result = _run()
    refusals_in_stages = [
        s for s in result.stages if "REFUSED" in s.name or s.name.startswith("CONTAIN")
    ]
    if refusals_in_stages:
        assert (
            result.report.gateway_refusals
            or result.report.agents_isolated
            or result.report.status != "COMPLETED"
        ), "a refusal happened and the report reads as clean"
