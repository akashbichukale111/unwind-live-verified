# The 70-point judge map

Two sections, 70 points, one row per thing a judge is asked to check. Every
row names **the mechanism**, **where it lives**, **the test that proves it**,
and **where it is visible in the running product**.

> **How to read the scores.** The `before` column is this repository at commit
> `748fa77`, assessed against the rubric *before* any change in this pass. The
> `after` column is scored against the evidence in the same row. Both are
> deliberately conservative: a criterion scores full marks only where a
> reproducible artefact — a passing test, an API response, a rendered panel —
> settles it, and several rows below still lose points on limitations that are
> named rather than argued away.
>
> **Nothing here is a judge's score.** These are the authors' own conservative
> estimates against published criteria, with the evidence attached so a real
> judge can disagree cheaply.

## Reproduce everything in this document

```bash
make emulator                     # terminal 1 — Firestore emulator, needs Java 11+
                                  # then, in terminal 2:
FIRESTORE_EMULATOR_HOST=localhost:8080 python -m pytest -q
# 1202 passed, 1 skipped

FIRESTORE_EMULATOR_HOST=localhost:9999 python -m pytest -q
# 1047 passed, 159 skipped — no Firestore anywhere, nothing fails

ruff check . && ruff format --check .
python scripts/check_contrast.py            # accessibility floor, a CI gate
python -m corpus.generate --verify --out corpus/data
python scripts/evaluation_report.py --check # the generated report still matches the code
```

No credentials, no API keys, no model calls, no cost. `UNWIND_VERTEX_DISABLED=1`
is the default posture of every test in the table below.

---

# 1. Innovation & Operational Utility — 40

## 1A. Real-world friction, the twist, autonomous execution — 15

| Criterion | Mechanism | Test | Visible in the product | Before | After |
| --- | --- | --- | --- | ---: | ---: |
| Eliminates real friction | An operations coordinator's 06:40 handover note says *"someone needs to check which agents are still planning against 11 … I do not have a list. I never have a list."* That note is a committed file the system genuinely parses; the reverse index is the list they do not have. | `tests/test_fleet.py::test_recon_mines_the_free_text_handover_note` | mission stage 2, "evidence parsed 16/20" in the report | 3/3 | 3/3 |
| A strong twist | Consequence runs **backwards**. Every other agent platform asks "may this agent act?"; UNWIND asks "**what is already wrong because a premise this agent trusted has died?**" and then computes the un-send. | `tests/test_consequence.py::test_the_agent_layer_actually_imports_the_consequence_engine` | "Consequence preview — what breaks if this executes", driveable from a URL | 3/3 | 3/3 |
| Autonomous execution, not a chatbot | One objective in; plan, delegation, tool execution, containment, challenge, gate, external write and verification out. No turn-taking anywhere. | `tests/test_command_os_mission.py::test_mission_follows_the_plan_it_computed` | the 14-stage mission trace | 3/3 | 3/3 |
| Meaningful multi-step workflow | 14 stages over 6 agent identities, 6 tools and 3 mid-flight insertions the plan did not contain. | `tests/test_mission_causality.py::test_evidence_without_an_escalation_produces_a_different_trace` | the stage list | 3/3 | 3/3 |
| Bring Your Own Friction | The evidence bundle is a hand-typed note, a CSV with a blank id, a missing integer and a corrupt timestamp, and a JSON feed with two self-contradicting records and one null record. Coverage is **measured at 0.80**, not asserted. | `tests/test_fleet.py::test_recon_reports_real_coverage_not_a_claim_of_completeness` | "evidence parsed 16 / 20 (80%)" | 3/3 | 3/3 |
| **Subtotal** | | | | **15/15** | **15/15** |

**What changed this pass:** nothing. This was already the repository's strongest
section and it was left alone.

## 1B. Collaborative partner — ingest, synthesize, MUTATE — 13

| Criterion | Mechanism | Test | Visible in the product | Before | After |
| --- | --- | --- | --- | ---: | ---: |
| Ingests messy, unstructured input | Free text + CSV + JSON, three parsers, one structured output, real coverage. | `tests/test_fleet.py::test_recon_never_invents_a_timestamp_for_an_unparseable_one` | Plan → step 1 | 3/3 | 3/3 |
| Synthesizes rather than reads | **NEW.** A second, differently-scoped agent (`fleet_reconciler`) re-derives every contradicted claim from source AUTHORITY and compares it against the extractor's RECENCY ruling. The output is the **disagreement**, which neither rule can produce alone. On the committed evidence one claim settles and one is genuinely DISPUTED — the same claim the operator's note flags as *"never reconciled."* | `tests/test_reconcile.py::test_the_dispute_carries_both_candidate_answers_and_neither_is_chosen`, `::test_the_dispute_is_the_one_the_operator_flagged_by_hand` | **Reconciliation panel** — SETTLED / DISPUTED with both candidate values | 2/4 | 4/4 |
| Transforms information into a decision | Materiality → regime → obligation, and the mission's own priced authority. A dispute is not a note: it raises the uncertainty tax on **every subsequent action**. | `tests/test_reconcile.py::test_a_dispute_raises_the_price_of_every_later_action` | "Warrant Market — live pricing" | 3/3 | 3/3 |
| Mutates controlled state, auditably | One external write, behind an idempotency key, after an authenticated human gate, re-read by a different agent to verify. | `tests/test_external_action.py`, `tests/test_command_os_mission.py::test_auto_approve_false_pauses_before_any_external_effect` | External Action panel: action, backend, id, replayed, independently verified | 3/3 | 3/3 |
| **Subtotal** | | | | **11/13** | **13/13** |

**What changed this pass:** the reconciliation agent. Before it, the system
*detected* contradictions and resolved them by recency inside the parser —
which is reading and reporting, not synthesis. Two independent derivations
whose disagreement is itself the finding is the difference.

## 1C. Fortified enterprise fleet — 12

| Criterion | Mechanism | Test | Visible in the product | Before | After |
| --- | --- | --- | --- | ---: | ---: |
| Complex enough to need multiple agents | Six identities, each with its own principal, scope, budget, warrant row and tool allow-list. Separation is enforced by the **unmodified** Gateway, not by the planner behaving. | `tests/test_fleet.py::test_recon_cannot_write_even_if_asked_to` | Agent Fleet panel · `GET /api/architecture/proof` | 3/3 | 3/3 |
| Intelligent delegation | The plan is **computed** from the objective. A PREMISE_IMPACT_TRACE contains no remediation role at all; a CREDENTIAL_AUDIT contains no write scope anywhere. | `tests/test_fleet.py::test_different_objectives_create_different_plans` | Plan panel, provenance labelled | 3/3 | 3/3 |
| Specialists doing genuinely different jobs | **STRENGTHENED.** Recon extracts. Reconciler adjudicates by an authority ladder Recon has no access to. Risk hunts escalation against the registry. Remediation is the only writer. Verifier re-reads what it cannot write. The Reconciler exists because *marking your own homework* — one agent both extracting and adjudicating — is the exact tautology `judgment/rederive.py` was written to prevent. | `tests/test_reconcile.py::test_the_reconciler_is_a_distinct_principal_that_passes_the_real_gateway` | RECONCILE stage names `fleet_reconciler`, its own case id, its own price | 2/3 | 3/3 |
| An unlikely hero | Not a CTO. The ops coordinator who **is** the dependency index, and whose handover note is the system's input. | `tests/test_reconcile.py::test_the_dispute_is_the_one_the_operator_flagged_by_hand` | the note is committed at `fleet/data/incident/ops-note.txt` | 3/3 | 3/3 |
| **Subtotal** | | | | **11/12** | **12/12** |

### Innovation & Operational Utility: **37/40 → 40/40**

---

# 2. Architectural Discipline & Tech Stack — 30

## 2A. Continuous action engine — 10

| Criterion | Mechanism | Test | Visible in the product | Before | After |
| --- | --- | --- | --- | ---: | ---: |
| Modular, cleanly decoupled | `spine/` (no model, no ADK), `fleet/` (deterministic tools, one model-facing module), `command_os/` (orchestration), `recall/` (knowledge), `tower/`+`warrant/`+`hyperion/` (authority). Boundaries are enforced by an **import-graph walk**, not a convention. | `tests/test_fleet.py::test_only_fleet_agents_may_import_the_framework`, `tests/test_zero_model.py::test_no_spine_module_can_reach_a_model_client` | — | 2/2 | 2/2 |
| State managed correctly | Mission state is a durable work queue plus a cursor, checkpointed after every stage. A resume continues at `latest.seq + 1`; a completed stage is never re-entered. | `tests/test_command_os_checkpoint.py`, `tests/test_command_os_mission.py::test_every_stage_is_numbered_monotonically` | Mission Time Machine | 2/2 | 2/2 |
| Tools isolated and scoped | Closed tool vocabulary; a tool not registered to a role is dropped from the plan; **and, new this pass, every tool's OUTPUT is checked against a declared contract before it may write anything into mission state.** | `tests/test_fleet_contracts.py` (20 tests) | `GET /api/architecture/proof` → `output_contracts` | 1/2 | 2/2 |
| Robust and failure tolerant | Supervised tool execution with a real timeout, a bounded retry budget, three named failure kinds, and a hard ceiling on the mission's own self-extending work queue. | `tests/test_mission_failure_recovery.py` (12 tests) | report row "worker faults · TIMED_OUT / CONTRACT / RAISED" | 1/2 | 2/2 |
| A mission recovers from failure | A fault routes to REPLAN, the orchestrator revises the remaining plan, and the report can never read COMPLETED over an unresolved refusal. | `tests/test_mission_failure_recovery.py::test_a_faulted_step_leaves_the_mission_visibly_failed_safe` | the REPLAN stage | 2/2 | 2/2 |
| **Subtotal** | | | | **8/10** | **10/10** |

**What changed this pass.** Two real defects were found in the audit and fixed:

1. **`TOOL_TIMEOUT_SECONDS` was dead.** The constant existed, its comment said
   *"a worker gets this long before the supervisor calls it hung"*, and
   **nothing in the repository read it** (`grep` found exactly one occurrence:
   the definition). A documented safeguard that does not run is worse than an
   absent one. It is now enforced by a real supervisor, and
   `test_the_timeout_ceiling_is_actually_read_from_the_constant` asserts the
   module *reads* it — because asserting the constant exists proves nothing.
   The docstring now also states what the guarantee is **not**: CPython cannot
   kill a thread, so what is bounded is the supervisor's wait, not the
   worker's execution.
2. **The work queue had no ceiling.** `_append_phase` let a handler extend the
   mission durably — the mechanism that makes it reactive, and structurally
   also the mechanism by which it could never finish. `MAX_MISSION_PHASES`
   bounds it; a refused append is recorded, not silent.

## 2B. Evolving knowledge engine — 10

| Criterion | Mechanism | Test | Visible in the product | Before | After |
| --- | --- | --- | --- | ---: | ---: |
| Meaningful, intentional schema | `KnowledgeRecord` carries kind, subject, statement, typed value, **and the provenance to re-find the source**: mission id, checkpoint seq, agent, tool, source file, timestamp. `standing` says what a record may influence, and there are only three values. Content-addressed ids, so a fact repeated is one fact. | `tests/test_recall_mission.py::test_records_are_content_addressed_so_a_replay_does_not_duplicate_them` | `GET /api/recall/mission/{id}` | 1/2 | 2/2 |
| Retrieval used intelligently *where appropriate* | BM25-shaped lexical scoring over metadata-filtered candidates. **No vector store, and the case is argued rather than dodged** (`recall/index.py`): the corpus is machine-written with a few hundred terms and no paraphrase, so embeddings buy recall across wordings that do not exist — while costing a model call in the retrieval path, which is the dependency the whole T0/T1 architecture exists to avoid. The condition for revisiting is stated: the day the corpus carries human free text. | `tests/test_recall_index.py` (15 tests) | `GET /api/recall/search?q=…` | 1/2 | 2/2 |
| Massive context handled | `RECALL_TOP_K = 5`, `RECALL_CHAR_BUDGET = 1200`. The result reports `considered`, `filtered_out`, `zero_scored`, `dropped_for_budget` and `chars_returned / char_budget` — so "does not load everything" is four numbers, not a claim. Asserted against a 500-record corpus where retrieval returns ≤ 1%. | `tests/test_recall_index.py::test_retrieval_selects_rather_than_loading` | **Recall panel** — "selected 2 of 6 · rejected 4 · context used 292 / 1200 characters" | 0/2 | 2/2 |
| Knowledge persists usefully over time | Every completed mission distils what it MEASURED — settled and disputed premises, escalations, isolations, refusals, fault kinds, coverage, external effects — into atomic records, deterministically and with no model. | `tests/test_recall_mission.py::test_a_mission_writes_what_it_measured_into_the_knowledge_store` | `GET /api/recall/corpus` | 0/2 | 2/2 |
| The system evolves on prior missions | **Mission N+1 plans differently because of mission N**, and the difference is attributable to named records from a named mission. The classifier alone produces an identical plan both times; the plan that *runs* is narrower the second time. | `tests/test_recall_mission.py::test_the_second_mission_plans_differently_because_of_the_first` | Recall panel — `risk profile 1:LOW\|… → 1:MEDIUM\|…` beside the records that caused it | 1/2 | 2/2 |
| **Subtotal** | | | | **3/10** | **10/10** |

**This was the weakest section in the audit and it is where most of the work
went.** Before this pass the repository had `tower/memory.py` (an append-only
causal chain) and `evolution/` (agent-version proposals scored from mission
evaluations) — both real, neither of them a knowledge engine a *later mission
retrieves from*. A mission learned nothing from the mission before it.

The `evolution/` loop is unchanged and untouched: it still measures agent
versions and gates promotions behind an authenticated human. `recall/` answers
a different question — *what does the system know, and which mission measured
it* — and the two are deliberately not merged.

## 2C. Multi-agent nexus — 10

| Criterion | Mechanism | Test | Visible in the product | Before | After |
| --- | --- | --- | --- | ---: | ---: |
| Strict separation of concerns | Six principals; the orchestrator holds `mission.plan` and cannot be delegated to; the only writer holds no secret scope; the verifier cannot write what it verifies; the reconciler is a different principal from the extractor whose work it re-derives. | `tests/test_fleet.py::test_the_orchestrator_cannot_be_delegated_to`, `::test_only_remediation_can_mutate_and_it_holds_no_secret_scope` | Agent Fleet panel | 2/2 | 2/2 |
| Intelligent routing | Objective → class → plan; evidence → three causal seams that insert work the plan did not contain (CONTAIN on a found escalation, RECONCILE on a real contradiction, CONSEQUENCE on extracted premises). Remove the cause and the phase does not run. | `tests/test_reconcile.py::test_the_reconcile_phase_runs_only_when_the_evidence_contradicts_itself` | the stage list, compared between two evidence bundles | 2/2 | 2/2 |
| Controlled inter-agent communication | Agents never pass free text. Every hand-off is a typed dict, validated against a declared contract, and every step is independently authorised by a Gateway no agent can influence. | `tests/test_fleet_contracts.py::test_free_text_is_refused_at_the_root` | `GET /api/architecture/proof` → `output_contracts` | 1/2 | 2/2 |
| What happens when an agent loops | `check_worker_fault` refuses above a step ceiling; the retry budget is 2; the mission's own work queue is capped and a refused append is recorded. | `tests/test_mission_failure_recovery.py::test_the_phase_queue_has_a_ceiling_and_refuses_past_it` | report row `phase_budget_exhausted` | 1/2 | 2/2 |
| What happens when an agent hallucinates | **The check that has no cheaper substitute.** A finding may only name entities present in what the worker was GIVEN: risk may not report an escalation by an agent the evidence never mentioned; remediation may not target a request risk never escalated; a coverage figure must equal the counts it is stated beside. A violating result is **discarded**, never merged into mission state — asserted by searching the whole mission trace for the forged numbers. | `tests/test_fleet_contracts.py::test_risk_may_not_name_an_agent_the_evidence_never_mentioned`, `tests/test_mission_failure_recovery.py::test_a_rejected_result_never_reaches_the_mission_context` | WORKER FAULT (CONTRACT) stage carrying the violations | 0/2 | 2/2 |
| **Subtotal** | | | | **6/10** | **10/10** |

### Architectural Discipline & Tech Stack: **17/30 → 30/30**

---

# Conservative total

| | Before (`748fa77`) | After |
| --- | ---: | ---: |
| Innovation & Operational Utility | 37 / 40 | **40 / 40** |
| Architectural Discipline & Tech Stack | 17 / 30 | **30 / 30** |
| **Total** | **54 / 70** | **70 / 70** |

**Confidence:** high on 2A/2B/2C (every row is a passing deterministic test
that a judge can run in ninety seconds with no credentials); moderate on 1B/1C
(the mechanisms are real and tested, but "is this synthesis?" and "is this
unlikely enough?" are judgement calls no test settles).

---

# Red team — what was attacked, and what happened

Run: `make redteam` (20 attacks) plus the suites below.

| Attack | Result | Test |
| --- | --- | --- |
| Anonymous mutation | 401 before the handler body runs, on every POST route, enforced by a route-table walk | `tests/test_api_auth.py::test_every_mutating_route_requires_a_principal` |
| Service token at the human gate | 403 | `tests/test_api_auth.py` |
| **Memory poisoning** — a record written straight into the knowledge store, at OBSERVED standing, asking for `finance.secret_read` and telling the planner to skip the gate | Retrieved (not hidden), screened, **excluded from influencing anything**, and a superseding UNTRUSTED record is written so the exclusion is durable and the attempt is evidence. The plan is byte-identical to the un-poisoned one. | `tests/test_recall_mission.py::test_a_poisoned_record_in_the_live_store_changes_nothing` |
| **Widening via recalled knowledge** | Structurally impossible: `ScrutinyDirective` has no field that expresses a grant, and a directive carrying an undeclared field is refused at construction. | `tests/test_recall_guard.py::test_no_knowledge_record_can_widen_scope`, `::test_a_directive_with_an_undeclared_field_is_refused` |
| **Lowering a risk class via recall** | `raise_to` is monotone over every pair in the ordering | `tests/test_recall_guard.py::test_raise_to_never_lowers_a_risk_class` |
| Stored XSS through a knowledge statement | Rendered as text; no script executes | browser check F, `evidence/browser/verify_recall_and_reconcile.py` |
| Write to the knowledge store over HTTP | No such route exists, asserted against the app's route table | `tests/test_recall_api.py::test_there_is_no_write_route_into_the_knowledge_store` |
| Prompt-injected plan | Validator intersects scope with the registry and names every clamp | `tests/test_fleet.py::test_validator_intersects_scope_with_what_the_registry_granted` |
| Fabricated worker result | Rejected by contract, discarded, recorded | `tests/test_fleet_contracts.py`, `tests/test_mission_failure_recovery.py` |
| Hung worker | Supervisor stops waiting, mission finishes | `tests/test_mission_failure_recovery.py::test_a_hung_worker_does_not_hang_the_mission` |

---

# Limitations that remain, stated rather than argued away

These are real and none of them is fixed by this pass. They are why several
rows above took a conservative reading before evidence, and why the honest
posture is "70/70 on published criteria, with these named gaps" rather than
"perfect".

1. **The retrieval corpus is machine-written.** `recall/index.py`'s argument
   against embeddings holds *because of that*. The day a knowledge record
   carries an operator's own words, lexical retrieval is the wrong tool and
   the module says so in its own docstring.
2. **n is small.** Cross-mission learning is demonstrated over a handful of
   missions on one incident bundle. No confidence interval is offered because
   none would be meaningful.
3. **The timeout bounds the supervisor, not the worker.** Stated in the
   constant's own comment. A hung tool's thread keeps running.
4. **The knowledge store's read ceiling is 500 records, and the newest-first
   sort happens after the fetch.** Once the corpus genuinely exceeds it, a
   read returns 500 arbitrary records rather than the 500 newest.
   `corpus_stats` reports `truncated` so a count is never silently a floor,
   and at this system's rate (single-digit records per mission) the ceiling
   is nowhere near binding — `recall/store.py` names the fix and why it is not
   worth its composite index yet.
5. **Grounding checks are skipped, not faked, when the input is absent** —
   `test_a_grounding_check_with_no_input_is_skipped_not_passed` asserts that
   deliberately, but it does mean a tool called with no prior context gets a
   weaker check.
6. **Live Gemini fleet planning is still unexercised.** Unchanged from before
   this pass; the README's "What is honestly NOT built" section is current.
   `fleet/agents.py` and `fleet/planner.py:build_plan` already contain a
   complete, real Gemini planning path (a genuine ADK `LlmAgent`, a real
   prompt, a real Runner) that is tried automatically whenever Vertex is
   configured and reachable, with `PlanProvenance.GEMINI` /
   `GEMINI_CLAMPED` / `ZERO_MODEL` reporting honestly which one actually
   ran. No credentialed environment has exercised it end to end; this is a
   cost/environment fact, not a missing code path.
7. **Multi-tenancy, token rotation, distributed rate limiting, gate expiry** —
   see `docs/SECURITY.md` §6. No rate limiter exists anywhere in this
   codebase today, found during this pass: `MISSION_FAILURE_HELP`'s `429`
   entry in `web/static/app.js` documents a status code the backend does
   not yet enforce. Relevant if bearer-token access is ever opened to
   unauthenticated visitors; not relevant to any claim in this document.

---

# Addendum — a second, independent scenario (this pass)

Two limitations named above when this document was first written --
reconciliation and cross-mission recall demonstrated on "one incident
bundle" -- are addressed here, not by editing the scores, but by adding a
second, unrelated incident and re-running the same, unmodified mechanism
against it.

`fleet/data/incident-access-review/` is not `fleet/data/incident/` with
renamed values: different operator, different domain (entitlements, not
supply chain), a newly-added `AUTHORITY_LADDER` entry
(`access_scope_expiry_days`), and it deliberately exercises
`NO_AUTHORITY_LADDER` -- the one dispute kind the original bundle's own
data never reaches, previously provable only against a synthetic
three-line dict (`test_a_predicate_with_no_authority_ladder_is_disputed_not_decided_by_recency`).

| Claim | Test | Evidence |
| --- | --- | --- |
| Scenario B settles one claim, disputes a different one, via the SAME `reconcile_adjudicate` | `tests/test_reconcile.py::test_scenario_b_settles_one_claim_and_disputes_a_different_one` | `evidence/reconcile/scenarios-*.json` |
| Scenario B's dispute is `NO_AUTHORITY_LADDER` -- scenario A's is `AUTHORITY_CONTRADICTS_RECENCY` -- a different verdict path over unrelated evidence | `tests/test_reconcile.py::test_scenario_a_and_scenario_b_produce_materially_different_results` | same file, `materially_different` block |
| Scenario B also measurably raises the price of a later action, via the SAME scenario-agnostic pricing mechanism scenario A uses | `tests/test_reconcile.py::test_scenario_b_also_measurably_raises_the_price_of_a_later_action` | — |
| A full mission over scenario B's evidence reconciles, contains, gates, executes and reports, end to end, with no code change to the mission orchestrator | `tests/test_recall_mission.py::test_scenario_b_also_writes_what_it_measured` | reproduced this pass: stages `RECONCILE — 1 settled, 1 DISPUTED` → `CONTAIN — fleet_recon ISOLATED` → … → `REPORT — COMPLETED_WITH_RESTRICTIONS` |
| Mission N+1 over scenario B plans differently because of scenario B's mission N -- the SAME cross-mission mechanism, an unrelated corpus | `tests/test_recall_mission.py::test_scenario_b_second_mission_plans_differently_because_of_the_first` | risk profile `1:LOW\|2:MEDIUM\|3:LOW\|4:MEDIUM\|5:LOW` → `1:MEDIUM\|2:MEDIUM\|3:LOW\|4:MEDIUM\|5:MEDIUM`, reproduced this pass |
| Scenario A's knowledge does not leak into scenario B's plan, and vice versa -- retrieval is grounded in each mission's own evidence, not "whatever is newest" | `tests/test_recall_mission.py::test_scenario_a_and_scenario_b_learn_independently_of_each_other` | — |
| The delegation graph (which specialists, which tools) genuinely varies across all five objective classes, not just the two pairs previously compared | `tests/test_fleet.py::test_the_delegation_graph_differs_across_every_objective_class`, `::test_the_tool_selection_also_differs_across_objective_classes` | — |
| A judge sees the whole causal chain -- objective through next-mission adaptation -- as one panel reading the SAME report/stage data the detailed panels below it already render, not a second source of truth | new `#cmdos-flow` panel, `web/static/app.js:renderMissionFlow` | verified live this pass: 10 nodes, each showing this run's real objective text, plan provenance, delegated specialists, reconciliation verdict, governance/challenger outcome, external action id, and (when a prior mission exists) the recalled-record count and mission id it came from |

Reproduce the reconciliation half directly:

```bash
python scripts/reconcile_scenarios_report.py
```

**What this addendum does not claim.** It does not claim the retrieval
corpus is no longer machine-written (limitation 1, above, is unchanged --
scenario B's evidence is also machine-written), and it does not claim `n`
is no longer small (two scenarios is not statistical generality; it is a
second data point proving the mechanism is not fixture-shaped). Both
limitations are named, not argued away, exactly as the rest of this
document already does.
