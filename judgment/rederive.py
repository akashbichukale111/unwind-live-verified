"""The blind re-deriver. THE BLINDNESS IS THE POINT.

It recomputes what a decision *would* have been under the new premise value,
without ever seeing what the decision actually was. If it can see the original
conclusion it will anchor on it — it will read "quoted 14 days", be asked "what
would you quote?", and answer "14 days". Materiality scoring then compares 14 to
14, finds no change, and the whole tier silently reports that nothing was
harmed.

That failure is invisible. The numbers look fine. It is the single most
dangerous thing that can go wrong in this system, and no prompt instruction
prevents it, because a prompt instruction is a request.

HOW THE BLINDNESS IS ENFORCED, IN THREE LAYERS
-----------------------------------------------
1. TYPE. `re_derive()` accepts a `BlindPremiseBundle`, a frozen structure that
   has no field capable of holding a conclusion. There is nothing to pass.
2. ACCESS. `BlindStore` wraps a store and raises `BlindnessViolation` on
   `get_conclusion`. Anything in this module that reaches for the original dies
   loudly rather than quietly anchoring.
3. STATIC. `tests/test_blindness.py` walks this module's AST for conclusion
   access, AND runs the same guard against a fixture that deliberately violates
   it. If the guard passes the violating fixture, the guard is broken — which is
   exactly how a broken guard was caught in Task 2.

With GCP credentials the same boundary would be an IAM one: a service account
with no read permission on `conclusions/`. That is the production answer and it
is [UNVERIFIED] here. The three layers above hold without credentials.

TIMEOUT RENDERS UNRESOLVED, NEVER DARK
--------------------------------------
A re-derivation that times out has not shown the conclusion to be unharmed. It
has shown nothing. The node renders UNRESOLVED and is displayed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from judgment.model import ModelReply, T2Model
from lib.config import Tier
from lib.telemetry import agent_decision_span

#: The principal that re-derives. It must NOT be the principal that grades the
#: re-derivation -- see `judgment/assessor.py`.
REDERIVER_PRINCIPAL = "rederiver@0.3.0"

PURPOSE = "blind_rederivation"


class BlindnessViolation(RuntimeError):
    """The re-deriver reached for the conclusion it is supposed not to see."""


@dataclass(frozen=True)
class BlindPremiseBundle:
    """Everything the re-deriver is allowed to know. Note what is absent.

    There is no `conclusion`, no `body`, no `committed_lead_days`, and no
    `conclusion_id`-keyed payload. The bundle carries the DECISION TYPE and the
    PREMISES, which is what a person would need to redo the work from scratch,
    and nothing that would tell them what was decided last time.
    """

    #: What kind of decision to make (quote, order, plan…). Not what was decided.
    decision_kind: str
    #: The premises, as canonical -> value, at the NEW values.
    premises: tuple[tuple[str, Any], ...]
    #: Free context that has been checked to contain no prior decision.
    context: str = ""
    #: Opaque handle for correlation. Deliberately not resolvable to a
    #: conclusion by anything in this module.
    correlation_id: str = ""

    def as_prompt(self) -> str:
        premise_lines = "\n".join(f"  {name} = {value}" for name, value in self.premises)
        return (
            "Given only the premises below, state what commitment would be made.\n"
            f"Decision type: {self.decision_kind}\n"
            f"Premises:\n{premise_lines}\n"
            f"{self.context}\n"
            'Answer as JSON: {"committed_lead_days": <number or null>, '
            '"confidence": <0..1>, "reasoning": "<one sentence>"}'
        )


@dataclass
class ReDerivation:
    correlation_id: str
    #: None means the re-deriver could not determine it. Never coerced.
    committed_lead_days: float | None
    confidence: float
    reasoning: str
    derived_by: str = REDERIVER_PRINCIPAL
    unresolved_reason: str | None = None
    model_id: str = ""
    derived_at: datetime | None = None

    @property
    def resolved(self) -> bool:
        return self.committed_lead_days is not None and self.unresolved_reason is None


@dataclass
class BlindStore:
    """A store view with the conclusion door welded shut.

    Wraps any GraphStore. Claims and edges pass through; `get_conclusion` raises.
    Passing this to the re-derivation path means an accidental reach for the
    original is a loud failure at the moment it happens.
    """

    inner: Any
    #: Recorded so a violation is evidence, not just an exception in a log.
    violations: list[str] = field(default_factory=list)

    def get_claim(self, claim_id: str):
        return self.inner.get_claim(claim_id)

    def get_source(self, source_id: str):
        return self.inner.get_source(source_id)

    def direct_dependents(self, claim_id: str):
        return self.inner.direct_dependents(claim_id)

    def get_conclusion(self, conclusion_id: str):
        message = (
            f"The re-derivation path attempted to read conclusion "
            f"{conclusion_id!r}. Re-derivation is blind by construction: seeing "
            "the original decision would anchor the answer and make materiality "
            "scoring meaningless."
        )
        self.violations.append(message)
        raise BlindnessViolation(message)


def build_bundle(
    decision_kind: str,
    premises: dict[str, Any],
    correlation_id: str,
    context: str = "",
) -> BlindPremiseBundle:
    """Assemble a bundle. Sorted, so two identical premise sets prompt identically."""
    return BlindPremiseBundle(
        decision_kind=decision_kind,
        premises=tuple(sorted(premises.items())),
        context=context,
        correlation_id=correlation_id,
    )


def re_derive(bundle: BlindPremiseBundle, model: T2Model, now: datetime) -> ReDerivation:
    """Recompute the commitment from premises alone.

    Takes a bundle, not a store and not a conclusion id. The signature is the
    first layer of the blindness: there is no argument through which the original
    decision could arrive.
    """
    with agent_decision_span(REDERIVER_PRINCIPAL, Tier.T2) as span:
        span.set_attribute("unwind.correlation_id", bundle.correlation_id)
        reply: ModelReply = model.complete(bundle.as_prompt(), purpose=PURPOSE)

        if not reply.available:
            # Unavailable is not "unchanged". It is "we do not know".
            span.set_attribute("unwind.rederivation", "unresolved")
            return ReDerivation(
                correlation_id=bundle.correlation_id,
                committed_lead_days=None,
                confidence=0.0,
                reasoning="",
                unresolved_reason=(
                    f"Re-derivation could not run: {reply.reason_unavailable}. "
                    "This node is UNRESOLVED -- it has not been shown unharmed."
                ),
                model_id=reply.model,
                derived_at=now,
            )

        payload = reply.as_json()
        if payload is None or "committed_lead_days" not in payload:
            span.set_attribute("unwind.rederivation", "unparseable")
            return ReDerivation(
                correlation_id=bundle.correlation_id,
                committed_lead_days=None,
                confidence=0.0,
                reasoning="",
                unresolved_reason=(
                    "The re-derivation reply could not be parsed into a "
                    "commitment. Treated as UNRESOLVED rather than guessed at."
                ),
                model_id=reply.model,
                derived_at=now,
            )

        value = payload.get("committed_lead_days")
        span.set_attribute("unwind.rederivation", "resolved" if value is not None else "null")
        return ReDerivation(
            correlation_id=bundle.correlation_id,
            committed_lead_days=float(value) if value is not None else None,
            confidence=float(payload.get("confidence", 0.0)),
            reasoning=str(payload.get("reasoning", ""))[:400],
            model_id=reply.model,
            derived_at=now,
            unresolved_reason=(
                None
                if value is not None
                else "The re-deriver declined to state a commitment from these premises."
            ),
        )


def bundle_contains_decision(bundle: BlindPremiseBundle, needles: list[str]) -> list[str]:
    """Leak check: does anything in this bundle echo the original decision?

    Used by the vacuity test, and cheap enough to run in anger. A bundle whose
    `context` was assembled from the wrong place is the realistic way blindness
    breaks -- not a direct read, but a summary that quietly includes the answer.
    """
    haystack = json.dumps(
        {
            "kind": bundle.decision_kind,
            "premises": list(bundle.premises),
            "context": bundle.context,
        },
        default=str,
    ).lower()
    return [needle for needle in needles if needle and str(needle).lower() in haystack]
