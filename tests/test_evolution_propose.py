"""Failure analysis and candidate generation, including the two ways a
proposer could quietly disarm the system:

  - removing the governance language from an instruction;
  - introducing a policy lever that was never on the permitted list.

Both are refused, and both are tested here against a hand-built hostile
proposal rather than only against the deterministic proposer's own output.
"""

from __future__ import annotations

import pytest

from evolution.propose import (
    MIN_INSTRUCTION_CHARS,
    MUTABLE_POLICY_KEYS,
    ProposalRejected,
    analyse_failures,
    propose_candidate,
    validate_candidate,
)
from evolution.schema import ProposalProvenance
from evolution.trajectory import evaluate_trajectory
from evolution.versions import SEED_POLICY, AuthorityEscalation, seed_versions


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.setenv("UNWIND_VERTEX_DISABLED", "1")


@pytest.fixture
def seed():
    return next(v for v in seed_versions() if v.agent_key == "orchestrator")


def _failing_evaluation():
    report = {
        "objective": "Investigate an anomalous finance capability request",
        "status": "COMPLETED",
        "objective_class": "CREDENTIAL_AUDIT",
        "steps_planned": 3,
        "steps_executed": 6,
        "tools_used": ["risk.probe", "remediation.execute", "recon.extract_claims"],
        "evidence_records_parsed": 6,
        "evidence_records_total": 20,
        "evidence_completeness": 0.3,
        "contradictions_found": 2,
        "escalations_found": 3,
        "agents_isolated": 0,
        "gateway_refusals": [],
        "unsafe_actions_executed": 1,
        "external_action": "CREATE_TICKET",
        "gate": "REQUIRED",
        "human_principal": None,
        "worker_faults": 2,
        "replans": 0,
        "drift_band": "CRITICAL",
        "challenger_agrees": False,
    }
    return evaluate_trajectory(report=report, mission_id="m1", agent_version_id="v1")


def _clean_evaluation():
    report = {
        "objective": "Trace the impact of a changed operational premise",
        "status": "COMPLETED",
        "objective_class": "PREMISE_IMPACT_TRACE",
        "steps_planned": 3,
        "steps_executed": 3,
        "tools_used": ["recon.extract_claims", "risk.probe", "verify.check"],
        "evidence_records_parsed": 20,
        "evidence_records_total": 20,
        "evidence_completeness": 1.0,
        "contradictions_found": 0,
        "escalations_found": 0,
        "gateway_refusals": [],
        "unsafe_actions_executed": 0,
        "worker_faults": 0,
        "external_action": None,
        "gate": "NOT_REQUIRED",
    }
    return evaluate_trajectory(report=report, mission_id="m2", agent_version_id="v1")


# ---------------------------------------------------------------------------
# Failure analysis is deterministic and refuses to invent work
# ---------------------------------------------------------------------------


def test_analysis_names_only_criteria_that_actually_failed():
    rows = analyse_failures([_failing_evaluation()])
    named = {r["criterion"] for r in rows}
    assert "POLICY_COMPLIANCE" in named
    assert "RISK_DISCIPLINE" in named
    assert "TASK_SUCCESS" not in named, "the mission completed; that did not fail"


def test_a_clean_history_yields_no_analysis_and_no_proposal(seed):
    assert analyse_failures([_clean_evaluation()]) == []
    with pytest.raises(ProposalRejected):
        propose_candidate(
            baseline=seed, evaluations=[_clean_evaluation()], version_n=2, allow_model=False
        )


def test_analysis_is_ordered_worst_first():
    rows = analyse_failures([_failing_evaluation(), _failing_evaluation()])
    counts = [r["failures"] for r in rows]
    assert counts == sorted(counts, reverse=True)


# ---------------------------------------------------------------------------
# The deterministic proposer
# ---------------------------------------------------------------------------


def test_zero_model_proposal_is_honest_about_its_provenance(seed):
    proposal, candidate = propose_candidate(
        baseline=seed, evaluations=[_failing_evaluation()], version_n=2, allow_model=False
    )
    assert proposal.provenance is ProposalProvenance.ZERO_MODEL
    assert proposal.model == ""
    assert candidate.provenance == ProposalProvenance.ZERO_MODEL.value


def test_the_candidate_descends_from_the_baseline_and_differs_from_it(seed):
    proposal, candidate = propose_candidate(
        baseline=seed, evaluations=[_failing_evaluation()], version_n=2, allow_model=False
    )
    assert candidate.parent_version_id == seed.version_id
    assert candidate.version_id != seed.version_id
    assert candidate.version_n == 2


def test_the_proposal_addresses_the_criteria_that_failed(seed):
    proposal, candidate = propose_candidate(
        baseline=seed, evaluations=[_failing_evaluation()], version_n=2, allow_model=False
    )
    failed = {r["criterion"] for r in proposal.failure_analysis}
    for criterion in failed & {"POLICY_COMPLIANCE", "RISK_DISCIPLINE", "CONTEXT_QUALITY"}:
        assert criterion in candidate.instruction


def test_the_proposal_only_ever_tightens_the_policy(seed):
    _, candidate = propose_candidate(
        baseline=seed, evaluations=[_failing_evaluation()], version_n=2, allow_model=False
    )
    assert candidate.policy["min_evidence_completeness"] >= seed.policy["min_evidence_completeness"]
    assert candidate.policy["require_human_on_contradiction"] is True
    assert candidate.policy["max_plan_steps"] <= seed.policy["max_plan_steps"]


def test_the_baselines_governance_language_survives(seed):
    _, candidate = propose_candidate(
        baseline=seed, evaluations=[_failing_evaluation()], version_n=2, allow_model=False
    )
    assert "authoriz" in candidate.instruction.lower()
    assert seed.instruction.strip() in candidate.instruction


def test_the_changes_are_a_reviewable_list_not_two_prose_blobs(seed):
    proposal, _ = propose_candidate(
        baseline=seed, evaluations=[_failing_evaluation()], version_n=2, allow_model=False
    )
    fields = {c["field"] for c in proposal.changes}
    assert "instruction" in fields
    assert any(f.startswith("policy.") for f in fields)


# ---------------------------------------------------------------------------
# The validator, against hostile proposals
# ---------------------------------------------------------------------------


def test_a_candidate_that_drops_the_governance_anchor_is_rejected(seed):
    """An agent talking itself out of its own governance is the single most
    plausible way this loop could go wrong."""
    with pytest.raises(ProposalRejected) as exc:
        validate_candidate(
            instruction=(
                "You are the Orchestrator. Decompose the objective into steps and "
                "execute whichever of them you judge appropriate, without waiting."
            ),
            policy=dict(SEED_POLICY),
            baseline=seed,
        )
    assert "anchor" in str(exc.value)


def test_a_collapsed_instruction_is_rejected(seed):
    with pytest.raises(ProposalRejected):
        validate_candidate(instruction="Be better.", policy={}, baseline=seed)
    assert MIN_INSTRUCTION_CHARS > 0


def test_an_unpermitted_policy_key_is_dropped_and_named(seed):
    instruction, policy, clamps = validate_candidate(
        instruction=seed.instruction,
        policy={**SEED_POLICY, "self_approve_promotions": True},
        baseline=seed,
    )
    assert "self_approve_promotions" not in policy
    assert any("self_approve_promotions" in c for c in clamps)


def test_an_authority_key_voids_the_whole_proposal(seed):
    """Not clamped. Rejected. A proposal that reached for scope is not a
    proposal to partially accept."""
    with pytest.raises(AuthorityEscalation):
        validate_candidate(
            instruction=seed.instruction,
            policy={**SEED_POLICY, "authority_scope": ["finance.secret_read"]},
            baseline=seed,
        )


def test_out_of_range_policy_values_are_clamped_to_the_bound(seed):
    _, policy, clamps = validate_candidate(
        instruction=seed.instruction,
        policy={**SEED_POLICY, "max_plan_steps": 400, "min_evidence_completeness": 5.0},
        baseline=seed,
    )
    assert policy["max_plan_steps"] == MUTABLE_POLICY_KEYS["max_plan_steps"][2]
    assert policy["min_evidence_completeness"] == 1.0
    assert len(clamps) >= 2


def test_a_policy_key_the_candidate_omitted_is_carried_forward_not_deleted(seed):
    """Silence is not a request to delete an operating preference."""
    _, policy, _ = validate_candidate(
        instruction=seed.instruction, policy={"max_plan_steps": 4}, baseline=seed
    )
    assert policy["require_human_on_contradiction"] == seed.policy["require_human_on_contradiction"]
    assert policy["max_plan_steps"] == 4


def test_every_mutable_key_is_a_subset_of_the_seed_policy():
    """A proposal may tune what exists; it may not introduce a new lever for
    itself."""
    assert set(MUTABLE_POLICY_KEYS).issubset(set(SEED_POLICY))
