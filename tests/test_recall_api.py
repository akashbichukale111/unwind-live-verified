"""The recall and architecture-proof routes: authenticated, honest, and
generated from the code they describe.
"""

from __future__ import annotations

import os
import socket

import pytest
from fastapi.testclient import TestClient

from services.api.main import app

AUTH = {"Authorization": "Bearer api-test-tok"}


def _emulator_up() -> bool:
    host = os.environ.get("FIRESTORE_EMULATOR_HOST", "localhost:8080")
    hostname, _, port = host.partition(":")
    try:
        with socket.create_connection((hostname, int(port or 8080)), timeout=1.0):
            return True
    except OSError:
        return False


requires_emulator = pytest.mark.skipif(
    not _emulator_up(), reason="Firestore emulator not running; start it with `make emulator`"
)


@pytest.fixture(autouse=True)
def _credentials(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("UNWIND_OPERATOR_TOKENS", "api-test-tok:api-test@example.com")
    monkeypatch.setenv("UNWIND_VERTEX_DISABLED", "1")
    monkeypatch.setenv("UNWIND_COUNTERSIGN_SIMULATED", "1")
    monkeypatch.delenv("UNWIND_ENV", raising=False)
    from services.api.security import reset_rate_limits

    reset_rate_limits()
    if _emulator_up():
        from command_os.mission import reset_for_test
        from recall.store import reset_for_test as reset_recall

        reset_recall()
        reset_for_test()
    yield


# ===========================================================================
# Authentication
# ===========================================================================


@pytest.mark.parametrize(
    "path",
    [
        "/api/recall/corpus",
        "/api/recall/search?q=fleet_recon",
        "/api/recall/mission/mission_x",
    ],
)
def test_recall_routes_refuse_an_anonymous_caller(path: str) -> None:
    """Knowledge carries mission provenance and evidence detail; reading it is
    a privileged read, exactly like a checkpoint read."""
    with TestClient(app) as client:
        assert client.get(path).status_code == 401


def test_there_is_no_write_route_into_the_knowledge_store() -> None:
    """The store has exactly one writer, in-process, after a terminal report.
    An HTTP write path would make it an injection surface reachable from
    outside -- guarded, but a door nobody needs."""
    recall_routes = [
        (r.path, sorted(r.methods))
        for r in app.routes
        if getattr(r, "path", "").startswith("/api/recall")
    ]
    assert recall_routes
    for path, methods in recall_routes:
        assert set(methods) <= {"GET", "HEAD"}, f"{path} accepts {methods}"


# ===========================================================================
# Retrieval, over a real corpus
# ===========================================================================


@requires_emulator
def test_search_reports_what_it_left_behind_not_only_what_it_returned() -> None:
    from command_os.mission import run_mission

    run_mission(
        "Investigate an anomalous finance capability request.",
        principal="human::test",
        auth_method="test",
        allow_model=False,
    )
    with TestClient(app) as client:
        body = client.get("/api/recall/search?q=fleet_recon+escalation&k=2", headers=AUTH).json()

    assert body["available"] is True
    assert body["considered"] > len(body["selected"])
    assert (
        body["zero_scored"] + body["dropped_for_budget"] + len(body["selected"])
        == body["considered"] - body["filtered_out"]
    )
    assert 0 < body["selection_ratio"] < 1
    for item in body["selected"]:
        assert item["record"]["mission_id"]
        assert item["matched_terms"]


@requires_emulator
def test_the_mission_route_shows_both_what_was_consulted_and_what_was_produced() -> None:
    from command_os.mission import reset_for_test, run_mission

    first = run_mission(
        "Investigate an anomalous finance capability request.",
        principal="human::test",
        auth_method="test",
        allow_model=False,
    )
    reset_for_test()
    second = run_mission(
        "Investigate an anomalous finance capability request.",
        principal="human::test",
        auth_method="test",
        allow_model=False,
    )

    with TestClient(app) as client:
        one = client.get(f"/api/recall/mission/{first.mission_id}", headers=AUTH).json()
        two = client.get(f"/api/recall/mission/{second.mission_id}", headers=AUTH).json()

    assert one["consulted"]["corpus_records"] == 0
    assert one["produced"], "the first mission produced no knowledge"

    assert two["consulted"]["selected"] > 0
    assert two["scrutiny_applied"]
    assert two["risk_profile"] != two["risk_profile_before_recall"]
    assert all(r["mission_id"] == first.mission_id for r in two["consulted"]["selected_records"])


@requires_emulator
def test_an_unknown_mission_is_a_404_not_an_empty_success() -> None:
    with TestClient(app) as client:
        assert client.get("/api/recall/mission/nope", headers=AUTH).status_code == 404


@requires_emulator
def test_an_unknown_record_kind_is_rejected_rather_than_ignored() -> None:
    with TestClient(app) as client:
        resp = client.get("/api/recall/search?q=x&kind=NONSENSE", headers=AUTH)
    assert resp.status_code == 400


@requires_emulator
def test_the_corpus_route_counts_what_is_there_and_says_when_it_truncated() -> None:
    from command_os.mission import run_mission

    run_mission(principal="human::test", auth_method="test", allow_model=False)
    with TestClient(app) as client:
        body = client.get("/api/recall/corpus", headers=AUTH).json()
    assert body["available"] is True
    assert body["records"] > 0
    assert body["missions"] == 1
    assert body["truncated"] is False
    assert body["by_kind"]


# ===========================================================================
# Architecture proof: generated from the enforcing modules
# ===========================================================================


def test_the_architecture_proof_matches_the_registry_it_describes() -> None:
    from fleet.roles import ALL_ROLES

    with TestClient(app) as client:
        body = client.get("/api/architecture/proof").json()

    served = {row["agent_id"]: row for row in body["fleet"]}
    assert set(served) == {r.agent_id for r in ALL_ROLES}
    for role in ALL_ROLES:
        row = served[role.agent_id]
        assert row["authority_scope"] == list(role.authority_scope)
        assert row["tools"] == list(role.tools)
        assert row["principal"] == role.principal

    # The properties the whole permission model rests on, readable from the
    # route rather than from a paragraph.
    writers = [row["agent_id"] for row in body["fleet"] if row["can_write"]]
    assert writers == ["fleet_remediation"]
    assert not any(row["can_read_secrets"] for row in body["fleet"])


def test_the_architecture_proof_reports_the_real_bounds() -> None:
    from command_os.mission import MAX_MISSION_PHASES, TOOL_TIMEOUT_SECONDS

    with TestClient(app) as client:
        bounds = client.get("/api/architecture/proof").json()["bounds"]
    assert bounds["tool_timeout_seconds"] == TOOL_TIMEOUT_SECONDS
    assert bounds["max_mission_phases"] == MAX_MISSION_PHASES


def test_the_architecture_proof_lists_a_contract_for_every_tool() -> None:
    from fleet.tools import TOOL_REGISTRY

    with TestClient(app) as client:
        body = client.get("/api/architecture/proof").json()
    contracted = {row["tool"] for row in body["output_contracts"]}
    assert set(TOOL_REGISTRY) <= contracted


def test_the_architecture_proof_shows_the_directive_has_no_widening_field() -> None:
    with TestClient(app) as client:
        guard = client.get("/api/architecture/proof").json()["recall_guard"]
    assert "scope" not in guard["directive_fields"]
    assert "raise_risk_class" in guard["directive_fields"]
    assert guard["grant_language_markers"] > 0
