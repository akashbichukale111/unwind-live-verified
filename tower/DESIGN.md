# tower/ — DESIGN.md (Card 2: Control Tower)

## Invariant

One choke point (`tower/gateway.py`) sees every delegated agent task before
any work happens, refuses deterministically by reason code, and nothing
downstream of it can be reached by a route that bypasses it.

## Threat model

Card 2 is infrastructure sitting between the registry (who an agent claims to
be) and the work an agent is dispatched to do. The threats that matter are
the ones that let a task run with authority it should not have, or that let a
misbehaving worker consume attention or budget silently.

## Data model

- `agents/{agent_id}` (`tower/schema.py:AgentRegistryEntry`) — mutable
  registration state (capabilities, scope, budget, status), not an event
  log. Registration is a current-state record, the same way `sources/` is
  one layer down; it is not append-only, because "what an agent is allowed
  to do right now" is exactly what must be overwritable when it changes.
- `decision_memory/{entry_id}` (`tower/schema.py:MemoryEntry`) — append-only,
  enforced by `tower/memory.py` never exposing an update or delete. `seq` is
  allocated via a Firestore transaction on a separate counter document, so
  concurrent writers cannot race into the same sequence number.
- `cases/{case_id}` (`tower/schema.py:CaseRecord`) — mutable current-state,
  like the registry: a case's status and current step are overwritten in
  place, and `decision_memory` is where the history of how it got there
  lives, not the case record itself.

## Runtime path

Relative to the Gateway: registry lookup (`tower/registry.py
:list_eligible_agents`) happens BEFORE a task is composed into a graph;
the Gateway's four checks happen BEFORE dispatch; `tower/memory.py` is
written to as a side effect of decisions made elsewhere (spine/court/
judgment/settle), never as a source of truth for them; `tower/runtime.py`'s
case record is the durability boundary a process restart reads back from.

## Deterministic boundary

`tower/registry.py` and `tower/gateway.py` are walked by
`tests/test_tower_zero_model.py` against the same forbidden-model-client set
`tests/test_zero_model.py` uses for `spine/` (minus `google.adk` itself,
which both legitimately import for their router/graph). `tower/memory.py`
and `tower/runtime.py` are storage and durability, not authority decisions,
and are deliberately not walked -- see that test file's own docstring for
why excluding them is not vacuous.

## Adversarial tests (File B §4)

| Test | Status | Where |
| --- | --- | --- |
| forged authority | N/A here | Card 2 does not re-check retraction authority; that is `spine/authority.py`'s job, untouched by this prompt. The Gateway's PRINCIPAL_VIOLATION is a different kind of authority (agent identity), tested below. |
| replay | N/A | No idempotent write path was added in this prompt that a replay could exploit; `lib/idempotency.py` (Task 1) is untouched. |
| stale authority | Partial — `RegistryStatus.SUSPENDED` makes an agent's authority revocable; `test_principal_violation_when_agent_is_suspended` proves a suspended agent is refused. Time-based staleness (e.g. an agent whose registration has expired) is not modelled -- no expiry field exists yet. |
| cross-principal transfer | **Tested.** `tests/test_principals.py::test_cross_principal_access_raises_non_transferable` |
| cross-risk-class laundering | **Tested.** `test_budget_exceeded_over_risk_class_ceiling_even_under_flat_ceiling` -- room under the flat ceiling cannot be used to launder a HIGH-risk request past its own tighter ceiling. |
| registry poisoning | Partial — `put_agent` enforces principal distinctness on every write (not just creation), so an edit that tries to introduce a collision is checked every time; there is no signature or origin check on WHO may call `put_agent`, because Card 2 has no external-facing registration API yet (non-goal: no UI). |
| model disagreement | N/A | No second model exists yet (Card 3, later prompt). |
| worker hallucination | **Tested.** `test_worker_fault_on_unparseable_output` |
| worker loop | **Tested.** `test_worker_fault_on_loop` |
| prompt injection | N/A for this prompt's code (no LLM-facing surface in `tower/` yet), but the deployed extraction path's defence was independently probed and evidenced this session: `scripts/armor_probe.sh` / `evidence/armor/`. |
| compromised tool | N/A | No tool execution exists yet; `tools` is a registry field with no dispatcher behind it. |
| revoked authority mid-flight | Partial — `check_principal` re-checks `status` on every Gateway call, so a suspension takes effect on the NEXT call; a task already mid-flight when suspension happens is not interrupted (no cancellation mechanism exists). |
| consequence change after issuance | N/A | This is CARD 0's territory (warrant decay); the slot exists (`WarrantSlot`), the arithmetic does not. |
| synthetic-data contamination | **Enforced by schema.** `WarrantProvenance.SYNTHETIC` is the default and the only value anything in this prompt writes; `EARNED` is reserved for Card 0. |
| restart / time-gap | **Tested.** `test_case_resumes_after_a_simulated_one_week_gap_and_a_process_restart` -- three separate subprocesses, a frozen injected clock, a real 7-day gap. |
| race around SPEND/BURN | N/A | Nothing spends or burns warrant yet; the access guard (`assert_warrant_access`) is the only enforcement point that exists, and it is not a race-prone read-modify-write. |
| Goodhart farming | N/A | No metric this prompt introduces is optimizable by an agent; nothing here scores an agent for advantage. |
| confused deputy | **Tested (partially).** The Gateway's `check_scope` refuses a request outside `authority_scope ∪ data_scope`, which is the classic confused-deputy shape (an agent asked to act beyond what it was granted). A true multi-hop confused-deputy chain (agent A tricks agent B into using B's authority on A's behalf) is not modelled -- there is no agent-to-agent call path yet. |
| excessive delegation | **Tested.** `test_budget_exceeded_over_flat_ceiling` and the risk-class variant above -- a request cannot exceed what was granted, flat or per-class. |
| least-privilege violation | **Tested.** `check_scope`'s missing-scope refusal is exactly this. |

## Novelty tests

**Registry (`tower/registry.py`) is NOT merely a lookup table because Y =
`tests/test_tower_registry.py::test_flipping_a_registry_field_changes_the_composed_graph`.**
That test flips one Firestore field and asserts a real `google.adk.workflow
.Workflow` object's own edge list changes shape -- a lookup table returns
data; this returns a different runnable graph.

**The Gateway (`tower/gateway.py`) is NOT merely an if-statement because Y =
`tower/gateway.py:gateway_workflow`**, a real ADK `Workflow` of `FunctionNode`s
with `ctx.route` branches, inspected directly by
`tests/test_tower_gateway.py::test_gateway_workflow_is_a_real_adk_workflow` --
the refusal path is an edge in a graph object a test can enumerate, not
prose describing what the code does.

**Decision Memory (`tower/memory.py`) is NOT a vector store because Y =
grep.** There is no embedding import anywhere in this module or its test
file, and `what_happened_because_of` is answered by walking an explicit
`parent_id` field -- `tests/test_tower_memory.py
::test_what_happened_because_of_walks_a_branching_chain` uses a chain that
BRANCHES, which a similarity search has no notion of getting "correct" or
"wrong" and an explicit causal graph does.

**The runtime (`tower/runtime.py`) is NOT a request-scoped in-memory state
machine because Y =
`tests/test_tower_runtime.py::test_case_resumes_after_a_simulated_one_week_gap_and_a_process_restart`**,
which runs the pause in one OS process and the resume in a completely
separate one, with no shared memory, and asserts the resumed step and state
match exactly what was persisted.
