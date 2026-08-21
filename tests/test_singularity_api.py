"""API-level tests for Singularity-Mesh's endpoints: the sixth card's
`/api/singularity*` surface, independent of `/api/hyperion*` and
`/api/instrument*`, which this suite never touches or breaks.
"""

from __future__ import annotations

import os
import socket

import pytest
from fastapi.testclient import TestClient

from services.api.main import app
from singularity.lifecycle import IMPLEMENTATION_STATUS

#: The probe endpoints WRITE to the mesh event log, so they are mutating and
#: therefore authenticated -- see `tests/test_api_auth.py`'s route-table walk.
#: Reads stay public. This header is what a probe caller now supplies.
AUTH = {"Authorization": "Bearer probe-tok"}


@pytest.fixture(autouse=True)
def _probe_credential(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("UNWIND_OPERATOR_TOKENS", "probe-tok:probe@example.com")
    from services.api.security import reset_rate_limits

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


def test_singularity_summary_serves_reference_content_even_offline() -> None:
    """The static architecture/fleet/lifecycle content must render even
    without the emulator -- only the live mesh-event aggregate is gated,
    the same honest-degrade discipline `/api/hyperion` uses."""
    with TestClient(app) as client:
        body = client.get("/api/singularity").json()
    assert len(body["fleet"]) == 7  # Sentinel + Orchestrator + 5 workers
    assert len(body["lifecycle_stages"]) == 15
    assert len(body["architecture_layers"]) == 7
    assert len(body["immune_layers"]) == 3
    assert body["implementation_status"] == IMPLEMENTATION_STATUS
    assert "mesh_available" in body


@requires_emulator
def test_genome_probe_normal_scenario_allows() -> None:
    with TestClient(app) as client:
        client.post(
            "/api/singularity/behavior/probe?scenario=normal", headers=AUTH
        )  # warm the collection
        resp = client.post("/api/singularity/genome/probe?scenario=normal", headers=AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["genome"]["decision"] == "ALLOW"


@requires_emulator
def test_genome_probe_attack_scenario_denies_the_export() -> None:
    with TestClient(app) as client:
        resp = client.post("/api/singularity/genome/probe?scenario=attack", headers=AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert "export_all" in body["genome"]["denied_actions"]


@requires_emulator
def test_behavior_probe_drift_scenario_isolates() -> None:
    with TestClient(app) as client:
        resp = client.post("/api/singularity/behavior/probe?scenario=drift", headers=AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["assessment"]["drift_band"] == "CRITICAL"
    assert body["assessment"]["capability_action"] == "ISOLATE"


@requires_emulator
def test_probes_are_reflected_in_the_summary_aggregate() -> None:
    with TestClient(app) as client:
        from singularity.mesh_memory import reset_for_test

        reset_for_test()
        client.post("/api/singularity/genome/probe?scenario=attack", headers=AUTH)
        client.post("/api/singularity/behavior/probe?scenario=drift", headers=AUTH)
        body = client.get("/api/singularity").json()
        reset_for_test()
    assert body["mesh_available"] is True
    assert body["events_total"] == 2
    assert body["capability_denials"] == 1
    assert body["behavioral_isolations"] == 1


def test_existing_hyperion_and_instrument_endpoints_still_respond() -> None:
    """Regression guard: adding the sixth card must not disturb Cards 0-4's
    endpoints."""
    with TestClient(app) as client:
        assert client.get("/api/instrument").status_code == 200
        assert client.get("/api/hyperion").status_code == 200
