"""The T2 model surface, and the three things that can be behind it.

    VertexT2Model     the real one. [VERIFIED] -- executed live against Vertex.
    ScriptedT2Model   deterministic, for tests and evals. Labelled everywhere.
    UnavailableT2Model what you get when Vertex is off. Returns UNRESOLVED.

WHY THE UNAVAILABLE CASE IS A CLASS AND NOT AN EXCEPTION
--------------------------------------------------------
Locked decision 2.2 says T2 is additive: with Vertex gone, T2 nodes render as
UNRESOLVED, never as silently resolved. If unavailability raised, every call
site would need a try/except and one of them would eventually swallow it into a
default. Making it a model that answers "I could not determine this" means the
degraded path is the same code path, and the honest answer is the only answer it
can give.

⚠ EVERY NUMBER THIS REPOSITORY REPORTS ABOUT T2 CAME FROM `ScriptedT2Model`.
That is a harness measuring itself on the model's side, and it is labelled as
such in `docs/COVERAGE.md`, in the eval output, and in the README. What the
scripted model does measure honestly is the ORCHESTRATION: separation of
principals, blindness, timeout handling, and whether an unavailable model
produces UNRESOLVED rather than a guess.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol

from lib.config import get_config
from lib.telemetry import model_call_span


@dataclass(frozen=True)
class ModelReply:
    """One model answer, with everything needed to audit it."""

    text: str
    model: str
    #: None when the model could not be reached at all.
    available: bool = True
    reason_unavailable: str | None = None
    prompt_tokens: int = 0
    response_tokens: int = 0

    def as_json(self) -> dict[str, Any] | None:
        """Parse the reply as JSON, or None. A malformed reply is not a guess."""
        try:
            return json.loads(self.text)
        except (json.JSONDecodeError, TypeError):
            return None


class T2Model(Protocol):
    model_id: str

    def complete(self, prompt: str, *, purpose: str) -> ModelReply: ...


@dataclass
class UnavailableT2Model:
    """The honest answer when there is no model. Never raises, never guesses."""

    model_id: str = "unavailable"
    reason: str = "Vertex AI is disabled or unreachable."

    def complete(self, prompt: str, *, purpose: str) -> ModelReply:
        with model_call_span(self.model_id, purpose=purpose) as span:
            span.set_attribute("unwind.model_available", False)
            return ModelReply(
                text="",
                model=self.model_id,
                available=False,
                reason_unavailable=self.reason,
            )


@dataclass
class ScriptedT2Model:
    """Deterministic replies keyed by purpose. For tests and evals ONLY.

    It does not simulate a language model and does not pretend to. It returns
    fixed, correct-shaped answers so that the code AROUND the model -- the
    blindness boundary, the principal separation, the under-reporting bias, the
    UNRESOLVED path -- can be exercised and measured without credentials.
    """

    model_id: str = "scripted-stub"
    replies: dict[str, str] = field(default_factory=dict)
    calls: list[tuple[str, str]] = field(default_factory=list)
    #: Set to make the next call behave as a timeout.
    fail_next: str | None = None

    def complete(self, prompt: str, *, purpose: str) -> ModelReply:
        with model_call_span(self.model_id, purpose=purpose) as span:
            self.calls.append((purpose, prompt))
            if self.fail_next:
                reason, self.fail_next = self.fail_next, None
                span.set_attribute("unwind.model_available", False)
                return ModelReply(
                    text="",
                    model=self.model_id,
                    available=False,
                    reason_unavailable=reason,
                )
            text = self.replies.get(purpose, "")
            span.set_attribute("unwind.model_available", True)
            span.set_attribute("unwind.response_chars", len(text))
            return ModelReply(
                text=text,
                model=self.model_id,
                prompt_tokens=len(prompt) // 4,
                response_tokens=len(text) // 4,
            )


@dataclass
class VertexT2Model:
    """The real path. [VERIFIED] -- executed against live Vertex on 2026-08-13.

    `make verify-live` drove this class against a real endpoint: 60 T2 nodes,
    **120 model calls** (one re-derivation and one assessment each), **zero
    exceptions**. The orchestration around the model is therefore proven end to
    end, and `docs/LIVE-VERIFICATION.md` is the record.

    ⚠ WHAT THAT RUN DID *NOT* PROVE. It resolved **0 of 60**. Every node in the
    T2 queue carries `committed_lead_days = None`, so `assess()` short-circuits
    to UNRESOLVED *before* the model's answer is consulted. The outcome was
    fixed by the corpus, not decided by Gemini. Plumbing: verified. Judgement
    quality: still unmeasured -- see `docs/T2-MEASUREMENT.md`.
    """

    model_id: str

    def complete(self, prompt: str, *, purpose: str) -> ModelReply:
        from lib.vertex import get_vertex_client  # noqa: PLC0415

        with model_call_span(self.model_id, purpose=purpose) as span:
            try:
                client = get_vertex_client()
                text = client.generate_text(prompt)
            except Exception as exc:  # noqa: BLE001
                # Any failure to reach the model is an UNRESOLVED, not a raise.
                # The caller must be able to render "could not determine".
                span.set_attribute("unwind.model_available", False)
                return ModelReply(
                    text="",
                    model=self.model_id,
                    available=False,
                    reason_unavailable=f"{type(exc).__name__}: {exc}",
                )
            span.set_attribute("unwind.model_available", True)
            span.set_attribute("unwind.response_chars", len(text))
            return ModelReply(
                text=text,
                model=self.model_id,
                prompt_tokens=len(prompt) // 4,
                response_tokens=len(text) // 4,
            )


def get_model(deep: bool = False) -> T2Model:
    """Resolve the model for this process.

    Returns `UnavailableT2Model` when Vertex is disabled, which is what makes
    `UNWIND_VERTEX_DISABLED=1` produce UNRESOLVED nodes rather than an exception
    or, far worse, a default.
    """
    cfg = get_config()
    if cfg.vertex_disabled:
        return UnavailableT2Model(
            reason="UNWIND_VERTEX_DISABLED=1: no model may be called on this run."
        )
    return VertexT2Model(model_id=cfg.model_deep if deep else cfg.model_fast)
