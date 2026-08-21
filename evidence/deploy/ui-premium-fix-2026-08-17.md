# Premium UI repair — 2026-08-17

## Root cause of the "plain white HTML controls" appearance

`.home-card` (a `<button>` in the four-card tile menu added earlier the
same day) never got an explicit `color`. Browsers do not cascade text
colour into `<button>` elements from an ancestor the way they do into a
`<div>` — the UA stylesheet gives the button its own default (black
text, native chrome) regardless of the page's dark theme. Confirmed via
headless-Chromium computed-style inspection against the live deployed
URL: `getComputedStyle(.home-card).color` was `rgb(0, 0, 0)` while
`body`'s colour was the intended bone `rgb(237, 232, 222)`. All
network requests (style.css, app.js, fonts) returned 200 — this ruled
out an asset-loading failure; the defect was purely a missing CSS
property on a native form control.

## Why the fix is not just "add `color`"

Patching `.home-card` would have left a *different* problem: the tile
menu was the wrong default screen. `web/static/style.css`'s own
`.instr-card`/`.instr-card0` overlay (`THE INSTRUMENT`, built earlier)
already renders the exact composition requested — WARRANT full-width
hero, SVG evidence lines flowing down, three cards in a row — using
only real API data (warrant bars, registry state, agreement rate). So
`#home` was retired entirely and `#instrument` became the default
landing view. See commit `ae027ac` for the full diff and reasoning.

## Verification (headless Chromium, real Cloud Run URL)

Local dev server and `https://unwind-hgeodtazqq-uc.a.run.app` (revision
`unwind-00007-2cn`), both checked:

- Fresh load: all four cards visible, no `T` keypress needed — PASS
- Click Card 0 (Warrant head) → stays on instrument, visible pulse — PASS
- Click Card 1 (Unwind Core) → opens Core (canvas + retraction bar) — PASS
- Click Card 2 (Control Tower) → stays on instrument, visible pulse — PASS
- Click Card 3 (Countersign) → stays on instrument, visible pulse — PASS
- `Esc` from Core → returns to the instrument — PASS
- `T` from Core → returns to the instrument — PASS
- "◂ the four cards" link (visible only while in Core) → returns to the instrument — PASS
- BURN button → real `/api/instrument/burn` call, bar/route update in
  place from the response; HIGH-risk balances start at 0bp so the very
  first click reaches a real `WARRANT_INSUFFICIENT` refusal (not a
  fake animation) — PASS
- EARN button → real `/api/instrument/earn` call, rookie LOW balance
  visibly moved 400bp → 300bp on screen from the live response — PASS
- Desktop (1440px) / laptop (1024px) / mobile (390px): WARRANT full
  width in all three; laptop keeps the same proportional hierarchy;
  mobile stacks the three lower cards — PASS
- Console/page errors: zero on both local and the deployed URL
- Note: the first `/api/instrument` fetch against the live Cloud Run
  URL takes ~1–1.8s (real Firestore round trip on a cold path, not a
  UI defect) — verification waits accounted for this

Screenshots: `evidence/deploy/shots/04-deployed-instrument-premium.png`
(fresh load, live URL), `05-deployed-core-from-card1.png` (Core opened
from Card 1, live URL), `06-instrument-mobile.png` (390px viewport).

## Tests and checks re-run after the fix

- `FIRESTORE_EMULATOR_HOST=localhost:8080 pytest -q` — 369 passed
- `bash scripts/verify_adk_mapping.sh` — 10/10 PASS
- `python scripts/check_contrast.py` — clean, no eighth colour, no gradients, radius ≤ 4px
- `ruff check . && ruff format --check .` — clean
- `git diff --stat stage-one-floor -- spine/ court/ judgment/ settle/` — empty (frozen dirs untouched)
- `bash scripts/health_check.sh` against the redeployed URL — PASS (`evidence/health/health-20260817T034428Z.md`)

## Redeploy

`UNWIND_PROJECT_ID=project-895d4ca8-d301-447d-916 UNWIND_RUN_REGION=us-central1 UNWIND_VERTEX_LOCATION=global ./infra/deploy.sh`
→ revision `unwind-00007-2cn`, 100% traffic, same URL
(`https://unwind-hgeodtazqq-uc.a.run.app`). Full log:
`evidence/deploy/deploy-20260817T034428Z.log`.
`evidence/deploy/deploy-20260817T031109Z.log` is a *prior* deploy from
earlier in this session (revision `unwind-00006-stk`) that predates
this fix — it shipped Prompt 9's tile-menu home screen, not the
premium instrument-as-default fix described here.
