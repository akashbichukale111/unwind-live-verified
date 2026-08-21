"""Pub/Sub publisher and subscriber, with an in-process shim of identical shape.

UNWIND's cascade is event-driven: a claim dies, the reverse index is walked, and
each dependent is re-derived and scored independently. That is a fan-out, so it
is Pub/Sub. The shim exists because the deterministic tier must run on a laptop
with no GCP account, and because swapping transports must not change a single
call site.

Delivery is at-least-once on the real service, so every consumer here is wrapped
in `IdempotentConsumer`: a message whose dedup key has been seen is acknowledged
and dropped. Re-deriving a conclusion twice is harmless; raising the same
correction obligation twice is a second apology to a real customer.
"""

from __future__ import annotations

import json
import threading
import uuid
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, Protocol

from lib.config import ALL_TOPICS, get_config


@dataclass(frozen=True)
class Message:
    """One event on the bus."""

    topic: str
    data: dict[str, Any]
    message_id: str
    #: Stable key used for deduplication. Defaults to message_id, but producers
    #: should set it to something semantic (claim_id + conclusion_id) so that a
    #: genuine republish after a crash still deduplicates.
    dedup_key: str

    def encode(self) -> bytes:
        return json.dumps(self.data, sort_keys=True, separators=(",", ":")).encode()


Handler = Callable[[Message], None]


class Bus(Protocol):
    def ensure_topics(self, topics: Iterable[str]) -> list[str]: ...
    def publish(self, topic: str, data: dict[str, Any], dedup_key: str | None = None) -> str: ...
    def subscribe(self, topic: str, handler: Handler) -> None: ...


# ---------------------------------------------------------------------------
# In-process shim
# ---------------------------------------------------------------------------


@dataclass
class LocalBus:
    """Synchronous in-process bus with the same surface as the real client.

    Publishing delivers to every subscriber before returning. That is not how
    Cloud Pub/Sub behaves, and the difference is deliberate: local runs are
    deterministic and orderable, which is what makes the eval harness
    reproducible. Anything relying on that ordering is a bug the real transport
    will find.
    """

    _topics: set[str] = field(default_factory=set)
    _handlers: dict[str, list[Handler]] = field(default_factory=lambda: defaultdict(list))
    _published: list[Message] = field(default_factory=list)
    _lock: threading.RLock = field(default_factory=threading.RLock)

    def ensure_topics(self, topics: Iterable[str]) -> list[str]:
        with self._lock:
            created = [t for t in topics if t not in self._topics]
            self._topics.update(topics)
        return created

    def publish(self, topic: str, data: dict[str, Any], dedup_key: str | None = None) -> str:
        if topic not in self._topics:
            raise KeyError(f"topic not created: {topic}")
        message_id = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"{topic}:{json.dumps(data, sort_keys=True)}:{len(self._published)}",
        ).hex
        msg = Message(
            topic=topic,
            data=data,
            message_id=message_id,
            dedup_key=dedup_key or message_id,
        )
        with self._lock:
            self._published.append(msg)
            handlers = list(self._handlers[topic])
        for handler in handlers:
            handler(msg)
        return message_id

    def subscribe(self, topic: str, handler: Handler) -> None:
        if topic not in self._topics:
            raise KeyError(f"topic not created: {topic}")
        with self._lock:
            self._handlers[topic].append(handler)

    def redeliver(self, message_id: str) -> int:
        """Replay a delivered message. Models at-least-once delivery in tests."""
        with self._lock:
            matches = [m for m in self._published if m.message_id == message_id]
            if not matches:
                raise KeyError(message_id)
            msg = matches[0]
            handlers = list(self._handlers[msg.topic])
        for handler in handlers:
            handler(msg)
        return len(handlers)

    @property
    def published(self) -> list[Message]:
        with self._lock:
            return list(self._published)


# ---------------------------------------------------------------------------
# Cloud Pub/Sub
# ---------------------------------------------------------------------------


class CloudBus:
    """Thin wrapper over google-cloud-pubsub.

    [UNVERIFIED] Never executed in this environment: no GCP credentials were
    available at build time. The shape follows the published client API; treat
    it as unproven until `make dev` runs against a real project.
    """

    def __init__(self, project_id: str) -> None:
        from google.cloud import pubsub_v1  # noqa: PLC0415

        self._project_id = project_id
        self._publisher = pubsub_v1.PublisherClient()
        self._subscriber = pubsub_v1.SubscriberClient()
        self._pubsub_v1 = pubsub_v1

    def _topic_path(self, topic: str) -> str:
        return self._publisher.topic_path(self._project_id, _wire_name(topic))

    def _subscription_path(self, topic: str) -> str:
        return self._subscriber.subscription_path(self._project_id, f"{_wire_name(topic)}-sub")

    def ensure_topics(self, topics: Iterable[str]) -> list[str]:
        from google.api_core import exceptions as gexc  # noqa: PLC0415

        created: list[str] = []
        for topic in topics:
            try:
                self._publisher.create_topic(request={"name": self._topic_path(topic)})
                created.append(topic)
            except gexc.AlreadyExists:
                pass
        return created

    def publish(self, topic: str, data: dict[str, Any], dedup_key: str | None = None) -> str:
        payload = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
        future = self._publisher.publish(
            self._topic_path(topic), payload, dedup_key=dedup_key or ""
        )
        return future.result()

    def subscribe(self, topic: str, handler: Handler) -> None:
        from google.api_core import exceptions as gexc  # noqa: PLC0415

        sub_path = self._subscription_path(topic)
        try:
            self._subscriber.create_subscription(
                request={"name": sub_path, "topic": self._topic_path(topic)}
            )
        except gexc.AlreadyExists:
            pass

        def _callback(message: Any) -> None:
            handler(
                Message(
                    topic=topic,
                    data=json.loads(message.data.decode()),
                    message_id=message.message_id,
                    dedup_key=message.attributes.get("dedup_key") or message.message_id,
                )
            )
            message.ack()

        self._subscriber.subscribe(sub_path, callback=_callback)


def _wire_name(topic: str) -> str:
    """Pub/Sub topic ids may not contain dots; the logical names in the brief do."""
    return topic.replace(".", "-")


# ---------------------------------------------------------------------------
# Idempotent consumption
# ---------------------------------------------------------------------------
# Lives in lib/idempotency.py, because the seen-set is now Firestore-backed and
# a durable store is a different concern from a transport. Re-exported here so
# existing call sites keep working.
from lib.idempotency import IdempotentConsumer  # noqa: E402, F401

# ---------------------------------------------------------------------------


_BUS: Bus | None = None


def get_bus() -> Bus:
    global _BUS
    if _BUS is None:
        cfg = get_config()
        _BUS = LocalBus() if cfg.pubsub_local else CloudBus(cfg.project_id)
        _BUS.ensure_topics(ALL_TOPICS)
    return _BUS


def reset_bus() -> None:
    """Test hook."""
    global _BUS
    _BUS = None
