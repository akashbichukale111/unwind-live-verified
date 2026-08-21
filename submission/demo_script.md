# Demo script v2 — the four-card system

**Target runtime 4:00 · hard ceiling 4:00.** Voiceover budget **≤560 words**
(≈140 wpm at an unhurried pace). Actual count is asserted at the bottom of
this file, by the same command that measured it.

**Every shot is marked `LIVE (deployed)` or `CUTAWAY`.** `LIVE (deployed)`
runs against the Cloud Run URL, unedited, in one take — as of 2026-08-17,
ALL FOUR CARDS are live there (revision `unwind-00005-2bl`,
`evidence/deploy/deploy-20260817T022816Z.log`), so nothing in this script
needs to fall back to localhost. `CUTAWAY` means a static screen — a
console, a file, a terminal that already finished. There is no third
category, and nothing here is a slide with numbers typed onto it.

> Superseded disclosure, kept for the record rather than deleted: an
> earlier draft of this script ran Act 2 against `127.0.0.1` because the
> deployed URL served Card 1 only at the time. Redeploying Cards 0–3
> (`evidence/firestore/deploy-2026-08-17.md`) closed that gap before
> recording — re-verify with `bash scripts/health_check.sh` immediately
> before rolling, same as always, in case the service has drifted since.

> **Rule for the presenter:** if a figure on screen disagrees with this
> document, the screen is right and this document is stale. Re-run
> `make ui-check` (Card 1) or `python scripts/rederive_warrant.py` (Card 0)
> to confirm before recording.

---

## Recording checklist

Work top to bottom. Do not skip the warm-up — a cold start on camera looks
exactly like a broken demo.

### Capture settings

- [ ] **Resolution 1920×1080**, 30 fps minimum. Record the *screen*, not a
      window, so the Cloud Run console, the terminal, and the browser are
      all the same capture.
- [ ] **Cursor visible.** Highlight/click-effects **off**.
- [ ] Microphone tested with **one** trial sentence played back.
- [ ] Browser at **100% zoom**, full screen, no bookmarks bar, no
      extensions visible, OS Do Not Disturb **on**.
- [ ] Terminal font **16pt or larger** — the `SYNTHETIC` labels in the
      instrument UI and the terminal's `SYNTHETIC`/`EARNED` lines must both
      be legible at 1080p. Test by squinting at a thumbnail.

### Warm-up — do this immediately before rolling

- [ ] `bash scripts/health_check.sh` → must print **PASS**. Hit one on the
      deployed URL.
- [ ] Open the deployed URL in the browser and let the field fully render.
      Hit two. **Wait for the second response before recording.**
- [ ] Run the cascade once, off-camera, so shot 1.4 does not stall.
- [ ] Confirm the Cloud Run console tab is already open, logged in, `unwind`
      service green — shot 1.1 must not include a login.
- [ ] Act 2 now runs against the SAME deployed URL as Act 1 — no local
      server needed. Off-camera, once: press `T` on the deployed URL and
      confirm the instrument renders with real bars, so the on-camera load
      in shot 2.1 is not the first one against production.

### Shooting

- [ ] Record **one continuous take per act**. Splicing *within* a LIVE shot
      is not allowed — the video claims unedited execution.
- [ ] Shot 1.4: **say nothing for six seconds.** Count it.
- [ ] Do not move the mouse during the cull or during the warrant bar
      animation (shot 2.2).
- [ ] If a LIVE shot fails, restart that act. Do not cut around the
      failure.

### Upload

- [ ] Trim to **≤4:00**. Check the final duration before uploading.
- [ ] Upload to **YouTube**, visibility **Public**.
- [ ] Title, English: `UNWIND — Consequence Clearing | Google All Things
      Agentic Hackathon`
- [ ] Description: one-line thesis, repo URL, deployed URL.
- [ ] Language **English**; auto-captions on.
- [ ] Watch the uploaded video **once, end to end, signed out**.
- [ ] Paste the URL into `submission/devpost.md` → Links → Demo video and
      into `submission/CHECKLIST.md`.

---

## ACT 1 — the thesis and the cull (0:00–1:05) · deployed

### 1.1 · 0:00–0:12 · `CUTAWAY` — Cloud Run console
Service `unwind`, region `us-central1`, green check, revision visible.

> This is UNWIND, on Cloud Run. Card One of a four-card system — the part
> that's deployed today.

### 1.2 · 0:12–0:28 · `LIVE (deployed)` — the field
The deployed URL. 4,206 nodes, causal debt in amber.

> Four thousand two hundred live decisions. A supplier says eleven days, so
> you quote, you order, you promise a customer. Then the world changes —
> and nothing points backwards from the fact to what was built on it.

### 1.3 · 0:28–0:42 · `LIVE (deployed)` — type into the bar, parse echo appears
Type `supplier_K lead time is now 20 days`. Do not press Confirm yet.

> Before it acts, it tells you what it heard: eleven to twenty, carrying
> two thousand five hundred ninety-four decisions.

### 1.4 · 0:42–1:05 · `LIVE (deployed)` — Confirm, then the cull. **Say nothing for six seconds.**

> Down to seventy-eight. Ninety percent removed by subtraction — model
> switched off, enforced in CI.

---

## ACT 2 — WARRANT and COUNTERSIGN, on the deployed service (1:05–2:55)

### 2.1 · 1:05–1:22 · `LIVE (deployed)` — press `T`
Still `unwind-hgeodtazqq-uc.a.run.app`. The four-card instrument opens.

> Three more cards live on this same deployed service — Warrant, Control
> Tower, Countersign. Three hundred sixty-nine tests passing, and this is
> the real thing, not a local rehearsal.

### 2.2 · 1:22–1:47 · `LIVE (deployed)` — the instrument, BURN
Every warrant bar reads `SYNTHETIC`. Click "Overturn a HIGH-risk judgement."

> Every bar here is labelled synthetic — seeded history, and it says so on
> screen, not just in a caption. Watch this one. A human overturns a
> judgement — the bar drops past the line — and the very next case of that
> kind is refused and routed to a person. No cache. This is the twenty-five
> second version of the whole warrant system.

### 2.3 · 1:47–2:08 · `LIVE (deployed)` — cold-start agent earns its first delegation
Click "Earn the rookie's first delegation."

> This agent started at zero — no seeding at all. A human concurs, an
> independent model countersigns, and it mints — live, on this run. The
> label flips from synthetic to earned. That's the only number in this
> whole demo that wasn't fabricated in advance.

### 2.4 · 2:08–2:30 · `CUTAWAY` — `countersign/DESIGN.md`, the live-Vertex attempt
Scroll to the escalation table: 403, then a real 404.

> Real Gemma access was attempted this session — real authentication, a
> real round trip to Vertex — and a real four-oh-four: this project doesn't
> have Model Garden access yet. So the agreement rate you're about to see
> is from a labelled simulator, not a live model. We say so everywhere it
> appears.

### 2.5 · 2:30–2:55 · `LIVE (deployed)` — Card 3 panel, agreement rate, freeze mark

> Seventy-five point six percent agreement across forty-one scenarios,
> simulated. Ten disagreements — each one froze a mint with a challenge
> mark, permanently, right here on the paper.

---

## ACT 3 — the honesty apparatus, and close (2:55–4:00) · deployed

### 3.1 · 2:55–3:16 · `LIVE (deployed)` — back to the deployed URL, press `H`

> Back on the deployed service — press H. This publishes the worst thing
> about the system on purpose: extraction recall is sixty-six point seven
> percent on absolute durations.

### 3.2 · 3:16–3:38 · `CUTAWAY` — README honesty map

> Parser alone, eighty-one point eight. Parser plus Gemini, one hundred —
> but the model's denominator is eight, not forty-four. Judgement quality
> is still unmeasured, and we call that a non-test, not a result.

### 3.3 · 3:38–4:00 · `LIVE (deployed)` — close card

> We evaluated Veo and Lyria and cut both — they failed our own necessity
> test. A model added for the sake of breadth is a model this architecture
> doesn't need. The world changed. Your decisions didn't — until now.

**Close card:** `THE WORLD CHANGED. YOUR DECISIONS DIDN'T.`

---

## The three moments that carry it

1. **The cull (1.4).** Silence over 2,594 becoming 78 says more than
   narration can.
2. **The bar dropping past the line (2.2).** Twenty-five seconds, one state
   change, no narration needed — the whole warrant thesis in one animation.
3. **`SYNTHETIC` flipping to `EARNED` (2.3).** The only number in the demo
   that becomes true during the recording instead of before it.

## If a live run fails

`make golden` writes a deterministic transcript of the Card 1 cascade. If
the deployed API is unreachable, the UI shows a full-width banner reading
**"REPLAY — live run failed, this is a recorded execution"** — never
concealed, said out loud if it happens. For Act 2, if the local server or
emulator fails to start during warm-up, do not attempt Act 2 live; cut it
from that take and note the gap in the video description rather than fake
the click sequence.

---

## PLANNED — video v3 replacement

| Replaces | v3 shot | Requires |
| --- | --- | --- |
| 2.4–2.5 | A genuine live Gemma verdict replacing the simulated agreement rate | Model Garden access to `gemma-3-27b-it` granted on the project |

(The redeployment item that used to be here is done — Cards 0–3 and the
instrument have been live on the Cloud Run URL since 2026-08-17. This
script's ACT 2 already reflects that.)

---

## Voiceover word count

Counted over the blockquoted voiceover lines inside the three acts only —
excluding stage directions, headings, tables, and this note:

```bash
awk '/^## ACT 1/,/^## The three moments/' submission/demo_script.md \
  | grep '^> ' | sed 's/^> //' | wc -w
```

**Measured: 407 words** — budget 560, well inside it. At 140 wpm that is
**2:54** of speech inside a 4:00 ceiling, leaving substantial room for the
silent beat (shot 1.4), the two full-take reaction pauses in Act 2 (shots
2.2 and 2.3, where the animation and the label flip need a second or two of
unforced silence to read on screen), and pacing slower than 140 wpm without
overrunning.
