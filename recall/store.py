"""Persistence for mission knowledge. Append-only, content-addressed.

APPEND-ONLY, AND WHY THAT IS THE SECURITY PROPERTY
-----------------------------------------------------
There is no `update_record` and no `delete_record` on this module's public
surface, the same contract `tower/memory.py`, `command_os/checkpoint.py` and
`evolution/store.py` hold to. A record whose provenance later turns out to
be bad is marked `UNTRUSTED` by writing a NEW record -- it is never edited
away, because an edited memory is a memory with no evidence that it was
attacked.

CONTENT-ADDRESSED IDS
------------------------
`KnowledgeRecord.make_id` hashes mission id, kind, subject, checkpoint seq
and statement. Re-distilling the same mission therefore overwrites identical
documents rather than accumulating duplicates -- which matters because a
duplicate would vote twice in `recall/index.py`'s ranking, and a fact
repeated by one mission is still one fact.

QUERY SHAPE
--------------
One collection, single-field equality filters, no combined `where` +
`order_by` on different fields. This module needs no new composite index in
`infra/indexes.json`, for the same reason `evolution/store.py` needs none.
Ordering is done in Python over a bounded fetch: the corpus this serves is
mission knowledge, which grows by a handful of records per mission, and a
`limit` is applied on every read.
"""

from __future__ import annotations

from lib.firestore import get_client
from recall.schema import KnowledgeRecord, RecordKind, Standing

COLLECTION_KNOWLEDGE = "recall_knowledge"

#: [ASSUMPTION] Ceiling on a single read. A retrieval that needs more than
#: this many records to answer a question is not a retrieval; it is a scan,
#: and the caller should be filtering. Stated rather than silently unbounded:
#: an unbounded read is how a "we do not load everything" claim quietly stops
#: being true as the corpus grows.
#:
#: [LIMITATION] The consequence, named rather than left to be discovered.
#: Firestore's stream order is not defined and the newest-first sort below
#: happens in Python, AFTER the fetch. So once the corpus genuinely exceeds
#: `MAX_FETCH`, a read returns 500 arbitrary records sorted correctly among
#: themselves -- not the 500 newest. `corpus_stats` reports `truncated` so a
#: count on screen is never silently a floor presented as a total, and at the
#: sizes this system produces (single-digit records per mission) the ceiling
#: is nowhere near binding. The fix when it does bind is an `order_by` on
#: `observed_at` with a cursor, which costs a composite index -- not worth
#: taking on before the ceiling is real.
MAX_FETCH = 500


def _col():
    return get_client().collection(COLLECTION_KNOWLEDGE)


def write_records(records: list[KnowledgeRecord]) -> int:
    """Write every record. Returns how many were written.

    Not transactional and deliberately so: these are independent facts, and a
    batch that fails halfway should leave the facts it managed to record
    rather than discarding them to preserve an all-or-nothing property
    nothing downstream needs.
    """
    written = 0
    for record in records:
        _col().document(record.record_id).set(record.model_dump(mode="json"))
        written += 1
    return written


def get_record(record_id: str) -> KnowledgeRecord | None:
    snap = _col().document(record_id).get()
    return KnowledgeRecord(**snap.to_dict()) if snap.exists else None


def list_records(
    *,
    kind: RecordKind | None = None,
    subject: str | None = None,
    mission_id: str | None = None,
    limit: int = MAX_FETCH,
) -> list[KnowledgeRecord]:
    """Records, newest first. At most one equality filter is applied in the
    query; any further narrowing happens in Python, which keeps this off the
    composite-index path."""
    query = _col()
    if mission_id is not None:
        query = query.where("mission_id", "==", mission_id)
    elif subject is not None:
        query = query.where("subject", "==", subject)
    elif kind is not None:
        query = query.where("kind", "==", kind.value)

    rows = [KnowledgeRecord(**doc.to_dict()) for doc in query.limit(min(limit, MAX_FETCH)).stream()]
    if kind is not None:
        rows = [r for r in rows if r.kind is kind]
    if subject is not None:
        rows = [r for r in rows if r.subject == subject]
    if mission_id is not None:
        rows = [r for r in rows if r.mission_id == mission_id]
    rows.sort(key=lambda r: (r.observed_at, r.record_id), reverse=True)
    return rows[:limit]


def corpus_stats() -> dict[str, object]:
    """What the store actually holds, counted -- never estimated.

    Served to the UI and the judge surface. A count computed from a fetch is
    honest about its own ceiling: `truncated` says whether `MAX_FETCH` cut
    the count short, so a number on screen is never silently a floor
    presented as a total.
    """
    rows = list_records(limit=MAX_FETCH)
    by_kind: dict[str, int] = {}
    by_standing: dict[str, int] = {}
    missions: set[str] = set()
    for record in rows:
        by_kind[record.kind.value] = by_kind.get(record.kind.value, 0) + 1
        by_standing[record.standing.value] = by_standing.get(record.standing.value, 0) + 1
        missions.add(record.mission_id)
    return {
        "records": len(rows),
        "missions": len(missions),
        "by_kind": dict(sorted(by_kind.items())),
        "by_standing": dict(sorted(by_standing.items())),
        "truncated": len(rows) >= MAX_FETCH,
        "max_fetch": MAX_FETCH,
    }


def mark_untrusted(record: KnowledgeRecord, reason: str) -> KnowledgeRecord:
    """Write a NEW record superseding one whose provenance failed a check.

    The original is left in place. `recall/index.py` excludes `UNTRUSTED`
    from every default search, so the superseding record removes the original
    from influence without removing it from the evidence.
    """
    superseded = record.model_copy(
        update={
            "record_id": f"{record.record_id}_untrusted",
            "standing": Standing.UNTRUSTED,
            "statement": f"[UNTRUSTED: {reason}] {record.statement}",
        }
    )
    write_records([superseded])
    return superseded


def reset_for_test() -> None:
    """Test hook. Mirrors `evolution.store.reset_for_test`."""
    for doc in _col().limit(MAX_FETCH).stream():
        doc.reference.delete()


__all__ = [
    "COLLECTION_KNOWLEDGE",
    "MAX_FETCH",
    "corpus_stats",
    "get_record",
    "list_records",
    "mark_untrusted",
    "reset_for_test",
    "write_records",
]
