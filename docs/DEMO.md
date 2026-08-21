# The demo — four minutes, and the judge drives

> ⚠ **SUPERSEDED for the submission recording.** The script that will actually
> be recorded is [`submission/demo_script.md`](../submission/demo_script.md),
> which is shot-by-shot, marks every shot `LIVE` or `CUTAWAY`, and is word-
> counted against the four-minute ceiling. This file is kept as the longer
> walkthrough for driving the UI by hand.

**Every number below is produced live by the running system.** Nothing on screen
is typed into a slide. If a figure here disagrees with what the screen shows,
the screen is right and this document is stale — run `make ui-check`, which
asserts the on-screen counter equals the cascade's own material count.

## Before you start

```bash
make install
make ui          # http://127.0.0.1:8000
```

No GCP account is needed. The cascade is T0/T1 and makes zero model calls, so
the entire demo runs with Vertex switched off — which is itself part of the
story, not a workaround.

Full screen, 1600×900 or wider. Hand the keyboard over at 0:15.

---

## The script

| Time | Screen | What you say |
| --- | --- | --- |
| **0:00–0:15** | The field | "Four thousand two hundred live decisions, resting on eleven hundred premises. The amber number is causal debt — **418.3** — how much of this stands on something shaky. That's a normal Tuesday. Nothing is wrong yet." |
| **0:15–0:35** | The bar | "One input. Type a fact that changed." *(hand over the keyboard — they type `supplier_K lead time is now 20 days`)* |
| **0:35–0:50** | Parse echo | "Before it touches anything, it tells you what it heard. Read as `supplier_K.lead_time_days`, eleven to twenty, carrying **2,594** decisions. If that's wrong, this is where you say so — a misparse arrives as a question, not as a correction somebody receives." |
| **0:50–1:05** | ⓪ The refusal | *(press R, type `broker says supplier_K lead time is 34`)* "Different source. The freight broker has authority over its own freight claims and none over the supplier's lead time. It refuses, names the reason — `source_outside_claim_scope` — and the radius is zero. A false retraction is worse than a missed one." |
| **1:05–1:25** | The wave | *(back to the supplier retraction, Confirm)* "The load lines go slack first — the premise stops bearing. Then two and a half thousand decisions light up, in depth order. That's the traversal, not an animation of one." |
| **1:25–2:00** | ⑤ **The cull** | *(let it run — ~15 seconds of silence)* "Now watch it come back down. **2,594 to 78.** 1,468 immaterial — the buffer absorbed the shock. 874 already closed out — the world moving cannot hurt a delivery that completed in March. 174 sent to judgment rather than guessed. **That's 90% culled by arithmetic, with the model switched off.**" |
| **2:00–2:20** | ⑥ The split | "Seventy-eight actually changed. Thirty are still correctable in place. **Forty-eight already went out to someone** — and **15 of those went out 120 days or more before the fact changed.** The oldest is 182 days. That gap is the entire product." |
| **2:20–2:45** | ⑦ The court | "Twelve owners seated from 48 eligible. Each owns one commitment and argues for it — that's a conflict of interest, deliberately. This one owns nothing and rules: **preserved 0, amended 7, conceded 5**, and it's marked advisory because the exposure is above the signing threshold. Dissent is recorded, not dropped. Twelve owners plead in parallel and the arbiter keeps the floor — `tests/test_court.py` asserts the pleas genuinely overlap in wall-clock time rather than trusting the docstring." |
| **2:45–3:20** | ⑧ **The obligation** | *(the field dissolves into paper)* "This is what the company now has to tell a customer. Named counterparty. One quote it can re-issue. **One payment it cannot take back** — that's the `[X]`. Residual exposure **USD 8,925.00**, as a range with its assumptions, never a point estimate. And a named human who has to sign it. That tag at the bottom says this was drafted without a model, because Vertex is off — it stays visible." |
| **3:20–3:35** | ⑨ Load rating | "The source that was wrong now carries less weight: **0.72 to 0.43**. Versioned and reversible — the downgrade appends, it never overwrites. And it's the *source's* rating, not the extractor's: an agent can read a liar perfectly." |
| **3:35–4:00** | ⑩ Honesty panel | *(press H)* "Extraction coverage including where it's bad — **81.8% overall, 66.7%** on absolute durations, highlighted, because that's exactly where the second pass earns its place. What's built, what's only designed. And the credentials status, which now records a real Vertex run: call OK, zero model errors." |

**Closing card:** `THE WORLD CHANGED. YOUR DECISIONS DIDN'T.`

---

## The three moments that carry it

1. **The cull.** Let it run. Do not talk over the first ten seconds. A judge who
   watches 2,594 become 78 without a model call understands the architecture
   before you explain it.
2. **The dissolve into paper.** The register change from machine to document is
   the argument that this is a write path and not a dashboard.
3. **The `[X]`.** One line that says a thing cannot be undone. Everything else
   in the demo is recoverable; that line is why the system exists.

## If the live run fails

`make golden` writes a deterministic transcript of the same cascade. If the API
is unreachable the UI shows a **full-width banner reading "REPLAY — live run
failed, this is a recorded execution"**, and it is never concealed. Say it out
loud if it happens; a disclosed replay costs less than a concealed one.

## What a judge will ask, and the short answer

- **"Why is Gemini load-bearing if the extractor is a regex?"** — Because the
  regex handles the easy half on purpose: it has no instruction-following
  surface, so injection fails structurally rather than through a filter. Gemini
  is the second pass on what the parser cannot read — the 66.7% class. `make
  verify-live` measures the delta; see `docs/LIVE-VERIFICATION.md`.
- **"Is the cull real or a tween?"** — Real. The counter is decremented inside
  the SSE handler and nowhere else, so it equals the number of events received.
  `make ui-check` asserts the final on-screen figure equals the cascade's own
  material count. Delivery is paced ~6 ms per batch for legibility and the
  screen says so.
- **"Why Flash and not Pro?"** — No Gemini 3.x Pro is GA as of 2026-08-12. Both
  models here are GA, chosen for live-demo reliability: a preview model can
  change or throttle underneath a demo.
- **"What isn't built?"** — Press H. Compensation synthesis refuses rather than
  guessing, Model Armor is unconfigured, and three of the four architectural cards
  — WARRANT, CONTROL TOWER, COUNTERSIGN — are locked design that is not built.
