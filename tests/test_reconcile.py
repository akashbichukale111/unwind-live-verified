"""The Reconciler: two derivations of the same fact, and the disagreement.

`recon_extract_claims` resolves a contradiction by RECENCY and says so.
`reconcile_adjudicate` re-derives it from AUTHORITY. Neither answer is the
product. The DISAGREEMENT is, and these tests are about when it appears,
when it does not, and what the mission does with it.
"""

from __future__ import annotations

import json
import os
import socket

import pytest

from fleet.tools import AUTHORITY_LADDER, recon_extract_claims, reconcile_adjudicate


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


# ===========================================================================
# The committed evidence produces one agreement and one genuine dispute
# ===========================================================================


def test_the_committed_evidence_settles_one_claim_and_disputes_another() -> None:
    """Both outcomes are latent in the fixture, unmodified.

    `clm_supplier_K_lead_time` -- procurement holds standing AND is the most
    recent record. Two rules, one answer: settled.

    `clm_tariff_rate_K` -- the ERP row is newer (July) but compliance holds
    standing over a tariff rate and says something different (May). The rules
    disagree, and no parser can settle it.
    """
    result = reconcile_adjudicate(recon=recon_extract_claims())

    assert result["verdict"] == "RESOLVED_WITH_DISPUTES"
    settled = {r["claim_id"] for r in result["resolutions"]}
    disputed = {d["claim_id"] for d in result["disputes"]}
    assert settled == {"clm_supplier_K_lead_time"}
    assert disputed == {"clm_tariff_rate_K"}


def test_the_settled_claim_names_the_authority_that_settled_it() -> None:
    result = reconcile_adjudicate(recon=recon_extract_claims())
    settled = result["resolutions"][0]
    assert settled["chosen_value"] == 20
    assert settled["chosen_authority"] == "procurement"
    assert settled["chosen_source"] == "src_procurement"
    assert settled["agreed_with_recency"] is True
    assert settled["superseded"], "a resolution must say what it displaced"


def test_the_dispute_carries_both_candidate_answers_and_neither_is_chosen() -> None:
    """The output must not contain a resolution for a disputed claim. A
    reconciler that quietly picked would be making an authority ruling it has
    no standing to make."""
    result = reconcile_adjudicate(recon=recon_extract_claims())
    dispute = result["disputes"][0]

    assert dispute["dispute_kind"] == "AUTHORITY_CONTRADICTS_RECENCY"
    assert dispute["recency_value"] == 8.0
    assert dispute["authority_value"] == 8.5
    assert dispute["authority_holder"] == "compliance"
    assert "chosen_value" not in dispute
    assert dispute["claim_id"] not in {r["claim_id"] for r in result["resolutions"]}


def test_the_dispute_is_the_one_the_operator_flagged_by_hand() -> None:
    """The handover note says of this exact claim: 'never reconciled. flagging
    it.' The system's dispute IS that flag, turned into a decision record."""
    from pathlib import Path

    note = (
        Path(__file__).resolve().parents[1] / "fleet" / "data" / "incident" / "ops-note.txt"
    ).read_text(encoding="utf-8")
    assert "never reconciled" in note
    assert "8.5" in note

    result = reconcile_adjudicate(recon=recon_extract_claims())
    assert result["disputes"][0]["claim_id"] == "clm_tariff_rate_K"


# ===========================================================================
# It refuses to guess
# ===========================================================================


def test_a_predicate_with_no_authority_ladder_is_disputed_not_decided_by_recency() -> None:
    """Falling back to recency when no authority is known would make the
    reconciler a second copy of the extractor with more ceremony."""
    recon = {
        "claims": [
            {
                "claim_id": "clm_x",
                "subject": "s",
                "predicate": "unknown_predicate",
                "value": 1,
                "source": "src_a",
                "authority": "nobody",
                "recorded_at": "2026-08-01T00:00:00+00:00",
            },
            {
                "claim_id": "clm_x",
                "subject": "s",
                "predicate": "unknown_predicate",
                "value": 2,
                "source": "src_b",
                "authority": "also_nobody",
                "recorded_at": "2026-08-02T00:00:00+00:00",
            },
        ],
        "contradictions": [
            {
                "claim_id": "clm_x",
                "values": ["1", "2"],
                "records": 2,
                "most_recent_value": 2,
                "most_recent_source": "src_b",
            }
        ],
    }
    result = reconcile_adjudicate(recon=recon)
    assert result["verdict"] == "DISPUTED"
    assert result["disputes"][0]["dispute_kind"] == "NO_AUTHORITY_LADDER"
    assert result["resolutions"] == []


def test_an_authority_that_contradicts_itself_is_disputed() -> None:
    recon = {
        "claims": [
            {
                "claim_id": "clm_y",
                "subject": "s",
                "predicate": "lead_time_days",
                "value": 11,
                "source": "src_p1",
                "authority": "procurement",
                "recorded_at": "2026-08-01T00:00:00+00:00",
            },
            {
                "claim_id": "clm_y",
                "subject": "s",
                "predicate": "lead_time_days",
                "value": 20,
                "source": "src_p2",
                "authority": "procurement",
                "recorded_at": "2026-08-02T00:00:00+00:00",
            },
        ],
        "contradictions": [
            {
                "claim_id": "clm_y",
                "values": ["11", "20"],
                "records": 2,
                "most_recent_value": 20,
                "most_recent_source": "src_p2",
            }
        ],
    }
    result = reconcile_adjudicate(recon=recon)
    assert result["disputes"][0]["dispute_kind"] == "AUTHORITY_SELF_CONTRADICTION"


def test_no_contradictions_produces_no_rulings_at_all() -> None:
    result = reconcile_adjudicate(recon={"claims": [], "contradictions": []})
    assert result["verdict"] == "NO_CONTRADICTIONS"
    assert result["resolutions"] == [] and result["disputes"] == []


def test_the_authority_ladder_is_per_predicate_not_global() -> None:
    """Procurement outranks planning about a lead time and holds no standing
    at all over a tariff rate. A global department ranking would be wrong."""
    assert AUTHORITY_LADDER["lead_time_days"][0] == "procurement"
    assert "procurement" not in AUTHORITY_LADDER["tariff_rate_pct"]
    assert AUTHORITY_LADDER["tariff_rate_pct"][0] == "compliance"


def test_the_tool_is_a_pure_function() -> None:
    recon = recon_extract_claims()
    a = reconcile_adjudicate(recon=recon)
    b = reconcile_adjudicate(recon=recon)
    assert json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)


# ===========================================================================
# The causal seam: the phase exists only because the evidence contradicts
# ===========================================================================


@requires_emulator
def test_the_reconcile_phase_runs_only_when_the_evidence_contradicts_itself(
    tmp_path,
) -> None:
    """The falsification. Same mission, same code, evidence with the second
    record for each claim removed: no reconciliation phase appears at all."""
    import shutil
    from pathlib import Path

    from command_os.mission import reset_for_test, run_mission

    source = Path(__file__).resolve().parents[1] / "fleet" / "data" / "incident"
    clean = tmp_path / "incident"
    clean.mkdir()
    for name in ("ops-note.txt", "capability-requests.csv"):
        shutil.copy(source / name, clean / name)

    feed = json.loads((source / "premise-feed.json").read_text(encoding="utf-8"))
    seen: set[str] = set()
    kept = []
    for record in feed["records"]:
        cid = record.get("claim_id")
        if cid in seen:
            continue
        seen.add(cid)
        kept.append(record)
    feed["records"] = kept
    (clean / "premise-feed.json").write_text(json.dumps(feed), encoding="utf-8")

    reset_for_test()
    without = run_mission(
        principal="human::test",
        auth_method="test",
        allow_model=False,
        incident_dir=str(clean),
    )
    assert not any(s.name.startswith("RECONCILE") for s in without.stages)
    assert without.report.contradictions_found == 0
    assert without.report.reconciliation_verdict == ""
    assert without.report.contradictions_disputed == 0

    reset_for_test()
    with_contradictions = run_mission(
        principal="human::test", auth_method="test", allow_model=False
    )
    assert any(s.name.startswith("RECONCILE") for s in with_contradictions.stages)
    assert with_contradictions.report.reconciliation_verdict == "RESOLVED_WITH_DISPUTES"
    assert with_contradictions.report.disputed_claims == ["clm_tariff_rate_K"]


@requires_emulator
def test_the_reconciler_is_a_distinct_principal_that_passes_the_real_gateway() -> None:
    """A reconciler sharing recon's identity would be re-deriving its own
    answer. It has its own principal, its own scope, and its own row."""
    from command_os.mission import reset_for_test, run_mission
    from fleet.roles import RECON, RECONCILER

    assert RECONCILER.principal != RECON.principal
    assert "claims.reconcile" in RECONCILER.authority_scope
    assert "claims.reconcile" not in RECON.authority_scope

    reset_for_test()
    result = run_mission(principal="human::test", auth_method="test", allow_model=False)
    stage = next(s for s in result.stages if s.name.startswith("RECONCILE"))
    assert stage.detail["decision"]["agent_id"] == "fleet_reconciler"
    assert stage.detail["decision"]["allowed"] is True
    assert stage.detail["priced"]["cost_bp"] > 0
    assert f"{result.mission_id}_reconcile" in result.report.case_ids


@requires_emulator
def test_a_dispute_raises_the_price_of_every_later_action() -> None:
    """The dispute is not a note. It is an uncertainty signal, and
    `warrant/economics.py` charges for it."""
    from warrant.economics import ActionKind, UncertaintySignals, price_action

    common = dict(
        evidence_age_seconds=0.0,
        evidence_completeness=0.8,
        drift_band="NORMAL",
        model_disagreement=False,
        external_state_changed=False,
        consequence_band="NONE",
    )
    without = price_action(
        ActionKind.CREATE_TICKET, UncertaintySignals(risk_divergence=False, **common)
    )
    with_dispute = price_action(
        ActionKind.CREATE_TICKET, UncertaintySignals(risk_divergence=True, **common)
    )
    assert with_dispute.cost_bp > without.cost_bp


@requires_emulator
def test_a_dispute_cannot_be_cleared_by_a_later_clean_step() -> None:
    """`_signals` ORs the two divergence sources rather than overwriting one
    with the other -- the reconciliation runs FIRST, so a single key would
    let the risk step silently clear a live dispute."""
    from command_os.mission import _signals

    ctx = {"reconciliation_disputed": True, "risk_divergence": False}
    assert _signals(ctx).risk_divergence is True
