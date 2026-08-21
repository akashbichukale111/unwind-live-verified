# warrant/ — DESIGN.md (Card 0: WARRANT)

## Invariant

Delegation is not chosen by a prompt. `tower/gateway.py`'s Gateway refuses
any delegation the agent's LIVE warrant does not cover, before any work
happens. A case no warrant covers routes to a human BY CONSTRUCTION -- there
is no code path from "warrant insufficient" to "do the work anyway", because
`warrant_check` runs before `dispatch` in the fixed router order and every
edge out of a refusal goes to `refuse`, never around it.

The project's thesis -- **AI is not allowed to control the load-bearing
truth layer** -- extends here: **AI is not allowed to grant its own
authority either.** MINT amounts are fixed in the registry
(`AgentRegistryEntry.warrant_mint_schedule`), never chosen by an agent, a
model, or a prompt, and MINT itself only fires from a human-concurrence
record plus an independent-family countersign -- never from a model's own
say-so.

## Prior-art position

> WARRANT is object-capability security where the capabilities are earned
> rather than granted: a classical capability is granted and delegable; a
> warrant is minted only from countersigned, human-validated outcomes, is
> non-transferable across principals, decays with idleness, and is scoped
> per risk class. Nobody hands it over; nobody can hand it on.

## Threat model

Card 0 sits between "an agent behaved well in the past" and "an agent is
allowed to act again right now". The threats that matter are the ones that
let an agent manufacture its own authority (forging a mint, laundering
across risk classes, farming easy cases), the ones that let authority
survive past the moment it should have been revoked (a cache, a slow
propagation path), and the one that would let a bad-actor agent's behaviour
contaminate the SEPARATE ledger that tracks whether a data SOURCE can be
trusted (`settle/loadrating.py`).

## Data model

- `warrant_ledger/{event_id}` (`warrant/ledger.py:WarrantEvent`) --
  append-only. Five kinds: `MINT`, `BURN`, `SPEND`, `DECAY`, `CHALLENGE`.
  Every event carries `provenance` (`EARNED` | `SYNTHETIC`) and a monotonic
  per-principal `seq` (see "Ordering" below). No `update_event` or
  `delete_event` exists in the module's public surface -- the same
  discipline `tower/memory.py` already enforces for decision memory.
- `warrant_ledger_counters/{principal}` -- one integer per principal,
  allocated transactionally. Bookkeeping, not an event; kept out of the
  event collection so a raw scan of it can never accidentally yield one.
- `agents/{agent_id}.warrant` (`tower/schema.py:WarrantSlot`) -- a DISPLAY
  SNAPSHOT, never the source of truth. Keyed by the composite string
  `f"{capability}::{risk_class}"` (`warrant.ledger.balance_key`), because
  balance identity is the 3-tuple (principal, capability, risk_class) and a
  bare risk-class key would silently collapse two capabilities' warrant
  into one number.
- `decision_memory/{entry_id}` with `kind=HUMAN_DECISION` /
  `kind=COUNTERSIGN` (`tower/memory.py`, `tower/schema.py`) -- the two
  records `mint` requires. These live in the Memory Bank, not in
  `warrant_ledger`, because a concurrence and a countersign are decisions
  ABOUT a case, which is exactly what decision memory already exists to
  hold.

## Balance is a pure integer fold

`warrant.ledger.fold_balance(events, principal, capability, risk_class,
as_of)` is a plain function: filter to the key, sort by `(at, seq)`, replay
MINT (credit) / BURN / SPEND (debit, floored at zero) with exponential
decay applied across every gap including the final gap to `as_of`. It never
reads `.provenance` -- see "Honest seeding" below for why that is the whole
point, not an oversight. `scripts/rederive_warrant.py` re-reads the log
fresh and re-folds it independently of whatever the registry's display
snapshot claims, and fails loudly on any mismatch.

**Bit-exactness.** Every quantity is an integer number of basis points.
Decay is computed as an exact rational (`199/200` per day, reduced with
`math.gcd`, floor-divided into the balance at the end) -- never a `float`.
`WarrantEvent.__post_init__` raises `TypeError` on a non-`int` `amount_bp`,
so "floating point in a ledger is a defect" is enforced, not merely stated.

**Ordering.** Two events with the identical wall-clock timestamp are common
(rapid succession, or a deliberately-backdated synthetic seed), and
breaking that tie by a random UUID is not deterministic. Every event
carries a `seq`, allocated transactionally per principal at append time
(the same counter-per-partition idiom `tower/memory.py:_next_seq` already
uses for `MemoryEntry.seq`), and the fold sorts by `(at, seq)`.

## Why exponential decay, specifically

The requirement is a LAZY fold: `current_balance` is never a running total
updated on every tick, it is recomputed from the log at whatever `as_of` a
caller asks for. Exponential decay is the only memoryless form -- the
fraction of a balance that survives `N` more idle days does not depend on
how much has already decayed, only on `N` itself. That means
`fold_balance(events, as_of=T)` returns the same integer NO MATTER WHEN IT
IS CALLED, as long as `T` is the same: computing it the instant after the
last event and computing it a year later, asked about that same `T`, agree
exactly. Linear decay does not have this property -- a linear "lose X per
day" schedule needs to know how much time has ALREADY been subtracted to
avoid going negative or double-subtracting, which makes the fold's result
depend on how often it happens to be evaluated rather than purely on the
event log and `as_of`. `tests/test_warrant_ledger.py::test_decay_is_deterministic_and_time_of_evaluation_independent`
is the executable version of this claim.

[ASSUMPTION] The specific rate, 0.5%/day (`199/200`), is chosen so three
idle weeks costs roughly 10% of a balance -- visible within a demo's
timescale, gentle enough that one quiet weekend does not zero an agent's
standing. `tests/test_warrant_ledger.py::test_idle_decay_loses_coverage`
demonstrates it crossing a coverage threshold at a documented day count.

## Why the atomic SPEND-or-refuse is an ADK 2 `FunctionNode`, not plain code

`tower/gateway.py`'s `warrant_check` is a `google.adk.workflow.FunctionNode`
wrapping `_warrant_node`, which calls `warrant.ledger.spend_or_refuse`. A
`FunctionNode` is the framework's own guaranteed-no-model node type -- the
same reason `tower/gateway.py`'s other three checks (`principal_check`,
`scope_check`, `budget_check`) are already `FunctionNode`s. Wiring the
warrant check as a fourth one, replacing the always-pass stub, means "zero
model calls in the authority path" is a property the ADK graph itself
enforces (inspectable by walking `gateway_workflow.edges` and asserting
every node is a `FunctionNode`, exactly as
`tests/test_tower_gateway.py::test_gateway_workflow_is_a_real_adk_workflow`
already does), not a convention this file has to be trusted to uphold.

The plain function underneath (`spend_or_refuse`, in `warrant/ledger.py`)
is directly testable without standing up the ADK runner -- the same
`check_*` / `FunctionNode` relationship `tower/gateway.py`'s module
docstring already describes for the other three checks.
`warrant/ledger.py` itself imports NO `google.adk` at all (see
`tests/test_warrant_zero_model.py`): the FunctionNode wrapping is
`tower/gateway.py`'s job, one layer up, exactly where the other three
checks' wrapping already lives.

## Atomicity and revocation latency

`spend_or_refuse` runs inside a single Firestore transaction: read every
event for the (principal, capability, risk_class) key, fold the live
balance, and -- only if it covers the registry-fixed cost -- append the
SPEND event in the SAME transaction. There is no cache in front of this: a
`BURN` committed a moment earlier is a committed document by the time the
next `spend_or_refuse` transaction starts its read, so it is unconditionally
part of what gets folded. `tests/test_warrant_ledger.py
::test_burn_causes_immediate_revocation_visible_to_next_routing_decision`
proves the very next call sees it. `tower/schema.py:WarrantSlot.balances`
(the registry's display snapshot) is never read by the Gateway for this
decision -- reading it would be exactly the cache this guarantee forbids.

## Honest seeding

The demo corpus is synthetic and single-author, so any pre-existing balance
was chosen by the person building this project, not earned. Three
enforced consequences:

1. **Labelled, always.** Every event `write_synthetic_seed_event` writes
   carries `provenance=SYNTHETIC`, permanently. `provenance_for_fold`
   labels a BALANCE (not just an event) `SYNTHETIC` if even one event
   folded into it is `SYNTHETIC` -- contamination is not diluted away by
   real events sitting alongside it. An empty fold (nothing minted yet) is
   also labelled `SYNTHETIC`, because "nothing has actually been earned"
   and "this is demo data" deserve the same honest label: neither is
   evidence of a validated outcome.
2. **One balance earned on camera.** `scripts/demo_warrant.py`'s Act 2
   starts a cold-start agent at exactly zero (no seeding at all), grants
   human concurrence and records a countersign LIVE on that run, mints, and
   shows the Gateway allow a delegation it refused a moment earlier -- so
   at least one balance in the demo is genuinely earned in front of the
   judge, not seeded in advance.
3. **The ledger cannot tell the difference, and neither can we.**
   `fold_balance` never reads `.provenance` -- it is not in the arithmetic
   at all. `tests/test_warrant_ledger.py
   ::test_seeded_and_earned_events_fold_identically` and
   `scripts/rederive_warrant.py`'s output on the demo corpus (SYNTHETIC and
   EARNED balances both re-derive bit-equal to their stored snapshot) are
   the proof: SYNTHETIC is a provenance LABEL, never different math.

## Simulated countersign

Real Gemma independent-family verification is a later prompt (Card 3).
Until then, `mint`'s countersign precondition accepts a countersign record
with `payload["simulated"] = True` ONLY when the process has
`UNWIND_COUNTERSIGN_SIMULATED=1` set (`warrant/ledger.py:_simulation_enabled`),
and every such record is permanently labelled `simulated=True` in the
Memory Bank and printed with the literal string `SIMULATED` by
`scripts/demo_warrant.py` wherever it appears on screen. A same-family
(Gemini) countersign never counts, real or simulated -- see
`_is_gemini_family` -- because a Gemini-family model agreeing with a
Gemini-family judgement proves nothing about independent verification.

## Separation from `settle/loadrating.py`

Different collection (`warrant_ledger`, never `agent_trust` or anything
`settle/` touches), different dataclass, different module. Neither file
imports the other -- `tests/test_warrant_separation.py` asserts this both
directions (the same `spine`<->`tower` boundary check
`tests/test_tower_zero_model.py` already runs, applied to `warrant`<->
`settle`), and additionally proves `settle.loadrating.assert_not_agent_trust`
-- the one place `settle/` already refuses agent-shaped data -- does not
mistake a `WarrantEvent` for something it should accept, while still
correctly refusing the classic agent-trust shape it was written to catch.
Source standing answers "should this SOURCE's claims carry weight"; warrant
answers "may this AGENT be delegated to, right now". Conflating them would
let an agent's good behaviour launder into how much a supplier is trusted,
or the reverse -- the same failure `settle/loadrating.py`'s own docstring
already refuses, from the other side of the boundary.

## Non-goals honoured

No changes to how Card 1 judges anything. No real Gemma calls -- every
countersign in this prompt's evidence is labelled SIMULATED. No full UI --
`scripts/demo_warrant.py` prints the minimal surface the demo moment needs
(SYNTHETIC labels, per-capability-per-risk-class balances, never a single
global reputation number). No ledger snapshotting: `tower/schema.py
:WarrantSlot` is a DISPLAY convenience updated by an operator script
(`scripts/rederive_warrant.py`'s materialize pass), not a second source of
truth the Gateway ever reads from -- replay at this scale is milliseconds,
so a snapshot buys nothing the live fold does not already give for free.

## Adversarial tests

| Test | Status | Where |
| --- | --- | --- |
| forger (mint without both records) | **Tested.** | `tests/test_warrant_ledger.py::test_mint_without_records_raises_forger`, `::test_mint_with_only_human_concurrence_still_raises` |
| forger, variant: same-family countersign | **Tested.** | `::test_mint_with_gemini_family_countersign_raises` |
| forger, variant: unflagged simulation | **Tested.** | `::test_mint_with_unflagged_simulation_env_off_raises` |
| poisoner (registry edit creates balance) | **Tested.** | `::test_registry_edit_cannot_create_balance_poisoner` |
| launderer (cross-risk-class mint) | **Tested.** | `::test_cross_class_mint_confers_nothing_launderer`, plus the pure `::test_fold_ignores_events_for_a_different_key` |
| identity / transfer (spend as another principal) | **Tested.** | `::test_transfer_raises_identity_adversary` |
| revoked authority mid-flight / cache staleness | **Tested.** | `::test_burn_causes_immediate_revocation_visible_to_next_routing_decision` |
| synthetic-data contamination | **Tested.** | `::test_seeded_and_earned_events_fold_identically`, `scripts/rederive_warrant.py`'s output |
| Goodhart farming | **Not solved -- documented.** | `warrant/FAILURE_MODES.md` |
| Sybil (multiple principals for one real actor) | **Out of scope -- documented residual risk.** | `warrant/FAILURE_MODES.md` |
| race around SPEND/BURN | **Tested via atomic transaction, not a race harness.** | `warrant/ledger.py:spend_or_refuse` reads-then-writes inside one Firestore transaction; no concurrent-writer stress test exists (single-tenant demo scale) |
| CHALLENGE freeze survives a later "fixed" countersign | **Tested.** | `::test_challenge_freezes_minting_for_that_case_only` -- no unfreeze path exists, deliberately (see FAILURE_MODES.md) |

## Novelty test

**`warrant/ledger.py` is NOT a reputation score because Y =
`tests/test_warrant_ledger.py::test_provenance_for_fold_is_synthetic_if_any_event_is`
and `tower/schema.py:WarrantSlot.balances`'s type.** A reputation score is
one number; this is a `dict[str, int]` keyed per (capability, risk class),
and no code path in this repository ever collapses it to one number
(`grep -rn "warrant.*reputation\|single.*warrant.*number"` finds nothing,
because there is nothing to find).

**The Gateway's warrant check is NOT an authorization flag because Y =
`warrant/ledger.py:spend_or_refuse`'s transaction.** A flag is read; this
DEBITS -- every ALLOWED decision durably spends the cost it just checked
for, in the same transaction, so a decision that says "yes" has already
paid for itself before returning. `tests/test_warrant_ledger.py
::test_earn_up_across_n_cases_crosses_threshold` shows the same call
refusing, then allowing, as the underlying event log changes -- proving the
check consults live state rather than a fixed permission.
