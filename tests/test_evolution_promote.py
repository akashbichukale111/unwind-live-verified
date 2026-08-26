"""The gates between a candidate agent version and production.

The tests that matter most in this file are the ones a hostile reviewer
would try first:

  - can an agent promote itself?                    (no, and it raises)
  - can a candidate carry scope?                    (no, at two layers)
  - can a candidate trade safety for completions?   (no)
  - can it trade completions for safety?            (yes, and it is NAMED)
  - does passing every automated gate promote it?   (no -- a human must concur)

No Firestore and no model: `persist=False` throughout, and the replay runs
the deterministic planner over the committed evidence bundle.
"""

from __future__ import annotations

import pytest

from evolution.promote import (
    MAX_THROUGHPUT_REGRESSION,
    SAFETY_CRITERIA,
    THROUGHPUT_CRITERIA,
    PromotionRefused,
    assert_human_principal,
    evaluate_promotion,
    promote,
)
from evolution.schema import PromotionOutcome
from evolution.versions import AuthorityEscalation, build_version, seed_versions

HUMAN = "human::operator@example.com"


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    """No model call may originate from this file. The deterministic planner
    produces every plan, which is also what makes these tests runnable on a
    cold clone with no credentials."""
    monkeypatch.setenv("UNWIND_VERTEX_DISABLED", "1")


@pytest.fixture
def seed():
    return next(v for v in seed_versions() if v.agent_key == "orchestrator")


@pytest.fixture
def ungoverned(seed):
    """An agent with the governance switched off. Stands in for the ordinary
    autonomous agent this repository is arguing against."""
    return build_version(
        agent_key="orchestrator",
        instruction=seed.instruction,
        policy={
            "min_evidence_completeness": 0.0,
            "require_human_on_contradiction": False,
            "max_plan_steps": 8,
            "verify_after_execute": False,
        },
        version_n=1,
    )


@pytest.fixture
def governed(seed, ungoverned):
    return build_version(
        agent_key="orchestrator",
        instruction=seed.instruction,
        policy=dict(seed.policy),
        version_n=2,
        parent_version_id=ungoverned.version_id,
    )


# ---------------------------------------------------------------------------
# 1. No model authorises its own promotion
# ---------------------------------------------------------------------------


def test_agent_principal_cannot_promote(ungoverned, governed):
    """The single most important assertion in this package."""
    with pytest.raises(PromotionRefused) as exc:
        promote(
            ungoverned,
            governed,
            human_principal="agent::fleet_orchestrator",
            persist=False,
        )
    assert "agent principal" in str(exc.value)


def test_service_principal_cannot_promote(ungoverned, governed):
    with pytest.raises(PromotionRefused):
        promote(ungoverned, governed, human_principal="service::ci", persist=False)


def test_missing_principal_cannot_promote(ungoverned, governed):
    for principal in (None, "", "   "):
        with pytest.raises(PromotionRefused):
            promote(ungoverned, governed, human_principal=principal, persist=False)


def test_the_principal_check_runs_before_any_measurement(monkeypatch, ungoverned, governed):
    """A self-promotion attempt must be refused before it can cause work.

    If the check ran after the comparison, an agent could drive arbitrary
    replay load simply by asking, and the refusal would be a rate-limit
    problem rather than an authority one.
    """
    import evolution.promote as promote_module

    def _explode(*args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("the comparison ran before the principal was checked")

    monkeypatch.setattr(promote_module, "compare", _explode)
    with pytest.raises(PromotionRefused):
        promote(ungoverned, governed, human_principal="agent::x", persist=False)


@pytest.mark.parametrize("principal", ["human::a@b.c", "user::operator", "AGENTINA::x"])
def test_non_agent_principals_are_accepted(principal):
    assert assert_human_principal(principal) == principal


@pytest.mark.parametrize("principal", ["agent::x", "AGENT::X", "Agent::Fleet", "service::ci"])
def test_agent_and_service_principals_are_refused(principal):
    with pytest.raises(PromotionRefused):
        assert_human_principal(principal)


# ---------------------------------------------------------------------------
# 2. A candidate can never carry authority
# ---------------------------------------------------------------------------


def test_candidate_carrying_scope_cannot_even_be_constructed(seed):
    with pytest.raises(AuthorityEscalation):
        build_version(
            agent_key="orchestrator",
            instruction=seed.instruction,
            policy={**seed.policy, "authority_scope": ["finance.secret_read"]},
            version_n=2,
        )


def test_candidate_carrying_scope_is_refused_at_the_gate_too(ungoverned, seed):
    """Constructed around the builder, as a document read back from storage
    could be. The gate re-checks, because a check that only runs on the write
    path does not protect the read path.

    The candidate is rebuilt through `build_version` with a clean policy and
    then tampered with, so its content address is recomputed honestly and the
    AUTHORITY gate -- not the integrity gate -- is the one under test.
    """
    from evolution.versions import compute_version_id

    tampered_policy = {**seed.policy, "tools": ["shell.exec"]}
    smuggled = build_version(
        agent_key="orchestrator",
        instruction=seed.instruction,
        policy=dict(seed.policy),
        version_n=2,
        parent_version_id=ungoverned.version_id,
    ).model_copy(
        update={
            "policy": tampered_policy,
            # Re-address it, so this test exercises AUTHORITY rather than
            # tripping the integrity check first.
            "version_id": compute_version_id("orchestrator", seed.instruction, tampered_policy),
        }
    )
    decision = evaluate_promotion(ungoverned, smuggled, human_principal=HUMAN)
    assert decision.outcome is PromotionOutcome.REFUSED
    assert any(r.startswith("AUTHORITY:") for r in decision.reasons)


def test_a_version_altered_after_construction_is_refused_on_integrity(ungoverned, seed):
    """Content addressing is only a guarantee if something checks it."""
    altered = build_version(
        agent_key="orchestrator",
        instruction=seed.instruction,
        policy=dict(seed.policy),
        version_n=2,
        parent_version_id=ungoverned.version_id,
    ).model_copy(update={"instruction": seed.instruction + "\n\nSmuggled sentence."})
    decision = evaluate_promotion(ungoverned, altered, human_principal=HUMAN)
    assert decision.outcome is PromotionOutcome.REFUSED
    assert any(r.startswith("INTEGRITY:") for r in decision.reasons)


def test_nested_authority_key_is_refused(seed):
    with pytest.raises(AuthorityEscalation):
        build_version(
            agent_key="orchestrator",
            instruction=seed.instruction,
            policy={**seed.policy, "limits": {"warrant_mint_schedule": {"LOW": 9999}}},
            version_n=2,
        )


# ---------------------------------------------------------------------------
# 3. The asymmetric regression gate
# ---------------------------------------------------------------------------


def test_safety_and_throughput_criteria_partition_the_seven():
    from evolution.schema import CriterionKey

    assert SAFETY_CRITERIA | THROUGHPUT_CRITERIA == {k.value for k in CriterionKey}
    assert not (SAFETY_CRITERIA & THROUGHPUT_CRITERIA)


def test_governance_improvement_is_allowed_and_the_trade_is_named(ungoverned, governed):
    """The promotion this loop exists to make.

    Turning governance ON lowers TASK_SUCCESS -- the governed agent declines
    missions the ungoverned one completed. That is the intended behaviour, so
    it must not be refused, and it must not be silent either.
    """
    decision = evaluate_promotion(ungoverned, governed)
    assert decision.candidate_composite > decision.baseline_composite
    assert decision.outcome is PromotionOutcome.AWAITING_HUMAN
    trades = [r for r in decision.reasons if r.startswith("TRADE:")]
    assert trades, "a throughput regression bought by safety must be stated, not hidden"
    assert "TASK_SUCCESS" in trades[0]
    assert not decision.regressions


def test_trading_safety_away_is_refused(governed):
    """The reverse trade. Completions bought with compliance is exactly what
    an unconstrained optimiser would propose, and it must not pass."""
    loosened = build_version(
        agent_key="orchestrator",
        instruction=governed.instruction,
        policy={
            **governed.policy,
            "require_human_on_contradiction": False,
            "verify_after_execute": False,
        },
        version_n=3,
        parent_version_id=governed.version_id,
    )
    decision = evaluate_promotion(governed, loosened, human_principal=HUMAN)
    assert decision.outcome is PromotionOutcome.REFUSED
    assert any(r.startswith("REGRESSION (safety)") for r in decision.reasons)
    assert decision.regressions


def test_a_safety_criterion_falling_is_always_a_regression(governed):
    loosened = build_version(
        agent_key="orchestrator",
        instruction=governed.instruction,
        policy={**governed.policy, "require_human_on_contradiction": False},
        version_n=3,
        parent_version_id=governed.version_id,
    )
    decision = evaluate_promotion(governed, loosened, human_principal=HUMAN)
    fallen = {r["criterion"] for r in decision.regressions}
    assert fallen & SAFETY_CRITERIA


def test_no_measurable_improvement_is_refused_rather_than_invented(governed):
    """A candidate whose policy delta sits outside the dataset's measured
    coverage band changes nothing. The honest answer is refusal, not a
    rounded-up gain."""
    cosmetic = build_version(
        agent_key="orchestrator",
        instruction=governed.instruction + "\n\nA clarifying sentence about authorization.",
        policy=dict(governed.policy),
        version_n=3,
        parent_version_id=governed.version_id,
    )
    decision = evaluate_promotion(governed, cosmetic, human_principal=HUMAN)
    assert decision.outcome is PromotionOutcome.REFUSED
    assert any(r.startswith("IMPROVEMENT:") for r in decision.reasons)


# ---------------------------------------------------------------------------
# 4. Lineage, exercise, countersign, human
# ---------------------------------------------------------------------------


def test_identical_candidate_is_refused(governed):
    decision = evaluate_promotion(governed, governed, human_principal=HUMAN)
    assert decision.outcome is PromotionOutcome.REFUSED
    assert any("LINEAGE" in r for r in decision.reasons)


def test_candidate_for_a_different_agent_is_refused(seed, governed):
    other = build_version(
        agent_key="recon", instruction=seed.instruction, policy=dict(seed.policy), version_n=2
    )
    decision = evaluate_promotion(governed, other, human_principal=HUMAN)
    assert decision.outcome is PromotionOutcome.REFUSED
    assert any("LINEAGE" in r for r in decision.reasons)


def test_an_unexercised_instruction_change_is_declared_not_scored(ungoverned, seed):
    """With no model in the path the instruction is never read, so a changed
    instruction was NOT measured. The decision must say so."""
    candidate = build_version(
        agent_key="orchestrator",
        instruction=seed.instruction + "\n\nAdditional guidance, still authorized downstream.",
        policy=dict(seed.policy),
        version_n=2,
        parent_version_id=ungoverned.version_id,
    )
    decision = evaluate_promotion(ungoverned, candidate, human_principal=HUMAN)
    assert any(r.startswith("EXERCISE:") for r in decision.reasons)


def test_exercise_note_alone_does_not_block_promotion(ungoverned, seed):
    candidate = build_version(
        agent_key="orchestrator",
        instruction=seed.instruction + "\n\nAdditional guidance, still authorized downstream.",
        policy=dict(seed.policy),
        version_n=2,
        parent_version_id=ungoverned.version_id,
    )
    decision = evaluate_promotion(ungoverned, candidate, human_principal=HUMAN)
    assert decision.outcome is PromotionOutcome.PROMOTED


def test_a_disagreeing_countersign_refuses_the_promotion(ungoverned, governed):
    decision = evaluate_promotion(
        ungoverned, governed, human_principal=HUMAN, countersign="DISAGREE: coverage untested"
    )
    assert decision.outcome is PromotionOutcome.REFUSED
    assert any(r.startswith("COUNTERSIGN:") for r in decision.reasons)


def test_passing_every_automated_gate_still_requires_a_human(ungoverned, governed):
    """The distinction between a system that asks and a system that proceeds."""
    without = evaluate_promotion(ungoverned, governed)
    assert without.outcome is PromotionOutcome.AWAITING_HUMAN
    assert without.human_principal is None

    with_human = evaluate_promotion(ungoverned, governed, human_principal=HUMAN)
    assert with_human.outcome is PromotionOutcome.PROMOTED
    assert with_human.human_principal == HUMAN


def test_the_decision_records_the_numbers_it_was_made_from(ungoverned, governed):
    decision = evaluate_promotion(ungoverned, governed, human_principal=HUMAN)
    assert decision.comparison
    for row in decision.comparison:
        assert row["delta"] == pytest.approx(round(row["candidate"] - row["baseline"], 4), abs=1e-6)


def test_throughput_regression_beyond_the_bound_is_refused(governed):
    """A safety gain buys a bounded throughput loss, not an unbounded one."""
    assert 0.0 < MAX_THROUGHPUT_REGRESSION < 1.0
