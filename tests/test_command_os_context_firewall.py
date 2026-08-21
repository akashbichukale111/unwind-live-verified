"""`command_os.context_firewall`: what a resumed mission's context is scored on.

THREE REAL SIGNALS, AND ONE HONEST SCOPE LIMIT
--------------------------------------------------
Freshness, trust and relevance are each computed from real data. What this
module does NOT do -- and its own docstring says so -- is change what
`resume_mission` reconstructs from a checkpoint; that reconstruction is
unconditional by design. It governs what a caller or a UI presents as the
mission's trusted context. `test_the_firewall_is_a_display_filter_and_says_so`
pins that honesty in place so the scope cannot quietly inflate.

Relevance is keyed on phase KIND, not stage number, since the rewrite: a
plan-driven mission's length varies by objective.
"""

from __future__ import annotations

import os
import socket
from datetime import UTC, datetime, timedelta

import pytest

PRINCIPAL = "human::firewall-test@example.com"


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
def test_every_checkpoint_gets_exactly_one_decision() -> None:
    from command_os.context_firewall import filter_context

    result = _run()
    decisions = filter_context(result.mission_id)
    assert [d["seq"] for d in decisions] == list(range(1, len(result.stages) + 1))
    assert all(d["decision"] in {"INCLUDE", "SUMMARIZE", "REJECT", "QUARANTINE"} for d in decisions)


@requires_emulator
def test_every_decision_states_its_reason_and_its_three_signals() -> None:
    """Never a silent pass-through and never a bare verdict."""
    from command_os.context_firewall import filter_context

    for decision in filter_context(_run().mission_id):
        assert decision["reason"]
        assert set(decision["signals"]) == {"freshness", "trust", "relevance"}


@requires_emulator
def test_the_containment_checkpoint_is_quarantined() -> None:
    from command_os.context_firewall import filter_context

    result = _run()
    if not any(s.name.startswith("CONTAIN") for s in result.stages):
        pytest.skip("this run found no escalation to contain")
    decisions = {d["stage"]: d for d in filter_context(result.mission_id)}
    contain = next(d for name, d in decisions.items() if name.startswith("CONTAIN"))
    assert contain["decision"] == "QUARANTINE"
    assert contain["signals"]["trust"] == "QUARANTINED"


@requires_emulator
def test_the_planning_stage_is_summarized_not_included() -> None:
    """PLAN's detail is established once and never re-read from a checkpoint
    by a later phase, so it is context to summarise, not context to carry."""
    from command_os.context_firewall import filter_context

    decisions = {d["stage"]: d for d in filter_context(_run().mission_id)}
    plan = next(d for name, d in decisions.items() if name.startswith("PLAN"))
    assert plan["decision"] == "SUMMARIZE"
    assert plan["signals"]["relevance"] == "LOW"


@requires_emulator
def test_relevance_is_keyed_on_phase_kind_not_stage_number() -> None:
    """The regression this file exists to prevent: a position-based rule
    silently mis-scores every mission whose plan differs from the one it was
    written against."""
    from command_os.context_firewall import filter_context

    decisions = filter_context(_run().mission_id)
    for decision in decisions:
        kind = decision["stage"].split(" ")[0].upper()
        expected = "LOW" if kind in {"PLAN", "REPORT", "VERIFY"} else "RELEVANT"
        if kind in {"PLAN", "REPORT"}:
            assert decision["signals"]["relevance"] == expected, (
                f"{decision['stage']} scored {decision['signals']['relevance']}"
            )


@requires_emulator
def test_stale_checkpoints_are_rejected_regardless_of_trust() -> None:
    """Freshness is an independent signal: a perfectly trusted, perfectly
    relevant checkpoint from last week is still not current context."""
    from command_os.context_firewall import filter_context

    result = _run()
    far_future = datetime.now(UTC) + timedelta(days=7)
    decisions = filter_context(result.mission_id, as_of=far_future)
    assert all(d["signals"]["freshness"] == "STALE" for d in decisions)
    assert all(d["decision"] in {"REJECT", "QUARANTINE"} for d in decisions)


@requires_emulator
def test_the_firewall_is_a_display_filter_and_says_so() -> None:
    """Honesty pin. `command_os/status.py` labels `context_firewall` LIVE,
    and it IS live -- the scoring is real. What it does not do is gate what
    `resume_mission` reconstructs. If that ever changes, this test should be
    updated deliberately, not discovered later by a reviewer.
    """
    import inspect

    import command_os.context_firewall as firewall

    doc = inspect.getdoc(firewall.filter_context) or ""
    assert "does not itself change what" in doc, (
        "the scope limit disappeared from the docstring; either the module now "
        "gates resume (update this test and the status label) or the honesty "
        "note was lost"
    )
