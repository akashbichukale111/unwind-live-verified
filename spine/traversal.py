"""T0 -- the structural filter. Reverse-index traversal, no model, no arithmetic.

This is the step nothing in an enterprise can do today, because the edge was
never recorded. Given a dead claim, walk backwards to every decision that stood
on it, transitively: claim -> conclusions -> the claims those conclusions
themselves asserted -> further conclusions.

It is a breadth-first walk, so `depth` is the true shortest hop count, and every
node keeps the `path` that reached it. A verdict that cannot be explained back
to the retracted claim is not usable by a human being.

CYCLES ARE REAL HERE. A conclusion emits a claim, and nothing in the data model
prevents that claim from ending up back in the premise set of something upstream
-- a replenishment plan feeding a forecast that feeds the plan. The visited set
makes the walk terminate; `cycles_detected` records that it happened rather than
swallowing it.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Protocol

from lib.config import Tier
from lib.schema import Claim, Conclusion, ReverseEdge, Source
from lib.telemetry import tool_call_span


class GraphStore(Protocol):
    """The three reads a traversal needs. Deliberately tiny.

    Anything satisfying this can back a cascade: the committed corpus, the
    Firestore emulator, or production Firestore. `radius_truth.jsonl` is NOT
    reachable through it, by construction -- there is no method that would
    return it.
    """

    def get_claim(self, claim_id: str) -> Claim | None: ...
    def get_conclusion(self, conclusion_id: str) -> Conclusion | None: ...
    def get_source(self, source_id: str) -> Source | None: ...
    def direct_dependents(self, claim_id: str) -> list[ReverseEdge]: ...


@dataclass
class TraversalNode:
    conclusion_id: str
    depth: int
    path: list[str]
    weight: float


@dataclass
class TraversalResult:
    root_claim_id: str
    nodes: dict[str, TraversalNode] = field(default_factory=dict)
    #: Edges that pointed at a conclusion the store could not read. Recorded, not
    #: dropped: a dangling edge is a real integrity signal and it fails safe
    #: downstream (escapement treats an unreadable conclusion as escaped).
    dangling_edges: list[str] = field(default_factory=list)
    cycles_detected: list[str] = field(default_factory=list)
    claims_visited: int = 0
    max_depth: int = 0

    @property
    def size(self) -> int:
        return len(self.nodes)


def traverse(
    store: GraphStore, root_claim_id: str, max_depth: int | None = None
) -> TraversalResult:
    """Breadth-first transitive closure of what depends on `root_claim_id`.

    Deterministic: dependents are visited in sorted id order, so two runs over
    the same store produce identical paths, not merely identical sets.
    """
    with tool_call_span("t0_traverse", Tier.T0, claim_id=root_claim_id) as span:
        result = TraversalResult(root_claim_id=root_claim_id)
        visited_claims: set[str] = {root_claim_id}
        queue: deque[tuple[str, int, list[str]]] = deque([(root_claim_id, 0, [root_claim_id])])

        while queue:
            claim_id, depth, path = queue.popleft()
            result.claims_visited += 1
            if max_depth is not None and depth >= max_depth:
                continue

            for edge in sorted(store.direct_dependents(claim_id), key=lambda e: e.conclusion_id):
                conclusion_id = edge.conclusion_id
                if conclusion_id in result.nodes:
                    # Already reached by a shorter or equal path. Breadth-first
                    # guarantees the first arrival is the shallowest, so this is
                    # a genuine re-convergence, not a shorter route.
                    continue

                node_path = [*path, conclusion_id]
                result.nodes[conclusion_id] = TraversalNode(
                    conclusion_id=conclusion_id,
                    depth=depth + 1,
                    path=node_path,
                    weight=edge.weight,
                )
                result.max_depth = max(result.max_depth, depth + 1)

                conclusion = store.get_conclusion(conclusion_id)
                if conclusion is None:
                    result.dangling_edges.append(conclusion_id)
                    continue

                emitted = conclusion.emits_claim_id
                if not emitted:
                    continue
                if emitted in visited_claims:
                    # The conclusion asserted a claim we have already walked
                    # through. That is a cycle in the premise graph.
                    result.cycles_detected.append(
                        f"{conclusion_id} emits {emitted}, already visited on this walk"
                    )
                    continue
                visited_claims.add(emitted)
                queue.append((emitted, depth + 1, [*node_path, emitted]))

        span.set_attribute("unwind.radius_size", result.size)
        span.set_attribute("unwind.max_depth", result.max_depth)
        span.set_attribute("unwind.cycles_detected", len(result.cycles_detected))
        span.set_attribute("unwind.dangling_edges", len(result.dangling_edges))
        return result
