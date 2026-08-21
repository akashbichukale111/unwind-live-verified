"""Card 0: WARRANT ledger -- the pure fold, decay, and the guarded mutations.

Split in two halves, clearly marked:

  PURE section    -- no Firestore. `fold_balance`, `apply_decay`,
                     `is_case_challenged`, `provenance_for_fold`, and
                     `WarrantEvent`'s own integer-only validation are plain
                     functions over a `list[WarrantEvent]`; these tests
                     construct that list in-process and never touch a client.

  PERSISTED section -- skipped unless a Firestore emulator is answering
                     (`make emulator`), because `mint`/`burn`/`spend_or_refuse`/
                     `challenge` are guarded operations that read the Memory
                     Bank (`tower/memory.py`) and this ledger's own
                     collection.
"""

from __future__ import annotations

import os
import socket
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from warrant.ledger import (
    EventKind,
    Provenance,
    WarrantEvent,
    apply_decay,
    balance_key,
    fold_balance,
    is_case_challenged,
    parse_balance_key,
    provenance_for_fold,
)

# ===========================================================================
# PURE section -- no Firestore.
# ===========================================================================


def _ev(
    kind: EventKind,
    amount_bp: int,
    at: datetime,
    *,
    provenance: Provenance = Provenance.EARNED,
    principal: str = "agent::p",
    capability: str = "extract",
    risk_class: str = "LOW",
    case_id: str | None = None,
    event_id: str | None = None,
) -> WarrantEvent:
    return WarrantEvent(
        event_id=event_id or f"e_{uuid.uuid4().hex[:8]}",
        principal=principal,
        capability=capability,
        risk_class=risk_class,
        kind=kind,
        amount_bp=amount_bp,
        provenance=provenance,
        case_id=case_id,
        reason="test",
        at=at,
    )


T0 = datetime(2026, 1, 1, tzinfo=UTC)


def test_amount_bp_must_be_a_nonnegative_int() -> None:
    with pytest.raises(TypeError):
        _ev(EventKind.MINT, 1.5, T0)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        _ev(EventKind.MINT, True, T0)  # bool is technically an int -- rejected anyway
    with pytest.raises(ValueError):
        _ev(EventKind.MINT, -1, T0)


def test_balance_key_round_trips() -> None:
    key = balance_key("extract", "HIGH")
    assert key == "extract::HIGH"
    assert parse_balance_key(key) == ("extract", "HIGH")


def test_empty_fold_is_zero() -> None:
    assert (
        fold_balance([], principal="agent::p", capability="extract", risk_class="LOW", as_of=T0)
        == 0
    )


def test_mint_then_spend_is_a_pure_subtraction_with_no_gap() -> None:
    events = [_ev(EventKind.MINT, 1000, T0), _ev(EventKind.SPEND, 300, T0)]
    balance = fold_balance(
        events, principal="agent::p", capability="extract", risk_class="LOW", as_of=T0
    )
    assert balance == 700


def test_spend_cannot_drive_balance_negative() -> None:
    events = [_ev(EventKind.MINT, 100, T0), _ev(EventKind.SPEND, 500, T0)]
    balance = fold_balance(
        events, principal="agent::p", capability="extract", risk_class="LOW", as_of=T0
    )
    assert balance == 0


def test_fold_ignores_events_for_a_different_key() -> None:
    """Cross-class/cross-capability isolation, proven at the pure-fold level."""
    events = [
        _ev(EventKind.MINT, 5000, T0, risk_class="LOW"),
        _ev(EventKind.MINT, 5000, T0, risk_class="HIGH"),
        _ev(EventKind.MINT, 5000, T0, capability="draft"),
        _ev(EventKind.MINT, 5000, T0, principal="agent::other"),
    ]
    low = fold_balance(
        events, principal="agent::p", capability="extract", risk_class="LOW", as_of=T0
    )
    assert low == 5000  # only the matching key's MINT counted


def test_decay_reduces_balance_over_idle_days() -> None:
    events = [_ev(EventKind.MINT, 10_000, T0)]
    later = T0 + timedelta(days=30)
    balance = fold_balance(
        events, principal="agent::p", capability="extract", risk_class="LOW", as_of=later
    )
    assert 0 < balance < 10_000
    # 0.5%/day compounding for 30 days: retains (199/200)^30 ~ 0.8604.
    assert 8500 <= balance <= 8700


def test_decay_is_deterministic_and_time_of_evaluation_independent() -> None:
    """The whole point of exponential decay over a lazy fold: computing the
    balance now or computing it later, for the SAME as_of, gives the SAME
    integer. This is the property `apply_decay`'s docstring calls out."""
    events = [_ev(EventKind.MINT, 12_345, T0)]
    as_of = T0 + timedelta(days=17)
    first = fold_balance(
        events, principal="agent::p", capability="extract", risk_class="LOW", as_of=as_of
    )
    second = fold_balance(
        events, principal="agent::p", capability="extract", risk_class="LOW", as_of=as_of
    )
    assert first == second


def test_apply_decay_is_a_pure_integer_function() -> None:
    assert apply_decay(0, 100) == 0
    assert apply_decay(1000, 0) == 1000
    result = apply_decay(1000, 1)
    assert isinstance(result, int)
    assert result == 995  # 1000 * 199 // 200


def test_is_case_challenged() -> None:
    events = [_ev(EventKind.CHALLENGE, 0, T0, case_id="case_1")]
    assert is_case_challenged(events, "case_1") is True
    assert is_case_challenged(events, "case_2") is False


def test_challenge_event_carries_no_balance_arithmetic() -> None:
    events = [_ev(EventKind.MINT, 1000, T0), _ev(EventKind.CHALLENGE, 0, T0, case_id="c")]
    balance = fold_balance(
        events, principal="agent::p", capability="extract", risk_class="LOW", as_of=T0
    )
    assert balance == 1000  # the CHALLENGE did not touch the number


def test_decay_checkpoint_event_is_arithmetic_neutral() -> None:
    events = [
        _ev(EventKind.MINT, 1000, T0),
        _ev(EventKind.DECAY, 0, T0 + timedelta(days=5)),
    ]
    with_checkpoint = fold_balance(
        events,
        principal="agent::p",
        capability="extract",
        risk_class="LOW",
        as_of=T0 + timedelta(days=5),
    )
    without_checkpoint = fold_balance(
        events[:1],
        principal="agent::p",
        capability="extract",
        risk_class="LOW",
        as_of=T0 + timedelta(days=5),
    )
    assert with_checkpoint == without_checkpoint


def test_provenance_for_fold_is_synthetic_if_any_event_is() -> None:
    all_earned = [_ev(EventKind.MINT, 100, T0, provenance=Provenance.EARNED)]
    assert provenance_for_fold(all_earned) is Provenance.EARNED

    mixed = [
        _ev(EventKind.MINT, 100, T0, provenance=Provenance.EARNED),
        _ev(EventKind.MINT, 50, T0, provenance=Provenance.SYNTHETIC),
    ]
    assert provenance_for_fold(mixed) is Provenance.SYNTHETIC  # contamination not diluted

    assert provenance_for_fold([]) is Provenance.SYNTHETIC  # nothing earned yet == honest default


def test_seeded_and_earned_events_fold_identically() -> None:
    """The load-bearing claim: `fold_balance` never reads `.provenance`. Two
    event lists that differ ONLY in provenance labels fold to the same
    integer -- SYNTHETIC and EARNED are metadata, not different math.
    """
    earned = [
        _ev(EventKind.MINT, 1000, T0, provenance=Provenance.EARNED, event_id="e1"),
        _ev(
            EventKind.SPEND,
            250,
            T0 + timedelta(days=3),
            provenance=Provenance.EARNED,
            event_id="e2",
        ),
    ]
    synthetic = [
        _ev(EventKind.MINT, 1000, T0, provenance=Provenance.SYNTHETIC, event_id="e1"),
        _ev(
            EventKind.SPEND,
            250,
            T0 + timedelta(days=3),
            provenance=Provenance.SYNTHETIC,
            event_id="e2",
        ),
    ]
    as_of = T0 + timedelta(days=10)
    a = fold_balance(
        earned, principal="agent::p", capability="extract", risk_class="LOW", as_of=as_of
    )
    b = fold_balance(
        synthetic, principal="agent::p", capability="extract", risk_class="LOW", as_of=as_of
    )
    assert a == b


def test_rederive_bit_equality_over_500_mixed_events() -> None:
    """Eval scenario (f): 500 mixed EARNED+SYNTHETIC events, re-folded twice,
    bit-equal. Deterministic PRNG (seeded) so the test itself is reproducible.
    """
    import random

    rng = random.Random(20260817)
    events: list[WarrantEvent] = []
    cursor = T0
    for i in range(500):
        cursor = cursor + timedelta(hours=rng.randint(1, 40))
        kind = rng.choice([EventKind.MINT, EventKind.MINT, EventKind.SPEND, EventKind.BURN])
        amount = rng.randint(1, 500)
        provenance = rng.choice([Provenance.EARNED, Provenance.SYNTHETIC])
        events.append(_ev(kind, amount, cursor, provenance=provenance, event_id=f"mix_{i:04d}"))
    as_of = cursor + timedelta(days=2)

    first = fold_balance(
        events, principal="agent::p", capability="extract", risk_class="LOW", as_of=as_of
    )
    # Re-fold from a freshly-ordered COPY (simulating "read the log back from
    # storage in some other order") -- the fold sorts internally, so the
    # input order must not matter either.
    shuffled = list(events)
    rng.shuffle(shuffled)
    second = fold_balance(
        shuffled, principal="agent::p", capability="extract", risk_class="LOW", as_of=as_of
    )
    assert first == second
    assert isinstance(first, int)


# ===========================================================================
# PERSISTED section -- needs the Firestore emulator.
# ===========================================================================


def _emulator_up() -> bool:
    host = os.environ.get("FIRESTORE_EMULATOR_HOST", "localhost:8080")
    hostname, _, port = host.partition(":")
    try:
        with socket.create_connection((hostname, int(port or 8080)), timeout=1.0):
            return True
    except OSError:
        return False


pytestmark_emulator = pytest.mark.skipif(
    not _emulator_up(), reason="Firestore emulator not running; start it with `make emulator`"
)


@pytest.fixture(scope="module", autouse=True)
def _emulator_project():
    if not _emulator_up():
        yield
        return
    os.environ.setdefault("FIRESTORE_EMULATOR_HOST", "localhost:8080")
    os.environ["UNWIND_PROJECT_ID"] = "unwind-warrant-ledger-test"
    from lib import firestore as fs
    from lib.config import reset_config_cache

    reset_config_cache()
    fs.reset_client()
    yield
    fs.reset_client()
    reset_config_cache()


def _fresh_agent(agent_id: str, **overrides):
    from tower.registry import make_entry

    defaults = dict(
        capabilities=["extract"],
        max_budget=1000,
        authority_scope=["claim.read"],
        risk_class_thresholds={"LOW": 1000, "HIGH": 100},
        warrant_mint_schedule={"LOW": 500, "HIGH": 50},
        warrant_spend_schedule={"LOW": 100, "HIGH": 100},
    )
    defaults.update(overrides)
    return make_entry(agent_id, **defaults)


@pytestmark_emulator
def test_mint_without_records_raises_forger() -> None:
    """Adversary: forger. MINT is refused if neither a human-concurrence nor
    a countersign record exists for the case."""
    from warrant.ledger import MintPreconditionError, mint, reset_for_test

    agent = _fresh_agent(f"forger_{uuid.uuid4().hex[:6]}")
    reset_for_test(principal=agent.principal)
    case_id = f"case_{uuid.uuid4().hex[:8]}"

    with pytest.raises(MintPreconditionError):
        mint(agent=agent, capability="extract", risk_class="LOW", case_id=case_id, reason="forged")


@pytestmark_emulator
def test_mint_with_only_human_concurrence_still_raises() -> None:
    from warrant.ledger import MintPreconditionError, mint, record_human_concurrence, reset_for_test

    agent = _fresh_agent(f"forger2_{uuid.uuid4().hex[:6]}")
    reset_for_test(principal=agent.principal)
    case_id = f"case_{uuid.uuid4().hex[:8]}"
    record_human_concurrence(case_id, principal="human::alice", note="looks right")

    with pytest.raises(MintPreconditionError):
        mint(agent=agent, capability="extract", risk_class="LOW", case_id=case_id, reason="forged")


@pytestmark_emulator
def test_mint_with_gemini_family_countersign_raises() -> None:
    """A same-family countersign (Gemini agreeing with Gemini) does not
    count -- warrant requires an INDEPENDENT family."""
    from warrant.ledger import (
        MintPreconditionError,
        mint,
        record_countersign,
        record_human_concurrence,
        reset_for_test,
    )

    agent = _fresh_agent(f"samefam_{uuid.uuid4().hex[:6]}")
    reset_for_test(principal=agent.principal)
    case_id = f"case_{uuid.uuid4().hex[:8]}"
    record_human_concurrence(case_id, principal="human::alice", note="ok")
    from lib.config import MODEL_DEEP

    record_countersign(case_id, agrees=True, family=MODEL_DEEP, simulated=False)

    with pytest.raises(MintPreconditionError):
        mint(agent=agent, capability="extract", risk_class="LOW", case_id=case_id, reason="x")


@pytestmark_emulator
def test_mint_with_unflagged_simulation_env_off_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """A simulated countersign only counts with UNWIND_COUNTERSIGN_SIMULATED=1
    set -- otherwise a simulated input could silently be mistaken for real."""
    from warrant.ledger import (
        MintPreconditionError,
        mint,
        record_countersign,
        record_human_concurrence,
        reset_for_test,
    )

    monkeypatch.delenv("UNWIND_COUNTERSIGN_SIMULATED", raising=False)
    agent = _fresh_agent(f"unflagged_{uuid.uuid4().hex[:6]}")
    reset_for_test(principal=agent.principal)
    case_id = f"case_{uuid.uuid4().hex[:8]}"
    record_human_concurrence(case_id, principal="human::alice", note="ok")
    record_countersign(case_id, agrees=True, family="gemma-simulated", simulated=True)

    with pytest.raises(MintPreconditionError):
        mint(agent=agent, capability="extract", risk_class="LOW", case_id=case_id, reason="x")


@pytestmark_emulator
def test_mint_with_valid_records_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    from warrant.ledger import (
        current_balance,
        mint,
        record_countersign,
        record_human_concurrence,
        reset_for_test,
    )

    monkeypatch.setenv("UNWIND_COUNTERSIGN_SIMULATED", "1")
    agent = _fresh_agent(f"valid_{uuid.uuid4().hex[:6]}")
    reset_for_test(principal=agent.principal)
    case_id = f"case_{uuid.uuid4().hex[:8]}"
    record_human_concurrence(case_id, principal="human::alice", note="ok")
    record_countersign(case_id, agrees=True, family="gemma-simulated", simulated=True)

    event = mint(agent=agent, capability="extract", risk_class="LOW", case_id=case_id, reason="x")
    assert event.amount_bp == 500  # agent.warrant_mint_schedule["LOW"]
    assert current_balance(agent.principal, "extract", "LOW") == 500


@pytestmark_emulator
def test_challenge_freezes_minting_for_that_case_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """Eval scenario (e): CHALLENGE freeze on countersign disagreement."""
    from warrant.ledger import (
        CaseChallengedError,
        challenge,
        mint,
        record_countersign,
        record_human_concurrence,
        reset_for_test,
    )

    monkeypatch.setenv("UNWIND_COUNTERSIGN_SIMULATED", "1")
    agent = _fresh_agent(f"chal_{uuid.uuid4().hex[:6]}")
    reset_for_test(principal=agent.principal)

    disputed_case = f"case_{uuid.uuid4().hex[:8]}"
    record_human_concurrence(disputed_case, principal="human::alice", note="ok")
    record_countersign(disputed_case, agrees=False, family="gemma-simulated", simulated=True)
    challenge(
        case_id=disputed_case,
        principal=agent.principal,
        capability="extract",
        risk_class="LOW",
        reason="countersign disagreed",
    )
    # Even with a LATER valid countersign added, the freeze holds -- no unfreeze path.
    record_countersign(disputed_case, agrees=True, family="gemma-simulated", simulated=True)
    with pytest.raises(CaseChallengedError):
        mint(
            agent=agent,
            capability="extract",
            risk_class="LOW",
            case_id=disputed_case,
            reason="should be frozen",
        )

    # A DIFFERENT case for the same agent is unaffected.
    clean_case = f"case_{uuid.uuid4().hex[:8]}"
    record_human_concurrence(clean_case, principal="human::alice", note="ok")
    record_countersign(clean_case, agrees=True, family="gemma-simulated", simulated=True)
    event = mint(
        agent=agent, capability="extract", risk_class="LOW", case_id=clean_case, reason="fine"
    )
    assert event.amount_bp == 500


@pytestmark_emulator
def test_spend_or_refuse_cold_start_refuses() -> None:
    """Eval scenario (a): cold start, zero warrant, everything human-routed."""
    from warrant.ledger import reset_for_test, spend_or_refuse

    agent = _fresh_agent(f"cold_{uuid.uuid4().hex[:6]}")
    reset_for_test(principal=agent.principal)

    result = spend_or_refuse(
        agent=agent,
        capability="extract",
        risk_class="LOW",
        task="t",
        case_id=None,
        acting_principal=agent.principal,
    )
    assert result.allowed is False
    assert result.balance_before == 0


@pytestmark_emulator
def test_earn_up_across_n_cases_crosses_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    """Eval scenario (b): earn-up across N validated cases -> threshold
    crossed -> delegation begins. Mirrors the cold-start demo moment."""
    from warrant.ledger import (
        mint,
        record_countersign,
        record_human_concurrence,
        reset_for_test,
        spend_or_refuse,
    )

    monkeypatch.setenv("UNWIND_COUNTERSIGN_SIMULATED", "1")
    agent = _fresh_agent(f"earnup_{uuid.uuid4().hex[:6]}", warrant_spend_schedule={"LOW": 1200})
    reset_for_test(principal=agent.principal)

    # Below threshold: first two validated outcomes (500bp each = 1000bp) are
    # not enough to cover a 1200bp delegation.
    for i in range(2):
        case_id = f"case_earnup_{i}_{uuid.uuid4().hex[:6]}"
        record_human_concurrence(case_id, principal="human::alice", note="ok")
        record_countersign(case_id, agrees=True, family="gemma-simulated", simulated=True)
        mint(agent=agent, capability="extract", risk_class="LOW", case_id=case_id, reason="ok")

    still_short = spend_or_refuse(
        agent=agent,
        capability="extract",
        risk_class="LOW",
        task="t",
        case_id=None,
        acting_principal=agent.principal,
    )
    assert still_short.allowed is False

    # A third validated outcome crosses the threshold (1500bp >= 1200bp).
    case_id = f"case_earnup_2_{uuid.uuid4().hex[:6]}"
    record_human_concurrence(case_id, principal="human::alice", note="ok")
    record_countersign(case_id, agrees=True, family="gemma-simulated", simulated=True)
    mint(agent=agent, capability="extract", risk_class="LOW", case_id=case_id, reason="ok")

    now_allowed = spend_or_refuse(
        agent=agent,
        capability="extract",
        risk_class="LOW",
        task="t",
        case_id=None,
        acting_principal=agent.principal,
    )
    assert now_allowed.allowed is True


@pytestmark_emulator
def test_burn_causes_immediate_revocation_visible_to_next_routing_decision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Eval scenario (c) + the revocation-latency guarantee: a BURN
    committed in one transaction is visible to the VERY NEXT spend_or_refuse
    call -- no cache, live fold."""
    from warrant.ledger import (
        burn,
        current_balance,
        mint,
        record_countersign,
        record_human_concurrence,
        reset_for_test,
        spend_or_refuse,
    )

    monkeypatch.setenv("UNWIND_COUNTERSIGN_SIMULATED", "1")
    agent = _fresh_agent(f"burn_{uuid.uuid4().hex[:6]}", warrant_spend_schedule={"HIGH": 40})
    reset_for_test(principal=agent.principal)
    case_id = f"case_{uuid.uuid4().hex[:8]}"
    record_human_concurrence(case_id, principal="human::alice", note="ok")
    record_countersign(case_id, agrees=True, family="gemma-simulated", simulated=True)
    mint(agent=agent, capability="extract", risk_class="HIGH", case_id=case_id, reason="ok")
    assert current_balance(agent.principal, "extract", "HIGH") == 50

    covered = spend_or_refuse(
        agent=agent,
        capability="extract",
        risk_class="HIGH",
        task="t1",
        case_id=None,
        acting_principal=agent.principal,
    )
    assert covered.allowed is True  # 50 >= 40

    # A judgement gets overturned: burn the remaining balance.
    burn(
        agent=agent,
        capability="extract",
        risk_class="HIGH",
        amount_bp=100,
        case_id=case_id,
        reason="judgement overturned",
        acting_principal=agent.principal,
    )

    refused = spend_or_refuse(
        agent=agent,
        capability="extract",
        risk_class="HIGH",
        task="t2",
        case_id=None,
        acting_principal=agent.principal,
    )
    assert refused.allowed is False  # revoked, visible on the VERY NEXT call


@pytestmark_emulator
def test_idle_decay_loses_coverage() -> None:
    """Eval scenario (d): idle decay -> coverage lost."""
    from datetime import timedelta

    from warrant.ledger import (
        EventKind,
        reset_for_test,
        spend_or_refuse,
        write_synthetic_seed_event,
    )

    agent = _fresh_agent(f"decay_{uuid.uuid4().hex[:6]}", warrant_spend_schedule={"LOW": 900})
    reset_for_test(principal=agent.principal)
    minted_at = datetime.now(UTC) - timedelta(days=200)
    write_synthetic_seed_event(
        principal=agent.principal,
        capability="extract",
        risk_class="LOW",
        kind=EventKind.MINT,
        amount_bp=1000,
        case_id=None,
        reason="seed for decay scenario",
        at=minted_at,
    )
    # Immediately after minting: covers a 900bp task.
    fresh = spend_or_refuse(
        agent=agent,
        capability="extract",
        risk_class="LOW",
        task="t",
        case_id=None,
        acting_principal=agent.principal,
        at=minted_at,
    )
    assert fresh.allowed is True

    # 200 idle days later: (199/200)^200 ~ 0.366 of 1000bp ~= 366bp < 900bp.
    stale = spend_or_refuse(
        agent=agent,
        capability="extract",
        risk_class="LOW",
        task="t",
        case_id=None,
        acting_principal=agent.principal,
        at=datetime.now(UTC),
    )
    assert stale.allowed is False


@pytestmark_emulator
def test_cross_class_mint_confers_nothing_launderer(monkeypatch: pytest.MonkeyPatch) -> None:
    """Adversary: launderer. MINT in one risk class must not raise the
    balance in another."""
    from warrant.ledger import (
        current_balance,
        mint,
        record_countersign,
        record_human_concurrence,
        reset_for_test,
    )

    monkeypatch.setenv("UNWIND_COUNTERSIGN_SIMULATED", "1")
    agent = _fresh_agent(f"launder_{uuid.uuid4().hex[:6]}")
    reset_for_test(principal=agent.principal)
    case_id = f"case_{uuid.uuid4().hex[:8]}"
    record_human_concurrence(case_id, principal="human::alice", note="ok")
    record_countersign(case_id, agrees=True, family="gemma-simulated", simulated=True)
    mint(agent=agent, capability="extract", risk_class="LOW", case_id=case_id, reason="ok")

    assert current_balance(agent.principal, "extract", "LOW") == 500
    assert current_balance(agent.principal, "extract", "HIGH") == 0


@pytestmark_emulator
def test_registry_edit_cannot_create_balance_poisoner() -> None:
    """Adversary: poisoner. Editing a registry entry's issuance/spend
    schedule changes what a FUTURE mint/spend costs, never what the fold of
    the existing log already produced."""
    from warrant.ledger import (
        EventKind,
        current_balance,
        reset_for_test,
        write_synthetic_seed_event,
    )

    agent = _fresh_agent(f"poison_{uuid.uuid4().hex[:6]}")
    reset_for_test(principal=agent.principal)
    write_synthetic_seed_event(
        principal=agent.principal,
        capability="extract",
        risk_class="LOW",
        kind=EventKind.MINT,
        amount_bp=777,
        case_id=None,
        reason="seed",
        at=datetime.now(UTC),
    )
    before = current_balance(agent.principal, "extract", "LOW")

    # "Edit the registry": change the mint/spend schedule on the in-memory
    # entry. This never touches the ledger at all.
    edited = agent.model_copy(
        update={
            "warrant_mint_schedule": {"LOW": 999_999},
            "warrant_spend_schedule": {"LOW": 1},
            "risk_class_thresholds": {"LOW": 1},
        }
    )
    after = current_balance(edited.principal, "extract", "LOW")
    assert before == after == 777


@pytestmark_emulator
def test_transfer_raises_identity_adversary() -> None:
    """Adversary: identity/transfer. Spending against agent A's balance,
    claiming to act as principal B, raises -- warrants are non-transferable."""
    from lib.principals import NonTransferableError
    from warrant.ledger import reset_for_test, spend_or_refuse

    agent = _fresh_agent(f"identity_{uuid.uuid4().hex[:6]}")
    reset_for_test(principal=agent.principal)

    with pytest.raises(NonTransferableError):
        spend_or_refuse(
            agent=agent,
            capability="extract",
            risk_class="LOW",
            task="t",
            case_id=None,
            acting_principal="agent::someone_else",
        )
