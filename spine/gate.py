"""The confidence gate: render what was understood, before acting on it.

Before a cascade runs, the system says back what it thinks it was told:

    Read as: supplier_K.lead_time_days  11 → 20 days
    Source:  Kestrel Components GmbH (src_supplier_K) · confidence 0.94
    Affects: clm_000000, carrying 2,594 dependent commitments
    Decision: ASK_HUMAN — a mass unwind at this scale gets a signature

A MISPARSE MUST RENDER AS A QUESTION, NEVER AS A FAILURE
--------------------------------------------------------
The failure mode this exists to prevent is not "the system got it wrong". It is
"the system got it wrong and did it anyway, and the first anyone knew was the
customer email". An echo-back turns a parsing error from an incident into a
sentence somebody reads and says "no, that's not what we meant".

Showing a retraction the system refuses to make is worth more than any
successful cascade, so the gate renders REFUSE and DEFER in exactly the same
shape as EXECUTE. The states differ; the rendering does not.

API-level here. The UI lands in Task 5, and it renders this structure.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from lib.config import Tier
from lib.schema import Claim, DecisionState, Source, StatedDecision
from lib.telemetry import policy_gate_span

#: States where the echo-back is a confirmation prompt rather than a notice.
NEEDS_ANSWER: frozenset[DecisionState] = frozenset({DecisionState.ASK_HUMAN, DecisionState.DEFER})


@dataclass
class EchoBack:
    """What the system understood, in the shape a person can disagree with."""

    read_as: str
    source_line: str
    affects_line: str
    decision_line: str
    state: DecisionState
    #: True when this is a question awaiting an answer, not a statement of fact.
    awaiting_answer: bool
    #: Anything the system could not determine. Rendered, never omitted.
    unresolved: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def render(self) -> str:
        lines = [
            f"Read as: {self.read_as}",
            f"Source:  {self.source_line}",
            f"Affects: {self.affects_line}",
            f"Decision: {self.decision_line}",
        ]
        for item in self.unresolved:
            lines.append(f"UNRESOLVED: {item}")
        for warning in self.warnings:
            lines.append(f"⚠ {warning}")
        if self.awaiting_answer:
            lines.append("→ Is this right? Nothing has been sent.")
        return "\n".join(lines)

    def to_json(self) -> dict[str, Any]:
        return {
            "read_as": self.read_as,
            "source": self.source_line,
            "affects": self.affects_line,
            "decision": self.decision_line,
            "state": self.state.value,
            "awaiting_answer": self.awaiting_answer,
            "unresolved": list(self.unresolved),
            "warnings": list(self.warnings),
            "rendered": self.render(),
        }


def echo_back(
    claim: Claim | None,
    source: Source | None,
    new_value: Any,
    decision: StatedDecision,
    blast_radius: int,
    confidence: float,
    unresolved: list[str] | None = None,
    warnings: list[str] | None = None,
) -> EchoBack:
    """Render the understanding. Never raises: an unrenderable input is a question."""
    with policy_gate_span("confidence_gate", Tier.T0) as span:
        if claim is None:
            read_as = (
                "A retraction was proposed against a claim this system cannot "
                "find. Nothing was understood."
            )
            unit = ""
        else:
            unit = f" {claim.unit}" if claim.unit else ""
            read_as = f"{claim.canonical}  {_short(claim.value)} → {_short(new_value)}{unit}"

        if source is None:
            source_line = "unknown source · confidence not established"
        else:
            source_line = (
                f"{source.name} ({source.source_id}) · confidence {confidence:.2f} "
                f"· load rating {source.load_rating:.2f}"
            )

        affects_line = (
            f"{claim.claim_id if claim else 'unknown claim'}, carrying "
            f"{blast_radius} dependent commitment"
            f"{'' if blast_radius == 1 else 's'}"
        )

        decision_line = f"{decision.state.value.upper()} — {decision.why}"

        rendered = EchoBack(
            read_as=read_as,
            source_line=source_line,
            affects_line=affects_line,
            decision_line=decision_line,
            state=decision.state,
            awaiting_answer=decision.state in NEEDS_ANSWER,
            unresolved=list(unresolved or []),
            warnings=list(warnings or []),
        )
        span.set_attribute("unwind.gate_state", decision.state.value)
        span.set_attribute("unwind.awaiting_answer", rendered.awaiting_answer)
        return rendered


def _short(value: Any) -> str:
    """Render a value briefly. A clause is quoted, not dumped."""
    if isinstance(value, str) and len(value) > 60:
        return f'"{value[:57]}…"'
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)
