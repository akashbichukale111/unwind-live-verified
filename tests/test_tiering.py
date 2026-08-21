"""Tiered degradation is structural, not a convention.

Task 2 must prove the whole cascade runs with Vertex switched off. That proof is
only meaningful if switching Vertex off actually closes the door, so the door is
tested here, before there is anything behind it.
"""

from __future__ import annotations

import os

import pytest

from lib.config import MODEL_FREE_TIERS, Tier, get_config, reset_config_cache
from lib.vertex import VertexDisabledError, get_vertex_client, reset_vertex_client


@pytest.fixture(autouse=True)
def _clean_config(monkeypatch: pytest.MonkeyPatch):
    reset_config_cache()
    reset_vertex_client()
    yield
    reset_config_cache()
    reset_vertex_client()


def test_t0_and_t1_are_declared_model_free() -> None:
    assert MODEL_FREE_TIERS == {Tier.T0, Tier.T1}
    assert Tier.T2 not in MODEL_FREE_TIERS


def test_disabling_vertex_closes_the_only_door_to_a_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("UNWIND_VERTEX_DISABLED", "1")
    reset_config_cache()
    reset_vertex_client()
    assert get_config().vertex_disabled is True
    with pytest.raises(VertexDisabledError):
        get_vertex_client()


def test_vertex_is_enabled_by_default() -> None:
    monkeypatch_free = get_config()
    assert monkeypatch_free.vertex_disabled is False


def test_region_is_pinned_not_inferred() -> None:
    """`global`, and it is a measurement rather than a preference.

    This is the location the Vertex smoke test actually passed on -- request,
    tool call, echo_tier(T0), final response, no 401/403/404. A regional
    endpoint was tried first and is not the verified configuration, so pinning
    the region we merely assumed would put an untested value in the one file
    that is allowed to name it.
    """
    assert get_config().vertex_location == "global"


def test_backend_is_pinned_to_vertex_not_the_bare_gemini_api() -> None:
    """Without this pin, ADK falls through to the developer API and asks for a key."""
    from lib.vertex import configure_vertex_backend

    applied = configure_vertex_backend()
    assert applied["GOOGLE_GENAI_USE_ENTERPRISE"] == "true"
    assert applied["GOOGLE_CLOUD_LOCATION"] == "global"
    assert os.environ["GOOGLE_GENAI_USE_ENTERPRISE"] == "true"
    # The deprecated flag must NOT be set: google-adk 2.6.3 warns on it, and a
    # conflicting pair silently resolves in favour of the enterprise flag.
    assert "GOOGLE_GENAI_USE_VERTEXAI" not in os.environ


def test_smoke_agent_is_constructed_against_the_config_model() -> None:
    from agents.smoke.agent import root_agent

    assert root_agent.model == get_config().gemini_model


def test_telemetry_configures_an_exporter_and_says_which() -> None:
    from lib.telemetry import configure_telemetry

    exporter = configure_telemetry(force=True)
    assert exporter in {"console", "cloud-trace"}
