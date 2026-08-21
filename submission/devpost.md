# Devpost submission — UNWIND

Every field below is drafted ready to paste. Placeholders are marked
`⟨FILL⟩` and there are exactly three of them, all URLs that do not exist yet.

**Rule applied throughout: no number appears here that was not produced by a
committed script in the repository.** Where something is unmeasured, this text
says so rather than omitting it.

---

## Project name

```
UNWIND — Consequence Clearing
```

## Tagline (one line)

```
When a fact turns out false, every decision that rested on it raises its hand — and the system computes what must be un-sent, un-paid, or apologised for.
```

## Category / track

```
Fortified Enterprise Fleet
```

---

## Description

### The problem

Every decision an organisation makes rests on specific claims about the world: a
supplier will ship in 11 days, a tariff rate is 8%, a clause means X. Those
claims expire. When one changes, nothing in the enterprise points backwards from
the claim to the decisions built on it — the dependency edge was never recorded.
So correction propagates socially: someone remembers, sends an email, hopes.

The result is a permanent, invisible population of decisions that are already
wrong and still operating. The ones that already escaped into the world — sent,
signed, shipped, paid — are the expensive ones.

Premises do not fail because the model reasoned badly. They fail because the
world changed after the reasoning was correct.

### What it does

UNWIND records the dependency edge, watches the claim, and when the claim dies,
walks backwards.

A supplier lead time moves from 11 days to 20. The reverse index finds **2,594
dependent decisions**. The system reduces them to the **78** that actually need a
human:

- **1,468** immaterial — the buffer absorbed the shock
- **874** already closed out — the world moving cannot hurt a delivery that
  completed in March
- **174** handed to judgement — the tier is allowed to say "I cannot decide this"
- **78** material — of which **48 already escaped** to a counterparty

Each survivor is triaged for reversibility and converted into a **correction
obligation**: a named counterparty, the actions still reversible, the exposure
that is not — stated as a range with its assumptions — and a named human who
must sign it. That last step is the difference between this and a lineage tool.

### Features

- **Reverse-index consequence traversal** — the edge nobody records, recorded.
- **The arithmetic cull** — 2,594 → 78 with **zero model calls**. The blast
  radius is a graph traversal; materiality is subtraction.
- **Refusal before traversal** — a deterministic authority gate compares a
  source's authority to a claim's scope and refuses forged retractions at
  **radius 0**, with a closed-vocabulary reason code, before a single edge is
  walked.
- **A four-regime deterministic router** — materiality × escapement maps to
  exactly one of four regimes as a total function. Only one cell is an alert.
  The core novelty cannot hallucinate.
- **A repair court** — commitment owners argue for their own commitments; a
  neutral arbiter with no stake rules. Principal separation is enforced in code:
  an arbiter that shares a principal with any owner, assessor or re-deriver
  raises.
- **A bounded protocol** — four phases in a fixed tuple, no loop, no back-edge.
  A runaway hearing is not a monitored risk; it is a shape the code cannot take.
- **Correction obligations** — the product's actual output, routed to a human
  signatory. The system may request approval and cannot grant it.
- **An honesty apparatus** — the interface publishes the system's own worst
  extraction class, on screen, during the demo.
- **WARRANT (Card 0)** — a deterministic, decaying, capability-scoped
  authority ledger. An agent's delegated act is spent atomically, inside a
  single Firestore transaction, against a balance minted only from a
  human-concurrence record plus an independent-family countersign.
  Cold-start agents refuse `WARRANT_INSUFFICIENT` by construction — there
  is no code path from "insufficient" to "proceed anyway."
- **CONTROL TOWER (Card 2)** — an executable agent registry that drives ADK
  2's dynamic-composition pattern (flip one registry field, the actual
  workflow graph object changes), a deterministic-router Gateway with a
  `WORKER_FAULT` supervisor branch, an append-only causal decision memory
  (not a vector store — "what happened because of X" is a graph walk over
  an explicit parent edge), and a durable runtime proven across a genuine
  process restart.
- **COUNTERSIGN (Card 3)** — Gemma, a genuinely different model family,
  verifies a case's material as a single-turn ADK 2 `AgentTool` before any
  warrant mints. A collusion guard rejects a countersign whose family or
  principal matches the judging side. Disagreement freezes minting for that
  case, permanently.

### Technologies

- **Google ADK 2** (`google-adk==2.6.3`) — six constructs, all verified
  against the actual code by a committed script
  (`scripts/verify_adk_mapping.sh`, 10/10 pass): `Workflow`+`FunctionNode`
  (cascade graph, `agents/cascade/workflow.py`); a deterministic router
  (Gateway reason codes, `tower/gateway.py`); a second `FunctionNode` for
  the atomic warrant SPEND-or-refuse (`tower/gateway.py:476`); the dynamic
  pattern (registry → coordinator, `tower/registry.py`); a single-turn
  `AgentTool` (Countersign/Gemma, `countersign/agent.py`); and a durable
  `LongRunningFunctionTool` (case pause/resume, `tower/runtime.py`).
- **Gemini via Vertex AI** (`gemini-3.5-flash-lite`, `gemini-3.6-flash`, both
  GA) — the *second pass* only, on what a deterministic parser cannot read.
- **Gemma via Vertex AI** — the independent-family verifier gating warrant
  mints (Card 3). Live wiring verified this session (real Vertex round-trip,
  real `404` — the project lacks Model Garden access to
  `gemma-3-27b-it`; full escalation in `countersign/DESIGN.md`). The
  mechanism is proven with a labelled scripted simulator over all 41 eval
  scenarios: **75.6% agreement (31/41)**. **Veo and Lyria were evaluated
  and cut** for failing the same five-point necessity test Gemma passed —
  a model added for the sake of breadth is a model the architecture does
  not need.
- **Cloud Run** — the deployed service, serving the API and the UI from one
  origin. A cascade is bursty work that should scale to zero between retractions.
- **Firestore** — document-shaped decisions with a subcollection reverse index,
  per-cascade node records, durable idempotency keys, and a local emulator so the
  deterministic tier needs no cloud account.
- **Pub/Sub** — the cascade is a fan-out from one dead claim to thousands of
  independent re-derivations. Every consumer is wrapped in an idempotency guard,
  because raising the same correction obligation twice means apologising to a
  real customer twice.
- **Cloud Trace / OpenTelemetry** — every span carries a tier attribute, so a
  model call that leaked into a supposedly model-free cascade shows up in a trace
  instead of in the bill.
- **Python 3.12**, FastAPI, canvas.

Four Google Cloud services, each justified in one sentence. Everything else is
deliberately **NOT USED** — the full list, with a one-sentence reason for each
exclusion, is in `ARCHITECTURE.md`. **Veo and Lyria were evaluated and cut** for
failing a five-point necessity test. A model added to a submission for the sake
of breadth is a model the architecture does not need.

### Data sources

**The corpus is synthetic and written by a single author.** This is stated
plainly rather than buried: one scenario built completely — a supplier lead-time
premise feeding quotes, purchase orders, an ad flight and customer promises
across six months. 4,206 conclusions, 1,146 claims, 10,744 reverse-index edges.

`corpus/README.md` documents the generation model, every assumption it rests on,
and every place the measured result diverges from the original specification.
The corpus is byte-reproducible from its seed and CI fails if it drifts.

What this means for the results: the die-back is **computed** from the corpus,
not stipulated — `tests/test_corpus.py` recomputes it independently and asserts
the committed stats agree. But the artifacts and the extraction lexicon were
written by the same author, so extraction recall on this corpus is **not** a
claim about production supplier email.

### Findings — measured only

| | |
| --- | --- |
| Tests | **369 passed** with the Firestore emulator running · **325 passed, 44 skipped** without |
| Eval scenarios | **41 passed**, 5 classes, **0 model calls** |
| False-retraction rate | **0.0** |
| Blast radius → survivors | **2,594 → 78** |
| Die-back | **95.165%** |
| Extraction recall, parser only | **81.8%** (36/44 gold claims) |
| Extraction recall, parser + Gemini | **100.0%** (44/44) |
| Delta | **+18.2 percentage points** |
| Worst extraction class | `temporal:absolute-duration`, **66.7%** |
| Interface | **60 fps median** at 4,206 nodes, both idle and under a scripted pan; on-screen counter asserted equal to the cascade's own count (**78 = 78**) |
| Warrant re-derivation | **4/4 balances bit-equal** to a fresh fold of the ledger (`scripts/rederive_warrant.py`) |
| Countersign agreement rate | **75.6% (31/41 scenarios), SIMULATED** — live Gemma attempted, blocked by a real `404` |
| ADK 2 construct mapping | **10/10 PASS** — every construct this page claims, verified present at its cited `file:line` |
| Deployment verification, all four cards | **5/5 PASS**, exit 0, against the live service, re-verified 2026-08-17 after redeploying Cards 0–3 |
| Deploy preflight | **20/20 PASS** |

**How to read the 100% honestly: the model's denominator is 8, not 44.** The
parser missed 8 claims; Gemini was shown those 8 and returned 8 correct values.
The 100% is a property of the *combined pipeline over 44 gold claims* — it is
**not** a claim that the model extracts perfectly. The four classes where the
parser was already at 100% show a delta of exactly **zero**, because nothing in
them was ever sent to a model. That is the second-pass architecture measured
rather than argued.

### What is not built, and what is unmeasured

- **T2 judgement quality is unmeasured.** The live run attempted 60 nodes and
  resolved **0**, with **0 exceptions**. This is a *non-test, not a failure*: all
  174 queue nodes carry no numeric term, and the assessor returns UNRESOLVED
  before the model's answer is consulted. The corpus fixed the outcome, not
  Gemini. A fair fixture was designed and **deliberately not built**, because the
  clause text and the scoring key would be written by the same author — which
  makes a judgement benchmark a mirror rather than a measurement.
- **Compensation-path synthesis** refuses on purpose. `synthesise()` raises
  rather than emitting a reverse path that looks executable.
- **Model Armor** was never configured, so it has never blocked anything. The
  extraction quarantine is the real defence and does not depend on it.
- **Firestore rules and composite indexes** are written and deployed —
  verified live against a real GCP project
  (`evidence/firestore/deploy-2026-08-15.md`, `deploy-2026-08-17.md`).
- **All four cards are live on the deployed Cloud Run URL**, redeployed
  2026-08-17. Redeploying itself surfaced a real gap — a Firestore
  composite index the Memory Bank needed that predated Cards 0/2/3 and had
  never been added — fixed and documented rather than hidden
  (`evidence/firestore/deploy-2026-08-17.md`). The full system also still
  runs locally with `make emulator && make dev`, no credentials needed.
- **Live Gemma verification** is blocked by a Model Garden access gap —
  wiring proven (real auth, real API round-trip), the model call itself
  returns a real `404`. `countersign/DESIGN.md` has the full escalation.
- **Warrant's Goodhart and Sybil risks** are named, not solved —
  `warrant/FAILURE_MODES.md`.

### What I learned

That the honest version of a number is almost always more persuasive than the
flattering one. Publishing the worst extraction class on screen, and calling a
zero-resolution run a non-test rather than quietly dropping it, is what makes the
+18.2 pp worth believing. The measurement that changed the architecture most was
discovering that the four classes the parser already handled showed a delta of
exactly zero — which proved the second-pass ordering was right, and proved it
with a null result rather than a headline.

Also: Cloud Run reserves the literal path `/healthz` for its own platform health
checking and intercepts public requests to it before they reach user code. That
cost one failed deployment verification and is now written down in the repo.

---

## Built with

```
python, google-adk, gemini, gemma, vertex-ai, cloud-run, firestore, pub-sub, cloud-trace, opentelemetry, fastapi, javascript, canvas
```

---

## Links

| Field | Value |
| --- | --- |
| **Repository (public)** | `https://github.com/akashbichukale111/unwind` |
| **Hosted / try it out** | `https://unwind-hgeodtazqq-uc.a.run.app` |
| **Demo video** | `⟨FILL — YouTube URL, public, English, ≤4:00⟩` |
| **Architecture diagram** | `https://github.com/akashbichukale111/unwind/blob/main/assets/architecture.png` — `⟨FILL — confirm the branch name in the URL after any merge⟩` |
| **Spin-up instructions** | `README.md` § Quickstart |

⟨FILL⟩ #3: if the Devpost form requires a separate "team members" or
"submitter" field, complete it from the entrant's own account details. Nothing
in this repository supplies that.

---

## Pre-submit checklist

Superseded by the dedicated, exact-command checklist:
[`submission/CHECKLIST.md`](CHECKLIST.md). Do not check items off here —
that file is the one source of truth for submission readiness.
