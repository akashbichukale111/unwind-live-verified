# UNWIND — architecture

One justifying sentence per component. A component without one gets deleted.

## The shape of the problem, in one line

A blast radius is a **graph traversal** (thousands of nodes, no model), the
survivors are an **arithmetic filter** (dozens of nodes, no model), and only what
survives both is worth a **model call**. Every choice below follows from that
ordering.

## Tiers

| Tier | What runs there | Model? | Why it is a tier and not a convention |
| --- | --- | --- | --- |
| T0 | Blast-radius traversal over the reverse index | No | A cascade over 2,594 dependents must not cost 2,594 model calls, and must still run when Vertex is down. |
| T1 | Arithmetic materiality on numeric/temporal claims | No | `shock > slack` is subtraction; asking a model to do subtraction is how you get a confidently wrong unwind. |
| T2 | Ambiguous materiality, arbitration, drafting | Yes | Judgement, argument and prose are the only places a model earns its latency. |

`UNWIND_VERTEX_DISABLED=1` closes the single door to a model (`lib/vertex.py`),
so "T0/T1 survive a Vertex outage" is testable rather than asserted. The full
cascade runs with it set, **on every CI push**, and the job fails if a single
model call is made.

## Components

### `lib/config.py`
Holds the only two Gemini model strings and the only pinned region in the
repository, so a third model can never enter the system by accident (enforced by
`tests/test_config_singleton.py`, which greps the tree).

### `lib/schema.py`
Types every collection before any logic exists, because Temporal Truth
(`valid_from` / `invalidated_at` / `invalidation_reason`) and retraction
authority (`authority_scope`) are impossible to retrofit once thousands of
documents are written without them.

### `lib/firestore.py`
Gives the reverse index exactly one implementation to be correct in, and makes
the emulator a first-class target so the deterministic tier runs with no GCP
account.

### `lib/pubsub.py`
Carries the cascade fan-out, and wraps every consumer in `IdempotentConsumer`
because Pub/Sub is at-least-once and raising the same correction obligation
twice means apologising to a real customer twice.

### `lib/vertex.py`
Concentrates model access into one constructible object so the outage guarantee
has a single door to close — and pins the backend to Vertex AI, without which
ADK silently falls through to the developer Gemini API.

### `lib/telemetry.py`
Stamps `unwind.tier` on every span, so a T2 model call that leaked into a
supposedly model-free cascade shows up in a trace instead of in the bill.

### `agents/smoke/`
Proves ADK 2 + Vertex + `lib.config` are wired to each other, and is marked
delete-ready so it cannot quietly become load-bearing.

### `services/api/`
Serves the blast radius over SSE because a radius is discovered incrementally and
an operator needs to watch it fill in rather than wait for a total.

### `spine/` — the deterministic package boundary
Holds every T0/T1 step as plain functions with no ADK and no model client, so
"T0 and T1 survive a Vertex outage" is enforced by an import graph a test can
walk rather than by a convention someone remembers.

### `spine/authority.py`
Compares a source's authority prefixes to a claim's authority scope before a
single edge is walked, because a forged retraction is a weapon and a gate that
can be argued with is not a gate.

### `spine/traversal.py`
Walks the reverse index breadth-first to the transitive closure, keeping each
node's path so a verdict can be explained back to the retracted claim, and
recording cycles instead of silently surviving them.

### `spine/materiality.py`
Decides harm by subtracting a buffer from a shock, and routes contractual and
unparseable premises out to judgement rather than guessing at them.

### `spine/escapement.py`
Reads what already left the building, and defaults to ESCAPED whenever the
record is missing — a wasted check costs one person five minutes, an untold
customer costs the relationship.

### `spine/regimes.py`
Maps materiality × escapement onto exactly one of four regimes as a total
function, so the core novelty of the product is incapable of hallucinating.

### `spine/cartography.py`
Orders the radius by exposure deterministically, because a later tier that can
only afford fifty nodes needs the right fifty and ties must not break on luck.

### `spine/budget.py`
Decides how deep an investigation the radius has earned — and runs *after* the
free tiers, because severity is not knowable until the free work is done.

### `spine/temporal.py`
Closes a claim's validity interval and opens its successor's without destroying
the prior value, because a conclusion is only defensible if you can still see
the number it actually stood on.

### `spine/debt.py`
Scores standing consequence on a normal day, attributing every contribution to a
named premise, so UNWIND has an answer to "what does this show me when nothing
has broken".

### `spine/cascade.py`
Composes the above in the one order that is safe — gate, then propagate, then
traverse, then score, then budget — behind a store protocol that has no method
capable of returning the eval marking scheme.

### `agents/cascade/`
Expresses the cascade as an ADK 2 `Workflow` of `FunctionNode`s whose branch is
chosen by `ctx.route`, which is what makes the four-regime split a routing
decision in the framework rather than a paragraph in a prompt.

### `lib/idempotency.py`
Puts the seen-set in Firestore behind a conditional `create()`, because Cloud Run
instances are replaced without warning and raising the same correction
obligation twice means apologising to a real customer twice.

### `spine/extract.py`
Parses numeric and temporal premises deterministically, because a regex has no
instruction-following surface for an injected instruction to attack, and because
its recall is a number that can be measured rather than asserted.

### `spine/decision.py`
Routes every proposed retraction to exactly one of EXECUTE / ASK_HUMAN / RETRY /
DEFER / REFUSE, in two halves — standing and contest before the traversal,
confidence and corroboration after it, because only the second half needs to
know how big the blast radius is.

### `spine/defence.py`
Sets the evidence bar from what acting would cost — floor rising with blast
radius, a second source required above real exposure — and quarantines
extraction so attacker text cannot name a claim its source has no standing over.

### `spine/gate.py`
Renders what the system understood before it acts, so a misparse arrives as a
question somebody answers rather than as a correction somebody receives.

### `judgment/`
Holds everything that may be wrong: the tier where being wrong is expected, so
every module in it degrades to UNRESOLVED rather than to a guess.

### `judgment/rederive.py`
Recomputes a commitment from premises alone behind a type, a store and a static
check that between them make the original decision unreachable — because a
re-deriver that can see the answer will echo it, and the resulting "nothing
changed" is invisible when wrong.

### `judgment/assessor.py`
Grades the re-derivation as a different principal from the one that produced it,
because marking your own homework makes "nothing changed" the cheapest
self-consistent answer.

### `judgment/reconcile.py`
Decides whether two differently-worded claims are one claim, reversibly and with
a logged record, and refuses to decide at all in the margin where guessing
either fragments the graph or invalidates unrelated commitments.

### `judgment/watch.py`
Arms one dormant watcher per live claim and sweeps for silence — the signal
nobody notices — while being structurally unable to retract on an absence of
information.

### `judgment/coverage.py`
Measures extraction against a labelled corpus and publishes the class it is
worst at, and has no code path that can call an under-covered decision safe.

### `lib/principals.py`
Checks role separation across a whole bench rather than a pair, because ruling
1.10's failure — an arbiter that is also an owner, an assessor or a re-deriver —
turns a multi-agent system into one model talking to itself in different voices.

### `court/team.py`
Composes the repair team at runtime from a radius that did not exist a second
earlier, so team size is a function of what actually broke rather than of a
topology somebody drew in advance.

### `court/owners.py`
Makes each commitment argue its own case as a partisan single-turn agent tool —
the ADK 2 shape that lets the parent fan N of them out in parallel and keep the
floor — while `adjudicate()` raises so a party can never decide its own survival.

### `court/arbiter.py`
Rules as a third principal with no stake by construction, allocating a contested
resource rather than deadlocking on it, and going advisory above a cost
threshold so nothing expensive moves on the system's own authority.

### `court/protocol.py`
Bounds the hearing by SHAPE — four phases in a fixed tuple, no back-edge, no
`while` — so a runaway court is not a risk that is monitored but a program that
cannot be written without deleting a test.

### `settle/irreversibility.py`
Takes the more conservative of what the record claims and what the operation is
known to be, because a connector calling its own countersignature "idempotent"
is exactly the disagreement that would otherwise send an automated unwind at
something already signed.

### `settle/cartography.py`
Determines who holds a wrong belief this organisation put there and has no
capability to tell them, so a mapping bug produces a wrong list a human rejects
instead of a wrong email a customer receives.

### `settle/obligation.py`
Ends the pipeline at a drafted correction naming a counterparty, the actions
still reversible, the exposure that is not — as a range with its assumptions —
and the human who must sign, which is the difference between this and a lineage
tool.

### `settle/broker.py`
Routes an obligation to the person who must sign it and cannot sign it itself,
because an obligation approved by the system that raised it has not been
approved by anybody.

### `settle/compensation.py`
Refuses, loudly and on purpose: a half-built reverse-path synthesiser would emit
paths that look executable to every downstream component that assumes a proposal
was checked.

### `settle/loadrating.py`
Lowers how much future weight a SOURCE carries when its claims are falsified,
and refuses anything carrying agent-trust fields, because an agent can extract
perfectly from a source that lies constantly and merging the two punishes the
wrong party.

### `settle/pipeline.py`
Merges overlapping radii on the commitment before any obligation exists, because
two premises failing in the same week reach many of the same commitments and
raising two obligations against one means apologising to the same customer twice.

### `corpus/`
Is a deliverable, not a fixture: the die-back is **measured** off a stated model
of commercial behaviour, so the demo's central number is computed rather than
stipulated.

### `evals/`
Defines the metrics before any scenario exists, because a metric invented after
seeing results is a metric chosen to flatter them.

### `web/`
Holds the operator surface. `web/static/` is the live UI — canvas, 4,206 nodes,
served by FastAPI from the same origin as the API. The Next.js 15 skeleton
alongside it is **dead code**, retained only because deleting it is a change with
no reviewer; `web/README.md` says so plainly.

### `infra/`
Holds the composite index the reverse-index traversal cannot run without, the
rules that keep every write behind the service identity, and a deploy script that
wraps `adk deploy` rather than hand-rolling a container the framework already
builds.

## Google Cloud services

Four, each justified in one sentence. Nothing else is used.

| Service | One sentence |
| --- | --- |
| **Firestore** | Document-shaped decisions with a subcollection reverse index, per-cascade node records, durable idempotency keys, and a local emulator so the deterministic tier needs no cloud account. |
| **Pub/Sub** | The cascade is a fan-out from one dead claim to thousands of independent re-derivations, which is exactly what a topic is for. |
| **Cloud Run** | `adk deploy cloud_run` is the framework's own path, and a cascade is bursty work that should scale to zero between retractions. |
| **Vertex AI** | The only T2 dependency: ambiguous materiality, the repair court, and drafting the correction that goes to a counterparty. |

Deliberately **NOT USED**: GKE (Cloud Run already runs the container, and
`adk deploy gke` would add a cluster nobody needs), Cloud SQL and Spanner
(the data is documents with a subcollection index, not relations), BigQuery
(2,594 rows per cascade is not an analytics workload), Dataflow (Pub/Sub plus
Cloud Run is the whole pipeline), Redis and Memorystore (Firestore holds the
idempotency keys, and a second datastore is a second thing to be inconsistent).

## ADK 2 features, and what each one is for here

Verified present in `google-adk` 2.6.3 (`google.adk.workflow`, `google.adk.tools`).

| ADK 2 feature | Where UNWIND needs it |
| --- | --- |
| `FunctionNode` | **In use.** The cascade graph is nothing but function nodes — T0 traversal and T1 materiality, no model call. |
| `Workflow` + `Edge` / `DEFAULT_ROUTE` | **In use.** `agents/cascade/workflow.py` branches on `ctx.route`; the regime split is a routing decision, not a prompt. |
| `AgentTool` (agent-as-tool) | **NOT IN USE.** Locked design for Countersign (Card 3), which is not built. The repair court fans N owners out with a `ThreadPoolExecutor` (`court/protocol.py`) — the parallelism is real and `tests/test_court.py` asserts the pleas overlap in wall-clock time, but it is threads, not ADK, and this table will not say otherwise until the code changes. |
| Dynamic node scheduling | **NOT IN USE.** `court/team.py` composes the repair team at runtime from a blast radius that did not exist a second earlier, but it does so in plain Python. The ADK dynamic pattern is locked design for the Card 2 registry → coordinator selection. |
| `LongRunningFunctionTool` | **NOT IN USE.** Locked design for durable pause/resume: a human may sign a correction obligation on Tuesday. |

## The write path

UNWIND's output is **corrections that leave the building** — a re-issued quote, a
compensation, a signed apology. The reverse index, the authority gate and the
traces exist to make that write path safe; they are not the product.

## Framing the demo honestly

The hub radius reaches **170 clause-governed conclusions**, but those rest on
**40 distinct contractual claims** — so the court hears **forty distinct
arguments across 170 conclusions**, not 170 different ones. The replication is
real and it is not disguised: inflating the clause set to make the hearing look
busier would be padding, and an honest large number beats a manufactured one.

Both figures are computed by `corpus/generate.py` into
`corpus/data/stats.json` (`contractual_claims`, `clause_governed_conclusions`).
