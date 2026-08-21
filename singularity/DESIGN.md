# singularity/ — DESIGN.md (Card 5, the sixth card: Singularity-Mesh)

## What this is

Singularity-Mesh is Card 6 of the UNWIND instrument: a zero-trust
operating-architecture framework for an autonomous agent fleet. It is a
**broader architecture concept** than Hyperion-Zero (Card 4/5, the immune
control layer over Card 2's Gateway) and does not merge with it — see
"Relationship with Hyperion-Zero" below. Its UI card and API surface
(`/api/singularity`, `/api/singularity/genome/probe`,
`/api/singularity/behavior/probe`) are entirely independent of Hyperion's
(`/api/hyperion`, `/api/hyperion/probe`) and of Card 2's Gateway
(`tower/gateway.py`), which this package never imports or calls.

## What is actually built (LIVE)

- **Capability Genome** (`singularity/genome.py:compute_genome`) — a real,
  deterministic, pure-function negotiation of an agent's task-bound
  permissions from (role, task, risk class, requested actions). Every call
  recomputes from zero; there is no stored, standing grant. Three ordered
  narrowing stages (role ceiling → denylist → risk-recalculated safe
  subset), each fully explained in `reason`. Zero model calls —
  `tests/test_singularity_zero_model.py` proves it the same way
  `tests/test_hyperion_zero_model.py` proves it for `hyperion/risk.py`.
- **Behavioral DNA** (`singularity/behavior.py:detect_drift`) — a real,
  deterministic comparison of one observation against a stated per-role
  baseline envelope (`BASELINES`), folding independently-named signals
  (tool-call volume, unfamiliar dataset, latency, export request, secret
  access) into a 0–100 drift score and a four-band verdict
  (NORMAL/ELEVATED/DRIFT/CRITICAL). Also zero model calls.
- **Mesh event log** (`singularity/mesh_memory.py`) — a real, durable,
  append-only Firestore collection (`singularity_mesh_events`) logging
  every genome negotiation and every drift assessment, aggregated into the
  card's real summary counts (`aggregate_mesh_summary`). Same
  append-only-enforced discipline as `hyperion/immune_memory.py`.
- Two demo probes (`POST /api/singularity/genome/probe`,
  `POST /api/singularity/behavior/probe`) that each drive one real,
  in-repository scenario through the engine above end to end and log a
  genuine event — the same "one real, on-camera event" discipline
  `POST /api/hyperion/probe` and `POST /api/instrument/earn` already use.

## What is reference/architecture content, not a running system

Everything else the specification describes — Sentinel Shield and
Orchestrator as running processes, the five-worker fleet actually
executing tasks, Cloud Run sandboxes, the MCP layer, the Knowledge
Catalog, Model Armor, the Agent Gateway, per-agent IAM service accounts,
durable agent memory/checkpointing, the self-healing recovery controller,
and live agent-to-agent messaging — **is not implemented in this
repository**. `singularity/fleet.py` and `singularity/lifecycle.py` are
static Python data describing this intended architecture for the UI to
render; nothing in either module spawns a process, calls a model, executes
a task, or talks to any Google Cloud service. The UI labels every one of
these sections `ARCHITECTURE` or `DESIGN`, never `LIVE`, driven by the
single `IMPLEMENTATION_STATUS` table in `singularity/lifecycle.py` so the
badges and this document can never disagree.

Concretely, none of the following exist anywhere in this repository:

| Concept | Status | Note |
| --- | --- | --- |
| Sentinel Shield as a running input-classification process | **NOT BUILT** | No request-classification model or service exists; `SENTINEL` in `singularity/fleet.py` is a topology description only. |
| Orchestrator as a running planner/delegator | **NOT BUILT** | No task-planning loop exists in this package. |
| Worker Fleet actually executing tasks | **NOT BUILT** | The five workers in `singularity/fleet.py` are reference rows; nothing dispatches or runs a task against them. |
| Cloud Run Sandboxes | **NOT BUILT** | No sandboxed execution environment exists anywhere in this repository (the same "not built" finding `hyperion/DESIGN.md` already records for its own shadow-sandbox concept). |
| MCP layer (client/server/tool dispatch) | **NOT BUILT** | No MCP server, client, or tool dispatcher exists (same finding as `hyperion/DESIGN.md`'s MCP row). |
| Knowledge Catalog | **NOT BUILT** | No governed enterprise data-discovery service exists; `KNOWLEDGE_CATALOG_SOURCES` is a static example list for the UI. |
| Model Armor | **NOT BUILT** | No Model Armor API is called anywhere in this repository. |
| Agent Gateway (auth/rate-limit/routing front door) | **NOT BUILT** | `AGENT_GATEWAY_RESPONSIBILITIES` documents the intended responsibilities; no such gateway process exists. |
| Per-agent IAM service accounts | **NOT BUILT** | No new Google Cloud IAM role or service account was created; `IAM_IDENTITIES` is illustrative, not provisioned. |
| Durable agent memory / checkpointing | **NOT BUILT** | No checkpoint or task-state persistence mechanism exists in this package (`tower/runtime.py`'s `CaseRecord` is a separate, Card-2 concept this package does not extend). |
| Self-healing recovery controller | **NOT BUILT** | No process restarts, no automated credential rotation, no fresh-sandbox provisioning exists. `RECOVERY_FLOW` marks exactly which of its ten steps are LIVE (DETECT, BLOCK) versus ARCHITECTURE (the remaining eight). |
| Live agent-to-agent messaging | **NOT BUILT** | No inter-process message bus exists between the conceptual Sentinel/Orchestrator/Worker roles. |

## Deterministic boundary

`singularity/genome.py` and `singularity/behavior.py` import no framework
and no model client — `tests/test_singularity_zero_model.py` walks both
against the same broad forbidden-import set
`tests/test_hyperion_zero_model.py` uses for `hyperion/risk.py`.

## Relationship with Hyperion-Zero

Hyperion-Zero (Card 4/5) is the agent-runtime immune/security control layer
over Card 2's real Gateway (`tower.gateway.evaluate_gateway`) — it scores
and logs decisions that already happened there. Singularity-Mesh is a
broader, independent framework: an autonomous-agent-fleet architecture and
governed-autonomy concept, of which Capability Genome and Behavioral DNA
are this card's own new, live decision engines. The two systems are
conceptually complementary (both implement a form of "agent immunity") but
share no code path, no collection, and no API route — Hyperion's UI card
and endpoints are untouched by this change.
