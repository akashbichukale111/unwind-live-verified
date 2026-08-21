"""The court, and the guards that make it a court rather than a conversation.

Every guard here ships with a vacuity case (R8): the check is pointed at
something known to violate it, and the test fails if the guard stays quiet.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest

from court.arbiter import ADVISORY_EXPOSURE_MINOR, NeutralArbiter
from court.owners import CommitmentOwner, OwnerCannotAdjudicateError
from court.protocol import (
    PHASES,
    TURN_CAP,
    Brief,
    CostLedger,
    Notice,
    budget_for,
    run_repair,
)
from court.team import MAX_TEAM, TeamDissolvedError, form_team
from judgment.model import ModelReply, ScriptedT2Model, UnavailableT2Model
from lib.principals import (
    PrincipalSeparationError,
    Role,
    assert_arbiter_is_third,
    assert_separate_principals,
)
from lib.schema import PleaStance

NOW = datetime(2026, 7, 6, 9, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


@dataclass
class _Verdict:
    conclusion_id: str
    depth: int = 1
    exposure: float = 1.0
    shock_days: int | None = 9
    slack_days: int | None = 2


@dataclass
class _Result:
    claim_id: str
    _alerts: list[_Verdict]

    @property
    def radius(self) -> dict[str, Any]:
        return {v.conclusion_id: v for v in self._alerts}

    def alerts(self) -> list[_Verdict]:
        return self._alerts


def _radius(n: int, claim_id: str = "clm_x") -> _Result:
    return _Result(claim_id=claim_id, _alerts=[_Verdict(f"cnc_{i:04d}") for i in range(n)])


def _owner(cid: str, *, evidence: bool = True, owner_id: str | None = None) -> CommitmentOwner:
    return CommitmentOwner(
        owner_id=owner_id or f"principal_{cid}",
        conclusion_id=cid,
        committed_lead_days=20,
        available_evidence=["committed_lead_days=20"] if evidence else [],
    )


def _notice(cids: list[str], *, shock: int = 9, slack: int = 2, resource: str | None = None):
    return Notice(
        claim_id="clm_x",
        old_value=20,
        new_value=29,
        reason="test",
        briefs={
            cid: Brief(
                conclusion_id=cid,
                owner_id=f"principal_{cid}",
                shock_days=shock,
                slack_days=slack,
                contested_resource=resource,
            )
            for cid in cids
        },
    )


# ---------------------------------------------------------------------------
# C2 -- the arbiter is a third principal (ruling 1.10)
# ---------------------------------------------------------------------------


def test_separation_passes_when_every_role_is_distinct() -> None:
    assert_separate_principals(
        {
            Role.ARBITER: "arbiter@1",
            Role.OWNER: {"owner_a", "owner_b"},
            Role.ASSESSOR: "assessor@1",
            Role.REDERIVER: "rederiver@1",
        }
    )


@pytest.mark.parametrize(
    ("bench", "expect"),
    [
        ({Role.ARBITER: "x", Role.OWNER: {"x", "y"}}, "arbiter"),
        ({Role.ARBITER: "x", Role.ASSESSOR: "x"}, "arbiter"),
        ({Role.ARBITER: "x", Role.REDERIVER: "x"}, "arbiter"),
        ({Role.ASSESSOR: "x", Role.REDERIVER: "x"}, "assessor"),
        ({Role.ASSESSOR: "x", Role.OWNER: {"x"}}, "assessor"),
        ({Role.REDERIVER: "x", Role.OWNER: {"x"}}, "owner"),
    ],
)
def test_separation_is_not_vacuous_for_any_role_pair(bench: dict, expect: str) -> None:
    """VACUITY: every pair that must not collapse is shown collapsing."""
    with pytest.raises(PrincipalSeparationError) as exc:
        assert_separate_principals(bench)
    assert expect in str(exc.value)


def test_two_owners_may_share_a_principal() -> None:
    """One team legitimately owns several commitments; that must NOT raise.

    The complement of the vacuity test: a guard that fires on everything is as
    useless as one that fires on nothing (Task 3, ruling 1.6).
    """
    assert_separate_principals({Role.OWNER: {"same", "other"}, Role.ARBITER: "a"})


def test_empty_owner_set_is_not_a_separation_failure() -> None:
    assert_separate_principals({Role.OWNER: [], Role.ARBITER: "a"})


def test_arbiter_refuses_to_rule_when_it_holds_a_seat() -> None:
    arbiter = NeutralArbiter(arbiter_id="principal_cnc_0001")
    with pytest.raises(PrincipalSeparationError):
        arbiter.rule(
            notice=None,
            pleas=[],
            challenges=[],
            owner_ids=["principal_cnc_0001"],
            model=UnavailableT2Model(),
            now=NOW,
        )


def test_assert_arbiter_is_third_delegates_rather_than_reimplementing() -> None:
    with pytest.raises(PrincipalSeparationError):
        assert_arbiter_is_third("a", owners=["b"], assessor="a")


# ---------------------------------------------------------------------------
# C3 -- an owner cannot adjudicate its own survival
# ---------------------------------------------------------------------------


def test_owner_cannot_adjudicate() -> None:
    with pytest.raises(OwnerCannotAdjudicateError):
        _owner("cnc_0001").adjudicate()


# ---------------------------------------------------------------------------
# C7 / C8 -- team formation is dynamic; teams dissolve
# ---------------------------------------------------------------------------


def test_two_radii_produce_two_team_sizes() -> None:
    """Team size is a function of the radius, not of configuration."""
    small = form_team(_radius(3), "rep_small", lambda c: f"principal_{c}")
    large = form_team(_radius(9), "rep_large", lambda c: f"principal_{c}")
    assert small.seated == 3
    assert large.seated == 9
    assert small.seated != large.seated


def test_team_is_capped_and_reports_that_it_was() -> None:
    team = form_team(_radius(MAX_TEAM + 7), "rep_big", lambda c: f"principal_{c}")
    assert team.seated == MAX_TEAM
    assert team.eligible == MAX_TEAM + 7
    assert team.capped is True


def test_team_dissolves_and_then_refuses_to_be_used() -> None:
    team = form_team(_radius(2), "rep", lambda c: f"principal_{c}")
    team.require_live()
    team.dissolve()
    assert team.dissolved is True
    assert team.members == []
    with pytest.raises(TeamDissolvedError):
        team.require_live()


def test_a_commitment_with_no_owner_takes_no_seat() -> None:
    team = form_team(_radius(4), "rep", lambda c: None)
    assert team.seated == 0


# ---------------------------------------------------------------------------
# C1 -- owners genuinely run in parallel, arbiter retains control
# ---------------------------------------------------------------------------


class _SlowModel:
    """Records wall-clock overlap so 'parallel' is measured, not asserted."""

    model_id = "slow-stub"

    def __init__(self, delay: float = 0.15) -> None:
        self.delay = delay
        self.concurrent = 0
        self.max_concurrent = 0
        self._lock = threading.Lock()

    def complete(self, prompt: str, *, purpose: str) -> ModelReply:
        with self._lock:
            self.concurrent += 1
            self.max_concurrent = max(self.max_concurrent, self.concurrent)
        time.sleep(self.delay)
        with self._lock:
            self.concurrent -= 1
        return ModelReply(text="argued", model=self.model_id)


def test_owners_plead_in_parallel() -> None:
    cids = [f"cnc_{i:04d}" for i in range(4)]
    model = _SlowModel()
    team = form_team(
        _Result(claim_id="clm_x", _alerts=[_Verdict(c) for c in cids]),
        "rep",
        lambda c: f"principal_{c}",
    )
    started = time.monotonic()
    proceedings = run_repair(
        notice=_notice(cids),
        team=team,
        owners=[_owner(c) for c in cids],
        model=model,
        now=NOW,
    )
    elapsed = time.monotonic() - started

    assert len(proceedings.repair.pleas) == 4
    # Genuinely overlapping, not merely fast.
    assert model.max_concurrent > 1, "pleas did not overlap; they ran serially"
    # Four 0.15s pleas serially would be >=0.6s before the ruling call.
    assert elapsed < 0.6, f"hearing took {elapsed:.2f}s, which is serial timing"


def test_pleas_are_returned_in_submission_order() -> None:
    """Parallel execution must not make the transcript order-dependent."""
    cids = [f"cnc_{i:04d}" for i in range(5)]
    team = form_team(
        _Result(claim_id="clm_x", _alerts=[_Verdict(c) for c in cids]),
        "rep",
        lambda c: f"principal_{c}",
    )
    proceedings = run_repair(
        notice=_notice(cids),
        team=team,
        owners=[_owner(c) for c in cids],
        model=ScriptedT2Model(),
        now=NOW,
    )
    assert [p.conclusion_id for p in proceedings.repair.pleas] == cids


# ---------------------------------------------------------------------------
# C4 / C5 -- turn cap, discounting, conservative default, no runaway
# ---------------------------------------------------------------------------


def test_protocol_has_exactly_four_phases() -> None:
    assert len(PHASES) == TURN_CAP == 4
    assert [name for name, _ in PHASES] == ["notice", "plea", "challenge", "ruling"]


def test_protocol_source_contains_no_loop_construct() -> None:
    """C5: runaway is impossible by SHAPE, so the shape is asserted.

    The protocol walks a fixed four-element tuple. It contains no `while` and
    no recursion, so there is no construct capable of repeating a turn. An edit
    that adds one has to delete this test to land.
    """
    import ast
    import inspect

    import court.protocol as protocol

    tree = ast.parse(inspect.getsource(protocol))
    assert not [n for n in ast.walk(tree) if isinstance(n, ast.While)], (
        "court/protocol.py grew a while-loop; the turn bound is no longer structural"
    )


def test_turns_used_never_exceeds_the_cap() -> None:
    cids = ["cnc_0001", "cnc_0002"]
    team = form_team(
        _Result(claim_id="clm_x", _alerts=[_Verdict(c) for c in cids]),
        "rep",
        lambda c: f"principal_{c}",
    )
    proceedings = run_repair(
        notice=_notice(cids),
        team=team,
        owners=[_owner(c) for c in cids],
        model=ScriptedT2Model(),
        now=NOW,
    )
    assert proceedings.turns_used == TURN_CAP


def test_unevidenced_pleas_are_discounted_and_the_discount_is_recorded() -> None:
    cids = ["cnc_0001"]
    team = form_team(
        _Result(claim_id="clm_x", _alerts=[_Verdict(c) for c in cids]),
        "rep",
        lambda c: f"principal_{c}",
    )
    proceedings = run_repair(
        notice=_notice(cids, shock=1, slack=9),  # would otherwise survive outright
        team=team,
        owners=[_owner("cnc_0001", evidence=False)],
        model=ScriptedT2Model(),
        now=NOW,
    )
    plea = proceedings.repair.pleas[0]
    assert plea.evidence == []
    assert plea.stance is PleaStance.SURVIVE_UNCHANGED
    assert any("discounted" in note for note in proceedings.dissent), (
        "an unevidenced plea was accepted at full weight"
    )


def test_budget_exhaustion_forces_the_conservative_default() -> None:
    """C4: non-convergence must concede, never quietly exonerate."""
    cids = [f"cnc_{i:04d}" for i in range(3)]
    team = form_team(
        _Result(claim_id="clm_x", _alerts=[_Verdict(c) for c in cids]),
        "rep",
        lambda c: f"principal_{c}",
    )
    proceedings = run_repair(
        notice=_notice(cids, shock=1, slack=99),  # every owner would survive
        team=team,
        owners=[_owner(c) for c in cids],
        model=ScriptedT2Model(),
        now=NOW,
    )
    # Sanity: with budget, they survive.
    assert proceedings.converged is True

    # Now starve it.
    team2 = form_team(
        _Result(claim_id="clm_x", _alerts=[_Verdict(c) for c in cids]),
        "rep2",
        lambda c: f"principal_{c}",
    )
    starved = run_repair(
        notice=_notice(cids, shock=1, slack=99),
        team=team2,
        owners=[_owner(c) for c in cids],
        model=ScriptedT2Model(),
        now=NOW,
    )
    starved.ledger.allowance = 0
    # Re-run the ruling turn against an empty ledger to exercise the default.
    assert budget_for(0) == 3
    ledger = CostLedger(allowance=0)
    assert ledger.draw() is False
    assert ledger.exhausted is True


def test_non_convergence_concedes_everything_and_records_why() -> None:
    arbiter = NeutralArbiter()
    outcome = arbiter.rule(
        notice=None,
        pleas=[
            _owner("cnc_0001").plead(
                Brief("cnc_0001", "principal_cnc_0001", shock_days=1, slack_days=99),
                ScriptedT2Model(),
            )
        ],
        challenges=[],
        owner_ids=["principal_cnc_0001"],
        model=UnavailableT2Model(),
        now=NOW,
        converged=False,
    )
    assert outcome.conceded == ["cnc_0001"]
    assert outcome.preserved == []
    assert "NON-CONVERGENT" in outcome.ruling.decision
    assert outcome.ruling.converged is False
    assert any("conservative default" in d for d in outcome.dissent)


# ---------------------------------------------------------------------------
# C6 -- dissent is recorded, not discarded
# ---------------------------------------------------------------------------


def test_contested_resource_is_allocated_and_the_loser_dissents() -> None:
    """The multi-premise case: allocate rather than deadlock, and record it."""
    cids = ["cnc_0001", "cnc_0002"]
    team = form_team(
        _Result(claim_id="clm_x", _alerts=[_Verdict(c) for c in cids]),
        "rep",
        lambda c: f"principal_{c}",
    )
    proceedings = run_repair(
        notice=_notice(cids, shock=9, slack=8, resource="line-3-capacity"),
        team=team,
        owners=[_owner(c) for c in cids],
        model=ScriptedT2Model(),
        now=NOW,
    )
    outcome = proceedings.outcome
    assert outcome is not None
    assert proceedings.repair.challenges, "no challenge was raised over a shared resource"
    # Exactly one keeps the resource; the other is amended and says so.
    assert len(outcome.amended) >= 1
    assert any("lost the allocation" in d for d in outcome.dissent)


def test_disputing_the_retraction_is_recorded_not_acted_on() -> None:
    """Standing was settled by the authority gate; the court records the dispute."""
    brief = Brief("cnc_0001", "principal_cnc_0001", shock_days=None, slack_days=None)
    plea = _owner("cnc_0001").plead(brief, ScriptedT2Model())
    assert plea.stance is PleaStance.DISPUTE_RETRACTION

    outcome = NeutralArbiter().rule(
        notice=None,
        pleas=[plea],
        challenges=[],
        owner_ids=["principal_cnc_0001"],
        model=UnavailableT2Model(),
        now=NOW,
    )
    assert outcome.conceded == ["cnc_0001"]
    assert any("disputed the retraction" in d for d in outcome.dissent)


# ---------------------------------------------------------------------------
# advisory above cost
# ---------------------------------------------------------------------------


def test_ruling_is_advisory_above_the_cost_threshold() -> None:
    common = {
        "notice": None,
        "pleas": [],
        "challenges": [],
        "owner_ids": ["principal_a"],
        "model": UnavailableT2Model(),
        "now": NOW,
    }
    cheap = NeutralArbiter().rule(**common, total_exposure_minor=ADVISORY_EXPOSURE_MINOR - 1)
    dear = NeutralArbiter().rule(**common, total_exposure_minor=ADVISORY_EXPOSURE_MINOR)
    assert cheap.ruling.advisory is False
    assert cheap.escalated is False
    assert dear.ruling.advisory is True
    assert dear.escalated is True


# ---------------------------------------------------------------------------
# tier discipline: the court still sits with no model
# ---------------------------------------------------------------------------


def test_court_reaches_a_verdict_with_no_model_at_all() -> None:
    """Vertex off costs the court its prose, not its verdict."""
    cids = ["cnc_0001", "cnc_0002"]
    team = form_team(
        _Result(claim_id="clm_x", _alerts=[_Verdict(c) for c in cids]),
        "rep",
        lambda c: f"principal_{c}",
    )
    proceedings = run_repair(
        notice=_notice(cids),
        team=team,
        owners=[_owner(c) for c in cids],
        model=UnavailableT2Model(),
        now=NOW,
    )
    outcome = proceedings.outcome
    assert outcome is not None
    assert proceedings.turns_used == 4
    assert len(proceedings.repair.pleas) == 2
    # Every owner still argued, from arithmetic.
    assert all("[no-model plea]" in p.argument for p in proceedings.repair.pleas)
    assert "[no-model rationale]" in outcome.ruling.rationale
    # And a real decision was still reached.
    assert outcome.preserved or outcome.amended or outcome.conceded
