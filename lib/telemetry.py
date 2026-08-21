"""OpenTelemetry setup and the four span kinds UNWIND cares about.

A cascade is a fan-out over thousands of conclusions, most of which die
silently. When one of them wrongly survives -- or worse, wrongly dies -- the
only way to find out why is a trace that records which tier made the call.
Every span therefore carries `unwind.tier`, so a T2 span appearing inside a
cascade that was supposed to run model-free is visible rather than inferred.

Exports to Cloud Trace when credentials exist, console otherwise. Never both,
never silently neither.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

from lib.config import Tier, get_config

_CONFIGURED = False
#: Set at configure() time so callers can report honestly which exporter is live.
EXPORTER_IN_USE: str = "not-configured"


def configure_telemetry(force: bool = False) -> str:
    """Install the tracer provider. Returns the exporter actually in use."""
    global _CONFIGURED, EXPORTER_IN_USE
    if _CONFIGURED and not force:
        return EXPORTER_IN_USE

    cfg = get_config()
    resource = Resource.create(
        {
            "service.name": cfg.otel_service_name,
            "service.version": "0.1.0",
            "unwind.project_id": cfg.project_id,
            "unwind.vertex_location": cfg.vertex_location,
        }
    )
    provider = TracerProvider(resource=resource)

    exporter_name = "console"
    if cfg.has_gcp_credentials and not cfg.uses_emulator:
        try:
            from opentelemetry.exporter.cloud_trace import (  # noqa: PLC0415
                CloudTraceSpanExporter,
            )

            provider.add_span_processor(
                BatchSpanProcessor(CloudTraceSpanExporter(project_id=cfg.project_id))
            )
            exporter_name = "cloud-trace"
        except Exception as exc:  # pragma: no cover - depends on credentials
            print(
                f"[telemetry] Cloud Trace exporter unavailable ({exc}); falling back to console.",
                file=sys.stderr,
            )

    if exporter_name == "console" and cfg.otel_console_export:
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

    trace.set_tracer_provider(provider)
    _CONFIGURED = True
    EXPORTER_IN_USE = exporter_name
    return exporter_name


def get_tracer(name: str = "unwind") -> trace.Tracer:
    configure_telemetry()
    return trace.get_tracer(name)


# ---------------------------------------------------------------------------
# The four span helpers. Task 2+ uses these; they exist now so the attribute
# names are settled before there are hundreds of call sites.
# ---------------------------------------------------------------------------


@contextmanager
def _span(kind: str, name: str, tier: Tier, **attrs: Any) -> Iterator[trace.Span]:
    tracer = get_tracer()
    with tracer.start_as_current_span(f"{kind}:{name}") as span:
        span.set_attribute("unwind.span_kind", kind)
        span.set_attribute("unwind.tier", tier.value)
        for key, value in attrs.items():
            if value is not None:
                span.set_attribute(f"unwind.{key}", value)
        yield span


@contextmanager
def agent_decision_span(agent_id: str, tier: Tier, **attrs: Any) -> Iterator[trace.Span]:
    """An agent choosing one of the five decision states (locked decision 1.5)."""
    with _span("agent_decision", agent_id, tier, agent_id=agent_id, **attrs) as span:
        yield span


@contextmanager
def tool_call_span(tool_name: str, tier: Tier, **attrs: Any) -> Iterator[trace.Span]:
    with _span("tool_call", tool_name, tier, tool=tool_name, **attrs) as span:
        yield span


@contextmanager
def policy_gate_span(gate_name: str, tier: Tier, **attrs: Any) -> Iterator[trace.Span]:
    """A deterministic gate, e.g. the retraction-authority check (1.4).

    Always T0/T1. A policy gate that needed a model would not be a gate.
    """
    with _span("policy_gate", gate_name, tier, gate=gate_name, **attrs) as span:
        yield span


@contextmanager
def model_call_span(model: str, **attrs: Any) -> Iterator[trace.Span]:
    """A Vertex call. Always T2 by definition -- there is no other kind."""
    with _span("model_call", model, Tier.T2, model=model, **attrs) as span:
        yield span
