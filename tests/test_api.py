"""The API serves the real cascade, and every number it serves is computed.

A stub that returns a plausible-looking result is the single most damaging thing
this repository could contain. Task 1 tested the SSE endpoint for saying "NOT
BUILT"; now that it IS built, the same suspicion is applied the other way -- the
stream is tested for carrying the cascade's actual verdicts, and for the totals
it reports agreeing with the events it sent.
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from services.api.main import app


def test_healthz_reports_the_real_configuration() -> None:
    with TestClient(app) as client:
        body = client.get("/api/healthz").json()
    assert body["status"] == "ok"
    assert body["stage"] == "task-5-interface"
    assert len(body["topics"]) == 6
    assert body["pubsub"] in {"local-shim", "cloud"}
    assert body["firestore"] in {"emulator", "cloud"}


def _events(raw: str) -> list[tuple[str, dict]]:
    out: list[tuple[str, dict]] = []
    for block in raw.split("\n\n"):
        if not block.strip():
            continue
        name = payload = None
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line[7:]
            elif line.startswith("data: "):
                payload = json.loads(line[6:])
        if name and payload is not None:
            out.append((name, payload))
    return out


def test_cascade_stream_carries_the_real_verdicts() -> None:
    with TestClient(app) as client:
        response = client.get("/api/cascade/stream?pace_ms=0&batch=200")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        events = _events(response.text)

    names = [n for n, _ in events]
    assert names[0] == "begin", "the stream must open with `begin`, not `open`"
    assert names[-1] == "done"

    begin = events[0][1]
    done = events[-1][1]
    # Every node the cascade found was actually sent. A stream that reports a
    # total larger than what it delivered would let the counter lie.
    assert done["sent"] == done["radius"] == begin["radius"]
    assert done["model_calls"] == 0

    delivered = sum(len(p["n"]) for n, p in events if n == "nodes")
    assert delivered == done["radius"]

    # And the regime tallies must partition the radius exactly.
    assert sum(done["regimes"].values()) == done["radius"]
    assert (
        done["immaterial"] + done["closed_out"] + done["unresolved"] + done["material"]
        == (done["radius"])
    )


def test_a_refused_retraction_streams_a_refusal_and_no_radius() -> None:
    with TestClient(app) as client:
        raw = client.get("/api/cascade/stream?source=src_broker_Z&new_value=34&pace_ms=0").text
    events = dict(_events(raw))
    assert "refused" in events
    assert events["refused"]["reason_code"] == "source_outside_claim_scope"
    assert events["refused"]["why"], "a refusal with no stated reason is not a refusal"
    assert events["done"]["radius"] == 0
