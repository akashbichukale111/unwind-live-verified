"""WARRANT (Card 0): the append-only ledger and its pure integer fold.

WHAT THIS IS
------------
A deterministic, decaying, capability-scoped quantity of authority. It is
minted only from countersigned, human-validated outcomes (never by an agent,
a model, or a prompt), debited on every delegated act, and it decays with
idleness. A case no live warrant covers routes to a human BY CONSTRUCTION --
`tower/gateway.py`'s `_warrant_node` calls `spend_or_refuse` below and refuses
before any work happens if the answer is no. See `warrant/DESIGN.md` for the
full invention writeup, the prior-art position, and why the atomic spend is
wired as an ADK 2 `FunctionNode` in `tower/gateway.py` rather than here.

THIS MODULE IMPORTS NO FRAMEWORK AND NO MODEL CLIENT
-------------------------------------------------------
Not `google.adk`, not `lib.vertex`, nothing. The Gateway wraps
`spend_or_refuse` in a `FunctionNode`; this module is the plain, directly
testable function underneath it, in the same relationship
`tower/gateway.py`'s `check_principal` etc. have to their own module's ADK
graph. `tests/test_warrant_zero_model.py` proves it by import-graph walk, the
same technique `tests/test_zero_model.py` and `tests/test_tower_zero_model.py`
already use.

BALANCE IS A PURE FOLD, INTEGER ONLY
-------------------------------------
`fold_balance` takes a list of events and a point in time and returns an
`int` of warrant basis points. It touches no clock, no network, no random
state -- feed it the same events and the same `as_of` twice and it returns
the same integer twice, which is the whole of what "rederive is bit-equal"
means. Floating point never appears: decay is computed as an exact rational
(integer numerator over integer denominator, reduced), floor-divided into
`amount_bp` at the end. `scripts/rederive_warrant.py` is the tool that
re-runs this fold against the live log and diffs it against what Card 2's
registry snapshot claims.

SEPARATION FROM settle/loadrating.py
--------------------------------------
Different collection (`COLLECTION_WARRANT_LEDGER`, never
`COLLECTION_AGENT_TRUST` or anything `settle/` touches), different dataclass,
different module, and this file does not import `settle` -- `settle/` is
frozen and does not import this file either. `tests/test_warrant_separation.py`
asserts both halves of that directly: no shared storage, no shared code path.
Source standing (`settle/loadrating.py`) answers "should this SOURCE's claims
carry weight"; warrant answers "may this AGENT be delegated to, right now, for
this capability, at this risk class". Conflating them would let an agent's
good behaviour launder into how much a supplier's claims are trusted, or vice
versa -- the same failure `settle/loadrating.py`'s own docstring refuses for
its own reason.
"""

from __future__ import annotations

import math
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum

from lib.config import COLLECTION_WARRANT_LEDGER
from lib.firestore import get_client
from lib.principals import assert_warrant_access
from tower.memory import get_case_chain, write_entry
from tower.schema import AgentRegistryEntry, MemoryEntryKind

# ===========================================================================
# Vocabulary
# ===========================================================================


class EventKind(str, Enum):
    MINT = "MINT"
    BURN = "BURN"
    SPEND = "SPEND"
    DECAY = "DECAY"
    CHALLENGE = "CHALLENGE"


class Provenance(str, Enum):
    """Deliberately a SEPARATE enum from `tower.schema.WarrantProvenance`,
    not an import of it: `tower/schema.py` is Card 2's typed model for the
    registry's DISPLAY snapshot, and this module must not depend on `tower`
    for its own vocabulary -- the ledger is the source of truth and the
    display schema mirrors it, never the other way round. The two enums'
    values are kept identical (`EARNED`/`SYNTHETIC`) on purpose so mapping
    one to the other at the one seam that needs it (materializing a
    snapshot) is a straight `.value` round-trip, not a translation table.
    """

    EARNED = "EARNED"
    SYNTHETIC = "SYNTHETIC"


class MintPreconditionError(RuntimeError):
    """MINT was attempted without both required records, or the registry has
    no fixed issuance amount for the requested risk class."""


class CaseChallengedError(RuntimeError):
    """MINT was attempted for a case a countersign disagreement has frozen."""


def balance_key(capability: str, risk_class: str) -> str:
    """The composite key `tower.schema.WarrantSlot.balances` is keyed by.

    Never a bare risk class: warrant/DESIGN.md's balance identity is the
    3-tuple (principal, capability, risk_class), and a bare risk-class key
    would silently collapse two different capabilities' warrant into one
    number -- exactly the "never a single global number" failure the rest of
    this repository (`risk_class_thresholds`, `WarrantSlot.balances` itself)
    already refuses to make.
    """
    return f"{capability}::{risk_class}"


def parse_balance_key(key: str) -> tuple[str, str]:
    capability, sep, risk_class = key.partition("::")
    if not sep:
        raise ValueError(f"{key!r} is not a capability::risk_class balance key")
    return capability, risk_class


#: Non-Gemini-family requirement for a valid countersign (File B / the
#: project's own blindness-boundary discipline: a Gemini-family model cannot
#: countersign a Gemini-family judgement and have that mean anything).
_GEMINI_FAMILY_PREFIXES = ("gemini",)

#: [ASSUMPTION] Flat warrant cost per delegated task when a registry entry
#: does not specify one for the risk class in play. Small on purpose: the
#: registry's `warrant_spend_schedule` is where a real issuance/spend
#: economy is meant to live; this is only a floor so a registry that forgot
#: to configure a risk class fails closed (spends something, eventually runs
#: out) rather than failing open (spends nothing, never runs out).
DEFAULT_SPEND_COST_BP = 100


def _simulated_mint_permitted() -> bool:
    """May a countersign recorded as `simulated=True` satisfy `mint`'s
    independent-verification precondition right now?

    Delegates to `lib.simulation.resolve_policy`, which applies the hard
    production clamp: under `UNWIND_ENV=production` this is False no matter
    what any other environment variable says. Previously this read
    `UNWIND_COUNTERSIGN_SIMULATED` directly -- and `command_os/mission.py`
    SET that variable on itself at request time, so the flag protecting the
    authority path was controlled by the code the authority path was meant
    to constrain. See `lib/simulation.py`'s module docstring.
    """
    from lib.simulation import resolve_policy  # noqa: PLC0415

    return resolve_policy().simulated_mint_permitted


def family_root(model_name: str) -> str:
    """Normalize any model string to its FAMILY: the leading alphabetic run,
    lowercased -- e.g. any `lib.config.MODEL_FAST`/`MODEL_DEEP`-shaped Gemini
    string reduces to `"gemini"`, any `GEMMA_MODEL`-shaped string reduces to
    `"gemma"`. `countersign/verify.py`'s collusion guard uses this to decide
    whether a countersign's model family is independent of the judging
    side's -- the SAME normalization this module already uses for the
    non-Gemini-family MINT precondition (`_is_gemini_family`, below), so
    there is exactly one definition of "family" in the codebase rather than
    two that could quietly drift apart.
    """
    lowered = model_name.strip().lower()
    match = re.match(r"[a-z]+", lowered)
    return match.group(0) if match else lowered


def _is_gemini_family(family: str) -> bool:
    return family_root(family) in _GEMINI_FAMILY_PREFIXES


# ===========================================================================
# The event, and the pure integer fold over a list of them
# ===========================================================================


@dataclass(frozen=True)
class WarrantEvent:
    event_id: str
    principal: str
    capability: str
    risk_class: str
    kind: EventKind
    #: Basis points. Always >= 0; the SIGN of the effect is a property of
    #: `kind` (MINT credits, BURN/SPEND debit, DECAY/CHALLENGE do not touch
    #: the number directly), never of this field, so a caller cannot
    #: "credit via a negative burn".
    amount_bp: int
    provenance: Provenance
    case_id: str | None
    reason: str
    at: datetime
    #: Monotonic, allocated per-principal at append time (see `_next_seq`),
    #: the same reason `tower/memory.py`'s `MemoryEntry.seq` exists: two
    #: events with the identical wall-clock timestamp are common (rapid
    #: succession, clock resolution, or a deliberately-backdated seed) and a
    #: fold that broke such ties by a random UUID would not be deterministic
    #: -- `fold_balance` sorts by `(at, seq)`, never `(at, event_id)`.
    seq: int = 0

    def __post_init__(self) -> None:
        if isinstance(self.amount_bp, bool) or not isinstance(self.amount_bp, int):
            raise TypeError(
                f"WarrantEvent.amount_bp must be int basis points, got {type(self.amount_bp).__name__}: "
                "floating point in a warrant ledger is a defect, not a rounding choice."
            )
        if self.amount_bp < 0:
            raise ValueError("WarrantEvent.amount_bp must be >= 0; sign comes from `kind`.")


#: Exact rational per-day retention, 199/200 = 0.995 -- exponential decay is
#: the only memoryless form (see warrant/DESIGN.md for why that property is
#: required for a LAZY fold to be time-of-evaluation-independent). Kept as a
#: separate numerator/denominator pair rather than a float so every balance
#: this module ever produces is an exact integer, never an approximation.
#: [ASSUMPTION] 0.5%/day: three idle weeks (21 days) costs roughly 10% of a
#: balance -- enough that idleness has a visible, demo-able cost within the
#: scenario's timescale, gentle enough that one quiet weekend does not zero
#: an agent's standing.
_RETAIN_NUM = 199
_RETAIN_DEN = 200

#: The "precomputed per-whole-day integer table": index i holds the exact
#: reduced (numerator, denominator) for `(199/200) ** i`, extended lazily and
#: kept forever once computed -- every call after the first for a given day
#: count is a list index, not a fresh `pow`.
_decay_num: list[int] = [1]
_decay_den: list[int] = [1]


def _extend_decay_table(days: int) -> None:
    while len(_decay_num) <= days:
        n = _decay_num[-1] * _RETAIN_NUM
        d = _decay_den[-1] * _RETAIN_DEN
        g = math.gcd(n, d)
        _decay_num.append(n // g)
        _decay_den.append(d // g)


def apply_decay(balance_bp: int, days: int) -> int:
    """Balance after `days` whole days of idleness. Pure, integer, exact.

    `days` is always the WHOLE-day gap between two points in time -- callers
    truncate to `.date()` before subtracting, so decay is deterministic
    regardless of the time-of-day two events happen to fall on.
    """
    if days < 0:
        raise ValueError("days must be >= 0")
    if days == 0 or balance_bp == 0:
        return balance_bp
    _extend_decay_table(days)
    num, den = _decay_num[days], _decay_den[days]
    return (balance_bp * num) // den


def fold_balance(
    events: list[WarrantEvent],
    *,
    principal: str,
    capability: str,
    risk_class: str,
    as_of: datetime,
) -> int:
    """The pure fold. Filters to the (principal, capability, risk_class) key,
    sorts by time, and replays MINT/BURN/SPEND with exponential decay applied
    across every gap -- including the final gap up to `as_of`.

    CHALLENGE events carry no arithmetic here (see `is_case_challenged`); a
    stray DECAY checkpoint event is also arithmetic-neutral (decay for its
    own gap was already applied by the fold reaching it) -- both exist in
    the log as a narrated fact, not as a second source of delta.

    This function does not read `.provenance` at all. That is the proof, not
    a claim, that SYNTHETIC and EARNED events fold identically -- see
    `tests/test_warrant_ledger.py::test_seeded_and_earned_events_fold_identically`.
    """
    relevant = sorted(
        (
            e
            for e in events
            if e.principal == principal
            and e.capability == capability
            and e.risk_class == risk_class
            and e.kind in (EventKind.MINT, EventKind.BURN, EventKind.SPEND, EventKind.DECAY)
            and e.at <= as_of
        ),
        key=lambda e: (e.at, e.seq),
    )
    balance = 0
    last_ts: datetime | None = None
    for event in relevant:
        if last_ts is not None:
            days = (event.at.date() - last_ts.date()).days
            balance = apply_decay(balance, days)
        if event.kind is EventKind.MINT:
            balance += event.amount_bp
        elif event.kind in (EventKind.BURN, EventKind.SPEND):
            balance = max(0, balance - event.amount_bp)
        # DECAY: no direct delta -- the gap decay above already accounted for it.
        last_ts = event.at
    if last_ts is not None:
        days = (as_of.date() - last_ts.date()).days
        balance = apply_decay(balance, days)
    return balance


def is_case_challenged(events: list[WarrantEvent], case_id: str) -> bool:
    """True if any CHALLENGE event exists for this case -- minting for it is
    frozen permanently once challenged. No unfreeze path exists; see
    `warrant/FAILURE_MODES.md` for why that is a deliberately simple, if
    conservative, choice rather than a solved dispute-resolution workflow.
    """
    return any(e.kind is EventKind.CHALLENGE and e.case_id == case_id for e in events)


def provenance_for_fold(events: list[WarrantEvent]) -> Provenance:
    """SYNTHETIC if ANY event folded into a balance carries SYNTHETIC
    provenance -- contamination is not diluted away by real events sitting
    alongside it. An empty fold (no events at all) is also SYNTHETIC: the
    honest label for "nothing has actually been earned yet" is the same
    label as "this is demo data", because in both cases the number on screen
    is not evidence of a validated outcome.
    """
    if not events or any(e.provenance is Provenance.SYNTHETIC for e in events):
        return Provenance.SYNTHETIC
    return Provenance.EARNED


# ===========================================================================
# Persistence -- one collection, append-only, the same discipline
# `tower/memory.py` uses for decision_memory.
# ===========================================================================


def _new_event_id() -> str:
    return f"warr_{uuid.uuid4().hex}"


def _to_doc(event: WarrantEvent) -> dict:
    return {
        "event_id": event.event_id,
        "principal": event.principal,
        "capability": event.capability,
        "risk_class": event.risk_class,
        "kind": event.kind.value,
        "amount_bp": event.amount_bp,
        "provenance": event.provenance.value,
        "case_id": event.case_id,
        "reason": event.reason,
        "at": event.at,
        "seq": event.seq,
    }


def _from_doc(doc: dict) -> WarrantEvent:
    return WarrantEvent(
        event_id=doc["event_id"],
        principal=doc["principal"],
        capability=doc["capability"],
        risk_class=doc["risk_class"],
        kind=EventKind(doc["kind"]),
        amount_bp=int(doc["amount_bp"]),
        provenance=Provenance(doc["provenance"]),
        case_id=doc.get("case_id"),
        reason=doc.get("reason", ""),
        at=doc["at"],
        seq=int(doc.get("seq", 0)),
    )


def _collection():
    return get_client().collection(COLLECTION_WARRANT_LEDGER)


#: Sequence counters live in their own collection, one document per
#: principal -- the same reason `tower/memory.py:_COUNTERS` keeps its
#: counter out of `decision_memory`: a counter is bookkeeping, not an event,
#: and keeping it out of `COLLECTION_WARRANT_LEDGER` means a raw scan of that
#: collection can never accidentally yield one.
_SEQ_COUNTERS = "warrant_ledger_counters"


def _next_seq(principal: str, *, transaction=None) -> int:
    from google.cloud import firestore as fs  # noqa: PLC0415

    ref = get_client().collection(_SEQ_COUNTERS).document(principal)

    if transaction is not None:
        snap = ref.get(transaction=transaction)
        current = (snap.get("next_seq") if snap.exists else 0) or 0
        transaction.set(ref, {"next_seq": current + 1})
        return current

    @fs.transactional
    def _increment(txn: fs.Transaction) -> int:
        snap = ref.get(transaction=txn)
        current = (snap.get("next_seq") if snap.exists else 0) or 0
        txn.set(ref, {"next_seq": current + 1})
        return current

    return _increment(get_client().transaction())


def _append(event: WarrantEvent) -> WarrantEvent:
    """Plain durable write, with a freshly-allocated `seq` stamped in. `.set()`
    on a fresh document id only -- there is no `update_event` or
    `delete_event` in this module's public surface, the same append-only
    discipline `tower/memory.py` enforces for decision memory (File B: a
    record that can be edited after the fact is not evidence of anything).
    """
    from dataclasses import replace

    stamped = replace(event, seq=_next_seq(event.principal))
    _collection().document(stamped.event_id).set(_to_doc(stamped))
    return stamped


def read_events(
    *,
    principal: str | None = None,
    capability: str | None = None,
    risk_class: str | None = None,
    case_id: str | None = None,
    transaction=None,
) -> list[WarrantEvent]:
    """Every event matching the given filters, oldest first. This is the
    LIVE log -- no cache sits in front of it, which is what makes
    `spend_or_refuse` (below) see a `BURN` committed a moment ago.
    """
    query = _collection()
    if principal is not None:
        query = query.where("principal", "==", principal)
    if capability is not None:
        query = query.where("capability", "==", capability)
    if risk_class is not None:
        query = query.where("risk_class", "==", risk_class)
    if case_id is not None:
        query = query.where("case_id", "==", case_id)
    stream = query.stream(transaction=transaction) if transaction is not None else query.stream()
    events = [_from_doc(snap.to_dict()) for snap in stream]
    return sorted(events, key=lambda e: (e.at, e.seq))


def current_balance(
    principal: str, capability: str, risk_class: str, *, as_of: datetime | None = None
) -> int:
    """Convenience: read + fold in one call. Always live, never cached."""
    when = as_of or datetime.now(UTC)
    events = read_events(principal=principal, capability=capability, risk_class=risk_class)
    return fold_balance(
        events, principal=principal, capability=capability, risk_class=risk_class, as_of=when
    )


def reset_for_test(principal: str | None = None) -> None:
    """Test hook: delete every ledger event (optionally scoped to one
    principal, so parallel test modules do not stomp on each other)."""
    query = _collection()
    if principal is not None:
        query = query.where("principal", "==", principal)
    for snap in query.stream():
        snap.reference.delete()


# ===========================================================================
# Human concurrence + countersign records in the Memory Bank -- the two
# preconditions MINT requires. These write to `tower.memory` (the Memory
# Bank), not to this ledger's own collection: the concurrence and the
# countersign are decisions made ABOUT a case, which is exactly what
# decision_memory already exists to hold.
# ===========================================================================


def record_human_concurrence(
    case_id: str, *, principal: str, note: str, parent_id: str | None = None
) -> None:
    write_entry(
        case_id,
        MemoryEntryKind.HUMAN_DECISION,
        {"concurs": True, "principal": principal, "note": note},
        parent_id=parent_id,
    )


def record_countersign(
    case_id: str,
    *,
    agrees: bool,
    family: str,
    simulated: bool,
    note: str = "",
    parent_id: str | None = None,
) -> None:
    """Record a countersign result. `simulated=True` MUST be set (and stays
    visible in the stored payload forever) whenever `UNWIND_COUNTERSIGN_SIMULATED`
    is what produced this result rather than a real independent-family model
    -- Card 0's non-goal is real Gemma; this label is what keeps a simulated
    input from ever being presented as a real one, in code and on screen.
    """
    write_entry(
        case_id,
        MemoryEntryKind.COUNTERSIGN,
        {"agrees": agrees, "family": family, "simulated": simulated, "note": note},
        parent_id=parent_id,
    )


def _has_valid_mint_preconditions(case_id: str) -> tuple[bool, str]:
    chain = get_case_chain(case_id)
    human_ok = any(
        entry.kind is MemoryEntryKind.HUMAN_DECISION and entry.payload.get("concurs")
        for entry in chain
    )
    if not human_ok:
        return False, f"no human-concurrence record found in decision memory for case {case_id!r}"

    for entry in chain:
        if entry.kind is not MemoryEntryKind.COUNTERSIGN:
            continue
        if not entry.payload.get("agrees"):
            continue
        family = str(entry.payload.get("family", ""))
        if _is_gemini_family(family):
            continue  # must be a non-Gemini family
        if entry.payload.get("simulated") and not _simulated_mint_permitted():
            continue  # a simulated countersign never counts in production
        return True, "ok"
    return (
        False,
        f"no valid non-Gemini-family countersign record found for case {case_id!r} "
        "(missing, disagreeing, Gemini-family, or an unflagged simulation)",
    )


# ===========================================================================
# The four mutating operations
# ===========================================================================


def mint(
    *,
    agent: AgentRegistryEntry,
    capability: str,
    risk_class: str,
    case_id: str,
    reason: str,
    at: datetime | None = None,
) -> WarrantEvent:
    """Credit warrant for one validated outcome. Fixed amount, registry-set,
    never chosen by the caller -- see `AgentRegistryEntry.warrant_mint_schedule`.

    Raises `CaseChallengedError` if a countersign disagreement already froze
    this case, and `MintPreconditionError` if either required record is
    missing -- both BEFORE anything is appended, so a forged mint attempt
    leaves no trace of having credited anything.
    """
    when = at or datetime.now(UTC)
    existing = read_events(case_id=case_id)
    if is_case_challenged(existing, case_id):
        raise CaseChallengedError(
            f"case {case_id!r} was CHALLENGEd by a countersign disagreement; minting for it is frozen."
        )
    ok, why = _has_valid_mint_preconditions(case_id)
    if not ok:
        raise MintPreconditionError(f"cannot MINT for case {case_id!r}: {why}")
    amount_bp = agent.warrant_mint_schedule.get(risk_class)
    if not amount_bp:
        raise MintPreconditionError(
            f"agent {agent.agent_id!r} has no warrant_mint_schedule entry for risk class "
            f"{risk_class!r}; issuance amounts are fixed in the registry, not inferred."
        )
    event = WarrantEvent(
        event_id=_new_event_id(),
        principal=agent.principal,
        capability=capability,
        risk_class=risk_class,
        kind=EventKind.MINT,
        amount_bp=amount_bp,
        provenance=Provenance.EARNED,
        case_id=case_id,
        reason=reason,
        at=when,
    )
    return _append(event)


def burn(
    *,
    agent: AgentRegistryEntry,
    capability: str,
    risk_class: str,
    amount_bp: int,
    case_id: str,
    reason: str,
    acting_principal: str,
    at: datetime | None = None,
) -> WarrantEvent:
    """Debit warrant because a judgement was overturned. `acting_principal`
    must be the agent's own principal -- warrants are non-transferable, so
    even a debit against the right ledger row is refused if it is requested
    on behalf of the wrong principal (`lib.principals.assert_warrant_access`).
    """
    assert_warrant_access(balance_principal=agent.principal, acting_principal=acting_principal)
    when = at or datetime.now(UTC)
    event = WarrantEvent(
        event_id=_new_event_id(),
        principal=agent.principal,
        capability=capability,
        risk_class=risk_class,
        kind=EventKind.BURN,
        amount_bp=amount_bp,
        provenance=Provenance.EARNED,
        case_id=case_id,
        reason=reason,
        at=when,
    )
    return _append(event)


def challenge(
    *,
    case_id: str,
    principal: str,
    capability: str,
    risk_class: str,
    reason: str,
    at: datetime | None = None,
) -> WarrantEvent:
    """A countersign disagreement freezes minting for this case. No balance
    arithmetic -- `fold_balance` never branches on CHALLENGE."""
    when = at or datetime.now(UTC)
    event = WarrantEvent(
        event_id=_new_event_id(),
        principal=principal,
        capability=capability,
        risk_class=risk_class,
        kind=EventKind.CHALLENGE,
        amount_bp=0,
        provenance=Provenance.EARNED,
        case_id=case_id,
        reason=reason,
        at=when,
    )
    return _append(event)


@dataclass(frozen=True)
class SpendResult:
    allowed: bool
    balance_before: int
    cost_bp: int
    event: WarrantEvent | None
    reason: str


def spend_or_refuse(
    *,
    agent: AgentRegistryEntry,
    capability: str,
    risk_class: str,
    task: str,
    case_id: str | None,
    acting_principal: str,
    at: datetime | None = None,
) -> SpendResult:
    """THE atomic SPEND-or-refuse operation. Wrapped as an ADK 2 `FunctionNode`
    in `tower/gateway.py:_warrant_node` -- this function is the plain,
    directly testable body underneath that node.

    Runs inside a single Firestore transaction: reads every event for this
    (principal, capability, risk_class) key, folds the live balance, and --
    if and only if it covers `cost_bp` -- appends the SPEND event in the SAME
    transaction before returning. A `BURN` committed a moment earlier is a
    committed document by the time this transaction starts, so it is always
    part of what gets read here: there is no cache to go stale, which is the
    property `tests/test_warrant_ledger.py`'s revocation-latency test proves.
    """
    assert_warrant_access(balance_principal=agent.principal, acting_principal=acting_principal)
    when = at or datetime.now(UTC)
    cost_bp = agent.warrant_spend_schedule.get(risk_class, DEFAULT_SPEND_COST_BP)

    from google.cloud import firestore as fs  # noqa: PLC0415

    client = get_client()

    @fs.transactional
    def _txn(transaction: fs.Transaction) -> SpendResult:
        events = read_events(
            principal=agent.principal,
            capability=capability,
            risk_class=risk_class,
            transaction=transaction,
        )
        balance = fold_balance(
            events,
            principal=agent.principal,
            capability=capability,
            risk_class=risk_class,
            as_of=when,
        )
        if balance < cost_bp:
            return SpendResult(
                allowed=False,
                balance_before=balance,
                cost_bp=cost_bp,
                event=None,
                reason=(
                    f"warrant balance {balance}bp for {agent.agent_id!r}/{capability!r}/"
                    f"{risk_class!r} is below the {cost_bp}bp this delegation costs."
                ),
            )
        seq = _next_seq(agent.principal, transaction=transaction)
        event = WarrantEvent(
            event_id=_new_event_id(),
            principal=agent.principal,
            capability=capability,
            risk_class=risk_class,
            kind=EventKind.SPEND,
            amount_bp=cost_bp,
            provenance=Provenance.EARNED,
            case_id=case_id,
            reason=task,
            at=when,
            seq=seq,
        )
        transaction.set(_collection().document(event.event_id), _to_doc(event))
        return SpendResult(
            allowed=True, balance_before=balance, cost_bp=cost_bp, event=event, reason="spent"
        )

    return _txn(client.transaction())


def checkpoint_decay(
    *, principal: str, capability: str, risk_class: str, at: datetime | None = None
) -> WarrantEvent:
    """Append an explicit, informational DECAY event narrating that idleness
    reduced this balance -- purely for audit legibility. Arithmetic-neutral:
    the decay itself is already applied by `fold_balance` walking the gap up
    to this event's own timestamp, exactly as it would for any other gap.
    """
    when = at or datetime.now(UTC)
    events = read_events(principal=principal, capability=capability, risk_class=risk_class)
    realized = fold_balance(
        events, principal=principal, capability=capability, risk_class=risk_class, as_of=when
    )
    event = WarrantEvent(
        event_id=_new_event_id(),
        principal=principal,
        capability=capability,
        risk_class=risk_class,
        kind=EventKind.DECAY,
        amount_bp=0,
        provenance=Provenance.EARNED,
        case_id=None,
        reason=f"checkpoint: balance is {realized}bp as of {when.isoformat()} after idle decay",
        at=when,
    )
    return _append(event)


# ===========================================================================
# Seeding -- honestly. Every event this writes is SYNTHETIC, always, and
# this is the ONLY function in the module that skips MINT preconditions --
# because seeding a seven-week fabricated history through a real human+
# countersign flow would itself be a fabrication wearing a disguise.
# ===========================================================================


def write_synthetic_seed_event(
    *,
    principal: str,
    capability: str,
    risk_class: str,
    kind: EventKind,
    amount_bp: int,
    case_id: str | None,
    reason: str,
    at: datetime,
) -> WarrantEvent:
    """Write one fabricated demo-corpus event, unconditionally labelled
    SYNTHETIC. `fold_balance` does not know or care that this event took a
    shortcut around `mint`'s preconditions -- that is the point of
    `tests/test_warrant_ledger.py::test_seeded_and_earned_events_fold_identically`:
    the label is provenance, not different math, and this function is the
    one honest place that label is allowed to be attached without the checks
    `mint`/`burn`/`spend_or_refuse` otherwise enforce.
    """
    event = WarrantEvent(
        event_id=_new_event_id(),
        principal=principal,
        capability=capability,
        risk_class=risk_class,
        kind=kind,
        amount_bp=amount_bp,
        provenance=Provenance.SYNTHETIC,
        case_id=case_id,
        reason=f"[SYNTHETIC SEED] {reason}",
        at=at,
    )
    return _append(event)


__all__ = [
    "DEFAULT_SPEND_COST_BP",
    "CaseChallengedError",
    "EventKind",
    "MintPreconditionError",
    "Provenance",
    "SpendResult",
    "WarrantEvent",
    "apply_decay",
    "balance_key",
    "burn",
    "challenge",
    "checkpoint_decay",
    "current_balance",
    "family_root",
    "fold_balance",
    "is_case_challenged",
    "mint",
    "parse_balance_key",
    "provenance_for_fold",
    "read_events",
    "record_countersign",
    "record_human_concurrence",
    "reset_for_test",
    "spend_or_refuse",
    "write_synthetic_seed_event",
]
