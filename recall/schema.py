"""Typed models for the knowledge a completed mission leaves behind.

WHAT A KNOWLEDGE RECORD IS, AND WHAT IT DELIBERATELY IS NOT
--------------------------------------------------------------
It is ONE atomic operational fact, distilled from a mission that actually
ran, carrying enough provenance to answer three questions without a second
lookup:

    WHAT does the system believe?      `statement`, `subject`, `value`
    WHERE did that come from?          `mission_id`, `checkpoint_seq`,
                                       `agent_id`, `tool`, `source`
    HOW MUCH is it worth?              `standing`, `observed_at`

It is NOT a summary of a mission, and it is NOT a transcript. A summary is
unsearchable at the granularity a planner needs ("has anything ever escalated
scope for fleet_recon?") and a transcript is unbounded. Both are the shapes
that force a system to put its whole history into one prompt, which is the
thing `recall/index.py` exists to avoid.

`standing` IS THE FIELD THAT MAKES THIS SAFE
-----------------------------------------------
A record's standing says what it is allowed to influence, and there are only
three values. `OBSERVED` facts and `CAUTION` findings may raise scrutiny.
`UNTRUSTED` records may be read and displayed and may influence NOTHING --
they exist so that a record whose provenance failed a check is kept as
evidence rather than deleted, which would make an attack on the memory
invisible.

No standing anywhere in this vocabulary can widen authority. That is not a
convention: `recall/guard.py` enforces it, and it is asserted directly by
`tests/test_recall_guard.py::test_no_knowledge_record_can_widen_scope`.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=False)


class RecordKind(str, Enum):
    """Closed vocabulary. The planner and the retriever both filter on it, so
    a new kind is a code change in both, which is the point -- a free-text
    `kind` would make the filter a string match on whatever a writer felt
    like calling it."""

    #: A premise value the mission settled (two rules agreed).
    SETTLED_PREMISE = "SETTLED_PREMISE"
    #: A premise two rules DISAGREED about. Carries both candidate values.
    DISPUTED_PREMISE = "DISPUTED_PREMISE"
    #: An agent asked for scope it does not hold.
    SCOPE_ESCALATION = "SCOPE_ESCALATION"
    #: An agent was isolated by the Gateway during a mission.
    AGENT_ISOLATION = "AGENT_ISOLATION"
    #: A worker failed, with the failure kind named.
    WORKER_FAULT = "WORKER_FAULT"
    #: The Gateway refused a step.
    GATEWAY_REFUSAL = "GATEWAY_REFUSAL"
    #: An external action that actually left the process.
    EXTERNAL_EFFECT = "EXTERNAL_EFFECT"
    #: Measured coverage of an evidence bundle.
    EVIDENCE_COVERAGE = "EVIDENCE_COVERAGE"


class Standing(str, Enum):
    """What a record is permitted to influence. Never a score."""

    #: A fact the mission measured. May inform, may raise scrutiny.
    OBSERVED = "OBSERVED"
    #: A finding that something went wrong. May raise scrutiny.
    CAUTION = "CAUTION"
    #: Kept as evidence, permitted to influence nothing.
    UNTRUSTED = "UNTRUSTED"


class KnowledgeRecord(_Base):
    """One fact, with the mission that produced it named."""

    record_id: str
    kind: RecordKind
    standing: Standing = Standing.OBSERVED

    #: What the record is ABOUT -- a claim id, an agent id, a request id.
    #: The retriever's metadata filter keys on this, so a query for one
    #: agent's history never has to score the other agents' records.
    subject: str
    #: One sentence, in the words a human would use. This is the text the
    #: lexical retriever scores against; it is written by
    #: `recall/distill.py` from typed fields, never by a model.
    statement: str
    #: Typed detail. JSON-safe primitives only, mirroring
    #: `MissionCheckpoint.ctx`'s own discipline.
    value: dict[str, Any] = Field(default_factory=dict)

    # --- provenance. Every field required to re-find the source. ---------
    mission_id: str
    objective_class: str
    checkpoint_seq: int = 0
    agent_id: str = ""
    tool: str = ""
    #: The file, feed or system the underlying evidence came from.
    source: str = ""
    observed_at: datetime

    #: SHA-256 over the provenance-bearing fields. Two writes of the same
    #: fact from the same checkpoint collide on this id rather than
    #: accumulating duplicates that would each vote separately in retrieval.
    @staticmethod
    def make_id(
        *, mission_id: str, kind: RecordKind, subject: str, checkpoint_seq: int, statement: str
    ) -> str:
        digest = hashlib.sha256(
            "|".join([mission_id, kind.value, subject, str(checkpoint_seq), statement]).encode(
                "utf-8"
            )
        ).hexdigest()
        return f"kr_{digest[:24]}"


class RetrievedRecord(_Base):
    """One selected record plus WHY it was selected. The score is meaningless
    without the terms that produced it, so both travel together."""

    record: KnowledgeRecord
    score: float
    matched_terms: list[str] = Field(default_factory=list)


class RetrievalResult(_Base):
    """What retrieval selected, and -- just as importantly -- what it did not.

    `considered`, `filtered_out` and `dropped_for_budget` are the fields that
    make "this system retrieves rather than loading everything" checkable
    instead of asserted. A result where `considered == len(selected)` did not
    select; it dumped.
    """

    query: str
    selected: list[RetrievedRecord] = Field(default_factory=list)
    #: How many records existed in the corpus before any filter ran.
    considered: int = 0
    #: Removed by a metadata filter before scoring.
    filtered_out: int = 0
    #: Scored above zero but did not fit the k or character budget.
    dropped_for_budget: int = 0
    #: Scored zero -- no query term appears in them at all.
    zero_scored: int = 0
    #: Characters of statement text actually returned, and the ceiling.
    chars_returned: int = 0
    char_budget: int = 0
    filters: dict[str, Any] = Field(default_factory=dict)

    @property
    def selection_ratio(self) -> float:
        """Fraction of the corpus that reached the caller. Reported so a
        judge can see the number rather than infer it."""
        return (len(self.selected) / self.considered) if self.considered else 0.0


__all__ = [
    "KnowledgeRecord",
    "RecordKind",
    "RetrievalResult",
    "RetrievedRecord",
    "Standing",
]
