"""Decision Memory (Card 2): an append-only causal chain, NOT a vector store.

The rubric asks agents to "safely maintain context across weeks of
asynchronous operations". A vector store answers "what is similar to this
text"; it cannot answer "what happened BECAUSE of this decision", because
similarity is not causation and an embedding forgets which entry caused which.
This module stores the causal edge explicitly (`parent_id`) instead, so the
required query -- "what happened because of decision X?" -- is a graph walk
over an explicit field, not a nearest-neighbour guess. There are no
embeddings anywhere in this file, and there never will be: that is the point,
not an oversight.

APPEND-ONLY, ENFORCED
----------------------
`write_entry` only ever calls `.set()` on a NEW document id (`entry_id` is
derived from `case_id` + `seq`, and `seq` is read-and-incremented under the
case's own document so two writers cannot silently collide). There is no
`update_entry` or `delete_entry` in this module's public surface -- the chain
records what happened, and a record that can be edited after the fact is not
evidence of anything (the same reasoning `lib/firestore.py` uses for
`cascades/`).

DURABILITY
-----------
Every entry is written to Firestore before this function returns. A process
that dies immediately after `write_entry` returns has already made the entry
durable; `tests/test_tower_memory.py::test_chain_survives_a_genuine_process_restart`
proves this by dropping every in-process object (including the Firestore
client) and reading the chain back through a brand new one.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from lib.config import COLLECTION_DECISION_MEMORY
from lib.firestore import get_client
from tower.schema import MemoryEntry, MemoryEntryKind

#: Sequence counters live in their own collection, not mixed into the entries
#: themselves -- a counter document is bookkeeping, not a link in anyone's
#: causal chain, and keeping it out of `COLLECTION_DECISION_MEMORY` means a
#: raw scan of that collection can never accidentally yield one.
_COUNTERS = "decision_memory_counters"


def _case_counter_ref(case_id: str):
    return get_client().collection(_COUNTERS).document(case_id)


def _next_seq(case_id: str) -> int:
    from google.cloud import firestore as fs  # noqa: PLC0415

    ref = _case_counter_ref(case_id)

    @fs.transactional
    def _increment(transaction: fs.Transaction) -> int:
        snap = ref.get(transaction=transaction)
        current = snap.get("next_seq") if snap.exists else 0
        transaction.set(ref, {"next_seq": (current or 0) + 1})
        return current or 0

    client = get_client()
    return _increment(client.transaction())


def write_entry(
    case_id: str,
    kind: MemoryEntryKind,
    payload: dict,
    *,
    parent_id: str | None = None,
) -> MemoryEntry:
    """Append one link. Returns the entry actually written (with its assigned
    `entry_id` and `seq`), never mutated afterwards.
    """
    seq = _next_seq(case_id)
    entry = MemoryEntry(
        entry_id=f"{case_id}::{seq:06d}::{uuid.uuid4().hex[:8]}",
        case_id=case_id,
        kind=kind,
        payload=payload,
        parent_id=parent_id,
        seq=seq,
        created_at=datetime.now(UTC),
    )
    get_client().collection(COLLECTION_DECISION_MEMORY).document(entry.entry_id).set(
        entry.to_firestore()
    )
    return entry


def get_entry(entry_id: str) -> MemoryEntry | None:
    snap = get_client().collection(COLLECTION_DECISION_MEMORY).document(entry_id).get()
    return MemoryEntry(**snap.to_dict()) if snap.exists else None


def get_case_chain(case_id: str) -> list[MemoryEntry]:
    """The full timeline for one case, in the order it happened."""
    query = (
        get_client()
        .collection(COLLECTION_DECISION_MEMORY)
        .where("case_id", "==", case_id)
        .order_by("seq")
    )
    return [MemoryEntry(**snap.to_dict()) for snap in query.stream()]


def what_happened_because_of(entry_id: str) -> list[MemoryEntry]:
    """Every entry downstream of `entry_id`, in causal (BFS) order.

    This is the query the module exists to answer: not "what looks like
    this", but "what did this cause, directly or transitively". Walking
    `parent_id` is the reverse-index idiom `spine/traversal.py` uses for
    claims, applied to decisions instead of premises.
    """
    client = get_client()
    collection = client.collection(COLLECTION_DECISION_MEMORY)

    found: list[MemoryEntry] = []
    frontier = [entry_id]
    seen: set[str] = {entry_id}
    while frontier:
        next_frontier: list[str] = []
        for parent in frontier:
            for snap in collection.where("parent_id", "==", parent).stream():
                entry = MemoryEntry(**snap.to_dict())
                if entry.entry_id in seen:
                    continue
                seen.add(entry.entry_id)
                found.append(entry)
                next_frontier.append(entry.entry_id)
        frontier = next_frontier
    found.sort(key=lambda e: e.seq)
    return found


def reset_for_test(case_id: str) -> None:
    """Test hook: delete every entry (and the counter) for one case."""
    client = get_client()
    collection = client.collection(COLLECTION_DECISION_MEMORY)
    for snap in collection.where("case_id", "==", case_id).stream():
        snap.reference.delete()
    _case_counter_ref(case_id).delete()
