"""Output contracts: the boundary `check_worker_fault` cannot see.

Every test below hands `validate_tool_output` a `dict`. That is the point.
`tower/gateway.py:check_worker_fault` accepts all of them; these are the
failures that only a contract catches.
"""

from __future__ import annotations

from fleet.contracts import contract_summary, validate_tool_output
from fleet.tools import recon_extract_claims, reconcile_adjudicate, risk_probe


def _checks(violations) -> set[str]:
    return {v.check for v in violations}


def _fields(violations) -> set[str]:
    return {v.field for v in violations}


# ---------------------------------------------------------------------------
# The real tools satisfy their own contracts. If they did not, every other
# assertion here would be about a boundary nothing can pass.
# ---------------------------------------------------------------------------


def test_the_real_tools_satisfy_their_own_contracts() -> None:
    recon = recon_extract_claims()
    assert validate_tool_output("recon.extract_claims", recon) == []

    scopes = {"fleet_recon": ["evidence.read", "corpus.read"]}
    risk = risk_probe(recon=recon, fleet_scopes=scopes)
    assert validate_tool_output("risk.probe", risk, inputs={"recon": recon}) == []

    rec = reconcile_adjudicate(recon=recon)
    assert validate_tool_output("reconcile.adjudicate", rec, inputs={"recon": recon}) == []


# ---------------------------------------------------------------------------
# SELF-CONSISTENCY: a number that does not follow from the numbers beside it
# ---------------------------------------------------------------------------


def test_a_coverage_figure_that_does_not_follow_from_its_counts_is_rejected() -> None:
    """THE test for this module.

    The output below is a `dict`, carries every required key of the right
    type, and would sail through `check_worker_fault`. It reports perfect
    evidence coverage over counts that say otherwise -- and
    `evidence_completeness` is the exact number `warrant/economics.py` uses
    to price the next action.
    """
    forged = {
        "claims": [],
        "requests": [],
        "contradictions": [],
        "anomalies": [],
        "parsed": 20,
        "total": 20,
        "completeness": 1.0,
        "newest_age_seconds": 0.0,
    }
    assert validate_tool_output("recon.extract_claims", forged) == []

    forged["total"] = 3  # 20 parsed of 3 encountered
    violations = validate_tool_output("recon.extract_claims", forged)
    assert violations, "a result claiming more parsed than encountered was accepted"
    assert "SELF_CONSISTENCY" in _checks(violations)


def test_completeness_must_equal_parsed_over_total() -> None:
    output = {
        "claims": [],
        "requests": [],
        "contradictions": [],
        "anomalies": [],
        "parsed": 16,
        "total": 20,
        "completeness": 1.0,  # actually 0.8
        "newest_age_seconds": 0.0,
    }
    violations = validate_tool_output("recon.extract_claims", output)
    assert "completeness" in _fields(violations)


def test_a_verifier_cannot_claim_success_while_listing_mismatches() -> None:
    violations = validate_tool_output(
        "verify.check", {"verified": True, "mismatches": ["action: proposed X, recorded Y"]}
    )
    assert "SELF_CONSISTENCY" in _checks(violations)


def test_a_verifier_cannot_fail_without_saying_why() -> None:
    violations = validate_tool_output("verify.check", {"verified": False, "mismatches": []})
    assert "SELF_CONSISTENCY" in _checks(violations)


def test_a_verdict_must_agree_with_the_findings_beside_it() -> None:
    recon = recon_extract_claims()
    output = {
        "escalations": [
            {
                "agent_id": "fleet_recon",
                "requested_scope": "finance.secret_read",
                "request_id": "req-8802",
            }
        ],
        "hypotheses": [],
        "verdict": "NO_ESCALATION_FOUND",
    }
    violations = validate_tool_output("risk.probe", output, inputs={"recon": recon})
    assert "SELF_CONSISTENCY" in _checks(violations)


# ---------------------------------------------------------------------------
# GROUNDING: a finding about something the evidence never mentioned
# ---------------------------------------------------------------------------


def test_risk_may_not_name_an_agent_the_evidence_never_mentioned() -> None:
    """The check with no cheaper substitute.

    `fleet_ghost` is a well-formed agent id in a well-formed escalation
    record. Nothing about its SHAPE is wrong. It is simply not in the
    evidence, which is the signature of a finding that was generated rather
    than derived.
    """
    recon = recon_extract_claims()
    output = {
        "escalations": [
            {
                "agent_id": "fleet_ghost",
                "requested_scope": "finance.secret_read",
                "granted_scope": [],
                "request_id": "req-8802",
                "risk_class": "HIGH",
                "tool_calls": 147,
                "dataset": "finance",
                "why": "invented",
            }
        ],
        "hypotheses": [],
        "verdict": "ESCALATION_FOUND",
    }
    violations = validate_tool_output("risk.probe", output, inputs={"recon": recon})
    assert "GROUNDING" in _checks(violations)
    assert any("fleet_ghost" in v.detail for v in violations)


def test_risk_may_not_cite_a_request_id_the_evidence_does_not_contain() -> None:
    recon = recon_extract_claims()
    output = {
        "escalations": [
            {
                "agent_id": "fleet_recon",
                "requested_scope": "finance.secret_read",
                "request_id": "req-9999",
            }
        ],
        "hypotheses": [],
        "verdict": "ESCALATION_FOUND",
    }
    violations = validate_tool_output("risk.probe", output, inputs={"recon": recon})
    assert "GROUNDING" in _checks(violations)


def test_a_grounding_check_with_no_input_is_skipped_not_passed() -> None:
    """A check that cannot run must not report a pass.

    With no `recon` input there is nothing to ground against, so the
    grounding violation is absent -- and this test exists so that absence is
    a deliberate, asserted property rather than an accident nobody noticed.
    """
    output = {
        "escalations": [{"agent_id": "fleet_ghost", "requested_scope": "x", "request_id": "y"}],
        "hypotheses": [],
        "verdict": "ESCALATION_FOUND",
    }
    violations = validate_tool_output("risk.probe", output, inputs={})
    assert "GROUNDING" not in _checks(violations)


def test_a_correction_may_not_target_a_request_risk_never_escalated() -> None:
    risk = {"escalations": [{"request_id": "req-8802", "agent_id": "fleet_recon"}]}
    output = {
        "action": "REVOKE_CAPABILITY_REQUEST",
        "target_request_id": "req-0000",
        "idempotency_key": "k",
        "reversal": "re-grant",
        "reversible": True,
    }
    violations = validate_tool_output("remediation.prepare", output, inputs={"risk": risk})
    assert "GROUNDING" in _checks(violations)


def test_a_mutating_proposal_must_carry_an_idempotency_key_and_a_reversal() -> None:
    output = {"action": "REVOKE_CAPABILITY_REQUEST", "reversible": True}
    violations = validate_tool_output("remediation.prepare", output, inputs={})
    assert {"idempotency_key", "reversal"} <= _fields(violations)


def test_a_no_action_proposal_needs_neither() -> None:
    """The contract must not force ceremony onto a proposal that does nothing
    -- otherwise an uneventful mission is pushed toward manufacturing one."""
    output = {"action": "NO_ACTION_REQUIRED", "reversible": True}
    assert validate_tool_output("remediation.prepare", output, inputs={}) == []


def test_a_reconciler_may_not_rule_on_a_claim_nobody_contradicted() -> None:
    recon = recon_extract_claims()
    output = {
        "resolutions": [{"claim_id": "clm_invented", "chosen_source": "src_x"}],
        "disputes": [],
        "verdict": "RESOLVED",
    }
    violations = validate_tool_output("reconcile.adjudicate", output, inputs={"recon": recon})
    assert "GROUNDING" in _checks(violations)


# ---------------------------------------------------------------------------
# SHAPE and VOCABULARY
# ---------------------------------------------------------------------------


def test_a_missing_required_key_is_a_violation() -> None:
    violations = validate_tool_output("verify.check", {"verified": True})
    assert "mismatches" in _fields(violations)


def test_a_bool_is_not_accepted_where_a_number_is_required() -> None:
    output = {
        "claims": [],
        "requests": [],
        "contradictions": [],
        "anomalies": [],
        "parsed": True,
        "total": 1,
        "completeness": 1.0,
        "newest_age_seconds": 0.0,
    }
    violations = validate_tool_output("recon.extract_claims", output)
    assert "parsed" in _fields(violations)


def test_an_invented_verdict_is_refused() -> None:
    output = {"escalations": [], "hypotheses": [], "verdict": "PROBABLY_FINE"}
    violations = validate_tool_output("risk.probe", output, inputs={})
    assert "VOCABULARY" in _checks(violations)


def test_free_text_is_refused_at_the_root() -> None:
    violations = validate_tool_output("risk.probe", "everything looks fine to me")
    assert len(violations) == 1
    assert violations[0].field == "<root>"


def test_a_tool_with_no_declared_contract_is_refused_rather_than_trusted() -> None:
    """An unverifiable result is refused. The alternative -- passing anything
    whose tool nobody wrote a contract for -- makes the contract layer opt-in,
    and a security boundary nobody opted into is not a boundary."""
    violations = validate_tool_output("some.new.tool", {"anything": 1})
    assert violations and violations[0].check == "REGISTRY"


def test_every_registered_tool_has_a_contract() -> None:
    """The registry and the contract table must not drift apart."""
    from fleet.tools import TOOL_REGISTRY

    covered = {row["tool"] for row in contract_summary()}
    assert set(TOOL_REGISTRY) <= covered, f"tools with no contract: {set(TOOL_REGISTRY) - covered}"


def test_contract_summary_is_generated_from_the_tables_the_checks_read() -> None:
    summary = {row["tool"]: row for row in contract_summary()}
    assert "verdict" in summary["risk.probe"]["required_keys"]
    assert summary["risk.probe"]["closed_vocabulary"] == [
        "ESCALATION_FOUND",
        "NO_ESCALATION_FOUND",
    ]
    assert summary["risk.probe"]["grounding"]
