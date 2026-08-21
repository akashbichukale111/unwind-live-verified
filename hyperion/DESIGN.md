# hyperion/ — DESIGN.md (Immune layer over Card 2)

## Invariant

Hyperion never gates anything. `hyperion/guard.py:evaluate_with_hyperion`
calls `tower.gateway.evaluate_gateway` unchanged and returns its exact
`GatewayDecision` alongside a deterministic `RiskAssessment`
(`hyperion/risk.py`) folded from it, then logs the pair to an append-only
collection (`hyperion/immune_memory.py`). The Gateway's four ordered checks
(`tower/DESIGN.md`) remain the one choke point; Hyperion is a read-only lens
on what already happened there, not a fifth check.

## Why this exists

The Gateway already produces a closed vocabulary of security-relevant
outcomes (`GatewayReasonCode`: PRINCIPAL_VIOLATION, SCOPE_EXCEEDED,
BUDGET_EXCEEDED, WARRANT_INSUFFICIENT, WORKER_FAULT, ALLOWED), but nothing
before this module scored those outcomes for severity or accumulated them
into a fleet-level picture. Hyperion answers "how bad, in aggregate, across
every delegation this process has evaluated" — a presentation and
aggregation layer over real enforcement, not a new enforcement surface.

## Data model

- `hyperion_events/{event_id}` (`hyperion/schema.py:HyperionEvent`) —
  append-only, one row per `evaluate_with_hyperion` call. Never the same
  collection as `decision_memory` (see `lib/config.py`'s note): a Hyperion
  event is caused by a Gateway *check*, which fires far more often than a
  case-worthy decision, and is not part of any case's causal chain.

## Deterministic boundary

`hyperion/risk.py` imports no framework and no model client —
`tests/test_hyperion_zero_model.py` walks its import graph the same way
`tests/test_warrant_zero_model.py` does for `warrant/ledger.py`. Scoring a
six-value closed enum into a 0-100 band is table lookup, not judgement; see
that module's docstring for the full argument and the `[ASSUMPTION]` label
on the weight table itself.

## What is built

- Real risk scoring over real Gateway decisions (`hyperion/risk.py`),
  deterministic and reproducible.
- A real, durable, append-only event log (`hyperion/immune_memory.py`),
  aggregated into fleet counts (agents protected/observed, threats detected,
  blocked actions, fleet health %, risk-band histogram, recent events).
- A wrapper (`hyperion/guard.py`) any caller of `evaluate_gateway` can swap
  in for identical enforcement plus logging.
- `scripts/demo_hyperion.py` drives one real refusal
  (`SCOPE_EXCEEDED`) through the wrapper end to end against the Firestore
  emulator and prints the resulting fleet summary — a genuine event, not a
  scripted number.

## What is NOT built, and why — read this before claiming otherwise

The wider "agentic immune system" concept this module is a scoped slice of
also describes several components this repository does not implement. Each
is listed here as architecture, honestly, rather than mocked up to look
live — the same discipline `warrant/DESIGN.md`'s "Simulated countersign"
section and `countersign/DESIGN.md`'s "Live verification, attempted and
reported honestly" section already use.

| Concept | Status | Note |
| --- | --- | --- |
| MCP tool-call guard | **NOT BUILT** | No MCP server or tool dispatcher exists anywhere in this repository (`tower/schema.py`'s `tools` field is a registry attribute with no dispatcher behind it — see `tower/DESIGN.md`'s adversarial-test table, "compromised tool: N/A"). Wiring Hyperion in front of one is straightforward once a real tool-call path exists; there is nothing to guard today. |
| Model Armor / live cloud policy enforcement | **PROBED, NOT INTEGRATED** | `scripts/armor_probe.sh` independently probed the deployed extraction path's defence this project cycle; results are in `evidence/armor/`. That is a one-off probe of the *deployed Gemini extraction endpoint*, not a wired Model Armor client Hyperion calls per-request. No Model Armor API call exists in this module. |
| Shadow sandbox / isolated execution environment | **NOT BUILT** | No sandboxed execution path exists. A `SandboxProvider`-shaped interface is easy to add once there is a real tool-execution step to sandbox (see MCP guard, above) — building one now would be an adapter around nothing. |
| Cognitive air-gap (blocking direct agent→production access) | **PARTIALLY TRUE BY CONSTRUCTION, NOT A SEPARATE MODULE** | `tower/gateway.py`'s four-check choke point already is the enforced boundary between an agent and anything it is delegated to do — there is no code path around it. Hyperion does not add a second boundary; it observes the existing one. |
| Quarantine as real process/session isolation | **NOT BUILT** | A blocked decision is logged (`allowed: false`, reason code, risk band); nothing here suspends a running process, revokes a live session, or isolates state. `tower.registry.RegistryStatus.SUSPENDED` is the one real revocation mechanism in this repository (`tower/DESIGN.md`), and it is a registry edit a human makes, not an automated quarantine action Hyperion triggers. |
| Checkpoint / recovery engine | **NOT BUILT** | No checkpoint or rollback mechanism exists. `tower/runtime.py`'s `CaseRecord` is a durability boundary for a *case*, not an agent execution checkpoint, and this module does not extend it. |
| Fleet-level threat propagation ("Agent A's detection protects Agent B") | **NOT BUILT** | `aggregate_fleet_summary` counts events per agent; nothing here changes one agent's registry entry, scope, or budget because of another agent's blocked event. The log is shared (any agent's events are visible fleet-wide on read), but nothing *acts* on that visibility automatically. |
| Google Cloud IAM roles / service accounts for this layer | **NOT ADDED** | No new IAM role, service account, or GCP resource was created for Hyperion. It reads/writes the same Firestore project and collection style every other card already uses, under the same credentials. |

Anything not in the "What is built" list above and not called out here as
architecture-only should be treated as unimplemented, not simulated.
