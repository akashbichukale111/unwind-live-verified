"""The evaluation and evolution API surface.

The authentication assertions here run WITHOUT Firestore, deliberately: the
auth dependency resolves before the route body's availability check, so an
anonymous or agent caller is refused whether or not a database is reachable.
That ordering is the property being pinned -- an authority check that only
runs when the backend happens to be up is not an authority check.

The routes that read or write documents need the emulator and skip without it.
"""

from __future__ import annotations

import os
import socket

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from services.api.main import app
from services.api.security import require_human_principal, require_principal, reset_rate_limits

AUTH = {"Authorization": "Bearer evo-test-tok"}


@pytest.fixture(autouse=True)
def _credentials(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("UNWIND_OPERATOR_TOKENS", "evo-test-tok:evo-test@example.com")
    monkeypatch.setenv("UNWIND_VERTEX_DISABLED", "1")
    monkeypatch.setenv("UNWIND_COUNTERSIGN_SIMULATED", "1")
    monkeypatch.delenv("UNWIND_ENV", raising=False)
    reset_rate_limits()
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


def _route(path: str, method: str = "POST") -> APIRoute:
    return next(
        r
        for r in app.routes
        if isinstance(r, APIRoute) and r.path == path and method in (r.methods or ())
    )


def _dependencies(route: APIRoute) -> set:
    return {d.call for d in route.dependant.dependencies}


# ---------------------------------------------------------------------------
# The authority boundary, asserted structurally and over the wire
# ---------------------------------------------------------------------------


def test_promote_requires_a_human_principal_structurally() -> None:
    """The one route that can change what is serving."""
    assert require_human_principal in _dependencies(_route("/api/evolution/promote"))


def test_rollback_requires_a_human_principal_structurally() -> None:
    assert require_human_principal in _dependencies(_route("/api/evolution/rollback"))


def test_propose_requires_at_least_a_principal() -> None:
    """Proposing is not promoting -- any authenticated principal may generate
    a candidate, because a candidate does not serve."""
    assert require_principal in _dependencies(_route("/api/evolution/propose"))


def test_compare_is_a_get_so_a_dry_run_cannot_mutate() -> None:
    route = _route("/api/evolution/compare", "GET")
    assert "POST" not in (route.methods or ())


@pytest.mark.parametrize(
    "path",
    [
        "/api/evolution/promote?candidate_version_id=v_x",
        "/api/evolution/rollback?rollback_to_version_id=v_x&reason=r",
        "/api/evolution/propose",
    ],
)
def test_anonymous_callers_are_refused_before_any_backend_is_consulted(path) -> None:
    with TestClient(app) as client:
        assert client.post(path).status_code == 401


def test_a_service_credential_cannot_promote(monkeypatch) -> None:
    """A CI robot is not a human. 403, not 401 -- it authenticated fine and
    is simply not permitted to move authority."""
    monkeypatch.setenv("UNWIND_OPERATOR_TOKENS", "svc-tok:service::ci-runner")
    with TestClient(app) as client:
        resp = client.post(
            "/api/evolution/promote?candidate_version_id=v_x",
            headers={"Authorization": "Bearer svc-tok"},
        )
    assert resp.status_code == 403


def test_reading_evaluations_needs_a_principal_but_not_a_human() -> None:
    assert require_principal in _dependencies(_route("/api/evolution/evaluations", "GET"))


# ---------------------------------------------------------------------------
# Wiring, against the emulator
# ---------------------------------------------------------------------------


@requires_emulator
def test_versions_seeds_from_the_live_roster_on_first_read() -> None:
    from evolution.store import reset_for_test

    reset_for_test()
    with TestClient(app) as client:
        body = client.get("/api/evolution/versions?agent_key=orchestrator", headers=AUTH).json()
    assert body["available"] is True
    assert body["active_version_id"], "the serving version must be named"
    assert body["versions"]
    seed = body["versions"][0]
    assert seed["version_n"] == 1
    assert seed["provenance"] == "SEED"

    from fleet.roles import ORCHESTRATOR

    assert seed["instruction"] == ORCHESTRATOR.instruction.strip()


@requires_emulator
def test_proposing_with_a_clean_history_is_a_409_not_an_invented_candidate() -> None:
    """An evolution loop that manufactures a candidate for a clean history is
    a loop that will eventually promote noise."""
    from evolution.store import reset_for_test

    reset_for_test()
    with TestClient(app) as client:
        client.get("/api/evolution/versions", headers=AUTH)
        resp = client.post("/api/evolution/propose?agent_key=orchestrator", headers=AUTH)
    assert resp.status_code == 409
    assert "nothing measured to improve" in resp.json()["detail"]


@requires_emulator
def test_a_mission_writes_a_real_evaluation_of_its_own_trajectory() -> None:
    """Evaluation is production behaviour, not a side tool: running a mission
    scores it, and the score is attributable to the version that was serving."""
    from command_os.mission import reset_for_test as reset_mission
    from evolution.store import reset_for_test

    reset_for_test()
    reset_mission()
    with TestClient(app) as client:
        mission = client.post("/api/command-os/mission", headers=AUTH).json()
        mission_id = mission["mission_id"]
        body = client.get(f"/api/evolution/mission/{mission_id}/evaluation", headers=AUTH).json()

    assert body["available"] is True
    assert body["evaluations"], "a completed mission must be scored"
    evaluation = body["evaluations"][0]
    assert evaluation["mission_id"] == mission_id
    assert len(evaluation["criteria"]) == 7
    assert 0.0 <= evaluation["composite"] <= 1.0
    # The evaluation carries the mission's own status verbatim and can never
    # read better than the mission it scores.
    assert evaluation["outcome"] == mission["status"]
    assert evaluation["agent_version_id"].startswith("v_")


@requires_emulator
def test_an_unscored_mission_returns_empty_rather_than_a_backfilled_score() -> None:
    with TestClient(app) as client:
        body = client.get(
            "/api/evolution/mission/mission_does_not_exist/evaluation", headers=AUTH
        ).json()
    assert body["available"] is True
    assert body["evaluations"] == []


@requires_emulator
def test_history_is_available_and_empty_before_anything_is_decided() -> None:
    from evolution.store import reset_for_test

    reset_for_test()
    with TestClient(app) as client:
        body = client.get("/api/evolution/history", headers=AUTH).json()
    assert body["available"] is True
    assert body["decisions"] == []
