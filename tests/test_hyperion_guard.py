"""`evaluate_with_hyperion`: real Gateway enforcement, unchanged, plus a
real, durable, append-only log of what it decided.

Needs the Firestore emulator (`make emulator`) -- the same
`requires_emulator` skip pattern `tests/test_tower_gateway.py` already uses,
since `evaluate_gateway`'s warrant check now reads the live ledger.
"""

from __future__ import annotations

import os
import socket
import uuid

import pytest

from hyperion.guard import evaluate_with_hyperion
from hyperion.immune_memory import aggregate_fleet_summary
from hyperion.immune_memory import reset_for_test as reset_hyperion
from hyperion.schema import RiskLevel
from tower.gateway import evaluate_gateway
from tower.registry import make_entry
from tower.registry import reset_for_test as reset_registry
from tower.schema import GatewayReasonCode


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


def _agent(agent_id: str, *, warrant_spend_schedule: dict[str, int] | None = None):
    return make_entry(
        agent_id,
        capabilities=["extract"],
        max_budget=50,
        authority_scope=["claim.read"],
        data_scope=[],
        risk_class_thresholds={"LOW": 50, "HIGH": 5},
        warrant_spend_schedule=warrant_spend_schedule or {},
    )


def _fund(agent, *, risk_class: str, amount_bp: int = 1000) -> None:
    """Seed enough LIVE warrant that the Gateway's real warrant check
    reaches ALLOWED, the same synthetic-seed path
    `tests/test_tower_gateway.py::test_all_checks_pass_reaches_allowed` uses
    -- a cold-start agent refuses WARRANT_INSUFFICIENT by construction
    (`warrant/ledger.py:DEFAULT_SPEND_COST_BP`), so a test that expects
    ALLOWED past the warrant check must fund it first."""
    from warrant.ledger import EventKind, write_synthetic_seed_event

    write_synthetic_seed_event(
        principal=agent.principal,
        capability="extract",
        risk_class=risk_class,
        kind=EventKind.MINT,
        amount_bp=amount_bp,
        case_id=None,
        reason="test fixture: funded for the ALLOWED path",
        at=agent.registered_at,
    )


@pytest.fixture(autouse=True)
def _clean_state():
    if _emulator_up():
        reset_registry()
        reset_hyperion()
    yield
    if _emulator_up():
        reset_registry()
        reset_hyperion()


@requires_emulator
def test_wrapper_returns_the_same_decision_the_real_gateway_would() -> None:
    agent = _agent(f"gw_agent_{uuid.uuid4().hex[:6]}", warrant_spend_schedule={"LOW": 100})
    from tower.registry import put_agent

    put_agent(agent)
    _fund(agent, risk_class="LOW", amount_bp=1000)

    direct = evaluate_gateway(
        agent,
        task="in-scope read",
        requested_scope=["claim.read"],
        requested_cost=1,
        risk_class="LOW",
        capability="extract",
        case_id="direct_case",
    )
    wrapped, _assessment = evaluate_with_hyperion(
        agent,
        task="in-scope read (second call)",
        requested_scope=["claim.read"],
        requested_cost=1,
        risk_class="LOW",
        capability="extract",
        case_id="wrapped_case",
    )
    assert direct.reason_code == wrapped.reason_code == GatewayReasonCode.ALLOWED


@requires_emulator
def test_scope_exceeded_is_logged_and_scored_high() -> None:
    agent = _agent(f"gw_agent_{uuid.uuid4().hex[:6]}")
    from tower.registry import put_agent

    put_agent(agent)

    decision, assessment = evaluate_with_hyperion(
        agent,
        task="reach outside granted scope",
        requested_scope=["claim.confidential_terms"],
        requested_cost=1,
        risk_class="HIGH",
        capability="extract",
        case_id="scope_case",
    )
    assert decision.reason_code is GatewayReasonCode.SCOPE_EXCEEDED
    assert decision.allowed is False
    assert assessment.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL)


@requires_emulator
def test_fleet_summary_is_a_real_aggregate_over_logged_events() -> None:
    agent = _agent(f"gw_agent_{uuid.uuid4().hex[:6]}", warrant_spend_schedule={"LOW": 100})
    from tower.registry import put_agent

    put_agent(agent)
    _fund(agent, risk_class="LOW", amount_bp=1000)

    evaluate_with_hyperion(
        agent,
        task="nominal",
        requested_scope=["claim.read"],
        requested_cost=1,
        risk_class="LOW",
        capability="extract",
        case_id="agg_case_1",
    )
    evaluate_with_hyperion(
        agent,
        task="over scope",
        requested_scope=["claim.confidential_terms"],
        requested_cost=1,
        risk_class="HIGH",
        capability="extract",
        case_id="agg_case_2",
    )

    summary = aggregate_fleet_summary()
    assert summary["events_total"] == 2
    assert summary["threats_detected"] == 1
    assert summary["blocked_actions"] == 1
    assert summary["fleet_health_pct"] == 50.0
    assert agent.agent_id in {e["agent_id"] for e in summary["recent_events"]}


def test_empty_log_reports_honest_zeros_and_full_fleet_health(monkeypatch) -> None:
    """No emulator required: `aggregate_fleet_summary` over an empty log
    returns zeros and 100% health, never a fabricated placeholder number."""
    monkeypatch.setattr("hyperion.immune_memory.list_events", lambda: [])
    monkeypatch.setattr("tower.registry.list_agents", lambda: [])
    summary = aggregate_fleet_summary()
    assert summary["events_total"] == 0
    assert summary["threats_detected"] == 0
    assert summary["fleet_health_pct"] == 100.0
    assert summary["recent_events"] == []
