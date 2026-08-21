"""All six topics exist, carry a message, and deduplicate a redelivery.

Cloud Pub/Sub is at-least-once, so redelivery is not an edge case, it is the
contract. Re-deriving a conclusion twice is harmless; raising the same correction
obligation twice is a second apology to a real customer. The dedup wrapper is
therefore tested against an explicit replay rather than assumed.
"""

from __future__ import annotations

import pytest

from lib.config import ALL_TOPICS
from lib.pubsub import IdempotentConsumer, LocalBus, Message


@pytest.fixture()
def bus() -> LocalBus:
    b = LocalBus()
    b.ensure_topics(ALL_TOPICS)
    return b


def test_all_six_topics_are_created(bus: LocalBus) -> None:
    assert set(ALL_TOPICS) == {
        "claim.retracted",
        "node.rederive",
        "node.scored",
        "repair.convened",
        "obligation.raised",
        "unwind.executed",
    }
    # ensure_topics is idempotent: a second call creates nothing new.
    assert bus.ensure_topics(ALL_TOPICS) == []


def test_every_topic_publishes_and_consumes_one_message(bus: LocalBus) -> None:
    received: dict[str, list[Message]] = {topic: [] for topic in ALL_TOPICS}
    for topic in ALL_TOPICS:
        bus.subscribe(topic, lambda m, t=topic: received[t].append(m))

    for topic in ALL_TOPICS:
        bus.publish(topic, {"claim_id": "clm_000000", "topic": topic})

    for topic in ALL_TOPICS:
        assert len(received[topic]) == 1, f"{topic} did not deliver"
        assert received[topic][0].data["claim_id"] == "clm_000000"


def test_redelivery_is_suppressed_on_every_topic(bus: LocalBus) -> None:
    executions: dict[str, int] = {topic: 0 for topic in ALL_TOPICS}
    consumers: dict[str, IdempotentConsumer] = {}

    for topic in ALL_TOPICS:

        def handler(_message: Message, t: str = topic) -> None:
            executions[t] += 1

        consumer = IdempotentConsumer(handler, name=f"{topic}-consumer")
        consumers[topic] = consumer
        bus.subscribe(topic, consumer)

    message_ids = {
        topic: bus.publish(topic, {"claim_id": "clm_000000"}, dedup_key=f"clm_000000:{topic}")
        for topic in ALL_TOPICS
    }

    # At-least-once: the same message arrives twice more.
    for message_id in message_ids.values():
        bus.redeliver(message_id)
        bus.redeliver(message_id)

    for topic in ALL_TOPICS:
        assert executions[topic] == 1, f"{topic} executed {executions[topic]} times"
        assert consumers[topic].delivered == 1
        assert consumers[topic].suppressed == 2


def test_distinct_dedup_keys_are_not_suppressed(bus: LocalBus) -> None:
    """Deduplication must key on identity, not on topic traffic."""
    executed: list[str] = []
    consumer = IdempotentConsumer(
        lambda m: executed.append(m.data["conclusion_id"]), name="rederive"
    )
    bus.subscribe("node.rederive", consumer)

    for i in range(3):
        bus.publish(
            "node.rederive",
            {"conclusion_id": f"cnc_{i:06d}"},
            dedup_key=f"clm_000000:cnc_{i:06d}",
        )

    assert executed == ["cnc_000000", "cnc_000001", "cnc_000002"]
    assert consumer.suppressed == 0


def test_publishing_to_an_uncreated_topic_fails_loudly() -> None:
    bus = LocalBus()
    with pytest.raises(KeyError):
        bus.publish("claim.retracted", {"claim_id": "clm_000000"})
