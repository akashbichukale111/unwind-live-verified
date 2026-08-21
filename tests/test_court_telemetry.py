"""3.12: a judge must be able to watch the court as a trace.

The brief names nine things that must carry a span: team formation, each plea,
each challenge, the ruling, the dissent, irreversibility triage, obligation
creation, approval routing, and load-rating adjustment. This test collects real
spans from an in-memory exporter and asserts each one appears -- a span that
exists only in a docstring is not observability, it is a claim.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from lib.schema import Conclusion, ConclusionKind, ExternalEffect, Reversibility, Source, SourceKind

NOW = datetime(2026, 7, 6, 9, 0, tzinfo=UTC)


@pytest.fixture
def spans():
    """Capture spans from the live tracer provider."""
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    import lib.telemetry as telemetry

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    previous = trace.get_tracer_provider()
    trace._TRACER_PROVIDER = provider  # noqa: SLF001
    telemetry._CONFIGURED = True  # noqa: SLF001
    try:
        yield exporter
    finally:
        trace._TRACER_PROVIDER = previous  # noqa: SLF001


def _names(exporter) -> set[str]:
    return {s.name for s in exporter.get_finished_spans()}


def _all_attributes(exporter) -> dict:
    merged = {}
    for span in exporter.get_finished_spans():
        merged.update(dict(span.attributes or {}))
    return merged


def test_the_whole_court_is_visible_as_a_trace(spans) -> None:
    from court.owners import CommitmentOwner
    from court.protocol import Brief, Notice, run_repair
    from court.team import form_team
    from judgment.model import ScriptedT2Model

    class _V:
        def __init__(self, cid):
            self.conclusion_id = cid
            self.depth = 1
            self.exposure = 1.0

    class _R:
        claim_id = "clm_x"

        def __init__(self, cids):
            self._a = [_V(c) for c in cids]

        @property
        def radius(self):
            return {v.conclusion_id: v for v in self._a}

        def alerts(self):
            return self._a

    cids = ["cnc_0001", "cnc_0002"]
    team = form_team(_R(cids), "rep", lambda c: f"principal_{c}")
    run_repair(
        notice=Notice(
            claim_id="clm_x",
            old_value=20,
            new_value=29,
            reason="test",
            briefs={
                c: Brief(
                    c, f"principal_{c}", shock_days=9, slack_days=8, contested_resource="line-3"
                )
                for c in cids
            },
        ),
        team=team,
        owners=[
            CommitmentOwner(
                owner_id=f"principal_{c}",
                conclusion_id=c,
                committed_lead_days=20,
                available_evidence=["committed_lead_days=20"],
            )
            for c in cids
        ],
        model=ScriptedT2Model(),
        now=NOW,
    )

    names = _names(spans)
    assert any("team-formation" in n for n in names), "team formation is not traced"
    assert any("court-turn-2-plea" in n for n in names), "the plea turn is not traced"
    assert any("court-turn-3-challenge" in n for n in names), "the challenge turn is not traced"
    assert any("court-turn-4-ruling" in n for n in names), "the ruling is not traced"
    assert any("four_turn_protocol" in n for n in names), "the protocol gate is not traced"
    # Each owner's own decision span, so a judge can see N parties, not one blob.
    # Spans are named "<kind>:<id>", so an owner's is "agent_decision:principal_...".
    assert sum(1 for n in names if n.startswith("agent_decision:principal_cnc_")) == 2

    attrs = _all_attributes(spans)
    assert "unwind.team_size" in attrs
    assert "unwind.dissent_count" in attrs, "dissent is not visible in the trace"
    assert "unwind.plea_stance" in attrs
    assert "unwind.turns_used" in attrs
    assert "unwind.budget_spent" in attrs


def test_settlement_steps_are_traced(spans) -> None:
    from settle.broker import ApprovalBroker
    from settle.loadrating import ledger_for
    from settle.obligation import build_obligation

    conclusion = Conclusion(
        conclusion_id="cnc_test",
        kind=ConclusionKind.ORDER,
        body="b",
        decided_at=NOW,
        owner_principal="principal_01",
        premise_ids=["clm_000000"],
        external_effects=[
            ExternalEffect(
                connector="email",
                op="send_quote",
                ref="e-1",
                reversibility=Reversibility.IDEMPOTENT,
                occurred_at=NOW,
            )
        ],
        committed_lead_days=20,
    )
    drafted = build_obligation(
        conclusion=conclusion,
        obligation_id="obl_1",
        old_summary="old",
        new_summary="new",
        correction_text="text",
    )
    ApprovalBroker().request_signature(
        obligation=drafted.obligation, unrecoverable_count=0, now=NOW, why="test"
    )
    ledger = ledger_for(
        Source(
            source_id="src_supplier_K",
            name="K",
            kind=SourceKind.SUPPLIER_EMAIL,
            authority=["supplier_K."],
        ),
        at=NOW,
    )
    ledger.falsified(at=NOW, claim_id="clm_000000", reason="false")

    names = _names(spans)
    assert any("irreversibility_triage" in n for n in names), "triage is not traced"
    assert any("correction-obligation" in n for n in names), "obligation creation is not traced"
    assert any("counterparty-cartographer" in n for n in names), "cartography is not traced"
    assert any("approval-broker" in n for n in names), "approval routing is not traced"
    assert any("load-rating" in n for n in names), "load-rating adjustment is not traced"

    attrs = _all_attributes(spans)
    assert "unwind.rating_before" in attrs and "unwind.rating_after" in attrs
    assert "unwind.exposure_low" in attrs and "unwind.exposure_high" in attrs
