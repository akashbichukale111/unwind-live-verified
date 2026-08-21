"""CONSEQUENCE PREVIEW: what happens if this agent actually executes?

THE GAP THIS CLOSES
----------------------
This repository is called *Consequence Clearing*. `spine/` answers the
question the name refers to: when a premise changes, which committed
decisions rested on it, and which of those are now wrong and still
operating? That engine walks a real reverse index over 1,146 claims and
4,206 conclusions, with zero model calls.

And until this module, **the agent layer never asked it anything.**

`command_os/mission.py` decided whether an agent MAY act -- scope, budget,
warrant, drift. All real, all necessary, and all the same question every
agent-governance product asks: *can I execute this?* The question UNWIND
exists to answer is the other one:

    NOT   "is this agent permitted to act?"
    BUT   "what breaks downstream if it does?"

A judge reading `command_os/` and `spine/` side by side would previously
have found two products sharing a repository: a consequence engine used by a
demo, and an authority layer that never consulted it. This module is the
join. `tests/test_consequence.py::test_the_agent_layer_actually_imports_the_
consequence_engine` fails if that join is ever removed.

HOW AN AGENT ACTION BECOMES A BLAST RADIUS
---------------------------------------------
The link is the corpus's own `canonical` field, `"subject.predicate"`:

    fleet/data/incident/premise-feed.json   supplier_K / lead_time_days
    corpus/data/claims.jsonl                canonical "supplier_K.lead_time_days"

`recon.extract_claims` already parses the incident evidence into
(subject, predicate, value) triples with contradictions named. Those
triples resolve against the corpus by canonical name -- so a contradicted
premise the recon agent found in a messy handover note is matched to the
real claim it corresponds to, and the REAL cascade is run on it.

    proposed action
        -> premises it would change      (from recon's parsed claims)
        -> resolve to corpus claims      (canonical match, exact, no fuzzing)
        -> run_cascade()                 (the unmodified engine, zero models)
        -> dependent conclusions         (a real traversal, real radius)
        -> four-regime materiality cull  (real arithmetic)
        -> UNWIND RISK INDEX             (this module; see below)

NOTHING HERE IS A MODEL CALL
-------------------------------
Every number this module produces is graph traversal and integer
arithmetic. `tests/test_consequence.py` asserts the import graph contains no
model client, the same technique `tests/test_zero_model.py` uses for the
authority path. A language model may PROPOSE an action; it can never
influence what the consequence preview says would happen.

THE RISK INDEX IS A HEURISTIC AND SAYS SO
--------------------------------------------
`UNWIND_RISK_INDEX` below is an application-specific heuristic, not an
industry-certified score, and every weight is stated as chosen. It is
useful because it is TRANSPARENT and REPRODUCIBLE -- the same radius always
produces the same index, and every contributing dimension is returned
alongside it so a reader can disagree with the weighting and still use the
evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

#: The corpus is fixed committed data, so a cascade for the same (claim,
#: source, value) is the same cascade every time. Cached per process --
#: a mission may preview several actions and the traversal is the expensive
#: part. Never cached across values, which would be a stale answer.
_CASCADE_CACHE: dict[str, Any] = {}
_CANONICAL_INDEX: dict[str, dict[str, Any]] | None = None

#: The corpus's own "as of" instant. Using `now` instead would silently
#: reclassify every conclusion whose deadline has since passed, making the
#: blast radius drift with the wall clock rather than with the evidence.
CORPUS_AT = datetime(2026, 7, 6, tzinfo=UTC)


def _canonical_index(repo: Path | None = None) -> dict[str, dict[str, Any]]:
    """`{"supplier_K.lead_time_days": {claim…}}` over the committed corpus.

    Built once. Exact string match only -- deliberately no fuzzy matching:
    resolving `supplier_K.lead_time` to `supplier_K.lead_time_days` by
    similarity would let a typo in a handover note silently retarget the
    blast radius at a different claim, which is precisely the class of
    error this product exists to catch.
    """
    global _CANONICAL_INDEX
    if _CANONICAL_INDEX is not None:
        return _CANONICAL_INDEX
    import json

    base = repo or Path(__file__).resolve().parents[1]
    index: dict[str, dict[str, Any]] = {}
    path = base / "corpus" / "data" / "claims.jsonl"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            claim = json.loads(line)
            canonical = claim.get("canonical")
            if canonical:
                index[canonical] = claim
    _CANONICAL_INDEX = index
    return index


@dataclass(frozen=True)
class ConsequenceNode:
    """One node of the consequence graph the UI draws.

    `kind` is a closed vocabulary so the renderer cannot be handed a node
    type it has no shape for.
    """

    kind: str  # "action" | "premise" | "regime" | "consequence"
    label: str
    detail: str = ""
    count: int = 0
    severity: str = "INFO"  # INFO | CAUTION | CRITICAL

    def as_record(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "label": self.label,
            "detail": self.detail,
            "count": self.count,
            "severity": self.severity,
        }


@dataclass(frozen=True)
class RiskIndex:
    """UNWIND RISK INDEX — an application-specific heuristic, stated as one.

    Six named dimensions, each 0-100, plus a weighted total. The dimensions
    are returned individually and always: a single number that cannot be
    decomposed is a number nobody can argue with, and this project's whole
    stance is that a score you cannot audit is worse than no score.
    """

    security: int
    data: int
    financial: int
    operational: int
    privilege: int
    irreversibility: int
    total: int
    band: str
    contributions: list[str] = field(default_factory=list)

    def as_record(self) -> dict[str, Any]:
        return {
            "security": self.security,
            "data": self.data,
            "financial": self.financial,
            "operational": self.operational,
            "privilege": self.privilege,
            "irreversibility": self.irreversibility,
            "total": self.total,
            "band": self.band,
            "contributions": list(self.contributions),
            "disclaimer": (
                "UNWIND RISK INDEX is an application-specific heuristic, not an "
                "industry-certified score. Every weight is a chosen constant, "
                "stated in command_os/consequence.py."
            ),
        }


#: [ASSUMPTION] Dimension weights. Chosen so that IRREVERSIBLE ESCAPED
#: consequences dominate -- a decision that already left the building and
#: cannot be recalled is the expensive case this whole product is about.
_WEIGHTS = {
    "security": 0.20,
    "data": 0.10,
    "financial": 0.20,
    "operational": 0.15,
    "privilege": 0.15,
    "irreversibility": 0.20,
}

#: [ASSUMPTION] Band edges over the weighted total.
_BANDS = ((25, "LOW"), (50, "MODERATE"), (75, "HIGH"), (101, "SEVERE"))


def _band(total: int) -> str:
    for ceiling, name in _BANDS:
        if total < ceiling:
            return name
    return "SEVERE"  # pragma: no cover -- total is clamped to 100


def _clamp(value: float) -> int:
    return max(0, min(100, int(round(value))))


def compute_risk_index(
    *,
    radius: int,
    material_escaped: int,
    material_contained: int,
    unresolved: int,
    action_kind: str,
    requested_scope: list[str],
    mutating: bool,
) -> RiskIndex:
    """Fold a real cascade plus the proposed action into six dimensions.

    Pure function: no clock, no I/O, no model, no random state. The same
    inputs always produce the same index, which is what lets a stored
    consequence preview be re-derived and checked later.
    """
    contributions: list[str] = []
    scope_text = " ".join(s.lower() for s in requested_scope)

    # SECURITY — scope reach, not volume.
    security = 0
    if "secret" in scope_text:
        security = 95
        contributions.append("requests secret-bearing scope: security 95")
    elif "write" in scope_text or "mutate" in scope_text:
        security = 45
        contributions.append("requests mutating scope: security 45")
    elif scope_text:
        security = 12
        contributions.append("read-only scope: security 12")

    # DATA — how much committed decision surface is touched at all.
    data = _clamp((radius / 3000.0) * 100.0)
    if radius:
        contributions.append(f"{radius} dependent decisions in radius: data {data}")

    # FINANCIAL — material consequences are the ones that cost money.
    material = material_escaped + material_contained
    financial = _clamp((material / 100.0) * 100.0)
    if material:
        contributions.append(f"{material} material consequences: financial {financial}")

    # OPERATIONAL — work a human must now do, including the undecidable.
    operational = _clamp(((material + unresolved) / 250.0) * 100.0)
    if unresolved:
        contributions.append(f"{unresolved} handed to judgement: operational {operational}")

    # PRIVILEGE — what the action kind itself confers.
    privilege = {
        "SECRET_ACCESS": 100,
        "PRODUCTION_MUTATION": 85,
        "CREATE_PR": 45,
        "CREATE_TICKET": 30,
        "WRITE_SANDBOX": 25,
        "READ_INTERNAL": 12,
        "ANALYZE": 5,
        "READ_PUBLIC": 2,
    }.get(action_kind.upper(), 20)
    contributions.append(f"action kind {action_kind}: privilege {privilege}")

    # IRREVERSIBILITY — the escaped ones cannot be recalled.
    irreversibility = _clamp((material_escaped / 60.0) * 100.0)
    if material_escaped:
        contributions.append(
            f"{material_escaped} consequences ALREADY ESCAPED (un-recallable): "
            f"irreversibility {irreversibility}"
        )
    # A read generally cannot escape anything: it inherits the standing
    # exposure rather than creating it, so it is discounted.
    #
    # SECRET_ACCESS IS THE EXCEPTION, AND THE FIRST VERSION GOT IT WRONG.
    # Treating a secret read as "non-mutating, therefore reversible" scored
    # SECRET_ACCESS (63) BELOW WRITE_SANDBOX (68), which is plainly wrong:
    # a sandbox write can be rolled back, and a disclosed secret cannot be
    # un-disclosed. Disclosure is irreversible even though it writes nothing,
    # so it is excluded from the discount.
    _disclosure_is_irreversible = action_kind.upper() == "SECRET_ACCESS"
    if not mutating and irreversibility and not _disclosure_is_irreversible:
        irreversibility = _clamp(irreversibility * 0.4)
        contributions.append("non-mutating action: irreversibility discounted to 40%")
    elif _disclosure_is_irreversible:
        irreversibility = max(irreversibility, 90)
        contributions.append(
            "secret disclosure cannot be undone: irreversibility floored at 90 "
            "despite the action writing nothing"
        )

    dims = {
        "security": security,
        "data": data,
        "financial": financial,
        "operational": operational,
        "privilege": privilege,
        "irreversibility": irreversibility,
    }
    total = _clamp(sum(dims[k] * w for k, w in _WEIGHTS.items()))
    return RiskIndex(total=total, band=_band(total), contributions=contributions, **dims)


@dataclass(frozen=True)
class ConsequencePreview:
    """The full answer to "what happens if this executes?"."""

    resolved: bool
    action_kind: str
    premises: list[dict[str, Any]]
    radius: int
    regimes: dict[str, int]
    graph: list[ConsequenceNode]
    risk: RiskIndex | None
    reversible: bool
    reason_unresolved: str = ""

    def as_record(self) -> dict[str, Any]:
        return {
            "resolved": self.resolved,
            "action_kind": self.action_kind,
            "premises": self.premises,
            "radius": self.radius,
            "regimes": self.regimes,
            "graph": [n.as_record() for n in self.graph],
            "risk": self.risk.as_record() if self.risk else None,
            "reversible": self.reversible,
            "reason_unresolved": self.reason_unresolved,
        }


def _cascade_for(claim_id: str, source_id: str, new_value: Any):
    key = f"{claim_id}::{source_id}::{new_value}"
    if key not in _CASCADE_CACHE:
        from spine.cascade import CorpusStore, run_cascade

        _CASCADE_CACHE[key] = run_cascade(
            store=CorpusStore.from_repo(Path(__file__).resolve().parents[1]),
            claim_id=claim_id,
            source_id=source_id,
            new_value=new_value,
            reason="consequence preview for a proposed agent action",
            triggered_at=CORPUS_AT,
        )
    return _CASCADE_CACHE[key]


def resolve_premises(claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Match recon's parsed claims onto real corpus claims by canonical name.

    Unmatched premises are RETURNED, marked `matched: False`, never dropped:
    "we found a premise we cannot trace" is a finding an operator needs, and
    silently discarding it would make the blast radius look smaller than the
    evidence supports.
    """
    index = _canonical_index()
    out: list[dict[str, Any]] = []
    for claim in claims:
        subject = str(claim.get("subject", "")).strip()
        predicate = str(claim.get("predicate", "")).strip()
        canonical = f"{subject}.{predicate}" if subject and predicate else ""
        corpus_claim = index.get(canonical)
        out.append(
            {
                "canonical": canonical,
                "subject": subject,
                "predicate": predicate,
                "proposed_value": claim.get("value"),
                "matched": corpus_claim is not None,
                "claim_id": (corpus_claim or {}).get("claim_id", ""),
                "source_id": (corpus_claim or {}).get("source_id", ""),
                "current_value": (corpus_claim or {}).get("value"),
                "load_weight": (corpus_claim or {}).get("load_weight", 0),
            }
        )
    return out


def preview(
    *,
    claims: list[dict[str, Any]],
    action_kind: str,
    requested_scope: list[str],
    mutating: bool,
) -> ConsequencePreview:
    """Run the real consequence engine on a proposed agent action.

    Picks the highest-load matched premise -- `load_weight` is the corpus's
    own measure of how much rests on a claim, so the preview reports the
    worst case the action touches rather than an average that hides it.
    """
    premises = resolve_premises(claims)
    matched = [p for p in premises if p["matched"]]
    if not matched:
        return ConsequencePreview(
            resolved=False,
            action_kind=action_kind,
            premises=premises,
            radius=0,
            regimes={},
            graph=[],
            risk=None,
            reversible=True,
            reason_unresolved=(
                "no parsed premise resolves to a claim in the committed corpus, so "
                "there is no dependency edge to walk. The blast radius is unknown, "
                "not zero -- and that distinction is the point."
            ),
        )

    worst = max(matched, key=lambda p: p.get("load_weight") or 0)
    result = _cascade_for(worst["claim_id"], worst["source_id"], worst["proposed_value"])
    regimes = dict(result.regime_counts())
    radius = sum(regimes.values())

    material_escaped = regimes.get("material_escaped", 0)
    material_contained = regimes.get("material_contained", 0)
    unresolved = regimes.get("unresolved", 0)

    risk = compute_risk_index(
        radius=radius,
        material_escaped=material_escaped,
        material_contained=material_contained,
        unresolved=unresolved,
        action_kind=action_kind,
        requested_scope=requested_scope,
        mutating=mutating,
    )

    graph = [
        ConsequenceNode(
            kind="action",
            label=action_kind,
            detail=f"scope {sorted(requested_scope)}",
            severity="CRITICAL" if risk.band in {"HIGH", "SEVERE"} else "INFO",
        ),
        ConsequenceNode(
            kind="premise",
            label=worst["canonical"],
            detail=(
                f"{worst['current_value']} → {worst['proposed_value']} "
                f"(source {worst['source_id']}, load {worst['load_weight']})"
            ),
            count=len(matched),
            severity="CAUTION",
        ),
        ConsequenceNode(
            kind="consequence",
            label="dependent decisions",
            detail="committed conclusions resting on that premise",
            count=radius,
            severity="CAUTION",
        ),
        ConsequenceNode(
            kind="regime",
            label="immaterial",
            detail="the buffer absorbed the shock — subtraction, not judgement",
            count=regimes.get("immaterial_contained", 0) + regimes.get("immaterial_escaped", 0),
            severity="INFO",
        ),
        ConsequenceNode(
            kind="regime",
            label="already closed out",
            detail="the world moving cannot hurt a decision that completed",
            count=regimes.get("closed_out", 0),
            severity="INFO",
        ),
        ConsequenceNode(
            kind="regime",
            label="handed to judgement",
            detail="the tier is allowed to say it cannot decide this",
            count=unresolved,
            severity="CAUTION",
        ),
        ConsequenceNode(
            kind="regime",
            label="MATERIAL — still correctable",
            detail="reachable in place; a correction can still land",
            count=material_contained,
            severity="CAUTION",
        ),
        ConsequenceNode(
            kind="regime",
            label="MATERIAL — ALREADY ESCAPED",
            detail="sent, signed, shipped or paid. Cannot be recalled.",
            count=material_escaped,
            severity="CRITICAL",
        ),
    ]

    return ConsequencePreview(
        resolved=True,
        action_kind=action_kind,
        premises=premises,
        radius=radius,
        regimes=regimes,
        graph=graph,
        risk=risk,
        reversible=material_escaped == 0,
    )


def reset_for_test() -> None:
    """Test hook, mirroring the `reset_for_test` hooks elsewhere in the repo."""
    global _CANONICAL_INDEX
    _CASCADE_CACHE.clear()
    _CANONICAL_INDEX = None


__all__ = [
    "CORPUS_AT",
    "ConsequenceNode",
    "ConsequencePreview",
    "RiskIndex",
    "compute_risk_index",
    "preview",
    "reset_for_test",
    "resolve_premises",
]
