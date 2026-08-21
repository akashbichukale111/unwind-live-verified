# Security posture — what is enforced, and what is not

This document exists because the previous version of this system had an
excellent security *design* and an absent security *deployment*, and nothing
in the repository said so. A hostile review found that
`POST /api/command-os/mission/{id}/gate?decision=approve` was reachable with
no credential, that the resulting decision-memory record named a module
constant (`"human::mission_operator"`) as the approving human, and that this
record satisfied one of the two preconditions `warrant.ledger.mint` requires.
An anonymous HTTP request minted earned authority and left a permanent,
authentic-looking audit entry for a person who was never present.

Everything below is either **enforced with a test named here**, or listed
under **Known gaps** with no test claiming otherwise.

---

## 1. Authentication and authorization

| Property | Enforced by | Test |
| --- | --- | --- |
| No mutating endpoint accepts an anonymous caller | `services/api/security.py:require_principal` | `test_api_auth.py::test_every_mutating_route_requires_a_principal` (walks the route table — a new unprotected POST is a test failure, not a review miss) |
| The Human Override Gate requires a **human** principal | `lib/auth.py:require_human` | `test_api_auth.py::test_service_token_cannot_approve_at_the_gate` (403) |
| The recorded approver is the **authenticated** caller | `command_os/mission.py:_phase_gate` reads `ctx["principal"]`, which only `services/api/main.py` populates, from `lib.auth.authenticate` | `test_api_auth.py::test_authenticated_principal_is_the_one_recorded` |
| The principal cannot be supplied as a request parameter | the gate route has no such parameter | `test_adversarial.py::test_attack_06_forged_principal_in_the_request_body` |
| `authenticate` has no anonymous fallback branch | structural | `test_auth.py::test_authenticate_has_no_fallback_return_path` |
| A bad credential 401s rather than downgrading to the dev identity | `lib/auth.py` ordering | `test_auth.py::test_wrong_bearer_token_is_refused_not_downgraded` |
| The dev identity is refused in production | `UNWIND_ENV=production` branch | `test_auth.py::test_dev_principal_is_refused_in_production` |
| The IAP header is ignored unless the deployment declares it is behind IAP | `UNWIND_TRUST_IAP_HEADER` | `test_auth.py::test_iap_header_is_ignored_unless_the_deployment_says_it_is_behind_iap` |
| `run_mission` cannot be called without a principal | keyword-only, no default | `test_command_os_mission.py::test_run_mission_requires_a_principal_with_no_default` |
| Resuming at the gate requires an authenticated principal | `resume_mission` raises | `test_command_os_checkpoint.py::test_resume_with_a_decision_but_no_principal_raises` |

**Configuration.** Exactly three resolvers, tried in order, all explicit:

```bash
# 1. Behind IAP (preferred in production)
UNWIND_TRUST_IAP_HEADER=1

# 2. Bearer tokens: token:principal pairs, comma separated
UNWIND_OPERATOR_TOKENS="tok-a:kim@ops.example,tok-b:service::ci-runner"

# 3. Local development only — refused when UNWIND_ENV=production
UNWIND_DEV_PRINCIPAL="you@example.com"
```

`GET /api/command-os/status` reports which of these this process will accept,
including `anonymous_mutation_possible`, and never reports a token.

---

## 2. Simulation isolation

Two separate questions, deliberately not one flag (`lib/simulation.py`):

- `simulated_countersign` — run the deterministic zero-model challenger
  instead of calling Gemma. A legitimate operating mode.
- `simulated_mint_permitted` — may a countersign produced that way satisfy
  `warrant.ledger.mint`'s independent-verification precondition. **An
  authority question.**

Under `UNWIND_ENV=production` the second is `False`, always, and the clamp is
applied last so no environment variable and no explicit argument can re-enable
it (`test_adversarial.py::test_attack_09_simulation_contamination_in_production`).

`run_mission` used to open with `os.environ.setdefault("UNWIND_COUNTERSIGN_SIMULATED", "1")`
— a request handler flipping process-wide state, which on Cloud Run
permanently switched the whole container into simulation mode. No module
under `command_os/` or `fleet/` writes to `os.environ` any more, and that is
asserted structurally by
`test_adversarial.py::test_attack_10_the_application_cannot_set_its_own_simulation_flag`.

---

## 3. The model cannot widen its own authority

A language model authors the plan. It cannot price an action, narrow a
genome, spend warrant, or overturn a refusal.

`fleet/planner.py:validate_plan` runs between the model and everything else:

- an unregistered **role** → the step is dropped;
- an unknown **tool**, or one belonging to another role → dropped;
- an unparseable **action kind** → **the whole plan is rejected**, because an
  action nobody costed must never execute at a default price;
- an action kind the role may not propose → clamped to `ANALYZE`;
- **requested scope is intersected with the registry's granted scope**;
- plan length is capped.

Every narrowing is named in `MissionPlan.clamps` and surfaces in the API and
the UI — a silently trimmed plan is a plan whose provenance is a lie.
Attacks 1–4 in `tests/test_adversarial.py` cover this.

The registry is the second line: `fleet_recon` holds no write scope, so a plan
that asks it to write is refused `SCOPE_EXCEEDED` by the **unmodified**
`tower/gateway.py` (`test_fleet.py::test_recon_cannot_write_even_if_asked_to`),
and `fleet_remediation` holds no secret scope even though it can write.

---

## 4. The external effect boundary

`command_os/external.py:execute_action` is the only function in this
repository that can change anything outside the process. It requires an
`ExternalActionAuthorization` carrying the Gateway decision, the priced cost,
the human principal and the challenger verdict; it refuses `None`, refuses a
non-`ALLOWED` decision, refuses a challenger disagreement, and refuses an
authorization bound to a different idempotency key. It is idempotent (a replay
returns the stored record and writes nothing — asserted by **counting lines in
the sandbox file**, not by trusting a flag) and reversible by compensation
rather than deletion.

---

## 5. Red team

`tests/test_adversarial.py` runs 20 attacks with asserted defences:

prompt injection · scope escalation · tool poisoning · cross-role tool
borrowing · anonymous approval · forged principal · service-token escalation ·
resume without a principal · simulation contamination · self-set simulation
flag · memory poisoning via a same-family countersign · minting without human
concurrence · cold-start authority · burn visibility · worker loop ·
hallucinated tool output · unauthorized external action · replay/double-spend ·
unavailable model read as agreement · a challenger talked into agreeing.

Reproduce: `make redteam`. Latest run: `evidence/redteam/`.

---

## 6. Known gaps — not defended, and said so

These are real. None of them has a test claiming otherwise, and
`GET /api/command-os/status` reports each as `DESIGNED`.

| Gap | Impact | Why it is not closed here |
| --- | --- | --- |
| **No multi-tenancy.** There is no `tenant_id` on the registry, ledger, memory bank or mission record. Any authenticated principal can read any mission. | A shared deployment leaks missions across tenants. | Single-tenant demo. Pinned by `test_adversarial.py::test_known_gap_cross_tenant_isolation_is_not_implemented`, which starts failing the moment tenancy is added, prompting a real cross-tenant test. |
| **Bearer tokens live in an environment variable**, not Secret Manager, and are never rotated or expired. | A leaked token is valid until the service is redeployed. | `lib/auth.py` is a principal resolver, not an identity provider. IAP is the intended production path. |
| **Rate limiting is per process.** `services/api/security.py` uses an in-memory bucket. | Across several Cloud Run instances the effective limit is N× the configured one. | A real deployment wants Cloud Armor or an API gateway in front. Stated at the call site too. |
| **No stage timeout or circuit breaker.** Tools get a bounded retry (`MAX_TOOL_ATTEMPTS`), no backoff and no jitter. | A networked tool backend could hang a mission. | Every tool in `fleet/tools.py` today is local and deterministic; a networked backend would need both, and does not exist yet. |
| **The human gate has no expiry.** A mission left `AWAITING_HUMAN` waits forever. | Stalled missions accumulate. | No escalation policy has been chosen; inventing one would be a guess. |
| **Firestore rules do not cover the new collections.** `infra/firestore.rules` predates `command_os_missions`, `command_os_external_actions` and the warrant/memory collections; the catch-all denies all *client* access, so this is fail-closed, but it is not explicit. | Nothing is exposed — server-side SDK access bypasses rules — but the rules file no longer documents the data model. | Worth an explicit block per collection; not done in this pass. |
| **Live Vertex AI has not been exercised in this pass.** No Google Cloud credentials were available. | The Gemini planning path and the Gemma challenger path are real code that has not run against the real service in this session. | Reported as `CONFIGURED_NOT_EXERCISED` by `/api/command-os/status`; the fallbacks are labelled `ZERO_MODEL` and never `GEMINI`. `evidence/adk/live-call-attempt-*.log` shows the real ADK Runner executing, resolving credentials, failing, and reporting `UNAVAILABLE` rather than `AGREE`. |

---

## 7. Threat model summary

**Defended:** an anonymous or wrongly-credentialled caller; a compromised or
prompt-injected planner; an agent requesting scope it does not hold; an agent
with insufficient earned authority; a worker that loops or returns garbage; a
replayed request; a same-family or unavailable verifier; simulated evidence in
production.

**Not defended:** a compromised runtime service account (it holds
`roles/datastore.user` and can write the ledger directly); a leaked operator
token before rotation; another tenant's data in a shared deployment, which has
no meaning here because tenancy does not exist.

**Structurally impossible rather than merely prevented:** a model call in the
authority path. `tests/test_warrant_zero_model.py` and
`tests/test_tower_zero_model.py` walk the import graph, and
`tower/gateway.py`'s warrant check is an ADK `FunctionNode`, a node type the
framework guarantees contains no model.
