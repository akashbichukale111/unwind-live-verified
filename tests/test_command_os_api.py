"""API-level tests for the Agentic Command OS surface
(`/api/command-os/*`), independent of the six existing cards' endpoints,
which this suite never touches or breaks.
"""

from __future__ import annotations

import os
import socket

import pytest
from fastapi.testclient import TestClient

from services.api.main import app

#: Every mutating Command OS route is authenticated now (see
#: `tests/test_api_auth.py`'s route-table walk). These tests run as a real
#: human principal; the anonymous-refusal cases live in `test_api_auth.py`
#: and `test_adversarial.py` so this file stays about wiring.
AUTH = {"Authorization": "Bearer api-test-tok"}


@pytest.fixture(autouse=True)
def _credentials(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("UNWIND_OPERATOR_TOKENS", "api-test-tok:api-test@example.com")
    monkeypatch.setenv("UNWIND_VERTEX_DISABLED", "1")
    monkeypatch.setenv("UNWIND_COUNTERSIGN_SIMULATED", "1")
    monkeypatch.delenv("UNWIND_ENV", raising=False)
    from services.api.security import reset_rate_limits

    reset_rate_limits()
    # Start from a known ledger state. Without this, a mission run by an
    # earlier test leaves the Remediation agent's warrant partly spent, and
    # the next mission's challenger correctly refuses on AUTHORITY EXCEEDS
    # EVIDENCE grounds -- real behaviour (the economy depletes), but it makes
    # this file's wiring assertions depend on execution order.
    if _emulator_up():
        from command_os.mission import reset_for_test

        reset_for_test()
    yield
    reset_rate_limits()


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


def test_status_serves_the_system_reality_table_even_offline() -> None:
    """No Firestore dependency -- `system_reality()` is static composition
    over already-in-memory constants, the same offline-safe discipline
    `/api/singularity`'s reference content already follows."""
    with TestClient(app) as client:
        body = client.get("/api/command-os/status").json()
    assert body["auth"]["anonymous_mutation_possible"] is False
    assert "simulation_policy" in body
    assert "external_action" in body
    areas = {row["area"] for row in body["rows"]}
    assert areas == {"Singularity-Mesh", "Hyperion-Zero", "Agentic Command OS"}
    statuses = {row["status"] for row in body["rows"]}
    # The vocabulary grew with the rewrite. Every value must still be an
    # honest label from the closed set -- a qualified LIVE (which backend,
    # which mode) is more honest than a bare one, and CONFIGURED_NOT_EXERCISED
    # is what a real integration with no credential must say.
    allowed = {
        "LIVE",
        "LIVE (ZERO-MODEL)",
        "LIVE (SANDBOX BACKEND)",
        "LIVE (TEST SUITE)",
        "LIVE (DISPLAY FILTER)",
        "CONFIGURED_NOT_EXERCISED",
        "REFERENCE",
        "ARCHITECTURE",
        "SIMULATED",
        "DESIGNED",
    }
    assert statuses <= allowed, f"unlabelled status values: {statuses - allowed}"
    # Nothing may claim live Gemini use: no credentials were available.
    gemini = next(r for r in body["rows"] if r["feature"] == "gemini_planning")
    assert gemini["status"] == "CONFIGURED_NOT_EXERCISED"


def test_concept_map_maps_all_fifteen_names() -> None:
    with TestClient(app) as client:
        body = client.get("/api/command-os/concept-map").json()
    assert len(body["rows"]) == 15
    names = {row["name"] for row in body["rows"]}
    assert "Chronos-9" in names
    assert "Pandora" in names
    assert all(row["status"] for row in body["rows"])


@requires_emulator
def test_mission_endpoint_runs_end_to_end() -> None:
    with TestClient(app) as client:
        resp = client.post("/api/command-os/mission", headers=AUTH)
    assert resp.status_code == 200
    body = resp.json()
    # A mission's length now varies by objective, so the assertion is on the
    # SHAPE rather than a fixed count: the plan is served, the trace matches
    # it, and the report is folded from what ran.
    assert body["plan"] is not None
    assert body["stages"][0]["name"].startswith("PLAN")
    assert body["stages"][-1]["name"].startswith("REPORT")
    assert body["report"]["status"] == body["status"]
    assert body["report"]["human_principal"] == "human::api-test@example.com"
    assert body["correlation_id"]


@requires_emulator
def test_gate_pause_approve_deny_and_resume_via_http() -> None:
    from command_os.mission import reset_for_test

    with TestClient(app) as client:
        paused = client.post("/api/command-os/mission?auto_approve=false", headers=AUTH).json()
        assert paused["status"] == "AWAITING_HUMAN"
        assert paused["report"] is None
        mission_id = paused["mission_id"]

        # the crash-recovery endpoint refuses a gated mission
        refused = client.post(f"/api/command-os/mission/{mission_id}/resume", headers=AUTH)
        assert refused.status_code == 409

        # an invalid decision is rejected before touching the mission
        bad = client.post(f"/api/command-os/mission/{mission_id}/gate?decision=maybe", headers=AUTH)
        assert bad.status_code == 422

        approved = client.post(
            f"/api/command-os/mission/{mission_id}/gate?decision=approve", headers=AUTH
        ).json()
        assert approved["status"] != "AWAITING_HUMAN"
        # The APPROVER is recorded, and it is the authenticated caller.
        assert approved["decided_by"] == "human::api-test@example.com"
        assert approved["report"]["human_principal"] == "human::api-test@example.com"
        assert approved["report"]["human_decision_mode"] == "explicit_gate_decision"

        checkpoints = client.get(
            f"/api/command-os/mission/{mission_id}/checkpoints", headers=AUTH
        ).json()
        assert len(checkpoints["checkpoints"]) == len(approved["stages"])
    reset_for_test(mission_id)


@requires_emulator
def test_trust_and_context_firewall_endpoints_are_wired() -> None:
    from command_os.mission import reset_for_test

    with TestClient(app) as client:
        result = client.post("/api/command-os/mission", headers=AUTH).json()
        mission_id = result["mission_id"]

        trust = client.get(f"/api/command-os/mission/{mission_id}/trust", headers=AUTH).json()
        assert trust["mission_status"] == result["status"]

        firewall = client.get(
            f"/api/command-os/mission/{mission_id}/context-firewall", headers=AUTH
        ).json()
        assert len(firewall["decisions"]) == len(result["stages"])

        missions = client.get("/api/command-os/missions", headers=AUTH).json()
        assert missions["available"] is True
        assert mission_id in {m["mission_id"] for m in missions["missions"]}
    reset_for_test(mission_id)


def test_checkpoints_for_an_unknown_mission_is_404() -> None:
    if not _emulator_up():
        pytest.skip("needs the emulator to reach Firestore at all")
    with TestClient(app) as client:
        resp = client.get(
            "/api/command-os/mission/mission_does_not_exist/checkpoints", headers=AUTH
        )
    assert resp.status_code == 404


def test_mission_endpoint_without_emulator_reports_unavailable_not_a_crash() -> None:
    """When Firestore is unreachable, the mission endpoint must fail the
    same honest way `/api/instrument/burn` and `/api/instrument/earn`
    already do -- a 503, never a 500 or a fabricated trace."""
    if _emulator_up():
        pytest.skip("this test asserts the no-emulator path specifically")
    with TestClient(app) as client:
        resp = client.post("/api/command-os/mission", headers=AUTH)
    assert resp.status_code == 503


def test_existing_six_card_endpoints_still_respond() -> None:
    """Regression guard: adding the Command OS layer must not disturb
    Cards 0-5's endpoints."""
    with TestClient(app) as client:
        assert client.get("/api/instrument").status_code == 200
        assert client.get("/api/hyperion").status_code == 200
        assert client.get("/api/singularity").status_code == 200
