# Continuous Mission State

**"An agent doesn't merely remember the past — it continuously maintains a
trusted, recoverable, policy-governed state of the mission."**

This document covers the five pieces `command_os/` adds on top of the
mission orchestrator described in `docs/architecture.md`: the Mission
Checkpoint Engine, resumability, Trusted State, the Human Override Gate, and
the Context Firewall. All five are real and tested; where something is
scoped down from a more ambitious version, that's stated here plainly
rather than left implicit.

## Mission Checkpoint Engine

Every phase `command_os/mission.py` runs is individually checkpointed. A
mission's length is no longer fixed: the plan is computed from the
objective, and a containment probe or a replan appends work mid-flight,
so the phase queue and cursor live in the checkpointed context itself.
After every stage, `command_os/checkpoint.py:write_checkpoint` persists one
document to `command_os_missions/{mission_id}/checkpoints/{seq}` — a real
Firestore write, not an in-memory trace: `stage` (the same `MissionStage`
the API returns), `ctx` (everything needed to continue: case IDs, the
isolated/minted/resumed booleans, nothing larger), and `status`. A parent
document `command_os_missions/{mission_id}` tracks the mission's own
`status`: `RUNNING`, `AWAITING_HUMAN`, `COMPLETED`, or `HALTED`.

Both queries this module needs (`checkpoints` ordered by `seq`, `missions`
ordered by `created_at`) are single-field orders with no combined `.where()`
filter, deliberately — see the module's docstring for why: it's what a past
redeploy's real gap (a missing composite index for `decision_memory`,
`docs/DEPLOY.md`) teaches, and this design needs no new entry in
`infra/indexes.json` to work against real Firestore, not just the emulator.

## Resumability — what "crash recovery" means here, precisely

`command_os/mission.py:resume_mission` distinguishes three real cases,
matching the vocabulary a checkpoint system should use rather than
guessing:

| Case | What happens |
| --- | --- |
| **ALREADY COMPLETED** (status `COMPLETED`/`HALTED`) | The stored trace is returned as-is. Nothing re-runs. |
| **REQUIRES HUMAN APPROVAL** (status `AWAITING_HUMAN`) | `resume_mission` refuses without an explicit `human_decision`, rather than silently proceeding past a gate nobody cleared. |
| **REPLAYABLE FROM THE NEXT STAGE** (status `RUNNING`) | The mission's own process exited between two stages (a crash or a redeploy). Resumes at `latest.seq + 1` — every stage at or before that is already-completed work and is never re-entered, so already-spent warrant and already-written Hyperion events are never duplicated. |

**What this does not claim**: recovery from a crash mid-instruction inside
a single stage. Firestore's own transactions (`warrant/ledger.py:
spend_or_refuse`) already guarantee a stage's own write either fully
committed or didn't happen at all — there is no partially-applied state for
`resume_mission` to reconcile, so it's always exactly one of "continue past
a completed stage" or "safely re-run a never-started one." This module adds
nothing beyond that; it doesn't need to.

## Trusted State — not a score

`command_os/trust.py:trusted_state_for_mission` folds a mission's
checkpoints and its own Hyperion events (matched exactly by `case_id`) into
four disjoint, named buckets: `TRUSTED`, `UNTRUSTED`, `QUARANTINED`,
`REVOKED`. There is no blended percentage anywhere in this module, and
that's not a style choice — `lib/schema.py:AgentTrust` (a `reputation:
float`) already exists in this repository for exactly one reason:
`settle/loadrating.py:assert_not_agent_trust` refuses it as a load-rating
input, with a test proving the refusal isn't vacuous. Trusted State follows
that same "never one number" discipline `warrant/DESIGN.md` and
`hyperion/schema.py`'s `RiskAssessment` docstring already state for
balances and risk. Memory ("what happened," the full checkpoint trace) and
Trusted State ("what are we willing to act on now," a strictly smaller
categorical fold) are deliberately different objects.

## Human Override Gate

`run_mission(..., auto_approve=True)` is the default and runs stages 1–11
straight through — byte-identical to the mission orchestrator's behaviour
before this pass, so the original one-click demo is unaffected.
`auto_approve=False` pauses at the GATE phase, before any external action, instead of
auto-concurring into repair. The only way past that pause is
`POST /api/command-os/mission/{id}/gate` with `{"decision": "approve"}` or
`{"decision": "deny"}`:

- **Approve** resumes into the exact same repair → re-mint → re-validate
  chain (`_stage9_repair` through `_stage11_resume_report`) the automatic
  path already runs.
- **Deny** finalises the mission `HALTED` without ever calling
  `compute_genome`, `record_human_concurrence`, or `mint` for the repair —
  the isolated agent simply stays isolated.

**The hard boundary this cannot cross**: stage 6's Gateway refusal
(`SCOPE_EXCEEDED`, from the unmodified `tower/gateway.py:evaluate_gateway`)
is never overturned by either choice. A human decision only ever authorises
a *new*, narrower request (stage 9's renegotiated genome) that the same
Gateway independently re-checks in stage 10. There is no code path in
`command_os/mission.py` that can make the Gateway allow the request it
already refused — this is true by construction, not by a promise the UI
makes.

## Context Firewall — three real signals, not ten

`command_os/context_firewall.py:filter_context` decides, per checkpoint,
one of `INCLUDE` / `SUMMARIZE` / `REJECT` / `QUARANTINE`, from three
deterministic signals:

- **Freshness** — age of the checkpoint vs. a stated threshold.
- **Trust** — reuses Trusted State's real categorical fold (never
  re-derived).
- **Relevance** — whether a checkpoint's stage is one a later stage
  function actually reads from `ctx` (a static fact about
  `command_os/mission.py`'s own stage functions, not a guess).

The brief this implements against lists ten metadata dimensions
(importance, relevance, trust, freshness, source, authority, missionId,
agentId, timestamp, securityClassification). Three of those are identifiers
already present on every checkpoint, not scoring signals; this module
computes exactly the three real, independent signals above, in the same
`[ASSUMPTION]`-labelled discipline `hyperion/risk.py`'s weight table
already uses for itself, rather than inventing seven more knobs with
nothing behind them.

## Mission Time Machine

The UI's Mission Time Machine — a section at the bottom of the Agentic
Command OS page, loaded with that page rather than opened from a button;
additive, nothing under `#instrument` changed — lists real missions
(`GET /api/command-os/missions`), lets you open one's real checkpoint
history (`GET /api/command-os/mission/{id}/checkpoints`), and click into a
checkpoint's full persisted state. This is **historical mission state
reconstruction**, not literal time travel or live replay — every checkpoint
shown is the actual document written at that point, read back, not
re-executed.

## Recall — the state that outlives one mission

Everything above is state *within* a mission. `recall/` is the state that
crosses missions, and it is deliberately a different shape:

| | Mission state | Recall knowledge |
| --- | --- | --- |
| Written by | every phase, after every stage | one caller, once, **after the terminal report** |
| Shape | a continuation (`ctx`, cursor, work queue) | atomic facts with provenance |
| Lifetime | one mission | every mission after this one |
| Read by | `resume_mission` | the PLAN phase of a later mission |
| May influence | everything | a risk-class raise and a read-only check, and nothing else |

The write happens **after** the report on purpose: a mission that could
retrieve its own findings mid-flight would be treating its own output as
corroboration. `tests/test_recall_mission.py::test_knowledge_is_written_after_the_report_so_a_mission_cannot_cite_itself`
asserts it.

What a later mission sees is bounded before it is seen: `RECALL_TOP_K = 5`
records and `RECALL_CHAR_BUDGET = 1200` characters, with the retrieval
reporting `considered`, `filtered_out`, `zero_scored`, `dropped_for_budget`
and `chars_returned` alongside what it selected. The PLAN checkpoint stores
all of it, plus the plan's risk profile **before and after** recall — so a
judge reading the stored mission, not the live response, can see exactly what
prior knowledge did to it.

## What is honestly not built

- No live agent-spawning fleet — `singularity/fleet.py`'s roster is
  reference data, unchanged by this pass.
- No autonomous red-team agent — the mission's one adversarial input
  (stage 4) is scripted and labelled `SIMULATED`, same as before this pass.
- No Digital Twin / forecasting engine.
- No literal replay/simulation execution in the Mission Time Machine —
  inspection of real, already-written state only.
