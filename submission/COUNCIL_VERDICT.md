# COUNCIL VERDICT — 200-Seat Innovation Council

**Session type:** research and selection. No code was changed. This file is the
only artifact.

**Audited commit:** `e60ba5a` · **Branch:** `claude/unwind-hackathon-foundation-s36wdi`
**Date:** 2026-08-15 · **Deadline:** 31 Aug 2026, 5:00 PM Pacific (16 days)
**Demo-ready gate:** 27 Aug 2026 (12 days)

**Status labels used throughout:** `[VERIFIED]` executed in this session or by a
committed script · `[DESIGNED]` written, never executed · `[PROJECTED]` an
estimate · `[SYNTHETIC]` produced by the corpus generator, not observed in the
world.

**Scoring scale, stated once.** Stage Two: three criteria scored **1–5**,
averaged, max **5.0**. Bonus max **+1.0**. Final max **6.0**. Stage One is
**pass/fail**. No other scale appears in this document, and the council notes as
a defect that `docs/JUDGE.md:157` states a self-score of "75/100" — a scale that
does not exist in this competition.

---

## PART 1 — REPOSITORY FORENSICS `[VERIFIED]`

### 1.1 The headline finding

**Three of the four cards do not exist in the repository.**

| Card | Claimed in the recap | Found in code |
| --- | --- | --- |
| **CARD 0 — WARRANT** | ledger, MINT, SPEND, basis points, EARNED/SYNTHETIC | **Nothing.** `grep -ri warrant` returns only the English verb "warrants" in `spine/budget.py` and one test name. No ledger, no basis points, no provenance enum. |
| **CARD 1 — UNWIND CORE** | reverse-index traversal, 2,594→78, zero model | **Built and frozen.** 261 tests pass. |
| **CARD 2 — CONTROL TOWER** | registry, Gateway, WORKER_FAULT, Memory Bank, durable runtime, Cloud Trace | **Cloud Trace only** (`lib/telemetry.py`). Zero hits for `registry`, `WORKER_FAULT`, `Memory Bank`. A five-state router exists (`spine/decision.py`) but is not a Gateway over workers. |
| **CARD 3 — COUNTERSIGN** | Gemma as single-turn AgentTool | **Nothing.** Zero occurrences of "Gemma" anywhere in the repository. |

This is not a criticism of the plan; it is the schedule. The repository is at the
end of a *different* five-task plan (31 completed tasks), and the four-card
framing is new work that has not started. **Sixteen days remain and Cards 0, 2
and 3 are greenfield.** Every recommendation below follows from that.

### 1.2 Actual ADK 2 usage, with construct and file:line `[VERIFIED]`

Only three files in the entire repository import ADK.

| Construct | Location | Real? |
| --- | --- | --- |
| `Workflow`, `FunctionNode`, `Edge`, `DEFAULT_ROUTE`, `START` | `agents/cascade/workflow.py:30`, nodes at `:152–154`, graph at `:160–172` | **Yes.** The four-regime branch is `ctx.route`, set at `:98`. This is genuine, idiomatic ADK 2. |
| `Agent` (LlmAgent) | `agents/smoke/agent.py:14` | **Yes**, but marked delete-ready. |
| `InMemoryRunner` | `agents/smoke/run.py:12,29` | **Yes**, smoke path only. |
| **`AgentTool`** | **nowhere** | **NO.** |
| **Dynamic node scheduling** | **nowhere** | **NO.** `court/team.py` is plain Python. |
| `LongRunningFunctionTool` | nowhere | Not claimed as in use. Honest. |

### 1.3 ⚠ THE LARGEST DOCUMENTATION/CODE DISAGREEMENT

**The one sentence the project uses to justify needing ADK 2 is not implemented.**

Claimed in four places:

- `README.md:48–52` — "Commitment owners are *single-turn agent tools*… `AgentTool` is what makes the parent the one still holding the gavel."
- `ARCHITECTURE.md:283` — "`AgentTool` (agent-as-tool) | **In use.** … This is the reason the project needs ADK 2."
- `court/owners.py:9–16` — "⚠ OWNERS ARE SINGLE-TURN AGENT TOOLS… THIS IS THE REASON THIS PROJECT NEEDS ADK 2."
- `docs/DEMO.md:34` — **in the spoken demo script**: "Single-turn agent tools let the arbiter fan twelve owners out in parallel and keep the gavel."

What the code does: `court/protocol.py:229` — `with ThreadPoolExecutor(max_workers=len(admitted)) as pool:`. `court/owners.py` imports no ADK at all.

**The parallelism is real and honestly tested** (`tests/test_court.py:237–257`
measures wall-clock overlap and asserts `max_concurrent > 1`). Only the
*attribution to ADK* is false. A judge who greps for `AgentTool` finds one
docstring and zero imports — and `docs/DEMO.md:34` would have the presenter say
it aloud, on camera, in a submission judged partly on Google-technology use.
**This is the single highest-severity item in the repository.**

### 1.4 Stage One status — pass/fail gates

| Requirement | Status | Evidence |
| --- | --- | --- |
| Public repo | **PASS** `[VERIFIED]` | GitHub API: `"visibility":"public"`. Default branch is the working branch, so a clone gets the work. |
| Spin-up instructions | **PASS** | `README.md:376–405`. |
| Text description | **PASS** | `README.md`, `docs/JUDGE.md`. |
| **Architecture diagram** | **FAIL** | **No diagram exists.** Zero mermaid, zero `.svg`, zero flowchart. `ARCHITECTURE.md` is 302 lines of prose. The only picture-shaped thing is a 2-line ASCII sketch in `agents/cascade/workflow.py:8–9`. The ten `docs/shots/*.png` are UI screenshots, not an architecture diagram. |
| **Video ≤4 min, public, live unedited execution + visual Google Cloud proof** | **FAIL** | `README.md:100` — `[FUTURE] Video, Devpost entry`. |
| Devpost entry | **FAIL** | Same line. |

**Two hard Stage One failures and no submission entry.** Stage Two work is worth
zero until these clear.

### 1.5 Other documentation/code disagreements `[VERIFIED]`

| # | Disagreement | Locations | Truth |
| --- | --- | --- | --- |
| 1 | AgentTool (§1.3) | 4 files | Threads, not ADK. |
| 2 | **`docs/JUDGE.md` says the project is NOT DEPLOYED** — "**NOT DEPLOYED.** No Cloud Run URL", listed as weakness #1, and "Cloud Run *(scripted, not deployed)*" | `JUDGE.md:45,107–108,124` | README/`docs/evidence` document a live deployment, 5/5 PASS. **JUDGE.md was never updated after the deploy.** It is the file headed *"if you read one file, read this one."* |
| 3 | Stale test count "245 passed" | `README.md:58,192`, `JUDGE.md:95` | **261 passed, 11 skipped** — re-run this session, exit 0. |
| 4 | **Headline number wrong in 8 places**: "2,424 transitive dependents" | `README.md:347,361,388`, `ARCHITECTURE.md:16,271`, `corpus/README.md:82,140,168` | `corpus/data/stats.json` → `hub_claim.transitive_dependents = 2594`. Everywhere else says 2,594. `corpus/README.md:140` derives a cull percentage from the wrong number. |
| 5 | Stale `[UNVERIFIED]` on the live model path | `lib/vertex.py:171–173` ("no GCP credentials were available"), `judgment/model.py:3,119` | `docs/LIVE-VERIFICATION.md` records 120 real Vertex calls through that class. |
| 6 | Demo script says "nothing has been deployed" and the honesty panel "currently says no model call has been made from this repository" | `docs/DEMO.md:37,76` | Both false since 2026-08-13. |
| 7 | "Task 2 builds step 4 and the arithmetic half of step 5. Steps 1–3 and 6–8 are not built." | `README.md:336` | Steps 6–8 are built (`court/`, `settle/`). Stale by three tasks. |
| 8 | "`make demo` and `make golden` exit non-zero and say they are not built" | `README.md:394–396` | `golden` is built and runs. `demo` still exits 1. |
| 9 | Preflight "19/19 PASS" | `docs/evidence/README.md:178` | `make deploy-check` is now 20/20. The screenshot is a genuine older artifact; the caption needs a date, not a re-shoot. |
| 10 | `web/` "Next.js 15 skeleton, no UI is built yet" | `ARCHITECTURE.md:247–249`, `README.md:488` | The real UI is `web/static/` (1,405 lines, served by FastAPI). The Next.js skeleton is dead code. |

### 1.6 Strongest and weakest current claims

**Strongest `[VERIFIED]`:** the deploy-verify step 5 assertion — a headless
browser reads the on-screen counter and asserts **78 = 78** against what the
deployed cascade actually computed. Opening a page proves a page loads; this
closes the most common way a demo lies. Second: the zero-model guarantee is
enforced by an AST walk of the import graph (`tests/test_zero_model.py`) plus a
CI job that fails on a single model call — not by convention.

**Weakest:** the AgentTool claim (§1.3), which is false. Then T2 judgement
quality: 60 nodes attempted, **0 resolved**, because all 174 queue nodes carry
`committed_lead_days = None` and the assessor short-circuits before the model's
answer is read. The repository states this plainly, which is to its credit, but
it means the judgement tier has never been meaningfully exercised.

**Demo-critical paths:** `services/api/main.py` (9 routes) → `web/static/app.js`
(716 lines) over SSE; `spine/cascade.py` → `spine/regimes.py`; and
`scripts/deploy_verify.py` for the on-camera Google Cloud proof.

---

## PART 2 — NOVELTY DECOMPOSITION `[VERIFIED]` where code is cited

| Mechanism | What a skeptical judge calls it | The honest distinction | Smallest experiment that proves it |
| --- | --- | --- | --- |
| **UNWIND core** (reverse-index traversal) | "A dependency graph. Data lineage. `dbt` for decisions." | Lineage tells you what *derived* from a fact. UNWIND scores what must now be **un-sent, un-paid or apologised for**, and ends at a document a named human signs (`settle/obligation.py`). Lineage tools have no escapement axis and no write path. | Ask any lineage tool for the *counterparty* to apologise to. It has no such concept. `make obligation` produces one. |
| **The arithmetic cull** | "You just didn't use the LLM." | Exactly — and it is enforced. 2,594→78 with `UNWIND_VERTEX_DISABLED=1`, CI fails on one model call. The claim is *architectural ordering*, and it is measured: parser 81.8% → +Gemini 100.0%, with delta **0.0 on the four classes the parser already handled**. | Already run. `docs/LIVE-VERIFICATION.md`. |
| **WARRANT vs RBAC** | "RBAC with extra steps." | RBAC is a *predicate* — it answers yes/no and is stateless across calls. A warrant is a *stock* that depletes. RBAC cannot express "you may do this three more times." | Issue N sub-threshold actions. RBAC admits all N. A ledger refuses at the budget line. **See §2.1 — the repo's current gate fails this test today.** |
| **WARRANT vs capability tokens (ocap)** | "This is object-capability, 1970s work." | **Owned explicitly, per the lock list.** ocap tokens are conserved but *not consequence-priced*: a capability's cost does not scale with the measured blast radius of the object it points at. That coupling is the delta, not the conservation. | Two warrants, identical capability, different targets — one with 3 dependents, one with 2,594. ocap prices them the same. |
| **WARRANT vs API budgets / rate limits** | "A quota." | A quota meters *calls*. This meters *consequence*, computed from the reverse index. 1,000 cheap calls cost less than one expensive one. | One SPEND on the hub claim exceeds a whole day of small ones. |
| **WARRANT vs trust/reputation scores** | "A trust score with a new name." | Reputation is *learned and continuous*; a warrant is *minted, integer, and conserved*. `settle/loadrating.py:1` already refuses anything carrying agent-trust fields — the repo has already drawn this line once. | Grep `settle/loadrating.py` for the refusal. It exists. |
| **COUNTERSIGN vs model ensembles / voting** | "Two models voting." | An ensemble votes on the *same* question to improve accuracy. Countersign is a **cross-family gate on a privileged operation** — Gemma cannot mint, only refuse. Different failure model: an ensemble improves the mean, a countersign bounds the worst case. | Show Gemma's refusal blocking a MINT that Gemini approved. Voting cannot produce that asymmetry. |
| **CONTROL TOWER vs agent registries** | "A service registry." | The registry being *executable* — driving ADK dynamic composition rather than documenting it — is the only defensible part. | Add a worker to the registry; the composed graph changes with no code edit. |
| **The ADK usage** | "Framework theater." | **Half-earned.** `Workflow`/`FunctionNode` are load-bearing and real. `AgentTool` and dynamic scheduling are claimed and absent (§1.3). | `grep -rn "AgentTool" --include=*.py .` → one docstring, zero imports. |

### 2.1 ⚠ THE FINDING THAT DECIDES THE INVENTION

The council ran the repository's own gate. `spine/defence.py:76–79` already
implements consequence-scaled authority:

```
required(radius) = min(0.97, 0.55 + 0.09 · log10(radius))
```

**So "the bar scales with blast radius" is already built.** The hint's stated
novelty — *pricing scales with measured consequence* — is, as worded, already in
the repository. Any candidate that only re-denominates this into basis points is
packaging.

But `ConfidenceFloor.evaluate()` is **stateless across calls**. It holds no
ledger. The council executed the consequence:

```
HUMAN_CONFIRMATION_RADIUS = 500
ONE retraction of radius 500  -> ask_human   (BLAST_RADIUS_REQUIRES_CONFIRMATION)
63 retractions of radius 8    -> all 63 execute; total touched = 504
```

`[VERIFIED]` — run this session against committed code.

**504 commitments can be unwound with no human involvement, while touching 500
at once requires a human signature.** Every individual act is correct. The
aggregate is a mass unwind that the system is structurally unable to see. This
is a real, reproducible defect in shipped code, and it is the strongest possible
justification for a *conserved* authority ledger.

---

## PART 3 — VERDICT ON THE HINT

> **Consequence-priced authority** — SPEND cost computed by the existing reverse
> index from measured blast radius.

**SELECTED — but only after being beaten on its stated grounds and reframed.**

- **Rejected as worded.** "Price scales with blast radius" is `spine/defence.py`.
  Shipping that as an invention would be a re-skin of committed code, and a judge
  who reads `defence.py` would find it.
- **Selected on the reframe.** The novelty is **conservation**, not scaling. A
  floor is a predicate that can be passed unlimited times; a ledger is a stock
  that depletes. The delta is §2.1's 504-vs-500 hole, which pricing alone cannot
  close and which conservation closes by construction.

**What a judge will say it resembles, and why that is wrong.** They will say
"object-capability tokens" — and the lock list already owns that. The answer is
not to deny the resemblance but to name the axis ocap does not have: a capability
token is conserved but *flat-priced*. Its cost is independent of what it points
at. Coupling the price to a measured blast radius drawn from the existing reverse
index is the part that is not in the ocap literature, and it is only available
here because Card 1 already computes the radius for free, with no model call.

The council notes it has **not** searched the prior-art literature this session.
The ocap position is asserted as a *position to defend*, not as a verified
novelty claim. §5 lists the prior-art questions that must be answered before any
novelty claim is made on camera.

---

## PART 4 — SELECTED INVENTIONS

**Two selected, not three.** With two Stage One failures, no Devpost entry, and
Cards 0/2/3 greenfield in 12 days to the gate, a third selection would be a
schedule fiction. The third candidate is on the cut ladder in §7.

---

### INVENTION 1 — CONSERVED CONSEQUENCE-PRICED WARRANT

**A.** Name: **Conserved consequence-priced warrant** (Card 0, minimum viable).

**B.** One sentence: Authority is a finite integer stock whose spend price is the
measured blast radius of the decision being touched, so a thousand individually
harmless actions cannot sum to a mass unwind nobody authorised.

**C.** Exact problem: `[VERIFIED]` §2.1 — 63 retractions of radius 8 execute
without a human; one retraction of radius 500 does not. The system cannot see
aggregate consequence because its gate holds no state between calls.

**D.** Why existing approaches fail: RBAC is a stateless predicate. Rate limits
meter calls, not consequence. Approval gates fire per-action and are exactly what
the salami slice defeats. Trust scores are continuous and learned, so they drift
under the same pressure. Capability tokens conserve but do not price by
consequence.

**E.** Mechanism: append-only ledger in integer basis points. `price(action) =
f(radius)` where `radius` comes from the **existing** reverse index — the same
traversal Card 1 already runs, zero extra model calls. SPEND debits or refuses;
the refusal carries a reason code and a number. Exponential decay per the lock
list. MINT requires human concurrence plus cross-family countersign; provenance
`EARNED|SYNTHETIC`, with SYNTHETIC visible on screen.

**F.** Minimal architecture change: **new top-level package `warrant/`.** Reads
`spine.traversal` output. Frozen code is imported, never modified. The SPEND
FunctionNode is added as a new ADK node *in front of* the existing cascade graph;
`agents/cascade/workflow.py` gains one edge and loses nothing.

**G.** Files affected: `warrant/ledger.py`, `warrant/price.py`, `warrant/mint.py`,
`warrant/node.py` (new) · `agents/warrant/workflow.py` (new) · `lib/schema.py`
(**additive only** — new models appended; no existing model altered) ·
`web/static/app.js` + `index.html` (new panel) · `services/api/main.py` (one
route) · `Makefile` (one target).

**H.** Tests required: `tests/test_warrant.py` — (1) **the salami-slice
regression**: 63×radius-8 must refuse before aggregate 500, asserted against the
number from §2.1; (2) ledger is append-only, no method mutates a prior entry;
(3) integer arithmetic throughout, no float in a balance; (4) decay is
memoryless — `decay(decay(x,t1),t2) == decay(x,t1+t2)` within integer rounding;
(5) MINT without countersign raises; (6) SYNTHETIC provenance cannot be laundered
into EARNED; (7) **zero-model guard extended** — `warrant/` added to the
`tests/test_zero_model.py` boundary walk, so pricing can never reach a model.

**I.** Evidence required: a `make warrant-attack` target that runs the §2.1
attack twice — once against `ConfidenceFloor` alone (63 approvals, 504 touched)
and once with the ledger (refused at N), printing both. Committed transcript, CI
gate on drift. This is evidence a judge can re-run in one command.

**J.** Demo moment (20–30s): the attack bar. "Sixty-three small retractions,
each one legal." Counter climbs 8, 16, 24… at **N** the field goes amber and one
line appears: `REFUSED — warrant exhausted: 4,880 of 5,000 bp spent, this action
prices at 340 bp.` Then: "each one was individually approved by the gate you
already saw. Together they were a mass unwind. The ledger is the only thing in
the system that can see the word *together*."

**K.** Novelty argument: conservation + consequence-pricing, where the price is
computed by a reverse index that already exists and costs no model call.

**L.** Prior-art questions that MUST be answered before claiming novelty:
(1) Does the ocap literature contain consequence-weighted capability amplification?
(2) Do differential-privacy budgets count as prior art for depleting-stock
authority? They are the closest structural analogue and must be addressed, not
avoided. (3) Do capability-based OS designs (KeyKOS, seL4) price by object
fan-out? (4) Is there prior art in financial risk limits (VaR budgets) that a
judge from finance would name instantly? **The council did not search these.
Budget 3 hours before the video is recorded.**

**M.** Failure modes: an operator legitimately needing 100 small retractions is
blocked at 63 — needs a documented human top-up path, or the demo becomes an
argument about false positives. Decay parameters are `[ASSUMPTION]`, not
measurement, and must be labelled the way `spine/defence.py:39` already labels
its own.

**N.** Goodhart risks: the moment warrant is a metric, work reshapes to minimise
spend — batching many small unwinds into one cheap one, or splitting to dodge a
threshold. Mitigation: price is superadditive in radius, so splitting never pays.
**Assert this as a test**, not a paragraph.

**O.** Security risks: the ledger becomes the highest-value target in the system.
Append-only is necessary and not sufficient; a forged MINT is worse than a forged
retraction because it authorises many. The cross-family countersign exists for
exactly this and must be built, not assumed.

**P.** Scope-cut version (**~10h**): ledger + pricing + SPEND refusal + the
salami-slice test + the attack transcript. **No MINT, no decay, no countersign,
no UI panel** — the refusal prints to the terminal on camera. This still
demonstrates the whole idea and still closes the §2.1 hole.

---

### INVENTION 2 — REVOCATION PROPAGATION OVER THE WARRANT LEDGER

**A.** Name: **Authority unwind** (revocation propagation through delegation
chains).

**B.** One sentence: When a warrant turns out to have been invalid, every action
taken under it raises its hand — by running the spend ledger through the same
reverse-index traversal and four-regime router that Card 1 already applies to
claims.

**C.** Exact problem: a countersignature is later found forged; a human's
concurrence is withdrawn; a source loses standing. Actions already taken under
that authority are in the world. Nothing points backwards from a revoked
permission to what it paid for. **This is the project's own thesis sentence with
"claim" replaced by "warrant"** — and the repository does not do it.

**D.** Why existing approaches fail: OAuth revocation stops *future* use and is
silent about the past. Certificate revocation lists are the same shape. Audit
logs record what happened but compute no consequence and produce no obligation.
None of them answer "what must now be un-sent."

**E.** Mechanism: spends are edges (`warrant_id → action_id`). Revocation walks
that index — **the same `spine/traversal.py` breadth-first closure** — scores each
touched action for materiality and escapement, and routes it through
`spine/regimes.py`. Contained actions are reversed silently. **Escaped actions
raise a correction obligation via `settle/obligation.py`.** Zero new algorithms;
zero model calls; zero frozen-code edits.

**F.** Minimal architecture change: `warrant/revoke.py` calls existing traversal
and regime functions over a different edge set.

**G.** Files affected: `warrant/revoke.py` (new) · `warrant/ledger.py` (extended)
· one API route · one UI state. Nothing in `spine/`, `court/`, `settle/`,
`judgment/` is modified — only imported.

**H.** Tests required: revoked warrant yields exactly the actions it paid for,
no more; an action paid by two warrants survives revocation of one; the four
regimes partition the revoked set totally (same total-function property as
`spine/regimes.py`); revocation of an unspent warrant touches nothing; **zero
model calls** during a full revocation.

**I.** Evidence required: `make revoke` — one revocation, printing warrant,
spend count, radius, four-regime split, obligations raised. Committed transcript,
CI gate on drift.

**J.** Demo moment (20–30s): "The countersignature on this mint was forged." One
keystroke. The field re-lights in a **different colour** from the claim cascade —
same motion, different cause. "Forty-one actions were paid for by a permission
that was never valid. Nine already left the building. Here is what we owe."

**K.** Novelty argument: revocation that computes consequence and produces an
obligation, rather than merely denying future use. It also makes UNWIND and
WARRANT one mechanism instead of two products in a trench coat — the strongest
possible answer to Phase 6.

**L.** Prior-art questions: (1) Does macaroon/biscuit revocation literature
compute downstream consequence? (2) Do SPIFFE/SPIRE or Zanzibar-style systems
propagate revocation to completed actions? (3) Is this "compensating transactions"
from the Saga pattern under a new name — and if so, what is the delta?
**Question 3 is the dangerous one and must be answered.**

**M.** Failure modes: if most spends are on contained actions, revocation
produces a boring result and the demo dies. **The corpus must be checked for a
revocation that produces escaped actions before this is scheduled** — if it does
not, this invention is not demoable and must be cut.

**N.** Goodhart risks: minimising revocation blast radius by fragmenting warrants
into many tiny ones — which directly conflicts with Invention 1's superadditive
pricing. **The two inventions must be tested together**, or one incentivises what
the other punishes.

**O.** Security risks: revocation is itself a privileged, high-blast-radius
operation. A forged revocation is a denial-of-service on the whole fleet. It must
pass through the same authority gate — and it must cost warrant.

**P.** Scope-cut version (**~8h**): revocation walks the ledger and prints the
affected action list with the four-regime split. **No obligation generation, no
UI.** The traversal is the idea; the obligation is the polish.

---

## PART 5 — HOSTILE CRITICS

| "This is just X" | Answer |
| --- | --- |
| "…RBAC." | RBAC is stateless. §2.1: 63 approvals, 504 commitments, no human. A predicate cannot see aggregates. |
| "…object-capability tokens." | Owned, per lock list. ocap conserves but flat-prices. Consequence-coupling is the delta. Prior art unsearched — §4-L. |
| "…a rate limit." | Meters consequence, not calls. Hub claim costs more than a day of small ones. |
| "…a trust score." | Integer, minted, conserved, not learned. `settle/loadrating.py:1` already refuses agent-trust fields. |
| "…an audit log." (Inv. 2) | An audit log records. This traverses, scores, and emits a signed obligation. |
| "…OAuth revocation." (Inv. 2) | OAuth stops future use. This computes what already escaped. |
| "…the Saga pattern." (Inv. 2) | **Weakest point.** Sagas compensate a known transaction set; this *discovers* the set by traversal. Must be answered on camera. |
| "Your agents don't decide anything." | Conceded and already in writing at `JUDGE.md:117–118`. Decisions are arithmetic; the model writes prose. That is the architecture, stated. |
| "You needed ADK for this?" | **Currently indefensible for `AgentTool`.** See §1.3 and the build order. |

---

## PART 6 — INTEGRATION TEST

> *"Does this make UNWIND + WARRANT more inevitable, or merely bigger?"*

**Invention 1 — INEVITABLE.** It closes a hole in committed code (§2.1). The
price comes from the reverse index that Card 1 already computes. Without Card 1
you cannot price this way at all; without the ledger Card 1's gate is defeatable
by division. Each card makes the other necessary.

**Invention 2 — INEVITABLE.** It is UNWIND's own thesis applied to authority,
reusing `spine/traversal.py` and `spine/regimes.py` unmodified. If UNWIND is
right that consequence must propagate backwards, then it must do so for
permissions too — otherwise the thesis is arbitrary.

**Rejection check:** neither is a dashboard, marketplace, memory system, RAG,
observability product, approval workflow, reputation score, or token economy.
Invention 1 sits nearest "token economy" — the defence is that warrant is never
transferable between principals and has no exchange rate. **If transferability is
ever added, it becomes a token economy and must be cut.**

---

## PART 7 — BUILD ORDER

Hours are `[PROJECTED]` and assume one developer at ~6 productive hours/day.
**12 days to the Aug 27 gate ⇒ a ~72h ceiling.**

### Tier 0 — STAGE ONE AND INTEGRITY (blocking, 27h)

Nothing below this line matters if this line does not clear.

| # | Task | h |
| --- | --- | --- |
| 0.1 | **Delete the AgentTool claim** from `README.md:48–52`, `ARCHITECTURE.md:283`, `court/owners.py:9–16`, `docs/DEMO.md:34`. Replace with what is true: "N owners run concurrently with the arbiter retaining control; parallelism is measured in `tests/test_court.py`." **Non-negotiable — this is on camera.** | 2 |
| 0.2 | **Rewrite `docs/JUDGE.md`** — it says NOT DEPLOYED. Fix deployment status, test count (261), and remove the "75/100" scale. | 3 |
| 0.3 | Fix 2,424 → 2,594 in 8 locations; recompute the derived percentage in `corpus/README.md:140`. | 2 |
| 0.4 | Clear stale `[UNVERIFIED]` in `lib/vertex.py:171`, `judgment/model.py:3,119`; fix `docs/DEMO.md:37,76`; fix `README.md:336,394`. | 3 |
| 0.5 | **Architecture diagram** — Stage One requirement, currently absent. Mermaid in `ARCHITECTURE.md` + exported PNG. | 4 |
| 0.6 | **Devpost entry** — text, links, diagram. | 3 |
| 0.7 | **Video ≤4 min**, public, live unedited execution, visible Google Cloud proof. Script exists (`docs/DEMO.md`) but is stale until 0.1/0.4 land. Budget for two takes. | 10 |

### Tier 1 — INVENTION 1 (30h, or 10h cut)

| # | Task | h |
| --- | --- | --- |
| 1.1 | `warrant/` package: ledger (append-only, integer bp), pricing from reverse index | 8 |
| 1.2 | SPEND as an ADK 2 `FunctionNode`, wired ahead of the cascade graph | 4 |
| 1.3 | MINT: human concurrence + cross-family countersign; `EARNED\|SYNTHETIC` | 6 |
| 1.4 | Tests H(1)–(7), incl. extending the zero-model boundary walk to `warrant/` | 6 |
| 1.5 | `make warrant-attack` + committed transcript + CI gate | 3 |
| 1.6 | UI panel; SYNTHETIC visible on screen | 3 |

### Tier 2 — INVENTION 2 (20h, or 8h cut)

**Gated on M:** confirm the corpus yields a revocation with escaped actions
before starting. If it does not, cut Tier 2 entirely.

| # | Task | h |
| --- | --- | --- |
| 2.0 | Corpus check — does a revocation produce escaped actions? | 2 |
| 2.1 | `warrant/revoke.py` over existing traversal + regimes | 6 |
| 2.2 | Obligation generation through `settle/obligation.py` | 4 |
| 2.3 | Tests + `make revoke` transcript + CI gate | 5 |
| 2.4 | UI: second cascade colour | 3 |

### Does it fit?

| Plan | Hours | Verdict |
| --- | --- | --- |
| Tier 0 only | 27 | **Fits with large slack.** Stage One clears. |
| Tier 0 + Tier 1 | 57 | **Fits.** ~15h slack. **← RECOMMENDED** |
| Tier 0 + Tier 1 + Tier 2 | 77 | **Does not fit.** 5h over ceiling, zero slack, no contingency for a failed video take. |
| Tier 0 + Tier 1 + Tier 2 (both cut) | 45 | Fits. Weaker demos, both ideas present. |
| Anything including Card 2 Control Tower in full | 105+ | **Does not fit. Do not attempt.** |

**Recommendation: Tier 0 + Tier 1 full + Tier 2 cut version (65h)** — fits with
~7h contingency, and both inventions appear on camera.

### Cut ladder (drop in this order)

1. Invention 2 UI colour (2.4)
2. Invention 2 obligation generation (2.2) → cut version
3. Invention 1 UI panel (1.6) → refusal prints to terminal
4. Invention 1 MINT/countersign (1.3) → SPEND-only ledger
5. Invention 2 entirely
6. **Never cut:** 0.1, 0.2, 0.5, 0.6, 0.7, 1.5

### ⚠ Note on the locked four-card shape

Per §1.1 Exception, the council reports as a **finding**: Card 2 (Control Tower)
cannot be built to the recap's description before Aug 27 alongside Stage One.
This is not a request to re-open the lock — it is the schedule arithmetic. Card 3
(Countersign) survives only as Invention 1's MINT gate (1.3), which is also the
**only place in the plan where a genuine ADK 2 `AgentTool` belongs** — making it
the one way to convert §1.3's false claim into a true one. If time appears after
Tier 1, spend it there rather than on Card 2.

---

## PART 8 — EVIDENCE PLAN

| Claim | Artifact | Gate |
| --- | --- | --- |
| Salami-slice hole is real | `make warrant-attack` transcript, before/after | CI drift |
| Ledger is append-only + integer | `tests/test_warrant.py` | CI |
| Pricing costs no model call | `warrant/` in the zero-model AST walk | CI |
| Splitting never pays | superadditivity test | CI |
| Revocation finds exactly the paid-for set | `make revoke` transcript | CI drift |
| Deployment is live | `make deploy-verify` 5/5 | on camera |
| Cull is real | on-screen counter = cascade count | `make ui-check` |

---

## PART 9 — THE PITCH

### 30 seconds

> Every decision your company made rests on facts that expire. When one turns out
> false, nothing points backwards — so correction happens by memory and email.
> UNWIND records the edge. Type a fact that changed: 2,594 decisions light up, 78
> survive, and the model is switched off for all of it — it's a graph walk and
> subtraction. The 78 become a correction a named human signs. And because the
> system knows what each decision is *worth*, it prices the authority to touch
> them: a thousand small unwinds can't add up to one big one nobody approved.

### 4-minute story

1. **0:00–0:30 — Normal Tuesday.** 4,206 live decisions. Nothing is wrong yet.
2. **0:30–1:00 — The refusal.** A broker tries to retract the supplier's lead
   time. `source_outside_claim_scope`, radius 0. *A false retraction is worse
   than a missed one.*
3. **1:00–2:00 — The cull.** The real retraction. 2,594 → **78**, model off,
   ~15 seconds of silence. Let it run.
4. **2:00–2:30 — ⭐ The attack.** Sixty-three individually legal retractions.
   The counter climbs. The ledger refuses. *Each one was approved. Together they
   were a mass unwind.*
5. **2:30–3:15 — The obligation.** Field dissolves to paper. Named counterparty,
   one re-issuable quote, **one payment that cannot be taken back**, a human who
   signs.
6. **3:15–3:45 — Google Cloud, live.** `make deploy-verify` on the deployed URL.
   5/5 PASS. A real browser asserting **78 = 78**.
7. **3:45–4:00 — Honesty panel.** What is built, what is only designed, and the
   worst extraction class — on screen, on purpose.

---

## PART 10 — JUDGE ATTACK LIST

| # | Question | Evidence-backed answer |
| --- | --- | --- |
| 1 | Why do you need ADK 2? | `Workflow` + `FunctionNode` make the four-regime split a route (`workflow.py:98,160–172`), not a prompt. **After Tier 0.1 this is the only ADK claim made.** |
| 2 | Is Gemini load-bearing, or decoration? | Second pass only. Parser 81.8% → +Gemini 100.0%, and **delta 0.0 on the four classes the parser already handled** — `docs/LIVE-VERIFICATION.md`. |
| 3 | You claim 100% recall. | The model's denominator is **8, not 44**. Stated in three places before you asked. |
| 4 | Is it deployed? | Yes. `make deploy-verify` → 5/5 PASS against the live URL. Step 5 drives a real browser. |
| 5 | Is the cull real or an animation? | The counter decrements only in the SSE handler; `make ui-check` asserts on-screen = cascade's own count (**78 = 78**). |
| 6 | Isn't this just data lineage? | Lineage has no escapement axis and no write path. Ours ends at a signed obligation naming a counterparty. |
| 7 | Isn't WARRANT just RBAC? | RBAC is stateless. 63 approvals → 504 commitments, no human. Reproducible. |
| 8 | Isn't this object-capability? | Yes, in the conservation half — we own that. ocap flat-prices; we price by measured blast radius. |
| 9 | Isn't the ledger just a quota? | A quota meters calls. This meters consequence from the reverse index. |
| 10 | Did the agents decide anything? | No, and we say so at `JUDGE.md`. Decisions are arithmetic; the model writes prose. |
| 11 | Is the corpus real? | **No — synthetic, and labelled everywhere.** `corpus/README.md` gives the generation model and every divergence from spec. |
| 12 | Then the numbers are made up? | The *inputs* are synthetic; the *die-back* is computed from them by committed script and recomputed by `tests/test_corpus.py`. |
| 13 | What is unmeasured? | T2 judgement quality. 60 attempted, **0 resolved**, because all 174 queue nodes carry no numeric term. A non-test, documented in `docs/T2-MEASUREMENT.md`. |
| 14 | Why didn't you build the fixture? | Same author would write clause text and scoring key — a mirror, not a measurement. Deliberately not built. |
| 15 | Prompt injection? | The parser runs first and has no instruction-following surface. `ExtractionQuarantine` (`spine/defence.py:178`) makes an out-of-scope claim *unnameable* — a data restriction, not an instruction. |
| 16 | Is the injection scanner your defence? | No, and the code says so (`defence.py:237`). The quarantine is the defence; the scanner is telemetry. |
| 17 | Zero model calls — really? | AST walk of `spine/`'s import graph + a CI job that fails on one call. |
| 18 | Does it survive a Vertex outage? | `UNWIND_VERTEX_DISABLED=1 make eval` — identical results, in CI on every push. |
| 19 | Why Flash, not Pro? | No Gemini 3.x Pro was GA on Vertex as of 2026-08-12; both pinned models are GA. A preview model can throttle under a live demo. |
| 20 | What is weakest? | T2 judgement quality is unmeasured; the corpus is synthetic; and until this week the repo claimed an ADK construct it did not use — we found it, and removed the claim rather than the evidence. |

---

## PART 11 — REJECTED CANDIDATES

Generated internally and cut. One line each.

| Candidate | Why rejected |
| --- | --- |
| Consequence-priced authority *as worded* | Already `spine/defence.py:76–79`. Selected only after reframing to conservation. |
| Authority debt | Re-skin of `spine/debt.py`. Bigger, not more inevitable. |
| Proof-carrying actions | A judge says "audit log" and is 80% right. |
| Minimum-authority computation | No 20-second demo. |
| Blast-radius budgets | Same mechanism as Invention 1. Merged. |
| Temporal authority / decay | Locked as a property of Card 0, not a separate invention. |
| Authority escrow on irreversible effects | Genuinely interesting; a second ledger mechanic is bloat at 12 days. **Best candidate if the schedule frees up.** |
| Refund-on-refusal | A detail of Invention 1, not an invention. |
| Warrant marketplace / transferable warrant | Fails Phase 6 outright — becomes a token economy. |
| Agent reputation feeding warrant | `settle/loadrating.py` already refuses this coupling, correctly. |
| Retroactive authority audit | Interesting, undemoable. |
| Policy-compiled routing | Mostly `spine/decision.py` already. |
| Warrant for model spend (cost budget) | `court/protocol.py` CostLedger already does it. |
| Multi-tenant warrant pools | Enterprise-plausible, zero novelty. |
| Warrant-weighted court seating | Cute; couples two frozen subsystems for no gain. |
| Memory Bank of past decisions | Explicitly a rejected category in Phase 6. |
| Control Tower registry UI | A dashboard. Rejected by Phase 6. |

---

## FINAL KILL LIST

Delete on sight, at any point before submission:

1. **The AgentTool claim** in all four locations — false, and currently scripted
   to be spoken on camera.
2. **"NOT DEPLOYED"** in `docs/JUDGE.md` — contradicts the README.
3. **"75/100"** in `docs/JUDGE.md:157` — a scale this competition does not use.
4. **"2,424"** in all 8 locations.
5. **`web/` Next.js skeleton** — dead code the docs still describe as the UI.
6. Any warrant feature that makes authority **transferable between principals**.
7. Card 2 Control Tower, unless Stage One and Tier 1 are both complete.
8. Any novelty claim made on camera before §4-L's prior-art questions are answered.

---

## SUMMARY

The engineering here is strong and unusually honest, and the honesty apparatus is
the moat. But the submission is currently failing **two pass/fail Stage One
gates** (no architecture diagram, no video), has no Devpost entry, and carries a
false claim about ADK usage in four files including the spoken demo script.

Twenty-seven hours of unglamorous work fixes all of it. Thirty more hours buys a
genuinely novel mechanism that closes a real, reproducible hole in the code —
**504 commitments unwound with no human, where 500 at once requires a signature.**

Do Tier 0 first. It is worth more than any invention on this list.
