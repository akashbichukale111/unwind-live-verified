"""Typed Firestore accessors, emulator-aware.

Every read and write in UNWIND goes through this module so that the reverse
index -- the one structure T0 traverses with no model -- has exactly one
implementation to be correct in.

Emulator awareness is not a convenience: with FIRESTORE_EMULATOR_HOST set, the
client library skips credential resolution entirely, which is what lets a cold
clone with no GCP account run the whole deterministic tier.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any

from lib.config import (
    COLLECTION_AGENT_TRUST,
    COLLECTION_CASCADES,
    COLLECTION_CLAIMS,
    COLLECTION_CONCLUSIONS,
    COLLECTION_OBLIGATIONS,
    COLLECTION_REPAIRS,
    COLLECTION_REVERSE_INDEX,
    COLLECTION_SOURCES,
    SUBCOLLECTION_DEPENDENTS,
    SUBCOLLECTION_NODES,
    get_config,
)
from lib.schema import (
    AgentTrust,
    Cascade,
    CascadeNode,
    Claim,
    Conclusion,
    Obligation,
    Repair,
    ReverseEdge,
    Source,
)

_CLIENT: Any = None


def get_client() -> Any:
    """Return a process-wide Firestore client.

    Import is deferred so that modules which never touch Firestore (the corpus
    generator, the metric definitions) do not pay for the dependency.
    """
    global _CLIENT
    if _CLIENT is None:
        from google.cloud import firestore  # noqa: PLC0415

        cfg = get_config()
        if cfg.uses_emulator:
            # The library reads FIRESTORE_EMULATOR_HOST itself and uses
            # anonymous credentials; passing the project keeps paths stable.
            _CLIENT = firestore.Client(project=cfg.project_id)
        else:
            # [ASSUMPTION] `google-cloud-firestore` is pinned `<2.29.0` in
            # pyproject.toml specifically because 2.29.0 broke this exact
            # call against real (non-emulator) Firestore -- see the comment
            # there and evidence/INDEX.md. This explicit `database=` kwarg
            # is not itself the defect (2.29.0 rejects the client library's
            # OWN internally-substituted default identically; verified by
            # reading google.cloud.firestore_v1.base_client's source), so it
            # is left exactly as it reads rather than "fixed" a second time.
            _CLIENT = firestore.Client(project=cfg.project_id, database=cfg.firestore_database)
    return _CLIENT


def reset_client() -> None:
    """Test hook."""
    global _CLIENT
    _CLIENT = None


# ---------------------------------------------------------------------------
# Claims
# ---------------------------------------------------------------------------


def put_claim(claim: Claim) -> None:
    get_client().collection(COLLECTION_CLAIMS).document(claim.claim_id).set(claim.to_firestore())


def get_claim(claim_id: str) -> Claim | None:
    snap = get_client().collection(COLLECTION_CLAIMS).document(claim_id).get()
    return Claim(**snap.to_dict()) if snap.exists else None


def put_claims(claims: Iterable[Claim], batch_size: int = 400) -> int:
    return _batched_set(
        COLLECTION_CLAIMS, ((c.claim_id, c.to_firestore()) for c in claims), batch_size
    )


# ---------------------------------------------------------------------------
# Conclusions
# ---------------------------------------------------------------------------


def put_conclusion(conclusion: Conclusion) -> None:
    get_client().collection(COLLECTION_CONCLUSIONS).document(conclusion.conclusion_id).set(
        conclusion.to_firestore()
    )


def get_conclusion(conclusion_id: str) -> Conclusion | None:
    snap = get_client().collection(COLLECTION_CONCLUSIONS).document(conclusion_id).get()
    return Conclusion(**snap.to_dict()) if snap.exists else None


def put_conclusions(conclusions: Iterable[Conclusion], batch_size: int = 400) -> int:
    return _batched_set(
        COLLECTION_CONCLUSIONS,
        ((c.conclusion_id, c.to_firestore()) for c in conclusions),
        batch_size,
    )


# ---------------------------------------------------------------------------
# Reverse index -- the structure T0 exists to walk
# ---------------------------------------------------------------------------


def put_reverse_edge(edge: ReverseEdge) -> None:
    (
        get_client()
        .collection(COLLECTION_REVERSE_INDEX)
        .document(edge.claim_id)
        .collection(SUBCOLLECTION_DEPENDENTS)
        .document(edge.conclusion_id)
        .set(edge.to_firestore())
    )


def iter_dependents(claim_id: str, max_depth: int | None = None) -> Iterator[ReverseEdge]:
    """Direct dependents of one claim, ordered by depth then weight.

    This is the query infra/indexes.json exists to serve. Transitive traversal
    is Task 2's job and composes this call; Task 1 only guarantees the index and
    the accessor are correct.
    """
    query = (
        get_client()
        .collection(COLLECTION_REVERSE_INDEX)
        .document(claim_id)
        .collection(SUBCOLLECTION_DEPENDENTS)
    )
    if max_depth is not None:
        query = query.where("depth", "<=", max_depth)
    query = query.order_by("depth").order_by("weight", direction="DESCENDING")
    for snap in query.stream():
        yield ReverseEdge(**snap.to_dict())


def put_reverse_edges(edges: Iterable[ReverseEdge], batch_size: int = 400) -> int:
    client = get_client()
    written = 0
    batch = client.batch()
    pending = 0
    for edge in edges:
        ref = (
            client.collection(COLLECTION_REVERSE_INDEX)
            .document(edge.claim_id)
            .collection(SUBCOLLECTION_DEPENDENTS)
            .document(edge.conclusion_id)
        )
        batch.set(ref, edge.to_firestore())
        pending += 1
        written += 1
        if pending >= batch_size:
            batch.commit()
            batch = client.batch()
            pending = 0
    if pending:
        batch.commit()
    return written


# ---------------------------------------------------------------------------
# Sources, obligations, repairs, agent trust
# ---------------------------------------------------------------------------


def put_source(source: Source) -> None:
    get_client().collection(COLLECTION_SOURCES).document(source.source_id).set(
        source.to_firestore()
    )


def get_source(source_id: str) -> Source | None:
    snap = get_client().collection(COLLECTION_SOURCES).document(source_id).get()
    return Source(**snap.to_dict()) if snap.exists else None


def put_sources(sources: Iterable[Source], batch_size: int = 400) -> int:
    return _batched_set(
        COLLECTION_SOURCES, ((s.source_id, s.to_firestore()) for s in sources), batch_size
    )


def put_obligation(obligation: Obligation) -> None:
    get_client().collection(COLLECTION_OBLIGATIONS).document(obligation.obligation_id).set(
        obligation.to_firestore()
    )


def get_obligation(obligation_id: str) -> Obligation | None:
    snap = get_client().collection(COLLECTION_OBLIGATIONS).document(obligation_id).get()
    return Obligation(**snap.to_dict()) if snap.exists else None


def put_repair(repair: Repair) -> None:
    get_client().collection(COLLECTION_REPAIRS).document(repair.repair_id).set(
        repair.to_firestore()
    )


def get_repair(repair_id: str) -> Repair | None:
    snap = get_client().collection(COLLECTION_REPAIRS).document(repair_id).get()
    return Repair(**snap.to_dict()) if snap.exists else None


def put_agent_trust(trust: AgentTrust) -> None:
    get_client().collection(COLLECTION_AGENT_TRUST).document(trust.agent_id).set(
        trust.to_firestore()
    )


def get_agent_trust(agent_id: str) -> AgentTrust | None:
    snap = get_client().collection(COLLECTION_AGENT_TRUST).document(agent_id).get()
    return AgentTrust(**snap.to_dict()) if snap.exists else None


# ---------------------------------------------------------------------------


def _batched_set(
    collection: str, docs: Iterable[tuple[str, dict[str, Any]]], batch_size: int
) -> int:
    client = get_client()
    written = 0
    batch = client.batch()
    pending = 0
    for doc_id, payload in docs:
        batch.set(client.collection(collection).document(doc_id), payload)
        pending += 1
        written += 1
        if pending >= batch_size:
            batch.commit()
            batch = client.batch()
            pending = 0
    if pending:
        batch.commit()
    return written


# ---------------------------------------------------------------------------
# Cascades -- runtime events, written per cascade
# ---------------------------------------------------------------------------
# The reverse index is a stable structural fact and a cascade is a runtime event
# with its own lifetime, so traversal depth is written HERE and the reverse index
# is never mutated by a cascade. Mutating it would make the graph unauditable and
# would leave Task 4's court unable to query one specific traversal rather than
# the union of every traversal that ever ran.


def put_cascade(cascade: Cascade) -> None:
    get_client().collection(COLLECTION_CASCADES).document(cascade.cascade_id).set(
        cascade.to_firestore()
    )


def get_cascade(cascade_id: str) -> Cascade | None:
    snap = get_client().collection(COLLECTION_CASCADES).document(cascade_id).get()
    return Cascade(**snap.to_dict()) if snap.exists else None


def put_cascade_nodes(cascade_id: str, nodes: Iterable[CascadeNode], batch_size: int = 400) -> int:
    client = get_client()
    parent = client.collection(COLLECTION_CASCADES).document(cascade_id)
    written = 0
    batch = client.batch()
    pending = 0
    for node in nodes:
        ref = parent.collection(SUBCOLLECTION_NODES).document(node.conclusion_id)
        batch.set(ref, node.to_firestore())
        pending += 1
        written += 1
        if pending >= batch_size:
            batch.commit()
            batch = client.batch()
            pending = 0
    if pending:
        batch.commit()
    return written


def iter_cascade_nodes(cascade_id: str, regime: str | None = None) -> Iterator[CascadeNode]:
    """Nodes of one cascade, shallowest first. Optionally one regime only.

    The regime filter is the query the operator surface will live on: "show me
    the correction obligations from this cascade" must not be a scan.
    """
    query = (
        get_client()
        .collection(COLLECTION_CASCADES)
        .document(cascade_id)
        .collection(SUBCOLLECTION_NODES)
    )
    if regime is not None:
        query = query.where("regime", "==", regime)
    for snap in query.order_by("depth").stream():
        yield CascadeNode(**snap.to_dict())
