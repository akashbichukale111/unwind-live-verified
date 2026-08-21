# Mission Time Machine — root cause and fix

## The bug

Clicking **MISSION TIME MACHINE ▶** appeared to do nothing.

## Root cause — a regression introduced by the authentication pass

`/api/command-os/missions` and `.../checkpoints` were placed behind
`require_principal` when authentication was added. The two `fetch` calls in
`showTimeMachine()` and `loadCheckpointTimeline()` were **not** updated at
the same time — they used the bare `fetch`, not the `authedFetch` helper
that `runMission` uses.

The consequence chain:

1. bare `fetch` sends no `Authorization` header → **401**
2. `d.available` is `undefined` → the `!d.available` branch runs
3. that branch rendered **"no missions recorded yet"** — the *same* empty
   state as a genuinely empty database
4. the panel therefore opened onto an empty column and reported the cause as
   "no missions" when the real cause was "not authenticated"
5. and because the bare `fetch` bypassed `authedFetch`, the
   `#cmdos-authfail` banner that exists precisely to say "your token is
   missing" never appeared

Reproduced before fixing (`/tmp/repro.py`): section visible `True`,
`#mtm-missions` innerHTML 132 chars, total page text 402 chars, console
`401 (Unauthorized)`. The section *did* open — it was simply blank, which
is indistinguishable from "the button does nothing".

**A second, independent bug** was found while fixing it: `Escape` from the
Time Machine called `showInstrument()`, stranding the user one screen away
from the Agentic Command OS they had opened it from.

## Fix

| File | Change |
| --- | --- |
| `web/static/app.js` | both Time Machine fetches now use `authedFetch`; **NOT AUTHENTICATED / FIRESTORE UNREACHABLE / empty / loaded are four distinct rendered states**; `Escape` from `mission-time-machine` returns to Agentic Command OS; added an `esc()` HTML-escaper and applied it to all server-derived text |
| `web/static/index.html` | added `#mtm-timeline` (mission arc) and `#mtm-state` (current state + capabilities) |
| `web/static/style.css` | `.mtm-arc`, `.mtm-state`, `.mtm-caps` — existing tokens only, contrast check passes |

An empty panel can no longer mean two different things.

### Security fix found in passing

The original code interpolated the operator-supplied `objective` into
`innerHTML` unescaped. Objectives round-trip through Firestore, so that was a
**stored XSS** path: an objective containing a script payload would execute
for the next operator who opened the panel. Now escaped, and tested — a
mission was run with the objective
`<img src=q onerror=window.__XSS__=1>pwn`, and the payload renders as
literal text, injects no `<img>` element, and does not execute.

## Behaviour before / after

| | Before | After |
| --- | --- | --- |
| Click, no token | blank panel saying "no missions recorded yet" | **NOT AUTHENTICATED**, with what to do |
| Click, with token | blank panel saying "no missions recorded yet" | mission list + 12 checkpoints, most recent auto-opened |
| Mission arc | none | 12 nodes, current one marked |
| Current state | none | status, checkpoints, trusted/quarantined/revoked |
| ESC | → Instrument | → **Agentic Command OS** |
| Hostile objective | executed as HTML | rendered as text |

## Replay / resume — labelled honestly

- **RESUME FROM LAST CHECKPOINT — LIVE.** `command_os/mission.py:resume_mission`,
  three real cases. Control is **disabled with the reason shown** when the
  mission is final, rather than offering a button that no-ops.
- **REPLAY FROM AN ARBITRARY CHECKPOINT — NOT IMPLEMENTED.** `resume_mission`
  continues strictly after the *last* persisted checkpoint. Re-entering at
  checkpoint N < last would need compensation for the external action and
  warrant already spent beyond N. Not faked.

## Verification

`evidence/browser/verify_timemachine_and_media.py` — **33/33 checks**, real
Chromium, against a live server on this branch. Screenshots:
`evidence/browser/timemachine.png`, `evidence/browser/media-lab.png`.
