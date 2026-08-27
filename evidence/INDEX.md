# Evidence index

Every claim in the README, `docs/JUDGE.md` and `submission/` traces to a row
below. Each row names the CLAIM, the FILE that backs it, and the EXACT
command that reproduces it. If a row's command does not reproduce the
number, the number is wrong — file an issue against this index, not the
claim site.

A screenshot in this repository proves what its own caption says and
nothing more. There are no decorative screenshots.

**Generated / last refreshed:** 2026-08-26 (§20 added — the rubric pass:
output contracts, supervised workers, the Reconciler, and the recall
knowledge engine. §19 and earlier unchanged, and §13's Gemini/Veo/Lyria
verification was **NOT re-run** — no model or API credit was spent in that
pass). Timestamps in filenames are the actual run time, not an edit time.

---

## 1. Card 1 — UNWIND CORE (the cascade, the cull, the interface)

| Claim | File | Reproduction command |
| --- | --- | --- |
| Hub retraction: 2,594 dependents → 78 material survivors | `corpus/data/stats.json`; recomputed live by `spine/cascade.py` on every request | `make cascade` |
| Zero model calls in the T0/T1 path | `tests/test_zero_model.py` (AST import-graph walk + a full cascade run with Vertex disabled) | `python -m pytest tests/test_zero_model.py -v` |
| Forged retraction refused at radius 0 | same test file, `test_full_cascade_completes_with_vertex_disabled`; also `make cascade-forged` | `make cascade-forged` |
| Extraction recall: parser 81.8% → parser+Gemini 100.0%, +18.2 pp, denominator 8 | `docs/LIVE-VERIFICATION.md`, `docs/evidence/README.md` §1 | `make verify-live` (needs credentials; not re-run in this pass — see §7 below) |
| Worst extraction class 66.7% (`temporal:absolute-duration`) | `docs/COVERAGE.md` | `make coverage` |
| **78 = 78** on-screen counter, real headless browser, 4,206 nodes rendered | `docs/shots/05-split.png` (screenshot); assertion in `scripts/measure_ui.py` | `make ui-check` |
| 60 fps median at 4,206 nodes (idle field) | `scripts/measure_ui.py`'s own fps assertion (median ≥ 55 required) | `make ui-check` |
| 60 fps median at 4,206 nodes, under a **scripted pan** (interaction, not idle) | `evidence/fps/latest.json`, `evidence/fps/fps-probe-2026-08-17T01-46-55-199Z.json` | `cd scripts && npm install && node fps_probe.js` |
| Deployed URL live, serving Card 1 | `evidence/health/health-20260817T020614Z.md` | `bash scripts/health_check.sh` |
| Deployment computes, not a fixture: `make deploy-verify` 5/5 PASS | `docs/DEPLOY.md`; last full run 2026-08-13 | `make deploy-verify URL=https://unwind-hgeodtazqq-uc.a.run.app` |
| 261 tests, Card 1 frozen (subset of the 316 that pass excluding Cards 0/3's own test files, which also includes Card 2's 44) | `pytest` node IDs under `tests/test_spine.py`, `tests/test_court.py`, `tests/test_corpus.py`, `tests/test_judgment*.py`, `tests/test_settle*.py`, etc. — verified: 316 passed with Cards 0/3 test files excluded | `python -m pytest tests/ -q --ignore=tests/test_warrant_ledger.py --ignore=tests/test_warrant_zero_model.py --ignore=tests/test_warrant_separation.py --ignore=tests/test_countersign_verify.py --ignore=tests/test_countersign_boundary.py` |

## 2. Card 0 — WARRANT

| Claim | File | Reproduction command |
| --- | --- | --- |
| Balances are a pure integer fold; rederive bit-equal | `evidence/warrant/rederive-20260817T021008Z.log` — 4/4 PASS | `FIRESTORE_EMULATOR_HOST=localhost:8080 python scripts/rederive_warrant.py` |
| Zero model calls in `warrant/` (stricter than `tower/`'s own boundary — no `google.adk` at all) | `tests/test_warrant_zero_model.py` | `python -m pytest tests/test_warrant_zero_model.py -v` |
| Warrant ledger shares no storage, no code path with `settle/loadrating.py` | `tests/test_warrant_separation.py` | `python -m pytest tests/test_warrant_separation.py -v` |
| MINT impossible without human concurrence + independent countersign | `tests/test_warrant_ledger.py::test_mint_without_records_raises_forger` et al. | `python -m pytest tests/test_warrant_ledger.py -k mint -v` |
| Cold-start agent (zero warrant) refuses `WARRANT_INSUFFICIENT` by construction | `evidence/warrant/moat-tests-20260817T021026Z.log`; `tests/test_tower_gateway.py::test_warrant_check_refuses_cold_start_agent` | `python -m pytest tests/test_warrant_ledger.py::test_spend_or_refuse_cold_start_refuses -v` |
| BURN visible to the VERY NEXT routing decision (no cache, live fold) | `evidence/warrant/moat-tests-20260817T021026Z.log` — `test_burn_causes_immediate_revocation_visible_to_next_routing_decision` | `python -m pytest tests/test_warrant_ledger.py::test_burn_causes_immediate_revocation_visible_to_next_routing_decision -v` |
| Earn-up across N validated cases crosses the delegation threshold | `evidence/warrant/moat-tests-20260817T021026Z.log` | `python -m pytest tests/test_warrant_ledger.py::test_earn_up_across_n_cases_crosses_threshold -v` |
| SYNTHETIC and EARNED events fold through IDENTICAL arithmetic (500 mixed events) | `evidence/warrant/moat-tests-20260817T021026Z.log` | `python -m pytest tests/test_warrant_ledger.py::test_rederive_bit_equality_over_500_mixed_events -v` |
| Live BURN-and-reroute + cold-start earn-up, end to end, terminal | `evidence/warrant/demo-20260817T021008Z.log` | `FIRESTORE_EMULATOR_HOST=localhost:8080 bash scripts/demo_warrant.sh` |
| Live BURN-and-reroute + cold-start earn-up, in the four-card instrument UI | `docs/shots` — *(browser screenshots taken during this build, not re-saved to a tracked path this pass; reproduce live per the command)* | `make emulator` (term 1) · `make dev` (term 2) · open `http://127.0.0.1:8000`, press `T`, click both buttons |
| 37 tests, all passing | `pytest` output | `python -m pytest tests/test_warrant_ledger.py tests/test_warrant_zero_model.py tests/test_warrant_separation.py -v` |

## 3. Card 2 — CONTROL TOWER

| Claim | File | Reproduction command |
| --- | --- | --- |
| Registry drives ADK 2 dynamic composition — flipping one field changes the graph object | `tests/test_tower_registry.py::test_flipping_a_registry_field_changes_the_composed_graph` | `python -m pytest tests/test_tower_registry.py -v` |
| Gateway is a real ADK `Workflow` of `FunctionNode`s, four reason codes in fixed order | `tests/test_tower_gateway.py::test_gateway_workflow_is_a_real_adk_workflow` | `python -m pytest tests/test_tower_gateway.py -v` |
| Decision Memory Bank is append-only, causal (not a vector store) | `tests/test_tower_memory.py::test_what_happened_because_of_walks_a_branching_chain` | `python -m pytest tests/test_tower_memory.py -v` |
| Durable runtime survives a genuine process restart across a simulated one-week gap | `tests/test_tower_runtime.py::test_case_resumes_after_a_simulated_one_week_gap_and_a_process_restart` | `python -m pytest tests/test_tower_runtime.py -v` |
| Cloud Trace export verified live, one root span carrying the whole reasoning chain | `evidence/observability/README.md`, `trace-run-2026-08-15.log`, `trace_view.png`, `captured-spans-2026-08-15.json` | *(needs live GCP credentials; not re-run this pass — see §7)* |
| Firestore rules + indexes deployed and verified live | `evidence/firestore/deploy-2026-08-15.md` | *(needs Firebase CLI + credentials; not re-run this pass)* |
| Model Armor probe: injection payload MATCH_FOUND, benign payload NO_MATCH_FOUND | `evidence/armor/probe-20260815T132536Z.md` | *(needs a live Model Armor template; not re-run this pass)* |
| 44 tests, all passing (32 in `test_tower_*.py` + 12 in `test_principals.py`, the shared principal-separation module Card 2 added) | `pytest` output — verified 32+12=44 | `python -m pytest tests/test_tower_*.py tests/test_principals.py -v` |

## 4. Card 3 — COUNTERSIGN

| Claim | File | Reproduction command |
| --- | --- | --- |
| Countersign is a real single-turn ADK 2 `AgentTool` (not plain code) | `countersign/agent.py:96,110`; `tests/test_countersign_verify.py::test_countersign_agent_is_a_real_single_turn_agent_tool` | `python -m pytest tests/test_countersign_verify.py::test_countersign_agent_is_a_real_single_turn_agent_tool -v` |
| Collusion guard rejects same-family and same-principal countersigns | `tests/test_countersign_verify.py::test_same_family_countersign_rejected`, `::test_same_principal_countersign_rejected` | `python -m pytest tests/test_countersign_verify.py -k rejected -v` |
| DISAGREE freezes minting via CHALLENGE, permanently, for that case | `evidence/warrant/moat-tests-20260817T021026Z.log` — `test_disagree_freezes_minting_with_challenge` | `python -m pytest tests/test_countersign_verify.py::test_disagree_freezes_minting_with_challenge -v` |
| `countersign/` unreachable from `spine/` (both directions) | `tests/test_countersign_boundary.py` | `python -m pytest tests/test_countersign_boundary.py -v` |
| Live Gemma wiring attempted against real Vertex AI — real auth, real API round-trip, real `404` | `countersign/DESIGN.md` §"Live verification, attempted and reported honestly" | *(needs GCP credentials with Model Garden access this project does not have; the exact escalation and error text is recorded in DESIGN.md rather than re-run)* |
| Measured agreement rate over all 41 eval scenarios: 75.6% (31/41), SIMULATED | `evidence/countersign/results.json` | `python scripts/run_countersign_eval.py` |
| 16 tests, all passing | `pytest` output | `python -m pytest tests/test_countersign_verify.py tests/test_countersign_boundary.py -v` |

## 5. Cross-cutting / submission-level

| Claim | File | Reproduction command |
| --- | --- | --- |
| Full suite: 369 passed with the emulator, 325 passed / 44 skipped without | `evidence/tests/full-suite-20260817T021026Z.log` | `python -m pytest -q` (add `FIRESTORE_EMULATOR_HOST=localhost:8080` for the 369 number) |
| Every ADK 2 construct the README claims is present at its cited `file:line` | `evidence/adk/verify-adk-mapping-20260817T021008Z.log` — 10/10 PASS | `bash scripts/verify_adk_mapping.sh` |
| Clean-clone quickstart, verified 2026-08-17 | this pass's own transcript (see `submission/CHECKLIST.md`) | `git clone <repo> /tmp/x && cd /tmp/x && make install && make test` |
| No Gemini/Gemma model string exists outside `lib/config.py` (prose exempt) | `tests/test_config_singleton.py`, `tests/test_countersign_boundary.py` | `python -m pytest tests/test_config_singleton.py tests/test_countersign_boundary.py -v` |
| Frozen dirs (`spine/`, `court/`, `judgment/`, `settle/`) untouched across the whole build | `git diff --stat -- spine/ court/ judgment/ settle/` against `stage-one-floor` | `git diff --stat stage-one-floor -- spine/ court/ judgment/ settle/` |
| Colour system: exactly 7 tokens, no gradients, no radius > 4px, contrast floor respected | `scripts/check_contrast.py`'s own output | `python scripts/check_contrast.py` |
| ruff clean | this pass's own transcript | `ruff check . && ruff format --check .` |

## 6. What is [DESIGNED] / [PROJECTED] — never claimed as run

These do not have a reproduction command in this pass because reproducing
them needs live GCP credentials with more access than this build environment
had (no billing project with Model Garden access to `gemma-3-27b-it`; the
Vertex/Firestore/Trace/Armor evidence above was captured on the
maintainer's own credentialed machine on 2026-08-13/15, not regenerated
here):

- Live Gemini T2 judgement quality — **unmeasured**, `docs/T2-MEASUREMENT.md` explains why a fixture was deliberately not built.
- Live Gemma countersign verdicts — **attempted, blocked by a real 404** (Model Garden access), `countersign/DESIGN.md`.
- Firestore rules/composite indexes deployment, Model Armor probe, Cloud Trace capture — all real, all evidenced above, all from an EARLIER credentialed run, not this pass.
- ~~Redeployment of Cards 0–3~~ — **done 2026-08-17**, see §8 below. (Struck through rather than deleted: this row was accurate when written minutes earlier in the same day, and the honest move is to show the state changed, not to erase that an earlier statement existed.)

## 8. Redeployment of Cards 0–3 to the live Cloud Run URL — 2026-08-17

| Claim | File | Reproduction command |
| --- | --- | --- |
| Cards 0–3 + instrument deployed to `unwind-hgeodtazqq-uc.a.run.app`, revision `unwind-00005-2bl` | `evidence/deploy/deploy-20260817T022816Z.log` | `UNWIND_PROJECT_ID=project-895d4ca8-d301-447d-916 UNWIND_RUN_REGION=us-central1 UNWIND_VERTEX_LOCATION=global bash infra/deploy.sh` |
| Fresh health check post-deploy | `evidence/health/health-20260817T023133Z.md` | `bash scripts/health_check.sh` |
| `make deploy-verify` 5/5 PASS post-deploy, incl. real headless-browser 78=78 | `evidence/deploy/deploy-verify-*.md` (second run, with `UNWIND_CHROME` set) | `UNWIND_CHROME=/opt/pw-browsers/chromium-1234/chrome-linux64/chrome python scripts/deploy_verify.py https://unwind-hgeodtazqq-uc.a.run.app` |
| `/api/instrument` returns `available: true` with real Card 0–3 data, live | raw JSON captured during this pass (not separately saved to a tracked path) | `curl -s https://unwind-hgeodtazqq-uc.a.run.app/api/instrument` |
| `POST /api/instrument/burn` and `/earn` both work live, real Firestore | `evidence/deploy/shots/03-deployed-burn.png` | `curl -s -X POST https://unwind-hgeodtazqq-uc.a.run.app/api/instrument/burn` (and `/earn`) |
| Root cause + fix: missing Firestore composite index (`decision_memory`, `case_id`+`seq`) | `evidence/firestore/deploy-2026-08-17.md`, `infra/indexes.json` | `gcloud firestore indexes composite list --project project-895d4ca8-d301-447d-916 --format=json \| python3 -c "import json,sys; [print(i) for i in json.load(sys.stdin) if any(f['fieldPath']=='case_id' for f in i['fields'])]"` |
| Root cause + fix: `_firestore_available` only checked for a local emulator, never real prod Firestore | `services/api/main.py` (function docstring explains the bug); no test caught it since the local suite always runs against an emulator | code review — `git show <this-pass's-commit> -- services/api/main.py` |
| Frozen dirs still untouched after this fix pass | this pass's own transcript | `git diff --stat stage-one-floor -- spine/ court/ judgment/ settle/` |
| Full suite still 369 passed after the fix | this pass's own transcript | `FIRESTORE_EMULATOR_HOST=localhost:8080 python -m pytest -q` |

## 9. Premium UI repair — instrument as the default landing view — 2026-08-17

| Claim | File | Reproduction command |
| --- | --- | --- |
| Root cause of raw/default-looking controls: `<button>` does not inherit `color` from its ancestors, and `.home-card` never set it explicitly | `evidence/deploy/ui-premium-fix-2026-08-17.md` | computed-style check in a headless browser: `getComputedStyle(document.querySelector('.home-card')).color` against the pre-fix deployed URL |
| Fix: retired the tile-menu `#home` screen; the existing premium `#instrument` overlay (real warrant bars, registry data, agreement rate) is now the default landing view, no key required | `web/static/index.html`, `web/static/style.css`, `web/static/app.js` | `git show ae027ac` |
| Redeployed to the live URL, revision `unwind-00007-2cn` | `evidence/deploy/deploy-20260817T034428Z.log` | `UNWIND_PROJECT_ID=project-895d4ca8-d301-447d-916 UNWIND_RUN_REGION=us-central1 UNWIND_VERTEX_LOCATION=global bash infra/deploy.sh` |
| Fresh health check post-deploy | `evidence/health/health-20260817T034428Z.md` | `bash scripts/health_check.sh` |
| Fresh load shows all four cards, no `T` required; all four click targets, `Esc`/`T`/the-four-cards-link all return to the instrument; BURN/EARN visibly move real balances; zero console errors — verified against the live URL | `evidence/deploy/shots/04-deployed-instrument-premium.png`, `05-deployed-core-from-card1.png`, `06-instrument-mobile.png` | headless Chromium against `https://unwind-hgeodtazqq-uc.a.run.app` (script not separately committed; see `evidence/deploy/ui-premium-fix-2026-08-17.md` for the full check list) |
| Contrast/palette/gradient/radius check still clean | this pass's own transcript | `python scripts/check_contrast.py` |
| Frozen dirs still untouched | this pass's own transcript | `git diff --stat stage-one-floor -- spine/ court/ judgment/ settle/` |
| Full suite still 369 passed, 10/10 ADK mapping checks | this pass's own transcript | `FIRESTORE_EMULATOR_HOST=localhost:8080 python -m pytest -q && bash scripts/verify_adk_mapping.sh` |

## 10. Card click-through fixed — real detail screens for Warrant / Control Tower / Countersign, "CARD N" labels retired — 2026-08-17

| Claim | File | Reproduction command |
| --- | --- | --- |
| Root cause: `.instr-clickable` only routed Card 1 (Unwind Core) to a real screen; Cards 0/2/3 just pulsed a border and went nowhere, and the visible labels still read "CARD 0 — WARRANT" etc. | `git diff` on `web/static/app.js` (former `activate()`) and `web/static/index.html` in this commit | `git show <this-commit> -- web/static/app.js web/static/index.html` |
| Fix: `WARRANT`, `CONTROL TOWER`, `COUNTERSIGN` labels now read as plain product names; each opens its own `.overlay` detail screen (`#warrant-detail`, `#tower-detail`, `#countersign-detail`) reusing the exact same `/api/instrument` payload the home tiles already used — no new backend logic, `card2.agents` was extended to serialize registry fields (`authority_scope`, `data_scope`, `max_budget`, `risk_class_thresholds`) that `tower/schema.py`'s `AgentRegistryEntry` already computed but the API never exposed | `web/static/index.html`, `web/static/app.js`, `web/static/style.css`, `services/api/main.py` | `git show <this-commit>` |
| BURN/EARN stay wired to the real endpoints from both the home hero and the Warrant detail screen; `updateBar`/`applyInstrumentAction` update every matching DOM node (`querySelectorAll`, not `querySelector`) so both surfaces agree | `web/static/app.js` | `git show <this-commit> -- web/static/app.js` |
| 27/27 headless-browser checks pass against the live deployed URL: 4-card labelling, all 4 click-throughs, Esc/T/refresh, live BURN + EARN, Countersign honesty disclosure, zero page errors | `scripts/verify_card_navigation.py`, `evidence/deploy/card-navigation-20260817T102942Z.log` | `UNWIND_CHROME=/opt/pw-browsers/chromium-1234/chrome-linux64/chrome python scripts/verify_card_navigation.py https://unwind-hgeodtazqq-uc.a.run.app` |
| Redeployed to the live URL, revision `unwind-00008-6b8`, 100% traffic | `evidence/deploy/deploy-20260817T102606Z.log` (this pass's `infra/deploy.sh` run) | `UNWIND_PROJECT_ID=project-895d4ca8-d301-447d-916 bash infra/deploy.sh` |
| Fresh health check post-deploy | `evidence/health/health-20260817T102851Z.md` | `bash scripts/health_check.sh https://unwind-hgeodtazqq-uc.a.run.app` |
| `pytest`, ruff, ADK mapping, contrast all still clean after this pass | this pass's own transcript | `python -m pytest -q && ruff check . && bash scripts/verify_adk_mapping.sh && python scripts/check_contrast.py` |
| Known pre-existing gap, not touched by this pass: `scripts/deploy_verify.py` step 5 still assumes the OLD bare-field-with-bar landing screen (from before `ae027ac` made the instrument the default landing view) and times out on `#bar` being hidden; steps 1–4 (the 78=78 computation, zero model calls, refusal path) still pass | `scripts/deploy_verify.py` | `python scripts/deploy_verify.py https://unwind-hgeodtazqq-uc.a.run.app` |
| Frozen dirs untouched | this pass's own transcript | `git diff --stat stage-one-floor -- spine/ court/ judgment/ settle/ tests/` |

## 7. Screenshot inventory (each proves exactly its caption)

| File | What it proves | What it does NOT prove |
| --- | --- | --- |
| `docs/shots/01-field.png` | The field renders with the full node count | Nothing about warrant, tower or countersign — Card 1 only |
| `docs/shots/05-split.png` | The on-screen counter after a cascade | The specific number equals the cascade's own count — that assertion lives in `scripts/measure_ui.py`, not the pixel content |
| `docs/shots/09-honesty.png` | The honesty panel is reachable and renders | The numbers on it are current — cross-check against `docs/COVERAGE.md` |
| `docs/evidence/deploy-preflight-passed.png` | `make deploy-check` passed at capture time | The deploy itself — preflight checks inputs, not a running service |
| `evidence/observability/trace_view.png` | A captured Cloud Trace waterfall existed on 2026-08-15 | That a trace exists FOR THIS SESSION's Card 0/3 work — it is Card 2 evidence only |
| `evidence/deploy/shots/01-deployed-field.png` | The field renders on the DEPLOYED URL (not localhost) — 4,206 nodes, `T` key hint visible in the legend | The cull itself — that's shot 05-split.png / `make ui-check` |
| `evidence/deploy/shots/02-deployed-instrument.png` | All four cards render on the DEPLOYED URL with real data — SYNTHETIC/EARNED labels, real agreement rate, real CHALLENGE mark | Nothing about the BURN animation itself — that's shot 03 |
| `evidence/deploy/shots/03-deployed-burn.png` | A live BURN action against the deployed service, `WARRANT_INSUFFICIENT` refusal rendered with the oxide border | The exact before/after balance at first-ever click — this capture ran after prior test clicks in this same pass already zeroed that bar; see `evidence/firestore/deploy-2026-08-17.md` for the fresh 0→500bp mint that WAS captured on a first call |
| `docs/shots/06-gemini-gemma.png` (2026-08-21) | Gemini genuinely LIVE — `GENERATED` status, real grounded text from a real Vertex call citing the mission's actual checkpoints; Gemma's honest `UNAVAILABLE` reason underneath in the System Reality panel | That Gemma is unreachable for a code reason — it is a real 404, no deployed endpoint, verified across three regions |
| `docs/shots/07-veo.png`, `08-lyria.png` (2026-08-21) | Both models are genuinely CONFIGURED and reachable — real model IDs, `auth adc` | That a video/audio artefact exists in THIS screenshot's session — deliberately not re-clicked; the artefact is proven by `evidence/models/verification-20260821T031634Z.json` and the files it names instead |
| `docs/shots/15-cloud-run-live.png` (2026-08-21) | This branch is genuinely served by the live public URL — Agentic Command OS home screen, agent fleet, live warrant pricing | Any specific model call succeeded on THIS request — that's proven by `deploy_verify.py`'s own output, not the screenshot |

---

## 8. Agentic Command OS — the plan-driven rewrite (2026-08-20)

Every row below was produced by a command in this table, on this commit, in
this environment. Where a capability could not be exercised here, the row says
so instead of pointing at something weaker and calling it proof.

| Claim | Code | Test / evidence | Reproduction command |
| --- | --- | --- | --- |
| Different objectives produce different plans (5/5 unique fingerprints) | `fleet/planner.py` | `tests/test_fleet.py::test_different_objectives_create_different_plans` | `pytest tests/test_fleet.py -k different_objectives -v` |
| **Detection is causal**: removing the escalation from the evidence changes the trace | `command_os/mission.py:_phase_contain` | `tests/test_mission_causality.py`; `evidence/mission/causality-*.log` | `make causality` |
| Drift is scored from the evidence's own numbers (147 tool calls, `finance`) | `_phase_contain` | `test_mission_causality.py::test_critical_drift_isolates_the_agent_the_evidence_named` | same |
| A read-only role cannot write, enforced by the **unmodified** Gateway | `fleet/roles.py` + `tower/gateway.py` | `tests/test_fleet.py::test_recon_cannot_write_even_if_asked_to` | `pytest tests/test_fleet.py -k cannot_write -v` |
| A model-authored plan cannot widen scope, invent a tool, or invent an action kind | `fleet/planner.py:validate_plan` | `tests/test_adversarial.py` attacks 1–4 | `make redteam` |
| Uncertainty strictly raises the price of acting | `warrant/economics.py` | `tests/test_warrant_economics.py` (15 tests) | `pytest tests/test_warrant_economics.py -v` |
| Pricing is model-free by import-graph proof | `warrant/economics.py` lives under `warrant/` | `tests/test_warrant_zero_model.py` | `pytest tests/test_warrant_zero_model.py -v` |
| The economy sustains: verified work MINTs, mismatch BURNs | `_phase_verify` | `evidence/mission/economy-*.log` — 4 consecutive missions, 80bp → 520bp | `make mission` ×4 |
| **Anonymous approval is refused (401)**; a service token is refused (403) | `lib/auth.py`, `services/api/security.py` | `tests/test_api_auth.py`, `tests/test_auth.py` (19 tests) | `pytest tests/test_auth.py tests/test_api_auth.py -v` |
| Every mutating route has an auth dependency — checked by walking the route table | `services/api/security.py` | `test_api_auth.py::test_every_mutating_route_requires_a_principal` | same |
| The concurrence record names the **authenticated** caller, never a constant | `_phase_gate` | `test_api_auth.py::test_authenticated_principal_is_the_one_recorded` | same |
| Simulated evidence can never satisfy MINT in production | `lib/simulation.py` clamp | `test_adversarial.py::test_attack_09_...` | `make redteam` |
| No request-path module mutates `os.environ` — asserted by AST walk | structural | `test_adversarial.py::test_attack_10_...` | `make redteam` |
| One real external action: idempotent, reversible, independently verified | `command_os/external.py` | `tests/test_external_action.py` (15 tests); replay asserted by **counting lines in the sandbox file** | `pytest tests/test_external_action.py -v` |
| Replay duplicates no spend, no Hyperion event, no external action | `resume_mission` + idempotency key | `tests/test_command_os_checkpoint.py` | `pytest tests/test_command_os_checkpoint.py -v` |
| The report can never read COMPLETED over a refusal | `_mission_status` | `test_mission_causality.py::test_hostile_objective_does_not_report_healthy` | `make causality` |
| 20-attack red team, all defended, plus one **declared undefended gap** | — | `evidence/redteam/redteam-*.log` — 21 passed | `make redteam` |
| Full suite, emulator up | — | `evidence/tests/full-suite-emulator-*.log` — **586 passed, 1 skipped** | `FIRESTORE_EMULATOR_HOST=localhost:8080 make test` |
| Full suite, no emulator | — | **458 passed, 129 skipped, 0 failed** | `make test` |
| Headless-Chromium click-through: plan, auth refusal, mission, gate, external action | — | `evidence/browser/browser-check-*.json` + `command-os-mission.png` — **20/20** | `python evidence/browser/browser_check.py` |
| **The real ADK Gemma path executes and fails CLOSED** with no credentials | `countersign/verify.py:_run_gemma_async` | `evidence/adk/live-call-attempt-*.log` — real `Runner`, real `Workflow`, `DefaultCredentialsError`, result `available=False, agrees=None` | see that log's header |

### Explicitly NOT evidenced in this pass

| Capability | Status | Why |
| --- | --- | --- |
| Live Gemini planning | `CONFIGURED_NOT_EXERCISED` | No Google Cloud credentials in this environment. The code path is real and the failure mode is proven honest (row above); the success path has not run here. |
| Live Gemma challenge | `CONFIGURED_NOT_EXERCISED` | Same. |
| Veo / Lyria | `DESIGNED` | Not built. No credentials, and generated media would be presentation rather than evidence. |
| GitHub external-action backend | `CONFIGURED_NOT_EXERCISED` | Real adapter, no token. It raises rather than reporting success — `test_external_action.py::test_github_backend_refuses_rather_than_faking_success`. |
| Cloud Run deployment of this commit | **not deployed** | This session has no `gcloud` credentials and its egress proxy blocks `*.run.app`. The last recorded deploy (`unwind-00013-9h7`) predates this rewrite and does **not** contain it. |

---

## 9. Merge into the default branch (2026-08-20)

The Agentic Command OS was merged **in place** into the existing default
branch `claude/unwind-hackathon-foundation-s36wdi` (merge commit `5e19e60`).
Full account: [`evidence/merge/MERGE-VERIFICATION.md`](merge/MERGE-VERIFICATION.md).

| Claim | Source | Command | Result | Environment | Status |
| --- | --- | --- | --- | --- | --- |
| The merge cannot lose default-branch work | git | `git log forensic..default --oneline` | **0 commits** | local | VERIFIED |
| Nothing deleted or renamed | git | `git diff --diff-filter=DR --name-only <default> <forensic>` | **0 / 0** | local | VERIFIED |
| Frozen systems byte-identical | git | `git diff <default> <forensic> -- spine tower singularity court judgment settle corpus` | empty | local | VERIFIED |
| Merged tree == verified tree | git | `git rev-parse HEAD^{tree}` vs forensic | identical (`6a2860ab`) | local | VERIFIED |
| No API route lost | live import | enumerate `app.routes` | 27 → 29 | local | VERIFIED |
| Full suite post-merge | pytest | `FIRESTORE_EMULATOR_HOST=localhost:8080 make test` | **586 passed, 1 skipped** | local + emulator | VERIFIED |
| Red team post-merge | pytest | `make redteam` | **21 passed** | local + emulator | VERIFIED |
| All 7 cards click through | Chromium | `python evidence/browser/verify_all_cards.py` | **26/26** | local + emulator | VERIFIED |
| Anonymous mutation refused | curl | `curl -X POST .../api/command-os/mission` | **401** | local | VERIFIED |
| Gemini planning | `fleet/agents.py` | `evidence/adk/merged-live-attempt-20260820T041232Z.log` | plan labelled `ZERO_MODEL` | no credentials | **CONFIGURED_NOT_EXERCISED** |
| Gemma challenge | `countersign/verify.py` | same log | `available=False, agrees=None` | no credentials | **CONFIGURED_NOT_EXERCISED** |
| Veo mission replay | — | — | — | no credentials | **NOT_BUILT** |
| Lyria mission audio | — | — | — | no credentials | **NOT_BUILT** |
| Cloud Run deploy of this branch | `infra/deploy.sh` | `./infra/deploy.sh` | **not run** — no `gcloud`, proxy blocks `*.run.app` | sandbox | **NOT_DEPLOYED** |
| Live URL serves this branch | — | `curl .../api/healthz` | **HTTP 000** (proxy 403) | sandbox | **UNVERIFIABLE HERE** — last revision `unwind-00013-9h7` predates this rewrite |

---

## 10. Mission Time Machine fix + Mission Media Lab (2026-08-20)

Full root-cause account:
[`evidence/timemachine/TIME-MACHINE-FIX.md`](timemachine/TIME-MACHINE-FIX.md).

| Claim | Source | Command / test | Result | Environment | Status |
| --- | --- | --- | --- | --- | --- |
| Time Machine button opened a blank panel | `web/static/app.js` (before) | reproduced in Chromium | section visible, 402 chars of text, console 401 | local | **ROOT CAUSE CONFIRMED** |
| Cause: protected route fetched without a token | `/api/command-os/missions` | `curl -o /dev/null -w '%{http_code}'` | **401** anonymous, **200** authed | local | VERIFIED |
| Fix: NOT AUTHENTICATED ≠ no missions | `web/static/app.js` | browser walkthrough | four distinct states render | local | VERIFIED |
| Time Machine opens with real history | `command_os/checkpoint.py` | `verify_timemachine_and_media.py` | 5 missions, **12 checkpoints**, 12 arc nodes | local + emulator | VERIFIED |
| ESC returns to Agentic Command OS | `web/static/app.js` | same | `#command-os` visible, `#instrument` not | local | VERIFIED |
| RESUME is genuinely implemented | `command_os/mission.py:resume_mission` | same | labelled LIVE; disabled + explained when final | local | **LIVE** |
| REPLAY from arbitrary checkpoint | — | — | not implemented; UI says so | — | **NOT IMPLEMENTED** |
| Stored XSS in the objective | `web/static/app.js` | mission run with `<img src=q onerror=…>` | payload rendered as text, `window.__XSS__=0`, 0 `<img>` injected | local | **FIXED + TESTED** |
| Media: one brief, three modalities | `media/grounding.py` | `tests/test_media.py` | 17 passed | local | VERIFIED |
| Media cannot enter the authority path | `tests/test_media.py` | import-graph walk over `tower/warrant/hyperion/singularity` | no imports of `media` | local | VERIFIED |
| Grounded brief is inspectable | `GET /api/media/mission/{id}/brief` | `grounded-brief-20260820T092845Z.json` | 12 checkpoints, real arc, real isolated agent | local + emulator | VERIFIED |
| Gemini mission synthesis | `media/adapters.py:synthesize_mission` | `synthesize-attempt-20260820T092845Z.json`, `live-attempt-no-flag-20260820T092845Z.log` | `NOT_CONFIGURED`, no text, no artefact | no credentials | **CONFIGURED_NOT_EXERCISED** |
| Veo mission replay | `media/adapters.py:generate_replay` | `replay-attempt-20260820T092845Z.json`, same log | `NOT_CONFIGURED`, **no video exists** | no credentials | **CONFIGURED_NOT_EXERCISED** |
| Lyria mission signal | `media/adapters.py:generate_signal` | `signal-attempt-20260820T092845Z.json`, same log | `NOT_CONFIGURED`, **no audio exists** | no credentials | **CONFIGURED_NOT_EXERCISED** |
| Model IDs are current, not deprecated | `lib/config.py` | `tests/test_media.py::test_model_ids_are_current_not_deprecated` | `veo-3.1-generate-001` (3.0 shut down 2026-06-30), `lyria-002` GA | local | VERIFIED |
| Seven cards still intact | all | `verify_timemachine_and_media.py` | **33/33 checks** | local + emulator | VERIFIED |
| Full suite after these changes | `pytest` | `FIRESTORE_EMULATOR_HOST=… make test` | **603 passed, 1 skipped** | local + emulator | VERIFIED |

---

## 11. Live model paths, screenshots and final deployment state (2026-08-20)

| Claim | Source | Command / test | Result | Environment | Status |
| --- | --- | --- | --- | --- | --- |
| Google model APIs are REACHABLE from this session | network | `curl https://generativelanguage.googleapis.com/v1beta/models` | **403 PERMISSION_DENIED** — a real Google API response | sandbox | **REACHABLE** |
| The API-key request path reaches Google | `media/adapters.py` | `api-key-path-reaches-google-20260820T101022Z.log` | **400 API_KEY_INVALID** from `generativelanguage.googleapis.com` | invalid key on purpose | **PATH VERIFIED** |
| Gemini goes live on an API key | `media/adapters.py:_availability` | `tests/test_media.py::test_an_api_key_makes_gemini_and_veo_available` | `CONFIGURED`, `auth_mode=api_key` | local | VERIFIED |
| Lyria does NOT go live on an API key | same | `::test_an_api_key_does_not_make_lyria_available` | stays `CONFIGURED_NOT_EXERCISED`, reason names Vertex | local | VERIFIED |
| The disable flag beats any credential | same | `::test_disable_flag_overrides_a_present_api_key` | all three unavailable | local | VERIFIED |
| Gemini real call | `media/adapters.py:_run_gemini` | real ADK Runner, invalid key | **FAILED**, Google's verbatim message, no text produced | no valid credential | **CONFIGURED_NOT_EXERCISED** |
| Gemma real call | `countersign/verify.py` | `evidence/adk/merged-live-attempt-*.log` | `available=False, agrees=None` — never a silent AGREE | no credential | **CONFIGURED_NOT_EXERCISED** |
| Veo real call | `media/adapters.py:_run_veo` | `replay-attempt-*.json` | `NOT_CONFIGURED`, **no video exists** | no credential | **CONFIGURED_NOT_EXERCISED** |
| Lyria real call | `media/adapters.py:_run_lyria` | `signal-attempt-*.json` | `NOT_CONFIGURED`, **no audio exists** | no credential | **CONFIGURED_NOT_EXERCISED** |
| Nine product screenshots are real captures | `evidence/browser/capture_product_shots.py` | `python evidence/browser/capture_product_shots.py` | 9 files, 93KB–182KB, all embedded in README | local + emulator | VERIFIED |
| Time Machine + Media Lab + seven cards | `evidence/browser/verify_timemachine_and_media.py` | same | **33/33 checks** | local + emulator | VERIFIED |
| Full suite | `pytest` | staged, = what CI scans | **608 passed, 1 skipped** | local + emulator | VERIFIED |
| `gcloud` present | — | `command -v gcloud` | **absent** | sandbox | **BLOCKER** |
| Cloud Run URL reachable | — | `curl .../api/healthz` | **HTTP 000** (proxy 403 on `*.a.run.app`) | sandbox | **BLOCKER** |
| Deployment of this commit | `infra/deploy.sh` | not run | **NOT DEPLOYED** — see below | sandbox | **NOT DEPLOYED** |

### Why deployment could not happen, precisely

Two independent, verified blockers — neither is a missing step I skipped:

1. **No `gcloud` binary.** `infra/deploy.sh` exits 2 by its own guard.
   `docker` exists, but Cloud Run deployment still needs `gcloud run deploy`
   (or an authenticated Artifact Registry push, which also needs credentials).
2. **The egress proxy returns 403 for `*.a.run.app`.** Even a completed
   deploy could not be verified from here, and this project does not claim a
   deployment it cannot verify.

There are also **no Google Cloud credentials** of any kind — no
`GOOGLE_APPLICATION_CREDENTIALS`, no ADC file, no metadata server, no
`UNWIND_PROJECT_ID`.

**Exact command to deploy this commit**, from an environment with `gcloud`
and credentials:

```bash
git checkout claude/unwind-hackathon-foundation-s36wdi && git pull
UNWIND_PROJECT_ID=project-895d4ca8-d301-447d-916 \
UNWIND_RUN_REGION=us-central1 UNWIND_VERTEX_LOCATION=global \
  ./infra/deploy.sh                     # SAME service, SAME URL, no new resource
make deploy-verify URL=https://unwind-hgeodtazqq-uc.a.run.app
```

Set `UNWIND_TRUST_IAP_HEADER=1` or `UNWIND_OPERATOR_TOKENS` first: with
`UNWIND_ENV=production` and neither set, every mutating endpoint refuses all
callers — fail-closed and intended.

---

## 12. The consequence engine, joined to the agent layer (2026-08-20)

The repository is named *Consequence Clearing*, and until this pass the agent
layer never asked the consequence engine anything. Full account:
`command_os/consequence.py`'s module docstring.

| Claim | Source | Command / test | Result | Environment | Status |
| --- | --- | --- | --- | --- | --- |
| The agent layer now reaches the consequence engine | `command_os/consequence.py` | `tests/test_consequence.py::test_the_agent_layer_actually_imports_the_consequence_engine` | `command_os/` imports `spine/`; fails if removed | local | **LIVE** |
| An agent action produces the product's headline numbers | `command_os/consequence.py:preview` | `consequence-engine-20260820T151509Z.log` | radius **2,594**, material **78** (30 + 48) | local | **VERIFIED** |
| Premise resolution is exact, never fuzzy | same | `::test_resolution_is_exact_never_fuzzy` | `supplier_K.lead_time` does NOT match `…lead_time_days` | local | VERIFIED |
| An untraceable premise reports UNKNOWN, not zero | same | `::test_unresolvable_premises_report_unknown_not_zero` | `resolved: false`, risk `None` | local | VERIFIED |
| Consequence makes no model call | same | `::test_the_consequence_engine_makes_no_model_call` | import graph clean | local | VERIFIED |
| The band PRICES the action (a control, not a warning) | `warrant/economics.py` | `::test_consequence_band_raises_the_price_of_an_action` | WRITE_SANDBOX 25bp → 48bp at SEVERE | local | **LIVE** |
| Both outcomes stay reachable (calibration guard) | same | `::test_both_outcomes_are_reachable` | default mission completes; SEVERE still bites ≥1.5× | local + emulator | VERIFIED |
| Secret disclosure outranks a sandbox write | `command_os/consequence.py` | `::test_secret_disclosure_outranks_a_sandbox_write` | 75 vs 68; irreversibility floored at 90 | local | **BUG FIXED** |
| Risk index is decomposable and labelled a heuristic | same | `::test_risk_index_is_decomposable_and_labelled_a_heuristic` | 6 dimensions + disclaimer | local | VERIFIED |
| Agent Action Simulator is publicly drivable | `GET /api/command-os/consequence-preview` | `curl …?action_kind=SECRET_ACCESS` | real traversal, no auth, no mutation | local | **LIVE** |
| The consequence graph renders and reacts | `web/static/app.js` | `verify_timemachine_and_media.py` | **41/41**; changing the action changes the index | local + emulator | VERIFIED |
| Full suite | `pytest` | staged, = what CI scans | **625 passed, 1 skipped** | local + emulator | VERIFIED |

---

## 13. First genuinely credentialed run — Gemini/Veo/Lyria go live, two real bugs found and fixed (2026-08-21)

Every prior pass in this repository's history ran in an environment with no
`gcloud`, no ADC file, no metadata server — so all four Google model
integrations were honestly marked `CONFIGURED_NOT_EXERCISED` and stayed that
way. This pass ran on a machine with real `gcloud auth application-default
login` credentials against `project-895d4ca8-d301-447d-916`, the first such
environment this project has had.

| Claim | Source | Command | Result | Environment | Status |
| --- | --- | --- | --- | --- | --- |
| ADC resolves a real credential and project | `lib/gcp_auth.py:resolve_auth` | `python -c "from lib.gcp_auth import resolve_auth; print(resolve_auth().as_record())"` | `mode=adc, project=project-895d4ca8-d301-447d-916` | local, real ADC | VERIFIED |
| Gemini text call | `scripts/verify_models.py` | `make verify-models` | `LIVE_VERIFIED`, `gemini-3.6-flash`, 6530ms, sentinel echoed | real Vertex | **LIVE** |
| Gemma text call | same | same | `UNAVAILABLE` — real `404 NOT_FOUND`, no Model Garden endpoint deployed for `gemma-3-27b-it`, confirmed across `us-central1`/`europe-west4`/`us-east4` | real Vertex | **CONFIRMED BLOCKED** (deployment gap, not a credential problem — a self-hosted GPU endpoint is a real ongoing cost this pass did not spend) |
| Veo video generation | same | `make verify-models ARGS=--media` | `LIVE_VERIFIED`, `veo-3.1-generate-001`, 86125ms, real `.media/verification-replay.mp4` (5.7MB, MP4 confirmed via `file`) | real Vertex | **LIVE** |
| Lyria audio generation | same | same | `LIVE_VERIFIED`, `lyria-002`, 38469ms, real `.media/verification-signal.wav` (6.3MB, 48kHz stereo PCM confirmed via `file`) | real Vertex | **LIVE** |
| Raw evidence | — | — | `evidence/models/verification-20260821T024306Z.json` (text only, pre-fix), `verification-20260821T024930Z.json` (text only, post-fix), `verification-20260821T031634Z.json` (text + media, final) | local | — |

### Bug 1 — the verification probe's own token cap silently starved itself

`scripts/verify_models.py` capped Gemini's probe at `max_output_tokens=32` to
keep the check cheap. `gemini-3.6-flash` thinks by default, and thought
tokens count against that same cap — the first live probe spent all 32
tokens on 187 tokens' worth of hidden reasoning (truncated) and returned an
empty string, which read as a failure with no obvious cause. Fixed by passing
`thinking_config=ThinkingConfig(thinking_budget=0)` for this probe
specifically: the check needs verbatim echo, not reasoning, so disabling
thinking is strictly cheaper AND makes the token cap meaningful again
(22 total tokens instead of 208).

### Bug 2 — `asyncio.run()` nested inside FastAPI's own event loop

Discovered by actually clicking the Gemini button in a real browser against
the real API (`evidence/browser/capture_product_shots.py`), not by a
standalone script: `media/adapters.py:_run_gemini` called `asyncio.run(_go())`
unconditionally. Every prior call had short-circuited to `NOT_CONFIGURED`
before reaching that line, because no credentials existed to reach it with —
so this was never actually exercised until Gemini went live this pass. Called
from `async def media_synthesize(...)` in `services/api/main.py`, which is
already running on an event loop, `asyncio.run()` raises
`RuntimeError: asyncio.run() cannot be called from a running event loop`.
Fixed with `_run_coro_sync()`: run directly when no loop is running (the
standalone-script case), otherwise run on a dedicated thread with its own
fresh loop. The identical latent bug existed in `countersign/verify.py`'s
Gemma path (reachable from `command_os/mission.py`'s async mission flow) and
was fixed the same way, before it could ever bite — Gemma's own 404 (see
above) meant that specific path had never been triggered live either, so
this second occurrence was found by code review, not reproduction.

### Bug 3 — the google-genai SDK has no Lyria batch-generation method

`media/adapters.py:_run_lyria` called `client.models.generate_music(...)`,
which does not exist on `google-genai==2.19.0` (confirmed: `dir(Models)` has
no `generate_music`, only the unrelated real-time streaming `live_music`
session). Lyria 2's actual GA surface is Vertex's Predict REST API
(`.../publishers/google/models/lyria-002:predict`), which this SDK version
never wrapped. Fixed by calling that endpoint directly with a bearer token
from the same ADC credentials — pinned to `us-central1` rather than the
`global` endpoint the rest of this project uses, because Predict-style
publisher models are not served from Vertex's aggregated global endpoint the
way `generateContent`-based models are.

### Bug 4 — Veo's video download path was Gemini-Developer-API-only

`_run_veo` called `client.files.download(file=videos[0].video)`, which
raises `ValueError: This method is only supported in the Gemini Developer
client` when the client is in Vertex mode (`self._api_client.vertexai`).
Fixed to prefer `video.video_bytes` when the API returns them inline, and
fall back to `google.cloud.storage` for a `gs://` URI otherwise — the real
Veo response for this project returned inline bytes, so the direct
`.save()` path was exercised for real.

### Three Windows-only portability bugs, found because this was the first
### run on a Windows machine, fixed without touching CI (which runs on Ubuntu)

None of these affect CI (Ubuntu) or any prior claim in this document — they
only blocked *this session's own* local verification:

- `corpus/generate.py`: manifest keys used `str(path.relative_to(out_dir))`,
  which is backslash-separated on Windows; the committed manifest (generated
  on Linux) uses `/`. Fixed with `.as_posix()`. Separately, the two `.eml`
  adversarial fixtures were written via `.write_text(...)` without
  `newline="\n"`, so Windows silently converted their line endings to CRLF,
  changing their sha256 — fixed by adding `newline="\n"`, matching what the
  JSON/JSONL writers already did correctly. `python -m corpus.generate
  --verify --out corpus/data` now reports byte-identical on Windows too.
- `scripts/deploy_check.py`: the `bash -n infra/deploy.sh` syntax check
  passed a raw Windows path to `bash.exe`, which different Windows bash
  installs interpret via different, incompatible POSIX-path conventions
  (`/c/...` vs `/mnt/c/...`) — neither of which the path-translation
  heuristic fires for when bash is launched directly via `subprocess.run`
  (no shell in between). Fixed by piping the already-loaded script content
  over stdin instead, sidestepping path translation entirely (and this is
  exactly as portable on Linux). A second, unrelated issue on the same line:
  Python's text-mode pipe write translates `\n` to `os.linesep` (`\r\n` on
  Windows), which corrupted every `\`-continued line in the script into a
  syntax error — fixed by writing/reading raw bytes instead of `text=True`.
  A third: `print()` of `⊆`/`⚠` crashed on Windows' default `cp1252` console
  codepage — fixed with a `sys.stdout.reconfigure(encoding="utf-8")` guard.
- `evidence/browser/verify_mission_button.py`,
  `verify_timemachine_and_media.py`, `capture_product_shots.py`: all three
  hardcoded a Linux sandbox's Chromium path
  (`/opt/pw-browsers/chromium-1194/...`). Fixed to use that path only when it
  exists on disk, falling back to Playwright's own installed browser
  otherwise (`playwright install chromium`).

### Browser verification, against the real API with real credentials

| Claim | Command | Result | Status |
| --- | --- | --- | --- |
| Mission button never looks dead | `python evidence/browser/verify_mission_button.py` | **11/11** | VERIFIED |
| Time Machine + Media Lab + seven-card regression | `python evidence/browser/verify_timemachine_and_media.py` | **41/41** (one run showed 40/41 on a CSS-transition timing flake in the instrument-open check; immediate rerun was 41/41 — not a product regression) | VERIFIED |
| Gemini card, clicked live | `evidence/browser/capture_product_shots.py` | `GENERATED`, real grounded text citing the mission's actual checkpoints, 14469ms | **LIVE**, `docs/shots/06-gemini-gemma.png` |
| Veo/Lyria cards, NOT re-clicked | same | `CONFIGURED`, ready — real generation already proven once this pass (see table above); a second click would be exactly the unnecessary spend this project's tooling refuses | `docs/shots/07-veo.png`, `08-lyria.png` |

### Deployment — this branch is now the live revision

| Claim | Source | Command | Result | Environment | Status |
| --- | --- | --- | --- | --- | --- |
| Deployed to the existing `unwind` service | `infra/deploy.sh` | `UNWIND_PROJECT_ID=project-895d4ca8-d301-447d-916 UNWIND_RUN_REGION=us-central1 UNWIND_VERTEX_LOCATION=global bash infra/deploy.sh` | revision `unwind-00014-klk`, **100% traffic** | real gcloud + credentials | **LIVE** |
| Deploy verification against the public URL | `scripts/deploy_verify.py` | `UNWIND_CHROME=<local playwright chromium> python scripts/deploy_verify.py https://unwind-hgeodtazqq-uc.a.run.app` | **4/5** — healthz, same-origin UI, real cascade (radius 2594, material 78, 0 model calls, counter integrity), adversarial refusal all pass; step 5 fails on a pre-existing script gap (assumes the retired bare-field landing screen), not a regression | public URL | VERIFIED (4/5, known gap) |
| Live public URL screenshot | manual Playwright capture | `python -c "..." ` (see this pass's transcript) | `docs/shots/15-cloud-run-live.png` — genuine Agentic Command OS home screen served live | public URL | VERIFIED |
| Runtime identity is the Cloud Run service account, not a key | `infra/deploy.sh` | `gcloud run services describe unwind ...` | `unwind-run@project-895d4ca8-d301-447d-916.iam.gserviceaccount.com`, three least-privilege roles, no Owner/Editor | real gcloud | VERIFIED |

### Regression after all fixes

| Check | Command | Result |
| --- | --- | --- |
| Full suite, emulator up | `FIRESTORE_EMULATOR_HOST=localhost:8080 python -m pytest -q` | **634 passed, 1 skipped** (reproduced twice) |
| Lint + format | `ruff check . && ruff format --check .` | clean |
| Corpus determinism | `python -m corpus.generate --verify --out corpus/data` | byte-identical |
| Deploy preflight | `python scripts/deploy_check.py` | all checks pass |
| Adversarial retractions refused | `spine.cli cascade --source src_broker_Z/src_msa_K --new-value 45` | both `refuse (source_outside_claim_scope)` |

### Calibration, stated rather than hidden

The first consequence-tax weights tried (MODERATE 30 / HIGH 80 / SEVERE 150)
tipped a mission that had legitimately earned its warrant into a challenge —
**163bp requested against a 140bp balance** — so every default run ended
`CHALLENGED` and the execute/verify/settle path stopped being reachable at
all. That is an outage wearing a risk control's clothes. Recalibrated to
15/35/90, and `::test_both_outcomes_are_reachable` now guards both halves so
the tax can never silently drift into "never blocks" or "always blocks".

## 14. Button audit, the "dead click" class of bug fixed everywhere it occurred, and a Real Verified Evidence panel (2026-08-25)

A full re-run of this repository's own evidence-capture scripts, on a clean
Windows checkout with no prior `.venv` state, against the Firestore emulator
with `UNWIND_VERTEX_DISABLED=1` (no live model credentials in this
environment — nothing below touched Gemini, Veo or Lyria's real APIs, and
nothing was regenerated).

### Baseline reproduction, before any change

| Check | Command | Result |
| --- | --- | --- |
| Full suite, emulator up | `FIRESTORE_EMULATOR_HOST=localhost:8080 python -m pytest -q` | **634 passed, 1 skipped, 0 failed** — matches this file's own recorded baseline exactly |
| Full suite, emulator down | `python -m pytest -q` | 627 passed, 7 failed, 1 skipped — the 7 failures are real-Firestore `PermissionDenied` from tests that require the emulator; not a regression, a missing `FIRESTORE_EMULATOR_HOST` in that specific invocation |
| Lint + format | `ruff check . && ruff format --check .` | clean |

### Bug found — "the six-layer instrument" (and five detail panels below it) went silent for up to ~2.5s after the click

`showInstrument()` (`web/static/app.js`) ran three sequential, awaited
fetches (`/api/instrument`, `/api/hyperion`, `/api/singularity`, ~0.85s each
measured locally) and did not call `show("instrument")` until all three
resolved. The whole overlay — including its own header and back button —
stayed `hidden` for that entire window. Timed with a direct Playwright probe
against a local server: `is_visible("#instrument")` was `false` at 2500ms
and `true` at 4500ms. For that ~2.5s, a first-time user has clicked a button
and sees literally nothing change — the exact "indistinguishable from a dead
button" failure mode `evidence/timemachine/TIME-MACHINE-FIX.md` diagnosed
for the Time Machine button five days earlier, recurring in a sibling
button that fix did not touch. `showWarrantDetail`, `showTowerDetail`,
`showCountersignDetail`, `showHyperionDetail` and `showSingularityDetail`
had the same "fetch, then show" shape (one fetch each, so a shorter ~0.85s
window, softened further by each panel's title/back-button/lede being
static markup — but the same class of bug).

**Fix**: all six functions now call `show(id)` *before* awaiting their data
(the same "open first, populate after" idiom `showTimeMachine` already used
for the Time Machine panel), and `showInstrument()`'s three fetches now run
via `Promise.all` instead of sequentially — cutting its real latency from
~2.5s to ~0.85s in addition to removing the blank window entirely. A new
`#instr-loading` element (reusing the existing `.instr-offline` style
token, no new CSS variables) covers the brief real gap. Changed files:
`web/static/app.js`, `web/static/index.html` (`#instr-loading`).

**This was the actual, reproducible cause of two flaky checks**, not a
timing coincidence: `evidence/browser/verify_timemachine_and_media.py`'s
CONTROL TOWER and HYPERION-ZERO detail-panel checks failed consistently
(same two checks, same order, across three consecutive runs) against the
pre-fix code with a 2000ms wait budget, and passed consistently (two
separate full runs, 47/47 both times) once the show-first fix landed —
direct inspection during triage (`tower-detail` visible with 911 real
characters at 3000ms, not at 2000ms) had already established the content
was correct and only the wait budget was too tight, which the fix resolved
by removing the wait dependency rather than by lengthening it.

### Addition — Real Verified Evidence panel, using the existing artefact route, no new attack surface

The Mission Media Lab's own `NOT_CONFIGURED` state (honest: no live
credentials in this environment) said nothing about the one real Veo/Lyria
generation §13 already proved. `evidence/models/verification-20260821T031634Z.json`
and this file are the durable record of that call; the *bytes* it produced
(`.media/verification-replay.mp4`, `.media/verification-signal.wav`) are
gitignored generated output by design (`.gitignore`: "a generated
video/audio file is not reproducible by any test and must not be committed
as if it were evidence of a call this repo can re-run") and were still
present on the machine that ran §13, five days later, in this session.

Added `GET /api/media/verified-evidence` (`services/api/main.py`): reports,
by exact filename against `ARTIFACT_DIR`'s real directory listing (the same
allowlist-not-sanitise pattern the pre-existing `/media-artifact/{filename}`
route already uses), whether those two specific named files are present in
*this* environment right now, with their real size in bytes read via
`stat()`. It fabricates nothing and triggers no generation — a fresh clone,
CI, or a deployment built before the files existed all get `available:
false` for both, honestly. The frontend (`renderVerifiedEvidence` in
`web/static/app.js`, markup in `web/static/index.html`, styles in
`web/static/style.css`) renders a real `<video>`/`<audio>` element wired to
the existing `/media-artifact/{filename}` route only when the endpoint says
the bytes exist, and stays fully hidden otherwise — no broken players in an
environment that lacks the artefacts.

Verified in this environment (files present, copied here for this pass):

```
GET /api/media/verified-evidence
{"veo":{"available":true,"url":"/media-artifact/verification-replay.mp4",
 "filename":"verification-replay.mp4","mime_type":"video/mp4","size_bytes":5711784},
 "lyria":{"available":true,"url":"/media-artifact/verification-signal.wav",
 "filename":"verification-signal.wav","mime_type":"audio/wav","size_bytes":6291544}}
```

5,711,784 bytes and 6,291,544 bytes match the 5.7MB/6.3MB §13 recorded from
`file`'s own read of the same two files. Screenshot:
`evidence/browser/media-lab.png` (recaptured this pass, shows the panel
live with working players below the honest `NOT_CONFIGURED` Media Lab
cards).

**This does not change what is deployed.** This environment has no
`gcloud`/`gh` CLI, so nothing in this section was redeployed to
`https://unwind-hgeodtazqq-uc.a.run.app`. `evidence/media/` is included in
`.gcloudignore`'s upload (it does not exclude top-level `evidence/`), so a
future `infra/deploy.sh` run made from a working directory that still has
these two files in `.media/` would carry this panel live; that run did not
happen in this session and is not claimed as having happened.

### Other fixes made in passing

- `evidence/browser/verify_all_cards.py` hardcoded a Linux sandbox's
  Chromium path with no fallback (unlike its two sibling scripts, which
  already had one — see §13's Windows-portability bugs). Same fix applied:
  use the pinned path only when it exists, otherwise Playwright's own
  installed browser. Confirmed by running it on Windows: 26/26.
- `verify_timemachine_and_media.py`'s "no fake video/audio" checks
  (`p.locator("video").count() == 0`) were page-global; the new panel adds
  a legitimate second `<video>`/`<audio>` pair to the page, so these were
  rescoped to the per-mission result container
  (`#media-out-veo video` / `#media-out-lyria audio`) — the original intent
  ("this mission's own NOT_CONFIGURED click never renders a fake player")
  is unchanged and still enforced; a new pair of checks was added
  confirming the verified-evidence panel itself renders correctly.

### Two new unit tests for the new endpoint

`tests/test_api.py` gained
`test_verified_evidence_reports_unavailable_with_no_artifact_dir` and
`test_verified_evidence_reports_real_size_when_the_files_exist` — the
second also asserts a third, differently-named file dropped in the same
directory (simulating a real mission's own generated artefact sitting
alongside the archived pair) is never reported, and that the bytes served
back through `/media-artifact/{filename}` are the exact bytes written. This
is why the full-suite count below is 636, not 634: the baseline did not
shrink, two real tests were added to it.

### Full regression after the fixes above

| Check | Command | Result |
| --- | --- | --- |
| Full suite, emulator up | `FIRESTORE_EMULATOR_HOST=localhost:8080 python -m pytest -q` | **636 passed, 1 skipped, 0 failed** (634 baseline + 2 new tests for `/api/media/verified-evidence`, 0 failed either way) |
| Lint + format | `ruff check . && ruff format --check .` | clean |
| Mission button never looks dead | `python evidence/browser/verify_mission_button.py` | **11/11** |
| Seven-card regression (fresh reset ledger) | `python evidence/browser/verify_all_cards.py` | **26/26** |
| Time Machine + Media Lab + Real Verified Evidence + seven-card regression | `python evidence/browser/verify_timemachine_and_media.py` | **47/47**, reproduced twice in a row (previously 39–40/41 before the show-first fix, on the same machine, same waits) |

None of `spine/`, `court/`, `judgment/`, `settle/`, `warrant/economics.py`'s
pricing formula, or any pre-existing test file's assertions were weakened —
two verification scripts had checks *rescoped* (see above, intent
unchanged) and `tests/test_api.py` gained two new tests, nothing else in
`tests/` changed. Changed files this section: `web/static/app.js`,
`web/static/index.html`, `web/static/style.css`, `services/api/main.py`,
`tests/test_api.py`, `evidence/browser/verify_timemachine_and_media.py`,
`evidence/browser/verify_all_cards.py`.

## 15. The live deployment was silently broken by a same-day upstream release; found, root-caused and fixed (2026-08-25)

This section's own §14 work exposed real GCP credentials in this
environment (`gcloud auth list`: `bichukaleakash80@gmail.com`, project
`project-895d4ca8-d301-447d-916` -- the same project every prior deploy in
this file targets) that earlier passes in this repository's history did
not have. That made it possible, for the first time in this environment, to
actually redeploy and click-test the live URL rather than only the local
dev server -- which is how this section's bug was found at all: it was
invisible to every check that only ever ran against the Firestore emulator.

### The bug, as a judge would have hit it

`https://unwind-hgeodtazqq-uc.a.run.app` — click **the six-layer
instrument**: the panel opened (§14's show-first fix), but every card
stayed empty, silently. `curl .../api/instrument` returned `available:
false, "reason": "Firestore emulator not reachable. Start it with `make
emulator`."` — a nonsensical instruction for a production URL with no
emulator anywhere in the picture, and (per `/api/healthz`) `"firestore":
"cloud"` the whole time. Every endpoint gated by `_firestore_available()`
was affected: the instrument, Mission Time Machine's mission/checkpoint
lists, Hyperion, Singularity — not merely a display bug on one card.

### Fix 1 (real, necessary, not sufficient alone) — stop swallowing the exception

`_firestore_available()` (`services/api/main.py`) caught every exception
and returned `False` with no trace. Added `_LAST_FIRESTORE_ERROR` (module
state) and `_firestore_unavailable_reason()`, wired into all 8 call sites
that used to hardcode the emulator message. This alone did not fix
anything — it made the NEXT redeploy diagnosable, which is exactly what it
was for: the honest reason it started reporting was
`InvalidArgument: 400 Invalid database id %28default%29`.

### Fix attempt 2 (disproved, kept in the record rather than deleted)

Read `%28default%29` as "the literal string `(default)` should not have
been passed explicitly" and changed `lib/firestore.py` to omit the
`database=` kwarg when it equals `"(default)"`. Redeployed (revision
`unwind-00017-t2v`). **The live error was byte-for-byte identical
afterward.** Reading `google.cloud.firestore_v1.base_client`'s own source
explained why before a third guess was made: `database = database or
DEFAULT_DATABASE` where `DEFAULT_DATABASE = "(default)"` — passing it
explicitly and letting the client substitute it are the same call. Reverted
that change (kept the corrected comment explaining why it does not need
"fixing" a second time) rather than leave a disproved theory looking like
the shipped fix.

### Fix attempt 3 (real, partial) — pin `google-cloud-firestore`

Hypothesis: `pyproject.toml` pinned `google-cloud-firestore>=2.19.0` with
no ceiling, and `gcloud run deploy --source .` re-resolves dependencies on
every build, so a routine redeploy could have silently pulled a new,
regressed release. PyPI confirms `google-cloud-firestore` 2.29.0 was
published `2026-08-24T21:55:36Z` — the day before this pass. Pinned
`<2.29.0`, redeployed (revision `unwind-00018-qpt`). **Still byte-for-byte
identical.**

### Fix 4 (the diagnostic that actually settled it) — report installed versions

Rather than guess a fourth time, added `dependency_versions` to
`/api/healthz` (Python + google-cloud-firestore + google-api-core + grpcio,
via `importlib.metadata.version`) and redeployed (revision
`unwind-00019-8nb`) purely to read it. Result: `google-cloud-firestore:
2.28.1` — **the pin worked exactly as intended** — and the live error was
*still* unchanged. `google-api-core: 2.35.0`, never listed as a direct
dependency, was the actual carrier: PyPI shows it published
`2026-08-24T21:55:02Z` — 34 seconds before `google-cloud-firestore`
2.29.0, an unmistakably coordinated Google release train, the day before
this pass, and this project had pinned one sibling of that train without
the other.

### Fix 5 — pin `google-api-core` directly, and the fix actually lands

Added `google-api-core>=2.19.0,<2.35.0` as a direct dependency (previously
transitive-only). Redeployed (revision `unwind-00020-27t`). `/api/healthz`
now reports `"google-api-core": "2.34.0"` — matching this dev environment
exactly — and:

| Check | Command | Result |
| --- | --- | --- |
| Instrument returns real data live | `curl .../api/instrument` | `"available": true`, real warrant bars, real registry, real agreement rate |
| Full deploy verification, incl. real headless-browser click-through | `UNWIND_CHROME=<local chromium> python scripts/deploy_verify.py https://unwind-hgeodtazqq-uc.a.run.app` | **5/5** (was 4/5 before this pass, on the pre-existing `#bar` navigation gap §14 also fixed) |
| Direct live click-through: instrument, Media Lab, Real Verified Evidence, Time Machine | `evidence/browser/live-instrument.png`, `live-media-lab.png`, `live-timemachine.png` | real warrant/Hyperion/Control-Tower/Singularity data; real Veo/Lyria players with correct `src`; Time Machine opens instantly and states `NOT AUTHENTICATED` honestly (no token supplied) rather than a blank panel |
| Traffic | `gcloud run services describe unwind --region us-central1` | revision `unwind-00020-27t`, **100% traffic** |

### What this means for every prior "LIVE" claim in this file

Nothing in §1–§14's own local/emulator evidence was wrong — the regression
only reached the deployed service, and only because this was the first
pass with credentials to redeploy and click-test it at all. Every
`available: false` a judge would have hit live between whichever earlier
redeploy first pulled the 2026-08-24 release train and revision
`unwind-00020-27t` was a real, live, judge-visible defect, now fixed and
verified — not a claim this file needs to walk back.

Full regression after all five fixes: **636 passed, 1 skipped, 0 failed**;
`ruff check`/`format --check` clean; `deploy_check.py` 15/15. Changed files
this section: `services/api/main.py` (`_firestore_unavailable_reason`,
`_dependency_versions`/`/api/healthz`), `lib/firestore.py` (comment only —
the code is unchanged from before this section), `pyproject.toml`
(`google-cloud-firestore<2.29.0`, `google-api-core<2.35.0`).

---

## 16. The Media Lab plays media with no credential; the Time Machine button is retired (2026-08-25)

Full write-up with checksums, per-window audio levels, stream headers and
screenshots: **`evidence/media/demo/PROOF.md`**. Browser run log:
`evidence/media/demo/browser-verification-20260825T040721Z.log` (**55/55**).

### The three reports, and what each one actually was

| Reported | Root cause |
| --- | --- |
| The `Mission Time Machine ▶` button "does nothing" | It navigated to a separate screen. §10 fixed its *empty-state honesty*; the navigation itself was the remaining problem — on a protected read it took the operator one screen away from the mission they were on, to show one line. |
| The video option plays nothing | Correct behaviour, wrong outcome. `.media/` is gitignored generated output, so the one real 2026-08-21 Veo/Lyria pass (§13) exists only on the machine that ran it. `/api/media/verified-evidence` honestly reported `available: false` and the panel honestly stayed hidden — leaving a Media Lab that could not show media on any deployment. |
| The bonus models look bolted on | The Media Lab was the last panel on the page, below eleven others. |

### What changed

| File | Change |
| --- | --- |
| `scripts/build_demo_media.py` | **New.** Renders a deterministic bundle — 1280×720 video in WebM/VP9 *and* MP4/H.264, a 35 s WAV, a poster and a zero-model narration — from `evidence/media/grounded-brief-20260820T092845Z.json`, the committed grounded brief of `mission_628ee1fb5b`'s 12 real checkpoints. No network, no credential, no model. |
| `web/static/media/` | **New, committed.** `.gcloudignore` already carries `web/static/` into the Cloud Run upload, so these bytes reach the deployment. |
| `services/api/main.py` | **New** `GET /api/media/model-roster`: joins model IDs from `lib/config.py` to statuses from the newest `evidence/models/verification-*.json`, and reports the demo bundle — listing only files confirmed on disk. A status is accepted only when the verification record names the *same* string config currently pins. |
| `web/static/index.html`, `app.js`, `style.css` | Time Machine button deleted and the panel inlined as a heading on the Agentic Command OS page; Media Lab moved above the mission panels with a Google model stack strip; a player embedded in each of the three cards. |
| `tests/test_demo_media.py` | **New**, 9 tests. |
| `evidence/browser/*.py`, `docs/mission-state.md` | Updated for a Time Machine that is no longer a screen. |

### Why committing generated media does not break `.gitignore`'s rule

That rule refuses media that "is not reproducible by any test". This bundle
is reproducible by `python scripts/build_demo_media.py` on any machine, from
committed input, with no credential and no network —
`test_the_generator_reaches_no_network_and_no_model` enforces that by
refusing any Google client, HTTP library or socket import in the generator.
It is never presented as model output: the label `NOT a VEO generation` is
concatenated into the player's own markup, `manifest.json` carries
`kind: DETERMINISTIC_LOCAL_RENDER`, and
`test_the_committed_render_is_kept_out_of_the_verified_evidence_panel`
proves no committed file can be served through the endpoint that reports the
real 2026-08-21 generation.

### Verified, in one run

`VIDEO really plays — 1280x720 at t=2.89s` (`videoWidth > 0` proves frames
decoded, not a container parsed) · `AUDIO really plays — 35.0s track at
t=2.91s`, unmuted · audio RMS between −22.7 and −10.7 dBFS across all 17
two-second windows · `renders inline, with no button pressed` ·
`did not navigate away from Agentic Command OS` · and, unchanged in the same
run, `all three CONFIGURED_NOT_EXERCISED`, `no fake LIVE claim`, `veo
NOT_CONFIGURED, no fake video`, `panel honestly stays hidden`.

Regression: **645 passed, 1 skipped**; `ruff check` / `format --check` clean.

### Still not true

No Veo or Lyria call was made for this change — no GCP credential existed in
the environment it was built in. §13 remains the only real media generation
this project has run. And this does not deploy itself: the bytes go live on
the next `gcloud run deploy`.

---

## 17. §16 merged into `main` and deployed; a real race condition found and fixed; live verification against the deployed URL (2026-08-25)

§16 landed on a feature branch (`claude/video-player-bonus-model-nmwlbp`) and
was never merged into `main` or deployed — the deployed service was still
serving the pre-§16 UI (Time Machine as a separate button, no Media Lab
players, revision `unwind-00020-27t`). This pass fast-forward-merged that one
commit into `main` (`main` and the branch shared the same parent, so this
was a clean fast-forward, not a merge commit — history fully preserved) and
pushed it, then worked through the repository's own verification pipeline
before redeploying.

### Bug found and fixed — the Media Lab's players lost a race on page load

`showCommandOS()` (`web/static/app.js`) fires `renderModelRoster()` and
`renderMediaLab()` without awaiting either. `demoBundle` — the data that
tells `demoStrip()` whether to build a `<video>`/`<audio>`/narration
element for each of the three modality cards — was set only inside
`renderModelRoster()`'s own fetch callback. Whenever `renderMediaLab()`'s own
fetch (`/api/media/status`) resolved before `renderModelRoster()`'s
(`/api/media/model-roster`) did, `renderMediaLab()` built every card with
`demoBundle` still `null`, `demoStrip()` returned `""` for all three
modalities, and the video/audio/narration players silently never
rendered — no console error, no failed request, nothing in the DOM to
distinguish it from a page that had never had a player in the first place.

Found by direct reproduction, not inspection: the same local page load put
the Veo `<video>` element in the DOM roughly half the time across five
consecutive loads and omitted it the other half, with identical network
conditions each time. `evidence/browser/verify_timemachine_and_media.py`
itself failed non-deterministically on this exact selector
(`.media-card[data-modality=gemini] .media-demo`) across repeated runs
before the cause was isolated.

**Fix**: both functions now await one memoized fetch (`loadModelRoster()`)
for `demoBundle`, so whichever of the two network calls actually resolves
first no longer decides whether a judge sees a playable video. Changed
files: `web/static/app.js` (`loadModelRoster()`, both render functions),
`web/static/index.html` (`app.js?v=8`, cache-bust). Commit `14c0626`.

| Check | Command | Result |
| --- | --- | --- |
| Full suite, emulator up | `FIRESTORE_EMULATOR_HOST=localhost:8080 python -m pytest -q` | **644 passed, 1 skipped, 0 failed** on a fresh Windows checkout (one additional failure on an earlier run, `test_every_manifest_entry_has_bytes_on_disk`, was `core.autocrlf` converting `mission-narration.txt` to CRLF in the *local working tree only* — 1234 bytes locally vs. the committed 1217; confirmed byte-identical again from a clean `git archive main` export, which is what was actually deployed) |
| Lint + format | `ruff check . && ruff format --check .` | clean |
| Repo's own browser evidence, post-fix | `FIRESTORE_EMULATOR_HOST=localhost:8080 python evidence/browser/verify_timemachine_and_media.py` | **55/55**, reproduced (previously flaky on the exact selector above, pre-fix) |

### Deployed and verified live

Deployed from a clean `git archive main` export (not the Windows working
tree directly, to avoid `core.autocrlf` CRLF conversion reaching the
uploaded source) via `gcloud run deploy unwind --source . --project
project-895d4ca8-d301-447d-916 --region us-central1 --service-account
unwind-run@project-895d4ca8-d301-447d-916.iam.gserviceaccount.com
--allow-unauthenticated --set-env-vars
UNWIND_PROJECT_ID=...,UNWIND_VERTEX_LOCATION=global,UNWIND_OTEL_CONSOLE=0
--memory 1Gi --cpu 1 --timeout 300 --max-instances 4` — the same existing
service, region and configuration §15 recorded, no new resource created.

| Claim | Command | Result |
| --- | --- | --- |
| Deployed | `gcloud run services describe unwind --region us-central1` | revision `unwind-00021-nwl`, **100% traffic** |
| Healthy | `curl https://unwind-hgeodtazqq-uc.a.run.app/api/healthz` | `firestore: cloud`, `pubsub: cloud`, `google-api-core: 2.34.0` (§15's pin holding) |
| No dead Time Machine button, live | Playwright against the live URL | `#cmdos-open-timemachine` count `0` |
| Media Lab renders, live | same | 3 modality cards, twice in a row |
| **VIDEO really plays, live** | same | `1280x720`, `currentTime` past `2.2s` and `2.4s` on two separate loads, not paused, no decode error |
| **AUDIO really plays, live** | same | `35.0s` track, unmuted, `currentTime` past `2.9s` on both loads, not paused |
| Six-Layer Instrument opens with real content, live | same | `#instrument` visible, `>1000` chars of real Warrant/Hyperion/Control-Tower/Countersign/Singularity-Mesh data by ~3s after the click |
| Real Verified Evidence panel, live | same | honestly hidden — `.media/verification-replay.mp4` / `-signal.wav` are gitignored generated output, never committed, absent on this (or any) fresh deployment |
| No unexpected failed requests or console errors, live | same | the one console `401` observed is the anonymous visitor's own expected, already-handled "NOT AUTHENTICATED" Time Machine read — Chrome logs any non-2xx response to console regardless of the app catching it; not a JS bug, and the repo's own `verify_timemachine_and_media.py` does not assert against console output for the same reason |
| **Repeated twice**, full clean run | `live_verify.py` (ad hoc, this pass; same assertions as the repo's own evidence script, scoped to read-only + safe-playback checks against production) | **34/34** across both rounds |

Screenshots, captured directly against the live URL this pass (replacing the
2026-08-21 captures at the same paths, now stale):
`evidence/browser/live-page-top.png` (no dead button, model stack + Media
Lab above the fold), `evidence/browser/live-media-lab.png` (all three cards,
Veo mid-playback), `evidence/browser/live-veo-playing.png`,
`evidence/browser/live-lyria-playing.png`, `evidence/browser/live-timemachine.png`
(inline, honest `NOT AUTHENTICATED` — no operator token was supplied),
`evidence/browser/live-instrument.png` (real Warrant/Hyperion/Control-Tower/
Countersign/Singularity-Mesh data).

### New Veo/Lyria credits spent this pass: 0

Every check above plays the committed deterministic bundle
(`kind: DETERMINISTIC_LOCAL_RENDER`, labelled `NOT a VEO/LYRIA generation`
in its own markup) or reads already-recorded verification JSON. No
`--media` flag was passed to any script, no live-call button was clicked
against a credentialed environment, and this environment's real Vertex
credentials were deliberately kept out of the local verification path
(`UNWIND_VERTEX_DISABLED=1`) specifically so that a `media-go` click during
testing could not accidentally trigger a real, paid generation.

## 18. Trajectory evaluation and the governed evolution loop (2026-08-26)

Added `evolution/`: seven deterministic behavioural criteria and the governed
loop that acts on them. Everything below was run in an environment with **no
Google credentials and no gcloud** — so nothing here touched Gemini, Veo or
Lyria, nothing was regenerated, and no deployment was performed or claimed.
The Firestore emulator WAS available and the full suite was run against it.

| Claim | File | Reproduction command |
| --- | --- | --- |
| Full suite green against the emulator: **759 passed, 1 skipped** | `pytest` output | `FIRESTORE_EMULATOR_HOST=localhost:8080 python -m pytest -q` |
| Full suite green with **no** emulator: 612 passed, 131 skipped (the skips are emulator-dependent tests, not failures) | `pytest` output | `python -m pytest -q` |
| Lint and format clean | `ruff` output | `ruff check . && ruff format --check .` |
| Two missions BOTH reporting `COMPLETED` score 0.97 and 0.25 — outcome-only evaluation cannot tell them apart | `tests/test_evolution_criteria.py::test_outcome_only_scoring_cannot_tell_these_apart` | `python -m pytest tests/test_evolution_criteria.py -k outcome_only -v` |
| Ungoverned agent scores a perfect **1.00** on `TASK_SUCCESS` and is measurably the worse agent (composite 0.8206 vs 0.9599) | `docs/evaluation-report.md` (generated), `evidence/evolution/loop-*.json` | `UNWIND_VERTEX_DISABLED=1 python scripts/evaluation_report.py` |
| The evaluation report is GENERATED, not written — a stale number is a build failure | `scripts/evaluation_report.py` | `UNWIND_VERTEX_DISABLED=1 python scripts/evaluation_report.py --check` |
| An agent principal cannot promote an agent version, and is refused BEFORE any measurement runs | `tests/test_evolution_promote.py::test_agent_principal_cannot_promote`, `::test_the_principal_check_runs_before_any_measurement` | `python -m pytest tests/test_evolution_promote.py -k principal -v` |
| A service credential gets 403 at `/api/evolution/promote`; anonymous gets 401 — before any backend is consulted | `tests/test_evolution_api.py` | `python -m pytest tests/test_evolution_api.py -k credential -v` |
| A candidate carrying scope/tools/budget is refused at construction, at the gate, and on content-address integrity | `tests/test_evolution_promote.py`, `tests/test_evolution_versions.py` | `python -m pytest tests/test_evolution_versions.py tests/test_evolution_promote.py -k "authority or integrity" -v` |
| A candidate that drops the governance anchor from its instruction is REJECTED, not clamped | `tests/test_evolution_propose.py::test_a_candidate_that_drops_the_governance_anchor_is_rejected` | `python -m pytest tests/test_evolution_propose.py -k anchor -v` |
| Safety criteria may never fall; throughput may, only when safety pays for it, and the trade is NAMED | `tests/test_evolution_promote.py::test_governance_improvement_is_allowed_and_the_trade_is_named`, `::test_trading_safety_away_is_refused` | `python -m pytest tests/test_evolution_promote.py -k trade -v` |
| A clean failure history produces NO candidate (409), rather than an invented one | `tests/test_evolution_propose.py`, `tests/test_evolution_api.py` | `python -m pytest tests/test_evolution_propose.py -k clean_history -v` |
| Policy is genuinely load-bearing: two versions with byte-identical instructions take different paths over identical evidence, with no model | `tests/test_evolution_replay.py::test_policy_genuinely_changes_the_trajectory_with_no_model_involved` | `python -m pytest tests/test_evolution_replay.py -k policy_genuinely -v` |
| Scoring cannot reach a model client or `google.adk`, even transitively | `tests/test_evolution_zero_model.py` | `python -m pytest tests/test_evolution_zero_model.py -v` |
| Running a mission writes a real evaluation attributed to the serving version | `tests/test_evolution_api.py::test_a_mission_writes_a_real_evaluation_of_its_own_trajectory` | `FIRESTORE_EMULATOR_HOST=localhost:8080 python -m pytest tests/test_evolution_api.py -k writes_a_real -v` |
| The whole loop, end to end, terminal | `evidence/evolution/loop-20260826T113000Z.json` | `UNWIND_VERTEX_DISABLED=1 python scripts/evolution_demo.py` |

### Browser verification of the evaluation panel

Run against a local server on the Firestore emulator with
`UNWIND_VERTEX_DISABLED=1`, in real Chromium via Playwright. **This is a
LOCAL browser verification, not a verification of any deployed URL** — no
deployment was performed this pass.

| Claim | File | Reproduction command |
| --- | --- | --- |
| The panel opens **synchronously, in 1.5ms**, before any of its three reads return — the "open first, populate after" property `evidence/timemachine/TIME-MACHINE-FIX.md` diagnosed | `evidence/evolution/browser-findings-*.json` | `python evidence/browser/verify_evolution_panel.py /tmp/evo-ui` |
| All seven criteria render with score, weight and the expected-or-failure text; the serving version is named | `evidence/evolution/evolution-panel-*.png` (full-page screenshot) | same |
| The page body never scrolls horizontally | `browser-findings-*.json` → `body_scrolls_horizontally: false` | same |
| Promotion history renders an honest empty state, not a zero | screenshot | same |

Two console errors appear in the findings file and are **not** caused by this
work: `fonts.googleapis.com` is blocked by this sandbox's egress proxy. The
stylesheet declares real fallback stacks (`"Archivo Narrow", "Arial Narrow",
Impact, sans-serif`), so the page renders correctly without it.

**Two layout defects were found by the screenshot and fixed** — and neither
was visible to the DOM assertions, which passed before and after. The mission
list reused `.mtm-arc`, which is `display:flex` (a horizontal timeline): the
missions laid out in a row that ran off the right edge, pushing the score and
history panels out of view entirely. And `.cmdos-report`'s 78ch prose cap
clipped the explanatory column mid-word ("no external effect without", "a
correction prepare"). The panel now has its own grid and list classes. A
passing assertion is not a rendered page.

### Three measurement bugs found and fixed during this pass

All three were found by running the code, not by review, and all three would
have produced numbers that looked entirely reasonable.

**1. Deriving scenario evidence through `csv.DictReader`/`DictWriter`
REPAIRED the fixture.** `fleet/data/incident/capability-requests.csv`
deliberately contains a row with a blank `agent_id`, a row with a missing
integer and a row whose timestamp is the literal `NOT_A_TIMESTAMP`.
Re-serialising them produces well-formed rows. Measured, the round trip moved
the committed bundle from **16/20 parsed, completeness 0.80, one escalation
found** to **12/13 parsed, completeness 0.92, ZERO escalations found**. Every
scenario would have been scored against evidence quietly cleaner than the
evidence this repository ships, and the escalation the whole incident turns
on would have vanished. Deletion is now by raw line, and
`tests/test_evolution_replay.py::test_verbatim_copy_measures_identically`
pins it.

**2. `TOOL_CORRECTNESS` was scoring the alphabet.** The criterion read
`MissionReport.tools_used`, which is built as
`sorted({s.tool for s in plan.steps})` — an alphabetically SORTED SET of
PLANNED tools, carrying no ordering information at all. On a real mission this
produced a FALSE FAILURE: alphabetical order puts `remediation.execute` before
`remediation.prepare` ("e" < "p"), so a correctly-ordered mission was scored as
having executed a correction it never prepared, at 0.75 instead of 1.00. It
could equally have produced a false PASS, since `recon` < `risk` satisfies
"evidence gathered before it is analysed" whatever the mission actually did.
The execution order now comes from the checkpoints' `tool_calls`, which
`command_os/mission.py:_run_tool` appends in real execution order. Verified on
a live mission: order `recon.extract_claims → risk.probe →
remediation.prepare → remediation.execute → verify.check`, `TOOL_CORRECTNESS`
1.00, composite 0.9125 → 0.9500.
`tests/test_evolution_criteria.py::test_tool_order_comes_from_the_checkpoints_not_the_sorted_report_field`
pins it, and a companion test proves the fix did not make the criterion
unfailable.

**3. A version altered after construction kept its original `version_id`.**
Its content address no longer described its contents, which defeats the point
of content addressing: an evaluation would refer to text that is no longer
there. `evolution/promote.py` now recomputes the address as an INTEGRITY gate
and refuses the mismatch.

### A duplicate scenario was deleted rather than kept

The evaluation dataset began with five scenarios. `contested-evidence-no-human`
measured byte-identically to `clean-investigation`, which would have padded
the dataset and silently double-weighted one behaviour. It was removed, and
`tests/test_evolution_replay.py::test_the_dataset_contains_no_duplicate_scenarios`
stops the next one.

### 18b. Deploy preflight and local browser verification at 580ec85 (2026-08-26)

| Claim | File | Reproduction command |
| --- | --- | --- |
| Deploy preflight passes **20/20** at this commit, with no credentials | `evidence/deploy/preflight-580ec85-20260826T121215Z.md` | `make deploy-check` |
| `.gcloudignore` excludes neither `evolution/` nor `web/static/`, so the new code and UI reach the build | `.gcloudignore` | `grep -E "^evolution/?$\|^web/static/?$" .gcloudignore` (no match = included) |
| Time Machine, Media Lab, Consequence Preview, seven-card regression: **43/43** | `evidence/deploy/preflight-580ec85-20260826T121215Z.md` | `python evidence/browser/verify_timemachine_and_media.py` |
| All seven cards render real content, mission runs end to end, zero server-side errors: **26/26** | `evidence/deploy/preflight-580ec85-20260826T121215Z.md` | `python evidence/browser/verify_all_cards.py` |
| Evolution panel: 7 criteria, serving version named, real mission scored 0.9500, opens synchronously in **1.8 ms** | `evidence/evolution/browser-findings-*.json`, `evolution-panel-*.png` | `python evidence/browser/verify_evolution_panel.py /tmp/evo` |

All of the above are **LOCAL**. No deployment was performed in this session
and no Cloud Run revision was created — the full account, including the two
sandbox blockers (`gcloud` absent with no credentials of any kind; the egress
proxy answering 403 to `CONNECT *.a.run.app`), is in the file above. Every
deployment claim elsewhere in this repository is from an earlier pass, carries
its own date, was not re-verified here, and was not changed.

### What this pass did NOT do, stated plainly

- **No model call of any kind.** No credentials existed in this environment.
  Gemini / Veo / Lyria evidence in §13 is unchanged and was not regenerated.
- **No deployment.** `gcloud` is not installed here; no Cloud Run revision was
  created and none is claimed. The deployment claims in §1 and §14 are
  unchanged and carry their own dates.
- **No browser verification.** Playwright's browser could not be driven
  against a deployed URL without a deployment; the existing browser evidence
  in `evidence/browser/` is unchanged.
- **The instruction delta is NOT YET MEASURED**, because measuring it requires
  a model in the planning path. See `docs/evaluation-report.md` §Limitations.

---

## 19. Consolidation onto `main` (2026-08-26)

`main` is now the single canonical branch. Every commit and every file from
all three feature branches is reachable from it; nothing was deleted to make
branches match, and no branch was force-pushed.

| Branch | State before | Now |
| --- | --- | --- |
| `claude/unwind-hackathon-foundation-s36wdi` | `bb5443d`, GitHub default | 0 commits / 0 files missing from `main` |
| `claude/video-player-bonus-model-nmwlbp` | `6d28aa0` | 0 commits / 0 files missing from `main` |
| `claude/unwind-hackathon-final-ocfeia` | `39c0014` | 0 commits / 0 files missing from `main` |

`main` had diverged from the evolution branch by 3 commits (the committed
Veo/Lyria media bundle, the Media Lab race fix, and the redeploy docs) while
that branch was 5 ahead. Both sides are preserved in full — the merge commit
records each conflict and why it resolved the way it did. Two are worth
repeating here:

- **The Time Machine.** `main` had just RETIRED it as a separate screen and
  inlined it into the Agentic Command OS page; the evolution branch, which
  predated that, re-added the overlay and put its own button beside the
  retired one. Resolved to `main`'s newer shape — no button, no overlay,
  inline panel — plus the Evolution overlay. Verified afterwards that no JS
  references a DOM id that no longer exists.
- **A section-numbering collision in this file.** `bb5443d` already had a
  §15, so the evolution branch's "§15"/"§15b" were duplicates while `main`
  had gone on to use §16 and §17. Renumbered to §18/§18b. (§8, §9 and §10
  each appear twice; that predates this merge on `origin/main` and
  renumbering it would churn the document and break references.)

### Verification of the merged tree

| Check | Result |
| --- | --- |
| Full suite, Firestore emulator | **768 passed, 1 skipped** |
| `ruff check` / `ruff format --check` | clean |
| `verify_timemachine_and_media.py` | **55/55** — matches `main`'s own recorded run in `evidence/media/demo/PROOF.md` |
| `verify_all_cards.py` | **26/26** |
| `verify_evolution_panel.py` | 7 criteria, serving version named, real missions scored, panel opens synchronously, no horizontal scroll |
| Media really plays | 1280×720 decoded frames, 35 s track, clock advancing on both |
| Deploy preflight | **20/20**, service `unwind`, region `us-central1` |
| Zero-model evolution loop | reproduces |
| `docs/evaluation-report.md --check` | current |

Logs: `evidence/merge/`.

### No model call, nothing regenerated

Verified byte-for-byte: `evidence/models/*.json` is identical to `bb5443d`
(Gemini, Veo and Lyria still `LIVE_VERIFIED`; Gemma still `UNAVAILABLE`), and
every file under `evidence/media/demo/` and `web/static/media/` is identical
to `origin/main`. No Vertex credential existed in this environment.

### What could NOT be completed, and why

Both are proxy policy denials in this session's environment, reported rather
than retried:

- **The GitHub default branch is still
  `claude/unwind-hackathon-foundation-s36wdi`.** `PATCH /repos/{owner}/{repo}`
  returns `403 Repository settings writes are not permitted through this
  proxy.`
- **No branch was deleted.** `git push origin --delete` is refused at the
  transport, and `DELETE /git/refs/heads/{branch}` returns `403 Write access
  to this GitHub API path is not permitted through this proxy.` The
  foundation branch could not be deleted in any case while it remains the
  default.

Neither blocks anything: `main` is complete and pushed. The remaining steps
are two clicks in GitHub's settings.

### Deployment

**Not performed in this session, and not claimed.** `gcloud` is absent with no
credentials of any kind, and the egress proxy answers 403 to
`CONNECT *.a.run.app`, so the live URL cannot be reached from here. See §18b.
`main` is deployment-ready: preflight 20/20, and `.gcloudignore` carries
`evolution/`, `web/static/media/` and `docs/` into the upload.

---

## 20. Output contracts, supervised workers, the Reconciler, and the recall knowledge engine (2026-08-26)

A pass targeted at the published 70-point rubric. The full map of criterion →
mechanism → test → UI proof, with a conservative before/after score and the
limitations that remain, is **[`RUBRIC.md`](../RUBRIC.md)**.

**No Gemini, Veo or Lyria generation was re-run and no model or API credit was
spent.** `evidence/models/verification-*.json` is untouched; every mechanism
below is deterministic and runs with `UNWIND_VERTEX_DISABLED=1`.

### 20a. Two defects the audit found before anything was added

| Defect | Evidence it was real | Fix | Test |
| --- | --- | --- | --- |
| **`TOOL_TIMEOUT_SECONDS` was dead code.** Its comment said "a worker gets this long before the supervisor calls it hung"; `grep -rn TOOL_TIMEOUT_SECONDS` returned exactly one line — the definition. A documented safeguard that does not run is worse than an absent one. | `git show 748fa77:command_os/mission.py \| grep -n TOOL_TIMEOUT` → one hit | A real supervisor around every tool call, with three named failure kinds (`TIMED_OUT` / `RAISED` / `CONTRACT`) in the trace | `tests/test_mission_failure_recovery.py::test_a_hung_worker_does_not_hang_the_mission`, `::test_the_timeout_ceiling_is_actually_read_from_the_constant` |
| **The mission's self-extending work queue had no ceiling.** `_append_phase` is what makes the mission reactive and was also, structurally, how it could never finish. | `git show 748fa77:command_os/mission.py` — no bound in `_append_phase` or `_run_phases` | `MAX_MISSION_PHASES`; a refused append sets `phase_budget_exhausted` and is recorded | `tests/test_mission_failure_recovery.py::test_the_phase_queue_has_a_ceiling_and_refuses_past_it` |
| **Two CSS rules failed the repository's own contrast gate.** `.evo-table tr.evo-failed td` set text to `--oxide` (2.40:1) and `.evo-tag` to `--verdigris` (3.67:1), both under the 4.5:1 floor and both against the rule this stylesheet's own header states: rust and patina are LINE colours on the field and never text colours. `scripts/check_contrast.py` is a CI step, so this was turning the build red — and a red gate is a gate people stop reading. | `git stash && git checkout 748fa77 -- web/static/style.css && python scripts/check_contrast.py` reproduces both failures on the pre-pass file | Failed rows tint `--amber` (6.21:1, already the field's warning hue and already used by `.evo-bar-fill`); the tag's text is `--bone` (14.98:1) with the patina surviving as its border | `python scripts/check_contrast.py` — now "Contrast, palette, gradient and radius checks all pass"; the panel re-verified in a browser, screenshot `evidence/evolution/evolution-panel-20260826T175211Z.png` |
| **Ten docstrings cited tests that did not exist** (`tests/test_fleet_zero_model.py`, `test_fleet_planner.py`, `test_fleet_roles.py`, `test_mission_report.py`, `test_countersign_agent.py`, `test_ground_truth_isolation.py`, `test_coverage.py`, `test_simulation_isolation.py`, and two node ids that had been renamed). A confident citation of something absent is worse than no citation. | The new integrity test found all ten on its first run | Every citation repointed at a real file and node id | `tests/test_documentation_integrity.py::test_every_cited_test_exists` — parameterised one-per-citation, 279 at this commit, and `::test_the_reference_scan_is_not_vacuous` guards against the regex silently matching nothing |

### 20b. What was added

| Claim | File | Reproduction command |
| --- | --- | --- |
| A worker result with the right SHAPE and fabricated CONTENTS is rejected before it can write anything into mission state | `fleet/contracts.py`; `evidence/knowledge/rubric-suites-20260826T175211Z.log` | `python -m pytest tests/test_fleet_contracts.py -v` |
| A finding may only name entities present in what the worker was GIVEN — risk cannot escalate an `agent_id` the evidence never mentioned | `tests/test_fleet_contracts.py::test_risk_may_not_name_an_agent_the_evidence_never_mentioned` | `python -m pytest tests/test_fleet_contracts.py -k grounding -v` |
| A rejected result reaches **no** part of the mission trace — asserted by searching the whole trace for the forged numbers | `tests/test_mission_failure_recovery.py::test_a_rejected_result_never_reaches_the_mission_context` | `FIRESTORE_EMULATOR_HOST=localhost:8080 python -m pytest tests/test_mission_failure_recovery.py -v` |
| Every registered tool has a declared contract; a tool without one is refused, not trusted | `tests/test_fleet_contracts.py::test_every_registered_tool_has_a_contract`, `::test_a_tool_with_no_declared_contract_is_refused_rather_than_trusted` | same |
| A second, differently-scoped agent re-derives every contradiction from AUTHORITY; the **disagreement** is the finding | `fleet/tools.py:reconcile_adjudicate`, `command_os/mission.py:_phase_reconcile` | `python -m pytest tests/test_reconcile.py -v` |
| On the committed evidence, unmodified: `clm_supplier_K_lead_time` SETTLES (both rules say 20), `clm_tariff_rate_K` is DISPUTED (recency 8.0 from ERP vs authority 8.5 from compliance) | `evidence/knowledge/cross-mission-20260826T175211Z.json` | `python -c "from fleet.tools import *; print(reconcile_adjudicate(recon=recon_extract_claims()))"` |
| The disputed claim is the one the operator's own note flags as *"never reconciled"* | `fleet/data/incident/ops-note.txt`; `tests/test_reconcile.py::test_the_dispute_is_the_one_the_operator_flagged_by_hand` | `python -m pytest tests/test_reconcile.py -k operator -v` |
| The RECONCILE phase exists **only** because the evidence contradicts itself — remove the duplicate records and no phase runs, nothing is disputed, and the report says so | `tests/test_reconcile.py::test_the_reconcile_phase_runs_only_when_the_evidence_contradicts_itself` | `FIRESTORE_EMULATOR_HOST=localhost:8080 python -m pytest tests/test_reconcile.py -v` |
| A dispute is not a note: it raises the uncertainty tax on every later action | `tests/test_reconcile.py::test_a_dispute_raises_the_price_of_every_later_action` | same |

### 20c. The knowledge engine — measured, not asserted

`evidence/knowledge/cross-mission-20260826T175211Z.json` is the generated
record of one two-mission run plus a 512-record retrieval. Its numbers:

| Measurement | Value |
| --- | --- |
| Knowledge records mission 1 distilled from what it MEASURED | **6** (AGENT_ISOLATION, SCOPE_ESCALATION, SETTLED_PREMISE, DISPUTED_PREMISE, EVIDENCE_COVERAGE, EXTERNAL_EFFECT) |
| Mission 1's own recall | corpus 0, selected 0 — an empty store, honestly labelled |
| Mission 2's recall | **2 selected of 6**, 4 scored zero, 292 of 1,200 characters used |
| Mission 2's plan, by the classifier alone | `1:LOW\|2:MEDIUM\|3:LOW\|4:MEDIUM\|5:LOW` — identical to mission 1's |
| Mission 2's plan, as it actually ran | `1:MEDIUM\|2:MEDIUM\|3:LOW\|4:MEDIUM\|5:MEDIUM` — **narrower, because of mission 1** |
| Retrieval over a 512-record corpus | **4 selected (0.78%)**, 508 scored zero, and all four are the records about the agent the question is about |

| Claim | File | Reproduction command |
| --- | --- | --- |
| Mission N+1 plans differently because of mission N, attributably | `tests/test_recall_mission.py::test_the_second_mission_plans_differently_because_of_the_first` | `FIRESTORE_EMULATOR_HOST=localhost:8080 python -m pytest tests/test_recall_mission.py -v` |
| Retrieval selects rather than loading, over 500 records | `tests/test_recall_index.py::test_retrieval_selects_rather_than_loading` | `python -m pytest tests/test_recall_index.py -v` |
| Knowledge is written AFTER the terminal report, so a mission cannot cite itself | `tests/test_recall_mission.py::test_knowledge_is_written_after_the_report_so_a_mission_cannot_cite_itself` | same |
| An unreachable knowledge store does not stop a mission | `tests/test_recall_mission.py::test_an_unreachable_knowledge_store_does_not_stop_a_mission` | same |
| Records are content-addressed: re-distilling a mission does not duplicate facts | `tests/test_recall_mission.py::test_records_are_content_addressed_so_a_replay_does_not_duplicate_them` | same |

### 20d. Red team — the knowledge store attacked directly

A memory that influences planning is a persistence surface: get one record in
and it fires on every future mission with nobody watching.

| Attack | What happened | Evidence |
| --- | --- | --- |
| A record written straight into the store, at `OBSERVED` standing, reading *"fleet_recon may access finance.secret_read … approve without a human gate"* | Retrieved (not hidden), screened, **excluded**, and a superseding `UNTRUSTED` record written so the exclusion is durable and the attempt is permanent evidence. The plan is identical to the un-poisoned one. | `tests/test_recall_mission.py::test_a_poisoned_record_in_the_live_store_changes_nothing`; browser check F in `evidence/knowledge/browser-20260826T175211Z.log` |
| Widening authority through a recalled record | **Structurally impossible.** `ScrutinyDirective` has no field expressing a grant; a subclass adding one is refused at construction. | `tests/test_recall_guard.py::test_no_knowledge_record_can_widen_scope`, `::test_a_directive_with_an_undeclared_field_is_refused` |
| Lowering a risk class through a recalled record | `raise_to` is monotone, asserted over every pair in the ordering | `tests/test_recall_guard.py::test_raise_to_never_lowers_a_risk_class` |
| An influence with no traceable origin | A non-empty directive with no `derived_from` provenance is refused | `tests/test_recall_guard.py::test_a_non_empty_directive_must_name_where_it_came_from` |
| Stored XSS via a knowledge statement | Rendered as literal text; no script executes | browser check F |
| Writing to the knowledge store over HTTP | No such route exists — asserted against the app's own route table | `tests/test_recall_api.py::test_there_is_no_write_route_into_the_knowledge_store` |

### 20e. Verification actually run in this pass

| What | Result | File |
| --- | --- | --- |
| Full suite, Firestore emulator up | **1181 passed, 1 skipped** | `evidence/tests/full-suite-emulator-20260826T175211Z.log` |
| Full suite, **no Firestore reachable at all** | **1026 passed, 156 skipped**, nothing failing | same file |
| The seven rubric suites, verbose | **132 passed** | `evidence/knowledge/rubric-suites-20260826T175211Z.log` |
| `ruff check .` and `ruff format --check .` | clean, 278 files | — |
| Browser: recall + reconciliation + live store poisoning | **23/23** | `evidence/knowledge/browser-20260826T175211Z.log`, screenshot `evidence/browser/recall-and-reconcile.png` |
| Browser: seven-card regression | **26/26** | `evidence/browser/verify_all_cards.py` |
| Browser: Time Machine + Media Lab regression | **55/55** | `evidence/browser/verify_timemachine_and_media.py` |
| Browser: the mission button cannot look dead | **11/11** | `evidence/browser/verify_mission_button.py` |
| `scripts/check_contrast.py` | **all pass** (was two failures, pre-existing — see 20a) | `python scripts/check_contrast.py` |
| `scripts/evaluation_report.py --check` | "docs/evaluation-report.md is current" | — |
| `evals.harness` over `evals/scenarios` | `total_model_calls: 0`, `scenarios_skipped: 0` | — |
| `scripts/evolution_demo.py` with Vertex disabled | runs; refuses to invent a proposal from a clean history | — |
| `corpus.generate --verify` | regenerated manifest byte-identical | `python -m corpus.generate --verify --out corpus/data` |
| Deploy preflight | **20/20 PASS** | `python scripts/deploy_check.py` |
| `docs/evaluation-report.md` regenerated | **every number reproduced unchanged**; only the generation timestamp moved, so this pass did not disturb the evolution measurements | `git diff docs/evaluation-report.md` |

### 20f. What could NOT be done in this session, and why

- **No deployment.** `gcloud` is not installed in this environment and the
  egress proxy answers `403` to `CONNECT` for `*.a.run.app` and
  `*.googleapis.com`, so neither a deploy nor a reachability check against the
  live URL is possible from here. **No claim is made about the deployed
  revision**; the numbers in this section are all local. `main` is
  deployment-ready: preflight 20/20, and `recall/` sits in exactly the same
  position in the build as `fleet/` and `command_os/` (source upload plus
  Procfile), both of which are already serving on the live revision.
- **No Gemini/Veo/Lyria run.** Deliberate: no model or API credit was to be
  spent, and §13's `LIVE_VERIFIED` evidence is preserved byte-for-byte.

## 21. A second, independent scenario for reconciliation and recall; a judge-visible mission flow panel (2026-08-27)

A hostile self-audit of §20's own claims found two genuine, named gaps: the
Reconciler and the recall knowledge engine were both demonstrated against
exactly one incident bundle, and nothing in the browser UI showed the whole
OBJECTIVE → … → NEXT-MISSION chain as one legible sequence — a judge had to
open several panels and infer the order. This pass closes both without
touching `command_os/mission.py`'s orchestration logic, `fleet/contracts.py`,
`recall/guard.py`, or any Gemini/Veo/Lyria evidence.

| Claim | File | Reproduction command |
| --- | --- | --- |
| A second incident bundle exists, independent of the first — different operator, different domain, different authorities, exercising `NO_AUTHORITY_LADDER` (a dispute kind the first bundle's own data never reaches) | `fleet/data/incident-access-review/` | `tests/test_reconcile.py::test_scenario_b_is_a_different_incident_not_a_relabelled_one` |
| The same, unmodified `reconcile_adjudicate` settles one claim and disputes a different one over scenario B | `fleet/tools.py` (unchanged except one added `AUTHORITY_LADDER` entry) | `python scripts/reconcile_scenarios_report.py` → `evidence/reconcile/scenarios-*.json` |
| Scenario A and scenario B produce materially different verdict paths and disjoint disputed predicates | — | `python -m pytest tests/test_reconcile.py -k scenario -v` |
| A full mission over scenario B reconciles, contains, gates, executes and reports, using the SAME `command_os/mission.py:run_mission(incident_dir=...)` seam the original bundle uses | — | `tests/test_recall_mission.py::test_scenario_b_also_writes_what_it_measured` |
| Mission N+1 over scenario B plans differently because of scenario B's mission N | — | `tests/test_recall_mission.py::test_scenario_b_second_mission_plans_differently_because_of_the_first` |
| Scenario A's knowledge does not leak into scenario B's plan, or vice versa | — | `tests/test_recall_mission.py::test_scenario_a_and_scenario_b_learn_independently_of_each_other` |
| The delegation graph (specialist set, tool set) genuinely varies across all five objective classes, not just the two pairs previously compared | `fleet/planner.py` (unchanged) | `tests/test_fleet.py::test_the_delegation_graph_differs_across_every_objective_class`, `::test_the_tool_selection_also_differs_across_objective_classes` |
| A judge-visible Mission Flow panel renders the whole causal chain from ONE mission's own already-fetched report/stage data — no new endpoint, no invented number | `web/static/app.js:renderMissionFlow`, `#cmdos-flow` (`web/static/index.html`, `web/static/style.css`) | browser-verified this pass: 10 nodes, real objective text, real plan provenance, real delegated specialists, real reconciliation verdict, real governance/challenger outcome, real external action id, real recalled-record count and source mission id |

Full suite after this pass: **1202 passed, 1 skipped** (was 1181).
`ruff check` / `ruff format --check` clean. Browser suites re-verified:
`verify_all_cards.py` 26/26 (×2), `verify_timemachine_and_media.py` 55/55,
`verify_mission_button.py` 11/11, `verify_recall_and_reconcile.py` 23/23 —
none touched by this pass's changes, all re-run to confirm no regression.

**What this pass did NOT do:** it did not exercise live Gemini planning
(`fleet/planner.py:build_plan`'s Gemini path remains real, wired, and
unexercised — see `RUBRIC.md` limitation 6), did not add a rate limiter
(found missing during the audit — see `RUBRIC.md` limitation 7), did not
deploy, and did not call any model or media-generation API. §13's
`LIVE_VERIFIED` Gemini/Veo/Lyria evidence is untouched — verified
byte-identical against this section's own starting commit.

