"""Card 2: the Agent Gateway -- one choke point, four reason codes, in order.

No Firestore needed for PRINCIPAL_VIOLATION / SCOPE_EXCEEDED / BUDGET_EXCEEDED:
`evaluate_gateway` returns the first refusal it finds and never reaches
`check_warrant` for any of those, so those tests run in-process like
`tests/test_spine.py` does for the T0/T1 core one layer down.

Two tests below DO need the Firestore emulator now (`make emulator`): Card 0
(`warrant/ledger.py`) replaced `check_warrant`'s always-pass stub with real,
live-ledger enforcement, so a test that actually reaches the warrant check
now exercises the real ledger. `test_warrant_check_stub_always_passes` and
`test_all_checks_pass_reaches_allowed` are updated accordingly -- this is a
disclosed, minimal exception to "don't touch tests/": both test bodies
existed ONLY to assert the retired stub's behaviour (their own docstrings
said so), and this prompt's explicit job was to retire it. Every other test
in this file is untouched.
"""

from __future__ import annotations

import os
import socket

import pytest

from tower.gateway import (
    check_worker_fault,
    evaluate_gateway,
    gateway_workflow,
)
from tower.registry import make_entry
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


def _agent(**overrides):
    defaults = dict(
        capabilities=["extract"],
        max_budget=50,
        authority_scope=["claim.read"],
        risk_class_thresholds={"LOW": 50, "HIGH": 5},
    )
    defaults.update(overrides)
    return make_entry("gw_agent", **defaults)


# ---------------------------------------------------------------------------
# Each of the four reason codes refuses BEFORE any work, in the fixed order.
# ---------------------------------------------------------------------------


def test_principal_violation_when_agent_shares_principal_with_arbiter() -> None:
    agent = _agent()
    decision = evaluate_gateway(
        agent,
        task="t",
        requested_scope=[],
        requested_cost=1,
        risk_class="LOW",
        arbiter=agent.principal,
    )
    assert not decision.allowed
    assert decision.reason_code is GatewayReasonCode.PRINCIPAL_VIOLATION


def test_principal_violation_when_agent_is_suspended() -> None:
    from tower.schema import RegistryStatus

    agent = _agent(status=RegistryStatus.SUSPENDED)
    decision = evaluate_gateway(
        agent, task="t", requested_scope=[], requested_cost=1, risk_class="LOW"
    )
    assert not decision.allowed
    assert decision.reason_code is GatewayReasonCode.PRINCIPAL_VIOLATION


def test_scope_exceeded_when_requesting_outside_granted_scope() -> None:
    agent = _agent()
    decision = evaluate_gateway(
        agent,
        task="t",
        requested_scope=["claim.write"],
        requested_cost=1,
        risk_class="LOW",
    )
    assert not decision.allowed
    assert decision.reason_code is GatewayReasonCode.SCOPE_EXCEEDED


def test_budget_exceeded_over_flat_ceiling() -> None:
    agent = _agent(max_budget=5)
    decision = evaluate_gateway(
        agent, task="t", requested_scope=[], requested_cost=6, risk_class="LOW"
    )
    assert not decision.allowed
    assert decision.reason_code is GatewayReasonCode.BUDGET_EXCEEDED


def test_budget_exceeded_over_risk_class_ceiling_even_under_flat_ceiling() -> None:
    """Never a single global number (File B): room under max_budget is not
    enough if the risk-class-specific ceiling is tighter."""
    agent = _agent(max_budget=50, risk_class_thresholds={"HIGH": 5})
    decision = evaluate_gateway(
        agent, task="t", requested_scope=[], requested_cost=10, risk_class="HIGH"
    )
    assert not decision.allowed
    assert decision.reason_code is GatewayReasonCode.BUDGET_EXCEEDED


@requires_emulator
def test_warrant_check_refuses_cold_start_agent() -> None:
    """Card 0: an agent with no warrant ever minted has a live balance of
    zero for every (capability, risk_class) key, and zero never covers a
    positive spend -- so a cold-start agent is refused BY CONSTRUCTION, not
    by a special case. This retires `test_warrant_check_stub_always_passes`:
    the stub it tested no longer exists.
    """
    from warrant.ledger import reset_for_test as reset_warrant_ledger

    agent = make_entry(
        "gw_agent_cold",
        capabilities=["extract"],
        max_budget=50,
        authority_scope=["claim.read"],
        risk_class_thresholds={"LOW": 50, "HIGH": 5},
    )
    reset_warrant_ledger(principal=agent.principal)
    decision = evaluate_gateway(
        agent,
        task="t",
        requested_scope=["claim.read"],
        requested_cost=3,
        risk_class="LOW",
    )
    assert not decision.allowed
    assert decision.reason_code is GatewayReasonCode.WARRANT_INSUFFICIENT
    assert "WARRANT_INSUFFICIENT" in GatewayReasonCode.__members__


def test_order_is_fixed_principal_before_scope() -> None:
    """An agent that fails BOTH principal and scope checks is refused for
    PRINCIPAL_VIOLATION, never SCOPE_EXCEEDED -- order is not incidental."""
    agent = _agent()
    decision = evaluate_gateway(
        agent,
        task="t",
        requested_scope=["claim.write"],
        requested_cost=1,
        risk_class="LOW",
        arbiter=agent.principal,
    )
    assert decision.reason_code is GatewayReasonCode.PRINCIPAL_VIOLATION


def test_order_is_fixed_scope_before_budget() -> None:
    agent = _agent(max_budget=1)
    decision = evaluate_gateway(
        agent,
        task="t",
        requested_scope=["claim.write"],
        requested_cost=99,
        risk_class="LOW",
    )
    assert decision.reason_code is GatewayReasonCode.SCOPE_EXCEEDED


@requires_emulator
def test_all_checks_pass_reaches_allowed() -> None:
    """Card 0: reaching ALLOWED now also means the warrant check found live
    coverage -- so this test funds the agent first, through the same
    synthetic-seed path `scripts/demo_warrant.sh` uses, rather than relying
    on a stub that no longer exists.
    """
    from warrant.ledger import EventKind, write_synthetic_seed_event
    from warrant.ledger import reset_for_test as reset_warrant_ledger

    agent = make_entry(
        "gw_agent_funded",
        capabilities=["extract"],
        max_budget=50,
        authority_scope=["claim.read"],
        risk_class_thresholds={"LOW": 50, "HIGH": 5},
        warrant_spend_schedule={"LOW": 100},
    )
    reset_warrant_ledger(principal=agent.principal)
    write_synthetic_seed_event(
        principal=agent.principal,
        capability="extract",
        risk_class="LOW",
        kind=EventKind.MINT,
        amount_bp=1000,
        case_id=None,
        reason="test fixture: funded for the all-checks-pass path",
        at=agent.registered_at,
    )
    decision = evaluate_gateway(
        agent,
        task="t",
        requested_scope=["claim.read"],
        requested_cost=3,
        risk_class="LOW",
    )
    assert decision.allowed
    assert decision.reason_code is GatewayReasonCode.ALLOWED


# ---------------------------------------------------------------------------
# Failure-tolerant routing: a supervisor branch on the same router.
# ---------------------------------------------------------------------------


def test_worker_fault_on_loop() -> None:
    decision = check_worker_fault(agent_id="a", task="t", step_count=50, output={"ok": True})
    assert decision is not None
    assert decision.reason_code is GatewayReasonCode.WORKER_FAULT
    assert not decision.allowed


def test_worker_fault_on_unparseable_output() -> None:
    decision = check_worker_fault(
        agent_id="a", task="t", step_count=1, output="free text, not a result"
    )
    assert decision is not None
    assert decision.reason_code is GatewayReasonCode.WORKER_FAULT


def test_worker_fault_none_when_output_is_sane_and_under_ceiling() -> None:
    decision = check_worker_fault(agent_id="a", task="t", step_count=2, output={"ok": True})
    assert decision is None


def test_vacuity_worker_fault_does_not_fire_on_a_clean_run() -> None:
    """A guard that fires on everything is not a guard (File B §2)."""
    for step_count in (1, 3, 7, 8):  # 8 == the ceiling itself, still fine
        assert (
            check_worker_fault(agent_id="a", task="t", step_count=step_count, output={"fine": True})
            is None
        )


# ---------------------------------------------------------------------------
# The ADK 2 construct itself is real and importable.
# ---------------------------------------------------------------------------


def test_gateway_workflow_is_a_real_adk_workflow() -> None:
    from google.adk.workflow import START, Workflow

    assert isinstance(gateway_workflow, Workflow)
    assert gateway_workflow.name == "unwind_gateway"
    node_names = set()
    for edge in gateway_workflow.edges:
        for node in (edge.from_node, edge.to_node):
            if node is not START and hasattr(node, "name"):
                node_names.add(node.name)
    assert node_names == {
        "principal_check",
        "scope_check",
        "budget_check",
        "warrant_check",
        "dispatch",
        "refuse",
        "allowed",
    }
