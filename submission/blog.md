# Building UNWIND: consequence clearing, and the honesty apparatus that made it worth trusting

*Google All Things Agentic Hackathon — Fortified Enterprise Fleet*

Every number in this post traces to a file in `evidence/INDEX.md`. Where I
haven't measured something, I say so instead of rounding it up.

---

## The problem I kept running into

Every decision an organisation makes rests on specific claims about the
world: a supplier will ship in 11 days, a tariff rate is 8%, a clause means
X. Those claims expire. When one changes, nothing in the enterprise points
backwards from the claim to the decisions built on it — the dependency edge
was never recorded. So correction propagates socially: someone remembers,
sends an email, hopes.

Premises don't fail because a model reasoned badly. They fail because the
world changed after the reasoning was correct. UNWIND records the edge,
watches the claim, and when it dies, walks backwards.

## What actually shipped

Four cards, one page:

- **Card 1 — UNWIND CORE.** A supplier lead time moves from 11 to 20 days.
  The reverse index finds 2,594 dependent decisions. An arithmetic cull —
  no model call — reduces that to the 78 that actually need a human: 1,468
  immaterial (the buffer absorbed the shock), 874 already closed out, 174
  handed to judgement, 78 material. `tests/test_zero_model.py` walks the
  import graph of every module in this path and fails the build if any of
  them can reach a model client.
- **Card 0 — WARRANT.** A deterministic, decaying, capability-scoped
  authority ledger. An agent doesn't get to decide it's earned trust — a
  balance is minted only from a human-concurrence record plus an
  independent-family countersign, and it's spent atomically, inside a
  single Firestore transaction, on every delegated act. Cold-start agents
  refuse `WARRANT_INSUFFICIENT` by construction — there's no code path from
  "insufficient" to "do it anyway."
- **Card 2 — CONTROL TOWER.** The registry, the gateway, an append-only
  causal decision memory (not a vector store — "what happened *because of*
  this decision" is a graph walk over an explicit parent edge, not a
  similarity search), and a durable runtime that survives a genuine process
  restart across a simulated one-week gap.
- **Card 3 — COUNTERSIGN.** Gemma, a genuinely different model family from
  Gemini, independently re-reads a case and returns AGREE or DISAGREE. A
  collusion guard rejects a countersign whose family or principal matches
  the judging side. DISAGREE freezes minting for that case, permanently —
  there's no unfreeze path, and I say so plainly in
  `warrant/FAILURE_MODES.md` rather than pretending the freeze is
  reversible when it isn't.

## The audit that mattered more than a score would have

Partway through, an internal repository audit (`submission/COUNCIL_VERDICT.md`,
2026-08-15) checked the "four cards" story against the actual code and came
back with a headline finding: **three of the four claimed cards had zero
code.** `grep -ri warrant` returned only the English verb; zero occurrences
of "Gemma"; Card 2's registry, Gateway and Memory Bank did not exist. Only
Card 1 was real. That same audit caught a second defect, smaller but telling:
an earlier draft of the judge card stated a self-score of **"75/100"** — a
scale this competition does not use anywhere in its rubric (Stage Two is
1–5 per criterion, max 6.0 with bonus). The audit flagged it and it was
removed; no self-score appears anywhere in this submission now, for the same
reason a number this project didn't measure doesn't appear anywhere else in
it.

Two things followed from that finding:

1. **A "locked design" is not a feature.** The three missing cards were
   built instead of described — the diagram now draws all four solid
   because they earned it, not because I redrew a box.
2. **A single reputation number is the failure mode this whole category
   exists to prevent.** Warrant balances are per (agent × capability × risk
   class) — never collapsed to one score. It would have been easier to
   ship one number. It would also have been the same mistake credit scores
   make: hiding which specific thing an actor is trusted for behind an
   aggregate nobody can audit — the identical mistake the invented "75/100"
   was making one level up, about the project itself.

## The simulated-countersign phase, and when it ended (mostly)

Real Gemma verification needs Vertex AI Model Garden access this project's
GCP project doesn't have. Rather than fake a result, I built a labelled
scripted simulator (`UNWIND_COUNTERSIGN_SIMULATED=1`) — deterministic, not
random, agreeing on clean material and disagreeing on anything marked
adversarial — and used it to prove the *mechanism* (collusion guard,
CHALLENGE freeze, the Memory Bank write path) end to end, everywhere except
the actual model call.

It didn't fully end. In this same session I traced the live path as far as
it would go: a real Vertex AI round-trip, real OAuth, and a real `404` —
the project has no access to the `gemma-3-27b-it` publisher model. That's
recorded verbatim in `countersign/DESIGN.md`, including the two earlier
attempts (`403 unwind-local`, then `404` on the real project) that got me
there. The measured 75.6% agreement rate over 41 eval scenarios is
therefore labelled `SIMULATED`, on screen, in the README, and in the raw
evidence file — never presented as a live model's judgement, because it
isn't one yet.

## Why WARRANT is object-capability security, explicitly

I'd rather own the resemblance than pretend it's novel from nothing:

> WARRANT is object-capability security where the capabilities are earned
> rather than granted: a classical capability is granted and delegable; a
> warrant is minted only from countersigned, human-validated outcomes, is
> non-transferable across principals, decays with idleness, and is scoped
> per risk class. Nobody hands it over; nobody can hand it on.

The object-capability literature got conservation right decades before this
project existed. What it doesn't usually carry is a price that scales with
the *measured consequence* of the act being authorised — and the only
reason that coupling is available here is that UNWIND already computes
blast-radius consequence for free, with zero model calls, as its core
novelty. This is a position I intend to defend, not a claim I've already
proven — the open questions (does differential-privacy budgeting count as
prior art for depleting-stock authority? do capability-based OS designs
ever price by object fan-out?) are named in the README rather than assumed
away.

## What I'd do differently with another week

**Update, 2026-08-17: redeployed.** Cards 0–3 are now live on the same
Cloud Run URL as Card 1 — and redeploying immediately surfaced a real bug
neither the emulator-backed local test suite nor the earlier local
Playwright runs could have caught: a missing Firestore composite index for
the Memory Bank, which real Firestore enforces and the emulator does not.
Fixed and documented rather than quietly worked around
(`evidence/firestore/deploy-2026-08-17.md`) — the honesty apparatus this
whole post is about doesn't get to stop applying to the deployment step
just because the code was already merged.

Next: get real Model Garden access and re-run
`scripts/run_countersign_eval.py` against live Gemma. The mechanism is
proven; the actual model's agreement rate isn't measured yet, and that's
the honest state to end this post on.

---

*Repository:* `https://github.com/akashbichukale111/unwind` · *Deployed
(Card 1):* `https://unwind-hgeodtazqq-uc.a.run.app` · *Full evidence index:*
`evidence/INDEX.md` in the repository.
