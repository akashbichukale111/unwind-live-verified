"""Integration: cascade persistence and durable idempotency, against the emulator.

Skipped unless a Firestore emulator is answering:

    make emulator     # one terminal
    make test         # another

Two things are proven here that cannot be proven in-process:

1. The idempotency seen-set survives a new process. An in-memory set would pass
   a single-process test and then fail in Cloud Run, which is exactly the bug
   this move was meant to prevent.
2. `FirestoreStore` satisfies the same protocol the corpus store does, so the
   emulator run and the eval run exercise one cascade rather than two.
"""

from __future__ import annotations

import json
import os
import socket
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
DATA = REPO / "corpus" / "data"
HUB = "clm_000000"
AT = datetime(2026, 7, 6, 9, 0, tzinfo=UTC)


def _emulator_up() -> bool:
    host = os.environ.get("FIRESTORE_EMULATOR_HOST", "localhost:8080")
    hostname, _, port = host.partition(":")
    try:
        with socket.create_connection((hostname, int(port or 8080)), timeout=1.0):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not _emulator_up(),
    reason="Firestore emulator not running; start it with `make emulator`",
)


@pytest.fixture(scope="module", autouse=True)
def _emulator_project():
    os.environ.setdefault("FIRESTORE_EMULATOR_HOST", "localhost:8080")
    os.environ["UNWIND_PROJECT_ID"] = "unwind-cascade-test"
    from lib import firestore as fs
    from lib.config import reset_config_cache

    reset_config_cache()
    fs.reset_client()
    yield
    fs.reset_client()
    reset_config_cache()


# ---------------------------------------------------------------------------
# Durable idempotency
# ---------------------------------------------------------------------------


def test_a_key_can_only_be_claimed_once() -> None:
    from lib.idempotency import FirestoreSeenSet

    seen = FirestoreSeenSet()
    key = f"test:{uuid.uuid4().hex}"
    assert seen.claim(key, note="first") is True
    assert seen.claim(key, note="second") is False


def test_the_seen_set_survives_a_new_client_instance() -> None:
    """The point of moving it out of memory. A fresh object still sees the key."""
    from lib.idempotency import FirestoreSeenSet

    key = f"test:{uuid.uuid4().hex}"
    assert FirestoreSeenSet().claim(key) is True
    assert FirestoreSeenSet().claim(key) is False


def test_redelivery_does_not_re_execute_the_handler() -> None:
    from lib.idempotency import FirestoreSeenSet, IdempotentConsumer
    from lib.pubsub import ALL_TOPICS, LocalBus

    executions: list[str] = []
    bus = LocalBus()
    bus.ensure_topics(ALL_TOPICS)
    consumer = IdempotentConsumer(
        lambda m: executions.append(m.data["claim_id"]),
        name=f"obligation-{uuid.uuid4().hex[:8]}",
        seen=FirestoreSeenSet(),
    )
    bus.subscribe("obligation.raised", consumer)

    dedup = f"clm_000000:{uuid.uuid4().hex}"
    message_id = bus.publish("obligation.raised", {"claim_id": HUB}, dedup_key=dedup)
    bus.redeliver(message_id)
    bus.redeliver(message_id)

    assert executions == [HUB], "an obligation was raised more than once"
    assert consumer.delivered == 1
    assert consumer.suppressed == 2


def test_distinct_keys_are_not_suppressed() -> None:
    from lib.idempotency import FirestoreSeenSet

    seen = FirestoreSeenSet()
    run = uuid.uuid4().hex
    assert all(seen.claim(f"{run}:{i}") for i in range(5))


# ---------------------------------------------------------------------------
# Cascade persistence
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def loaded_slice():
    """Load a small, self-contained slice: the hub and its direct dependents."""
    from lib import firestore as fs
    from lib.schema import Claim, Conclusion, ReverseEdge, Source

    def rows(name: str) -> list[dict]:
        return [
            json.loads(line)
            for line in (DATA / name).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    edges = [e for e in rows("reverse_index.jsonl") if e["claim_id"] == HUB][:40]
    wanted = {e["conclusion_id"] for e in edges}
    conclusions = [
        Conclusion(**c) for c in rows("conclusions.jsonl") if c["conclusion_id"] in wanted
    ]

    fs.put_sources([Source(**s) for s in rows("sources.jsonl")])
    fs.put_claims([Claim(**c) for c in rows("claims.jsonl") if c["claim_id"] == HUB])
    fs.put_conclusions(conclusions)
    fs.put_reverse_edges(ReverseEdge(**e) for e in edges)
    return {"edges": edges, "conclusions": conclusions}


def test_firestore_store_satisfies_the_same_protocol(loaded_slice) -> None:
    """One cascade implementation, two stores -- not two implementations."""
    from spine.cascade import FirestoreStore, run_cascade

    result = run_cascade(
        store=FirestoreStore(),
        claim_id=HUB,
        source_id="src_supplier_K",
        new_value=20,
        reason="emulator integration",
        triggered_at=AT,
    )
    assert result.status.value == "completed"
    assert result.model_calls == 0
    assert len(result.radius) == len(loaded_slice["edges"])


def test_cascade_and_nodes_persist_and_read_back(loaded_slice) -> None:
    from lib import firestore as fs
    from spine.cascade import FirestoreStore, run_cascade

    result = run_cascade(
        store=FirestoreStore(),
        claim_id=HUB,
        source_id="src_supplier_K",
        new_value=20,
        reason="emulator integration",
        triggered_at=AT,
    )
    fs.put_cascade(result.to_cascade_doc())
    written = fs.put_cascade_nodes(
        result.cascade_id,
        (v.to_cascade_node(result.cascade_id, AT) for v in result.radius.values()),
    )
    assert written == len(result.radius)

    stored = fs.get_cascade(result.cascade_id)
    assert stored is not None
    assert stored.claim_id == HUB
    assert stored.radius_size == len(result.radius)
    assert stored.model_calls == 0

    nodes = list(fs.iter_cascade_nodes(result.cascade_id))
    assert len(nodes) == len(result.radius)
    # Depth lives on the cascade node, and the path explains it.
    assert all(n.depth >= 1 for n in nodes)
    assert all(n.path and n.path[0] == HUB for n in nodes)


def test_a_cascade_never_mutates_the_reverse_index(loaded_slice) -> None:
    """Ruling 1.9: the reverse index is a structural fact, a cascade is an event."""
    from lib import firestore as fs
    from spine.cascade import FirestoreStore, run_cascade

    before = {(e.claim_id, e.conclusion_id, e.depth) for e in fs.iter_dependents(HUB)}

    result = run_cascade(
        store=FirestoreStore(),
        claim_id=HUB,
        source_id="src_supplier_K",
        new_value=20,
        triggered_at=AT,
    )
    fs.put_cascade(result.to_cascade_doc())
    fs.put_cascade_nodes(
        result.cascade_id,
        (v.to_cascade_node(result.cascade_id, AT) for v in result.radius.values()),
    )

    after = {(e.claim_id, e.conclusion_id, e.depth) for e in fs.iter_dependents(HUB)}
    assert after == before
    assert all(depth == 1 for _, _, depth in after)


def test_two_deliveries_of_one_retraction_resolve_to_one_cascade_id() -> None:
    """What makes the idempotency key meaningful at the cascade level."""
    from spine.cascade import cascade_id_for

    first = cascade_id_for(HUB, "src_supplier_K", AT)
    second = cascade_id_for(HUB, "src_supplier_K", AT)
    assert first == second
    assert cascade_id_for(HUB, "src_broker_Z", AT) != first
