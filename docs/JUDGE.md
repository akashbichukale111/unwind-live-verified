# UNWIND — judge card

*If you read one file, read this one. Every number here traces to
`evidence/INDEX.md`, and every row there names the exact command that
reproduces it. Nothing here is projected.*

> **This card predates the Agentic Command OS.** What follows (Cards 0–3,
> 369 tests) is still accurate and still live — it has not been removed or
> weakened, and the four-card instrument is now reachable from
> `the six-layer instrument ▶` on the Agentic Command OS page. But it is no
> longer the whole submission. Since this card was written, the project grew
> a second, larger layer on top: an **Agentic Command OS** (objective → plan
> → delegate → recon → risk → challenge → governance gate → sandboxed action
> → verify, with a Gemini/Veo/Lyria Mission Media Lab and an inline **Mission
> Time Machine** over every checkpoint), plus a **governed evolution loop**
> that scores agent trajectories on seven deterministic criteria and refuses
> to promote a version that trades safety for throughput. Since then it has also grown
> **output contracts** on every worker result, a **supervised** tool runner
> (real timeout, bounded retries, three named failure kinds), a
> **Reconciler** agent that re-derives contradicted claims from authority so
> the disagreement between two rules becomes the finding, and a **recall
> knowledge engine** in which mission N+1 provably plans differently because
> of mission N. The whole suite is now **1181 passed, 1 skipped** (was 369,
> then 768) — see [`evidence/INDEX.md` §16–20](../evidence/INDEX.md), and
> **[`RUBRIC.md`](../RUBRIC.md)** for the criterion → mechanism → test → UI
> map. Read this card for the original four-card architecture; read the
> README for everything built since.

---

**Project** — UNWIND, Consequence Clearing
**Track** — Google All Things Agentic Hackathon, Fortified Enterprise Fleet

**One line** — *Cache invalidation for decisions: when a fact turns out
false, everything it touched raises its hand, and the system computes what
must now be un-sent, un-paid, or apologised for.*

**The problem** — Premises don't fail because the model reasoned badly. They
fail because **the world changed after the reasoning was correct**. A quote
assumes an 11-day lead time; the lead time moves; nobody goes back to find
the 2,594 decisions built on it.

---

## All four cards are live on the deployed URL

Redeployed and verified 2026-08-17 (`evidence/deploy/`,
`evidence/firestore/deploy-2026-08-17.md`). Everything below runs directly
against `https://unwind-hgeodtazqq-uc.a.run.app` — no local setup needed.
(A local run still works too, and is documented in `README.md`, for
rehearsal without touching the shared demo agents' live state.)

---

## The 10-minute judge path

### Minutes 0–3: the cascade

1. Open `https://unwind-hgeodtazqq-uc.a.run.app`. Wait for the field to
   render (4,206 points).
2. Type `supplier_K lead time is now 20 days`, press Enter, click Confirm.
   Watch the counter fall from 2,594 to 78 — zero model calls, arithmetic
   only.
3. Press `H` for the honesty panel. The worst extraction class (66.7%) is
   on screen, highlighted, not buried.

### Minutes 3–7: the four-card instrument (Cards 0–3)

4. Press `T`.
5. Read Card 0's bars: every one is labelled `SYNTHETIC` in dim mono text —
   this is seeded demo history, not a real earned balance, and the UI says
   so on every bar, not just in a caption.
6. Click **"Overturn a HIGH-risk judgement (BURN)"**. Watch the amber bar
   drop past the oxide risk-class line — a real `BURN` event, wired through
   `tower/gateway.py`'s `FunctionNode`, live. The very next case of that
   class refuses `WARRANT_INSUFFICIENT`, no cache.
7. Click **"Earn the rookie's first delegation"**. A cold-start agent (zero
   warrant, no seeding) mints its first balance live — the bar's label
   flips from `SYNTHETIC` to `EARNED` in amber, because this one is real,
   on this run.

### Minutes 7–10: the honesty apparatus and the necessity-test cut

8. In the instrument's Card 3 panel: the measured Countersign agreement
   rate, **75.6% (31/41 scenarios)**, labelled `SIMULATED` because live
   Gemma was attempted this session and blocked by a real `404` (the
   project lacks Model Garden access to `gemma-3-27b-it`) — see
   `countersign/DESIGN.md` for the full escalation, including a genuine
   authenticated Vertex round-trip.
9. Read the README's "Prior art" section: the object-capability lineage,
   owned rather than hidden. Read "The honesty map": the Veo/Lyria cut, the
   residual Goodhart risk, the SYNTHETIC-seed policy.

---

## One test per moat

| Moat | Command |
| --- | --- |
| 1. Zero-model guarantee | `python -m pytest tests/test_zero_model.py -v` |
| 2. Deterministic refusal, reason codes | `python -m pytest tests/test_tower_gateway.py -v` |
| 3. `78 = 78`, real browser | `make ui-check` |
| 4. Principal separation (arbiter ≠ owner; countersigner ≠ judging side) | `python -m pytest tests/test_principals.py tests/test_countersign_verify.py -k reject -v` |
| 5. Honesty apparatus (worst class published, T2 a non-test) | `cat docs/T2-MEASUREMENT.md && cat docs/COVERAGE.md` |

Full moat-by-moat test list, including the ones this table compresses, is
`evidence/INDEX.md`.

---

## The four numbers to check

| Number | Where | Command |
| --- | --- | --- |
| **78 = 78** | on-screen counter equals the cascade's own computed material count | `make ui-check` |
| **Warrant re-derivation: 4/4 PASS** | every warrant balance bit-equal to a fresh fold of the ledger | `FIRESTORE_EMULATOR_HOST=localhost:8080 python scripts/rederive_warrant.py` |
| **Countersign agreement rate: 75.6% (31/41), SIMULATED** | measured over all 41 eval scenarios, live Gemma reported unreachable | `python scripts/run_countersign_eval.py` |
| **True test count: 369 passed** (with the emulator; 325 passed / 44 skipped without) | the whole suite, not a cherry-picked subset | `python -m pytest -q` |

---

## Where to look

| Question | File |
| --- | --- |
| Every claim ↔ evidence file ↔ reproduction command | `evidence/INDEX.md` |
| The live Gemini run | `docs/LIVE-VERIFICATION.md` |
| What each artifact proves, and does not | `docs/evidence/README.md` |
| Extraction coverage, incl. the worst class | `docs/COVERAGE.md` |
| Card 0's design, and what it does NOT solve (Goodhart, Sybil) | `warrant/DESIGN.md`, `warrant/FAILURE_MODES.md` |
| Card 3's design, and the exact live-Gemma escalation | `countersign/DESIGN.md` |
| Component-by-component justification | `ARCHITECTURE.md` |
| The 4-minute demo, shot by shot | `submission/demo_script.md` |
| The pre-submission checklist | `submission/CHECKLIST.md` |

Run it yourself, no GCP account needed:

```bash
make install && make test && make ui      # http://127.0.0.1:8000, Card 1
make emulator && make dev                 # + the four-card instrument, press T
```

---

## Final verdict, self-assessed

All four architectural cards are built, tested (369 passing), and deployed —
not three of four still locked, and not code that only runs on someone's
laptop. Redeploying itself surfaced one real, previously-undetected gap (a
missing Firestore composite index, `evidence/firestore/deploy-2026-08-17.md`)
that no local test could have caught, because the local test suite runs
against the emulator, which does not enforce it; that gap is disclosed and
fixed, not smoothed over. Weakest points, unchanged in kind from the
Card-1-only submission and still true: T2 judgement quality
is unmeasured, the corpus is synthetic and single-author, live Gemma
verification is blocked by a Model Garden access gap this environment could
not clear, and warrant's Goodhart/Sybil risks are named, not solved.

**No self-score is offered.** Scoring is the judges' to do, and inventing a
number against a rubric this submission does not own would be exactly the
kind of unbacked figure the rest of this repository refuses to print. The
honesty here is not modesty — it is the reason the 75.6% and the +18.2 pp
are both worth believing.

> **A note on [`RUBRIC.md`](../RUBRIC.md), which does print numbers.** That
> file was written later, against a rubric that was published, and it exists
> because a judge with published criteria is owed a map from each criterion
> to the artefact that settles it — not because the numbers in it are worth
> anything on their own. It says so itself: the scores are *the authors'
> conservative estimates, with the evidence attached so a real judge can
> disagree cheaply*, and it carries a limitations section naming what is
> still missing. Read the mechanism column and the test column; the score
> column is the least interesting thing in it.

**Since this verdict was written**, the same discipline was pointed at the
Agentic Command OS layer: `docs/evaluation-report.md` measures, rather than
asserts, that a governed agent trades a small amount of raw task success for
a large gain in safety/verification criteria — and shows an *ungoverned*
agent scoring a perfect 1.00 on outcome-only success while being the
measurably worse agent (composite 0.8206 vs 0.9599), which is the argument
for governance made in numbers instead of prose. That report's own weakest
point is stated in its Limitations section, not hidden from it.
