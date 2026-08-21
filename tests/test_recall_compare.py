"""The recall comparison must refuse to measure a stub.

This is the guard that keeps `docs/LIVE-VERIFICATION.md` honest. If it ever
passes against `ScriptedT2Model`, the document fills with numbers that read as
measurements and are not, which is the single worst failure available to this
project.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from judgment.model import ModelReply, ScriptedT2Model, UnavailableT2Model
from judgment.recall_compare import (
    RecallComparison,
    StubRefusedError,
    _parse_value,
    compare,
    render_markdown,
)
from lib.config import MODEL_FAST

NOW = datetime(2026, 7, 6, 9, 0, tzinfo=UTC)


def _artifact() -> dict:
    return {
        "artifact_id": "art_test",
        "subject": "supplier_K",
        "source_id": "src_supplier_K",
        "received_at": "2026-01-05T09:00:00Z",
        "text": "our standard lead time is 11 days from receipt of a clean order.",
        "gold_claims": [
            {
                "canonical": "supplier_K.lead_time_days",
                "suffix": "lead_time_days",
                "unit": "days",
                "value": 11.0,
            }
        ],
    }


def test_the_scripted_stub_is_refused() -> None:
    with pytest.raises(StubRefusedError) as exc:
        compare([_artifact()], model=ScriptedT2Model(), as_of=NOW)
    assert "not a live model" in str(exc.value)


def test_an_unavailable_model_is_refused() -> None:
    with pytest.raises(StubRefusedError):
        compare([_artifact()], model=UnavailableT2Model(), as_of=NOW)


def test_a_model_that_merely_renames_itself_is_still_refused() -> None:
    """VACUITY: the guard must check behaviour, not the model_id string.

    A stub relabelled with the real production model id is still a stub. The probe
    makes a real call and requires a non-empty reply, so renaming cannot get past it.
    """

    class _RenamedStub:
        # The real production model id, imported rather than written out, so
        # this stays a stub-wearing-the-real-name test AND keeps the model
        # string in lib/config.py alone.
        model_id = MODEL_FAST

        def complete(self, prompt: str, *, purpose: str) -> ModelReply:
            return ModelReply(text="", model=self.model_id, available=False)

    with pytest.raises(StubRefusedError):
        compare([_artifact()], model=_RenamedStub(), as_of=NOW)


def test_the_guard_is_not_vacuous_a_responding_model_gets_through() -> None:
    """The complement: something that actually answers must be allowed to run."""

    class _Responder:
        model_id = "fake-live"

        def complete(self, prompt: str, *, purpose: str) -> ModelReply:
            if purpose == "probe":
                return ModelReply(text="7", model=self.model_id)
            return ModelReply(text='{"value": 11}', model=self.model_id)

    result = compare([_artifact()], model=_Responder(), as_of=NOW)
    assert isinstance(result, RecallComparison)
    assert result.gold >= 1


def test_the_prompt_never_carries_the_gold_value() -> None:
    """A model shown the answer would score 100% and prove nothing."""
    seen: list[str] = []

    class _Recorder:
        model_id = "fake-live"

        def complete(self, prompt: str, *, purpose: str) -> ModelReply:
            if purpose == "probe":
                return ModelReply(text="7", model=self.model_id)
            seen.append(prompt)
            return ModelReply(text='{"value": null}', model=self.model_id)

    artifact = _artifact()
    # Force a parser miss so pass 2 actually runs.
    artifact["text"] = "our turnaround is ten working days from a clean order."
    artifact["gold_claims"][0]["value"] = 10.0
    compare([artifact], model=_Recorder(), as_of=NOW)

    assert seen, "pass 2 never ran, so this test proves nothing"
    for prompt in seen:
        assert "10.0" not in prompt
        assert "gold" not in prompt.lower()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('{"value": 11}', 11.0),
        ('{"value": 11.5}', 11.5),
        ('{"value": null}', None),
        ('```json\n{"value": 12}\n```', 12.0),
        ("The answer is 14 days.", 14.0),
        ("no number here", None),
    ],
)
def test_reply_parsing_tolerates_a_chatty_model(raw: str, expected: float | None) -> None:
    assert _parse_value(raw) == expected


def test_rendered_markdown_states_the_method() -> None:
    comparison = RecallComparison(model_id=MODEL_FAST)
    body = render_markdown(comparison, ran_at=NOW, project="proj")
    assert "never sees the gold" in body
    assert "refuses to run against `ScriptedT2Model`" in body
