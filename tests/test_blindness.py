"""The blindness guard, and the vacuity test that proves the guard works.

Ruling 1.3: every guard ships with a vacuity test. Point the guard at a fixture
known to violate it; if the guard passes, the guard is broken. This is not
ceremony — Task 2's zero-model detector matched module names by exact string and
would have missed `google.genai.types`. Its vacuity test is the only reason
anyone found out.
"""

from __future__ import annotations

import ast
from datetime import UTC, datetime
from pathlib import Path

import pytest

from judgment.model import ScriptedT2Model, UnavailableT2Model
from judgment.rederive import (
    REDERIVER_PRINCIPAL,
    BlindnessViolation,
    BlindStore,
    build_bundle,
    bundle_contains_decision,
    re_derive,
)

REPO = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 7, 6, 9, 0, tzinfo=UTC)

#: Calls that fetch the original decision.
CONCLUSION_CALLS = ("get_conclusion", "get_conclusions")
#: Fields that only exist ON a conclusion. Reading one off a conclusion-shaped
#: object is the anchor; reading `committed_lead_days` off the re-deriver's OWN
#: result is not, which is why the receiver matters and the name alone does not.
CONCLUSION_FIELDS = ("committed_lead_days", "body", "external_effects", "premise_ids")
#: Variable names that hold a conclusion.
CONCLUSION_HOLDERS = ("conclusion", "original", "decision_record", "prior_decision")


def _reaches_conclusion(path: Path) -> list[str]:
    """The guard: does this module read the original decision?

    Precision matters in both directions. Matching bare attribute NAMES fired on
    the re-deriver's own output field — a false positive that would have trained
    everyone to ignore the guard. Matching only exact call names would miss
    `conclusion.committed_lead_days`. So it checks the RECEIVER: an access is a
    violation when the thing being read is conclusion-shaped.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name in CONCLUSION_CALLS:
                hits.append(f"line {node.lineno}: {name}()")
        elif isinstance(node, ast.Attribute) and node.attr in CONCLUSION_FIELDS:
            receiver = getattr(node.value, "id", None) or getattr(node.value, "attr", None)
            if receiver and any(h in str(receiver).lower() for h in CONCLUSION_HOLDERS):
                hits.append(f"line {node.lineno}: {receiver}.{node.attr}")
    return hits


# ---------------------------------------------------------------------------
# The guard
# ---------------------------------------------------------------------------


def test_the_rederiver_never_reads_a_conclusion() -> None:
    """Layer 3: static. The re-derivation module cannot see the original."""
    hits = _reaches_conclusion(REPO / "judgment" / "rederive.py")
    # BlindStore.get_conclusion is the DEFINITION of the refusal, not a read.
    real = [h for h in hits if "get_conclusion()" not in h]
    assert not real, "judgment/rederive.py reaches for the original decision:\n" + "\n".join(real)


# ⚠ THE VACUITY TEST. Without this, the test above proves nothing.
def test_the_guard_catches_a_deliberate_violator() -> None:
    """Point the guard at code known to anchor. It must fire."""
    hits = _reaches_conclusion(REPO / "tests" / "fixtures" / "blindness_violator.py")
    assert hits, (
        "The blindness guard found nothing in a fixture written specifically to "
        "violate it. The guard is broken, not the fixture."
    )
    assert any("committed_lead_days" in h for h in hits)


# ---------------------------------------------------------------------------
# Layer 1: the type has nowhere to put a conclusion
# ---------------------------------------------------------------------------


def test_the_bundle_has_no_field_that_could_hold_a_conclusion() -> None:
    bundle = build_bundle("quote", {"supplier_K.lead_time_days": 20}, "cnc_1")
    fields = set(bundle.__dataclass_fields__)
    assert fields == {"decision_kind", "premises", "context", "correlation_id"}
    for forbidden in ("conclusion", "body", "committed_lead_days", "original"):
        assert forbidden not in fields


def test_the_prompt_carries_premises_and_not_the_answer() -> None:
    bundle = build_bundle(
        "quote", {"supplier_K.lead_time_days": 20}, "cnc_1", context="Standard terms."
    )
    prompt = bundle.as_prompt()
    assert "supplier_K.lead_time_days = 20" in prompt
    assert "14" not in prompt  # the original commitment appears nowhere


def test_a_leaky_context_is_detectable() -> None:
    """The realistic way blindness breaks: a summary that includes the answer."""
    clean = build_bundle("quote", {"x": 20}, "cnc_1", context="Standard terms apply.")
    assert bundle_contains_decision(clean, ["14 days"]) == []

    leaky = build_bundle(
        "quote", {"x": 20}, "cnc_1", context="Previously quoted 14 days to this account."
    )
    assert bundle_contains_decision(leaky, ["14 days"]) == ["14 days"]


# ---------------------------------------------------------------------------
# Layer 2: the store refuses
# ---------------------------------------------------------------------------


def test_the_blind_store_refuses_to_hand_over_a_conclusion() -> None:
    class Inner:
        def get_claim(self, claim_id):
            return "a claim"

        def get_conclusion(self, conclusion_id):
            return "THE ORIGINAL DECISION"

        def get_source(self, source_id):
            return "a source"

        def direct_dependents(self, claim_id):
            return []

    store = BlindStore(inner=Inner())
    assert store.get_claim("clm_1") == "a claim"  # claims still flow
    with pytest.raises(BlindnessViolation):
        store.get_conclusion("cnc_1")
    assert store.violations, "the violation was raised but not recorded"


# ---------------------------------------------------------------------------
# Behaviour
# ---------------------------------------------------------------------------


def test_an_unavailable_model_renders_unresolved_not_unchanged() -> None:
    """Locked decision 2.2. The dangerous answer is 'nothing changed'."""
    bundle = build_bundle("quote", {"supplier_K.lead_time_days": 20}, "cnc_1")
    result = re_derive(bundle, UnavailableT2Model(), now=NOW)
    assert result.committed_lead_days is None
    assert not result.resolved
    assert "UNRESOLVED" in (result.unresolved_reason or "")


def test_a_timeout_renders_unresolved() -> None:
    bundle = build_bundle("quote", {"supplier_K.lead_time_days": 20}, "cnc_1")
    model = ScriptedT2Model(fail_next="deadline exceeded after 30s")
    result = re_derive(bundle, model, now=NOW)
    assert not result.resolved
    assert "deadline exceeded" in (result.unresolved_reason or "")


def test_an_unparseable_reply_is_unresolved_not_guessed() -> None:
    bundle = build_bundle("quote", {"supplier_K.lead_time_days": 20}, "cnc_1")
    model = ScriptedT2Model(replies={"blind_rederivation": "probably about three weeks"})
    result = re_derive(bundle, model, now=NOW)
    assert result.committed_lead_days is None
    assert "could not be parsed" in (result.unresolved_reason or "")


def test_a_well_formed_reply_is_carried_through_with_its_principal() -> None:
    import json

    bundle = build_bundle("quote", {"supplier_K.lead_time_days": 20}, "cnc_1")
    model = ScriptedT2Model(
        replies={
            "blind_rederivation": json.dumps(
                {
                    "committed_lead_days": 29,
                    "confidence": 0.82,
                    "reasoning": "20-day premise plus buffer.",
                }
            )
        }
    )
    result = re_derive(bundle, model, now=NOW)
    assert result.committed_lead_days == 29
    assert result.confidence == 0.82
    assert result.derived_by == REDERIVER_PRINCIPAL
    assert result.resolved
