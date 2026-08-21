"""Behavioral DNA's deterministic drift scoring: a fixed baseline table plus
weighted-signal arithmetic, reproducible, zero model calls. No Firestore, no
emulator -- pure function tests, same register as
`tests/test_singularity_genome.py` and `tests/test_hyperion_risk.py`.
"""

from __future__ import annotations

from singularity.behavior import detect_drift
from singularity.schema import AgentRole, BehaviorObservation, CapabilityAction, DriftBand


def _obs(**overrides):
    base = {
        "agent_role": AgentRole.WORKER_BROWSER,
        "tool_calls": 6,
        "dataset": "web",
        "latency_ms": 1200,
        "requested_export": False,
        "requested_secret_access": False,
    }
    base.update(overrides)
    return BehaviorObservation(**base)


def test_within_baseline_is_normal_with_no_action() -> None:
    assessment = detect_drift(_obs())
    assert assessment.drift_band is DriftBand.NORMAL
    assert assessment.capability_action is CapabilityAction.NONE
    assert assessment.drift_score < 20


def test_the_spec_attack_scenario_is_critical_and_isolated() -> None:
    """147 tool calls, finance database, secret access attempt, export
    request, unusual latency -- the exact worked example from the spec."""
    assessment = detect_drift(
        _obs(
            tool_calls=147,
            dataset="finance",
            latency_ms=9000,
            requested_export=True,
            requested_secret_access=True,
        )
    )
    assert assessment.drift_band is DriftBand.CRITICAL
    assert assessment.capability_action is CapabilityAction.ISOLATE
    assert assessment.drift_score == 100


def test_secret_access_alone_meaningfully_elevates_score() -> None:
    normal = detect_drift(_obs())
    with_secret = detect_drift(_obs(requested_secret_access=True))
    assert with_secret.drift_score > normal.drift_score
    assert "secret" in " ".join(with_secret.signals).lower()


def test_unfamiliar_dataset_is_named_in_signals() -> None:
    assessment = detect_drift(_obs(dataset="finance"))
    assert any("dataset" in s for s in assessment.signals)


def test_every_field_stays_within_baseline_reports_the_default_signal() -> None:
    assessment = detect_drift(_obs())
    assert assessment.signals == ["within baseline on every measured signal"]


def test_score_is_capped_at_100() -> None:
    assessment = detect_drift(
        _obs(
            tool_calls=10_000,
            dataset="finance",
            latency_ms=999_999,
            requested_export=True,
            requested_secret_access=True,
        )
    )
    assert assessment.drift_score == 100


def test_detection_is_pure_and_deterministic() -> None:
    obs = _obs(tool_calls=25, dataset="finance")
    first = detect_drift(obs)
    second = detect_drift(obs)
    assert first == second


def test_elevated_band_restricts_but_does_not_isolate() -> None:
    assessment = detect_drift(_obs(dataset="finance"))  # +30 only
    assert assessment.drift_band is DriftBand.ELEVATED
    assert assessment.capability_action is CapabilityAction.RESTRICT
