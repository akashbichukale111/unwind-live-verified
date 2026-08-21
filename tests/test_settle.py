"""Settlement: triage, cartography, obligations, the broker, and load rating.

Same contract as the court tests: every guard is pointed at something known to
violate it, so none of them can pass by being vacuous.
"""

from __future__ import annotations

import ast
from datetime import UTC, datetime
from pathlib import Path

import pytest

from lib.schema import (
    AgentTrust,
    Conclusion,
    ConclusionKind,
    ExternalEffect,
    Obligation,
    ObligationStatus,
    ResidualExposure,
    Reversibility,
    Source,
    SourceKind,
)
from settle.broker import (
    ApprovalBroker,
    BrokerCannotApproveError,
    NotAHumanError,
)
from settle.cartography import counterparty_of, map_counterparties
from settle.compensation import CompensationNotBuiltError, synthesise
from settle.irreversibility import (
    COMPENSABLE_SIGNATURE_THRESHOLD_MINOR,
    triage_all,
    triage_effect,
)
from settle.loadrating import (
    FALSIFICATION_DECAY,
    MIN_RATING,
    NotASourceError,
    assert_not_agent_trust,
    ledger_for,
)
from settle.obligation import build_obligation, residual_exposure

REPO = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 7, 6, 9, 0, tzinfo=UTC)


def _effect(
    connector: str = "email",
    op: str = "send_quote",
    reversibility: Reversibility = Reversibility.IDEMPOTENT,
    amount: int | None = None,
    ref: str = "ref-1",
) -> ExternalEffect:
    return ExternalEffect(
        connector=connector,
        op=op,
        ref=ref,
        reversibility=reversibility,
        occurred_at=NOW,
        amount_minor=amount,
        currency="USD" if amount is not None else None,
    )


def _conclusion(effects: list[ExternalEffect]) -> Conclusion:
    return Conclusion(
        conclusion_id="cnc_test",
        kind=ConclusionKind.ORDER,
        body="test commitment",
        decided_at=NOW,
        owner_principal="principal_01",
        premise_ids=["clm_000000"],
        external_effects=effects,
        committed_lead_days=20,
    )


# ---------------------------------------------------------------------------
# D1 -- triage biases to irreversible under uncertainty
# ---------------------------------------------------------------------------


def test_unknown_reversibility_becomes_irreversible() -> None:
    result = triage_effect(_effect(reversibility=Reversibility.UNKNOWN))
    assert result.reversibility is Reversibility.IRREVERSIBLE
    assert result.defaulted is True
    assert result.requires_signature is True


def test_the_conservative_side_wins_a_disagreement() -> None:
    """A connector claiming a countersignature is idempotent is not believed."""
    result = triage_effect(
        _effect(
            connector="email",
            op="countersign_framework",
            reversibility=Reversibility.IDEMPOTENT,
        )
    )
    assert result.reversibility is Reversibility.IRREVERSIBLE
    assert "not believed" in result.reason


def test_triage_never_returns_unknown() -> None:
    """VACUITY-adjacent: sweep every recorded value and assert the output is total."""
    for recorded in Reversibility:
        for op in ("send_quote", "pay_invoice", "launch_flight", "some_unclassified_op"):
            out = triage_effect(_effect(op=op, reversibility=recorded))
            assert out.reversibility is not Reversibility.UNKNOWN


def test_a_genuinely_idempotent_effect_is_not_dragged_upwards() -> None:
    """The complement: the conservative bias must not classify everything as loss."""
    result = triage_effect(_effect(connector="email", op="send_quote"))
    assert result.reversibility is Reversibility.IDEMPOTENT
    assert result.requires_signature is False


def test_compensable_above_threshold_requires_a_signature() -> None:
    below = triage_effect(
        _effect(
            connector="ads",
            op="launch_flight",
            reversibility=Reversibility.COMPENSABLE,
            amount=COMPENSABLE_SIGNATURE_THRESHOLD_MINOR - 1,
        )
    )
    at = triage_effect(
        _effect(
            connector="ads",
            op="launch_flight",
            reversibility=Reversibility.COMPENSABLE,
            amount=COMPENSABLE_SIGNATURE_THRESHOLD_MINOR,
        )
    )
    assert below.requires_signature is False
    assert at.requires_signature is True


# ---------------------------------------------------------------------------
# D2 -- the cartographer cannot send
# ---------------------------------------------------------------------------

#: Anything that could put a message in front of a counterparty.
_SEND_MARKERS = {
    "send",
    "sendmail",
    "smtp",
    "post",
    "publish",
    "notify",
    "email_out",
    "requests",
    "httpx",
    "urlopen",
}


def _send_capability_names(path: Path) -> set[str]:
    """Every imported module and called attribute that looks like a send."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.update(part for part in alias.name.split("."))
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.update(node.module.split("."))
        elif isinstance(node, ast.Attribute):
            found.add(node.attr)
        elif isinstance(node, ast.FunctionDef):
            found.add(node.name)
    return {name for name in found if name.lower() in _SEND_MARKERS}


def test_cartographer_has_no_send_capability() -> None:
    offenders = _send_capability_names(REPO / "settle" / "cartography.py")
    assert not offenders, f"the cartographer can send: {sorted(offenders)}"


def test_the_no_send_detector_is_not_vacuous() -> None:
    """VACUITY: the same walk over a fixture that CAN send must find it."""
    offenders = _send_capability_names(REPO / "tests" / "fixtures" / "sending_cartographer.py")
    assert offenders, (
        "the no-send detector found nothing in a file that calls smtplib.sendmail, "
        "so it would not have caught a real violation either"
    )


def test_one_commitment_told_twice_is_still_one_counterparty() -> None:
    conclusion = _conclusion(
        [
            _effect(ref="email-1"),
            _effect(connector="payments", op="pay_invoice", ref="pay-1", amount=1000),
        ]
    )
    cmap = map_counterparties(conclusion, old_summary="old", new_summary="new")
    assert len(cmap.tellings) == 2
    assert len(cmap.counterparties) == 1
    assert cmap.counterparties[0] == counterparty_of(conclusion)


# ---------------------------------------------------------------------------
# D3 / D4 -- the obligation, end to end
# ---------------------------------------------------------------------------


def test_obligation_names_all_four_things_with_both_fates() -> None:
    conclusion = _conclusion(
        [
            _effect(ref="email-1"),
            _effect(
                connector="payments",
                op="pay_invoice",
                reversibility=Reversibility.IRREVERSIBLE,
                amount=892_500,
                ref="pay-1",
            ),
        ]
    )
    drafted = build_obligation(
        conclusion=conclusion,
        obligation_id="obl_test",
        old_summary="20 day lead time",
        new_summary="29 day lead time",
        correction_text="We are correcting this.",
    )
    ob = drafted.obligation
    assert ob.counterparties, "WHO is missing"
    assert ob.reversible_actions, "WHAT (reversible) is missing"
    assert drafted.unrecoverable, "the unrecoverable item is missing"
    assert ob.approver and ob.approver.startswith("human::"), "SIGN is missing"
    rendered = drafted.render()
    assert "STILL REVERSIBLE" in rendered
    assert "NOT REVERSIBLE" in rendered
    assert "[X]" in rendered


def test_residual_exposure_is_a_range_with_assumptions_never_a_point() -> None:
    triaged = triage_all(
        [
            _effect(
                connector="payments",
                op="pay_invoice",
                reversibility=Reversibility.IRREVERSIBLE,
                amount=1_000_00,
            ),
            _effect(
                connector="ads",
                op="launch_flight",
                reversibility=Reversibility.COMPENSABLE,
                amount=500_00,
            ),
        ]
    )
    exposure = residual_exposure(triaged)
    assert exposure.low == 1_000_00
    assert exposure.high == 1_500_00
    assert exposure.high > exposure.low, "a range collapsed to a point estimate"
    assert exposure.assumptions, "a range without stated assumptions is a guess"


def test_unpriced_effects_are_counted_never_invented() -> None:
    triaged = triage_all(
        [
            _effect(
                connector="payments",
                op="pay_invoice",
                reversibility=Reversibility.IRREVERSIBLE,
                amount=None,
            )
        ]
    )
    exposure = residual_exposure(triaged)
    assert exposure.unpriced_effects == 1
    assert exposure.low == 0 and exposure.high == 0, "an amount was invented"
    assert any("FLOOR" in a for a in exposure.assumptions)


# ---------------------------------------------------------------------------
# D5 / D6 -- the broker requests, never approves
# ---------------------------------------------------------------------------


def _obligation() -> Obligation:
    return Obligation(
        obligation_id="obl_1",
        conclusion_id="cnc_test",
        counterparties=["counterparty::cnc_test"],
        reversible_actions=["re-issue"],
        residual_exposure=ResidualExposure(low=0, high=0),
        approver="human::commercial-lead::order",
    )


def test_broker_cannot_approve() -> None:
    with pytest.raises(BrokerCannotApproveError):
        ApprovalBroker().approve(_obligation())


@pytest.mark.parametrize(
    "impostor",
    [
        "arbiter@1.0",
        "principal_07",
        "human::arbiter@0.4.0",
        "human::principal_07",
        "human::scripted-stub",
        "correction-obligation@0.4.0",
    ],
)
def test_only_a_human_may_sign(impostor: str) -> None:
    """VACUITY: every agent-shaped signatory is rejected by name."""
    with pytest.raises(NotAHumanError):
        ApprovalBroker().record_human_signature(_obligation(), human=impostor, at=NOW)


def test_a_real_human_can_sign() -> None:
    """The complement: the guard must not reject everybody."""
    broker = ApprovalBroker()
    ob = _obligation()
    broker.request_signature(obligation=ob, unrecoverable_count=0, now=NOW, why="test")
    signed = broker.record_human_signature(ob, human="human::dana.okafor", at=NOW)
    assert signed.status is ObligationStatus.SIGNED
    assert broker.open_obligations() == []


def test_unapproved_obligations_stay_visibly_open() -> None:
    broker = ApprovalBroker()
    ob = _obligation()
    broker.request_signature(obligation=ob, unrecoverable_count=1, now=NOW, why="test")
    assert ob.status is ObligationStatus.AWAITING_SIGNATURE
    # Nothing ages it out; there is no expiry path to call.
    assert len(broker.open_obligations()) == 1
    assert not hasattr(broker, "expire")
    assert not hasattr(broker, "auto_approve")


def test_broker_refuses_an_obligation_with_no_approver() -> None:
    ob = _obligation()
    ob.approver = None
    with pytest.raises(NotAHumanError):
        ApprovalBroker().request_signature(
            obligation=ob, unrecoverable_count=0, now=NOW, why="test"
        )


# ---------------------------------------------------------------------------
# 3.9 -- compensation is DESIGNED and refuses
# ---------------------------------------------------------------------------


def test_compensation_refuses_rather_than_half_generating() -> None:
    with pytest.raises(CompensationNotBuiltError) as exc:
        synthesise(_effect(connector="payments", op="pay_invoice"))
    assert "DESIGNED" in str(exc.value)


# ---------------------------------------------------------------------------
# D7 / D8 -- load rating: versioned, reversible, contestable, and NOT reputation
# ---------------------------------------------------------------------------


def _source() -> Source:
    return Source(
        source_id="src_supplier_K",
        name="Supplier K",
        kind=SourceKind.SUPPLIER_EMAIL,
        load_rating=0.5,
        authority=["supplier_K."],
    )


def test_load_rating_downgrades_and_is_versioned() -> None:
    ledger = ledger_for(_source(), at=NOW)
    assert ledger.rating == 0.5
    assert len(ledger.versions) == 1

    ledger.falsified(at=NOW, claim_id="clm_000000", reason="lead time was false")
    assert ledger.rating == pytest.approx(0.5 * FALSIFICATION_DECAY)
    assert len(ledger.versions) == 2
    # Nothing was overwritten.
    assert ledger.versions[0].rating == 0.5


def test_load_rating_is_reversible_without_erasing_history() -> None:
    ledger = ledger_for(_source(), at=NOW)
    ledger.falsified(at=NOW, claim_id="clm_1", reason="wrong")
    ledger.revert_to(1, at=NOW, reason="retraction was itself withdrawn")
    assert ledger.rating == 0.5
    assert len(ledger.versions) == 3, "reversion deleted history instead of appending"
    assert ledger.current.reverted_from == 1


def test_load_rating_is_contestable_and_the_contest_is_kept() -> None:
    ledger = ledger_for(_source(), at=NOW)
    ledger.falsified(at=NOW, claim_id="clm_1", reason="wrong")
    flagged = ledger.contest(2, note="the amendment, not us, moved the date")
    assert flagged.contested is True
    assert flagged.contest_note
    assert len(ledger.versions) == 2, "contesting removed the version"


def test_load_rating_never_reaches_zero() -> None:
    ledger = ledger_for(_source(), at=NOW)
    for i in range(40):
        ledger.falsified(at=NOW, claim_id=f"clm_{i}", reason="wrong again")
    assert ledger.rating >= MIN_RATING


def test_load_rating_refuses_agent_trust() -> None:
    """D8: the separation, enforced."""
    trust = AgentTrust(agent_id="extractor@1.0", reputation=0.9, reliability=0.9)
    with pytest.raises(NotASourceError):
        assert_not_agent_trust(trust)


def test_the_agent_trust_guard_is_not_vacuous_and_not_over_broad() -> None:
    """VACUITY both ways: it fires on agent-shaped input, stays quiet on a source."""
    with pytest.raises(NotASourceError):
        assert_not_agent_trust({"agent_id": "x", "reputation": 0.5})
    # And a genuine source passes.
    assert_not_agent_trust(_source())
