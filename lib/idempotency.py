"""Firestore-backed idempotency. Moved out of memory while it is still cheap.

Pub/Sub is at-least-once, and Cloud Run instances are replaced without warning.
An in-memory seen-set survives neither, so the guard that mattered would be the
one that quietly stopped working: re-deriving a conclusion twice is harmless,
but Task 4 puts `obligation.raised` behind this wrapper, and raising the same
correction obligation twice means apologising to a real customer twice.

The claim is atomicity, so it is worth being precise about how it is obtained:
`create()` fails if the document already exists. That is a single conditional
write, not a read-then-write, so two Cloud Run instances processing the same
redelivered message cannot both win.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    # Type-only: lib.pubsub re-exports IdempotentConsumer from here, so a runtime
    # import in this direction would close the cycle.
    from lib.pubsub import Message

COLLECTION_IDEMPOTENCY = "idempotency"


class SeenSet(Protocol):
    def claim(self, key: str, note: str = "") -> bool:
        """True if this caller claimed the key; False if it was already taken."""
        ...


@dataclass
class InMemorySeenSet:
    """For tests and single-process local runs. NOT the production story.

    Kept because the eval harness and the unit tests should not need a database
    to prove routing logic, and because being explicit about which one is in use
    is better than a Firestore client that silently no-ops.
    """

    _seen: set[str] = field(default_factory=set)
    _lock: threading.RLock = field(default_factory=threading.RLock)

    def claim(self, key: str, note: str = "") -> bool:
        with self._lock:
            if key in self._seen:
                return False
            self._seen.add(key)
            return True


@dataclass
class FirestoreSeenSet:
    """Durable across process restarts. This is the one that runs in Cloud Run."""

    collection: str = COLLECTION_IDEMPOTENCY

    def claim(self, key: str, note: str = "") -> bool:
        from google.api_core import exceptions as gexc

        from lib.firestore import get_client

        doc = get_client().collection(self.collection).document(_safe_key(key))
        try:
            # create() is the whole guarantee: it fails if the document exists,
            # so the winner is decided by Firestore, not by a race in Python.
            doc.create(
                {
                    "key": key,
                    "note": note,
                    "claimed_at": datetime.now(UTC).isoformat(),
                }
            )
            return True
        except gexc.AlreadyExists:
            return False


def _safe_key(key: str) -> str:
    """Firestore document ids may not contain '/'."""
    return key.replace("/", "__")


class IdempotentConsumer:
    """Wraps a handler so a redelivered message is dropped, not re-executed."""

    def __init__(
        self,
        handler: Callable[[Message], None],
        name: str,
        seen: SeenSet | None = None,
    ) -> None:
        self._handler = handler
        self.name = name
        self._seen: SeenSet = seen or InMemorySeenSet()
        self.delivered = 0
        self.suppressed = 0

    def __call__(self, message: Message) -> None:
        key = f"{self.name}:{message.dedup_key}"
        if not self._seen.claim(key, note=message.topic):
            self.suppressed += 1
            return
        self.delivered += 1
        self._handler(message)
