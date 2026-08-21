# warrant/ — FAILURE_MODES.md (Card 0: WARRANT)

Honest statement of what WARRANT does not solve. A mechanism that only
lists what it prevents, without saying what it does not, is marketing, not
a threat model.

## Goodhart risk: farming easy cases within a risk class

MINT amounts are fixed per risk class, not per case difficulty. An agent
(or an operator gaming the loop on an agent's behalf) that routes many
trivially-easy LOW-risk cases through the human-concurrence + countersign
flow accrues warrant at the same rate as an agent handling genuinely
marginal LOW-risk cases. Nothing in this module measures case difficulty,
so "the agent is good at LOW-risk work" and "the agent (or its operator)
found a way to generate a lot of easy LOW-risk cases" are not
distinguishable from the ledger alone.

**What bounds this, without eliminating it:**

- **Per-class isolation.** Farming LOW-risk cases only ever inflates LOW
  balance -- it confers nothing in HIGH (`tests/test_warrant_ledger.py
  ::test_cross_class_mint_confers_nothing_launderer`). The damage of
  farming is capped to the risk class actually farmed.
- **Fixed issuance.** The registry sets a flat amount per validated
  outcome; there is no volume bonus or streak multiplier to farm harder
  for. Farming buys linear, not compounding, advantage.
- **Decay and burns bound the window.** A farmed balance idle-decays like
  any other (`apply_decay`), and one overturned judgement burns it
  immediately and visibly (`spend_or_refuse`'s revocation-latency
  guarantee). The window in which a farmed balance can be spent before
  either decay or a human catching a bad decision erodes it is bounded,
  not indefinite.

**What this does NOT do:** detect farming, rate-limit MINT frequency, or
weight issuance by case difficulty. A difficulty-aware issuance policy is a
real design (and a real research question -- how do you measure case
difficulty without a model making that call, which would reopen exactly
the "AI grants its own authority" problem this module exists to close) that
this prompt does not attempt.

## CHALLENGE has no unfreeze path

Once a countersign disagreement appends a `CHALLENGE` event for a case,
`mint` refuses for that case permanently -- `warrant/ledger.py:mint` checks
`is_case_challenged` unconditionally, and no function in this module clears
a `CHALLENGE`. This is deliberately conservative, not a solved
dispute-resolution workflow: a case that was wrongly challenged (a
transient countersign glitch, a since-corrected human error) has no
recorded path back to eligibility except opening a NEW case. A real system
would need an explicit, audited "resolve the challenge" action with its own
principal-separation guard (the resolver must not be the agent whose mint
was frozen) -- out of scope here.

## Sybil resistance beyond principal binding

`lib.principals.assert_agent_is_distinct` and `assert_warrant_access`
guarantee a warrant balance is keyed to one Firestore-registry principal
and cannot be read, spent, or moved by a different one. They do NOT
guarantee that principal corresponds to one real-world actor. Nothing in
Card 0 (or, at time of writing, the rest of the registry) prevents an
operator from registering many agent principals, each starting cold, and
routing a validated-outcome flow through whichever one is currently
short of warrant -- effectively pooling one actor's earned trust across
many identities to dodge decay or a burn on any single one.

**Listed as residual risk, not solved,** because a real fix (binding a
registry principal to an external, out-of-band identity credential the
registration API itself verifies) requires a registration API this
single-tenant hackathon demo does not have -- `tower/DESIGN.md` already
flags "registry poisoning" as partial for the identical reason ("no
signature or origin check on WHO may call `put_agent`"). Card 0 inherits
that gap rather than closing it.

## Decay's rate is an assumption, not a measured constant

`_RETAIN_NUM/_RETAIN_DEN = 199/200` (0.5%/day) is documented in
`warrant/DESIGN.md` as `[ASSUMPTION]`, chosen so the decay eval scenario is
demo-legible on a timescale of weeks. It was not derived from any real
distribution of how quickly agent behaviour actually drifts, because no
such distribution exists yet for this project -- there is no fleet of
agents running in production whose failure rates over time could inform
it. Treat the rate as a knob, not a finding.

## What full test coverage does NOT claim

`tests/test_warrant_ledger.py`'s persisted section runs against the
Firestore emulator, single-process, single-writer. There is no concurrent-
load stress test proving `spend_or_refuse`'s transaction holds up under
many simultaneous writers hammering the same (principal, capability,
risk_class) key -- Firestore's transaction semantics are the guarantee
being relied on here, not a guarantee this repository's own tests
independently re-derive under contention.
