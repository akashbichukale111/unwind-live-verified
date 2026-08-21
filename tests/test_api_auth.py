"""Every mutating route requires a real principal -- asserted structurally.

The route-table walk below is the important test in this file. A behavioural
test only covers the endpoints someone remembered to write a case for; this
one fails the moment a POST route is added without an authentication
dependency, which is exactly how the previous unauthenticated gate would
have been caught.
"""

from __future__ import annotations

import os
import socket

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from services.api.main import app
from services.api.security import require_human_principal, require_principal, reset_rate_limits

AUTH_DEPENDENCIES = {require_principal, require_human_principal}


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
def _clean_limits():
    reset_rate_limits()
    yield
    reset_rate_limits()


def _route_dependencies(route: APIRoute) -> set:
    return {d.call for d in route.dependant.dependencies}


def test_every_mutating_route_requires_a_principal() -> None:
    """THE structural guarantee. A POST/PUT/PATCH/DELETE route with no
    authentication dependency is a test failure, not a review miss."""
    unprotected: list[str] = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        mutating = {"POST", "PUT", "PATCH", "DELETE"} & set(route.methods or ())
        if not mutating:
            continue
        if not (_route_dependencies(route) & AUTH_DEPENDENCIES):
            unprotected.append(f"{sorted(mutating)} {route.path}")
    assert not unprotected, (
        "these mutating routes have no authentication dependency: "
        f"{unprotected}. Add Depends(require_principal) or "
        "Depends(require_human_principal) in services/api/main.py."
    )


def test_the_human_gate_specifically_requires_a_human_principal() -> None:
    gate = next(
        r
        for r in app.routes
        if isinstance(r, APIRoute) and r.path.endswith("/gate") and "POST" in (r.methods or ())
    )
    assert require_human_principal in _route_dependencies(gate)


def test_anonymous_mission_run_is_refused() -> None:
    with TestClient(app) as client:
        assert client.post("/api/command-os/mission").status_code == 401


def test_anonymous_approval_rejected() -> None:
    """The exact request that used to mint warrant for nobody."""
    with TestClient(app) as client:
        response = client.post("/api/command-os/mission/anything/gate?decision=approve")
    assert response.status_code == 401


def test_anonymous_warrant_mutation_is_refused() -> None:
    with TestClient(app) as client:
        assert client.post("/api/instrument/earn").status_code == 401
        assert client.post("/api/instrument/burn").status_code == 401


def test_service_token_cannot_approve_at_the_gate(monkeypatch) -> None:
    monkeypatch.setenv("UNWIND_OPERATOR_TOKENS", "svc-tok:service::ci-runner")
    with TestClient(app) as client:
        response = client.post(
            "/api/command-os/mission/anything/gate?decision=approve",
            headers={"Authorization": "Bearer svc-tok"},
        )
    assert response.status_code == 403, "a service identity must not satisfy the human gate"


def test_status_and_fleet_stay_public() -> None:
    """A judge must be able to read the system's own reality panel and the
    fleet's permissions without a credential. Neither reveals a secret and
    neither mutates anything."""
    with TestClient(app) as client:
        assert client.get("/api/command-os/status").status_code == 200
        assert client.get("/api/command-os/fleet").status_code == 200
        assert client.get("/api/command-os/economics").status_code == 200


def test_rate_limit_engages_per_principal(monkeypatch) -> None:
    from services.api.security import RATE_LIMIT_REQUESTS

    monkeypatch.setenv("UNWIND_OPERATOR_TOKENS", "rl-tok:rl@example.com")
    headers = {"Authorization": "Bearer rl-tok"}
    with TestClient(app) as client:
        codes = [
            client.get("/api/command-os/missions", headers=headers).status_code
            for _ in range(RATE_LIMIT_REQUESTS + 3)
        ]
    assert 429 in codes, "the limiter never engaged"


@requires_emulator
def test_authenticated_principal_is_the_one_recorded(monkeypatch) -> None:
    """End to end: the principal in the concurrence record is the caller's.

    This is the positive half of the anonymous-approval fix. It is not enough
    that anonymous is refused; the recorded actor must be whoever actually
    authenticated.
    """
    monkeypatch.setenv("UNWIND_OPERATOR_TOKENS", "real-tok:kim@ops.example")
    monkeypatch.setenv("UNWIND_COUNTERSIGN_SIMULATED", "1")
    monkeypatch.setenv("UNWIND_VERTEX_DISABLED", "1")
    from command_os.mission import reset_for_test

    reset_for_test()
    with TestClient(app) as client:
        response = client.post(
            "/api/command-os/mission", headers={"Authorization": "Bearer real-tok"}
        )
    assert response.status_code == 200
    body = response.json()
    assert body["report"]["human_principal"] == "human::kim@ops.example"
    assert "human::mission_operator" not in response.text, (
        "the retired hardcoded principal must never appear in a mission response"
    )
