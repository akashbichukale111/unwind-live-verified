# The video plays, the audio is audible, and neither is a model call

**Date:** 2026-08-25 · **Branch:** `claude/video-player-bonus-model-nmwlbp`

This is the single evidence file for one change: the Mission Media Lab now
plays a real video and a real, audible audio track **on a deployment that has
never held a Vertex credential** — while still reporting, on the same cards,
that no live Veo or Lyria call can be made there.

Both halves of that sentence had to be true at once, and that is what this
file proves. Everything below was measured, not asserted.

---

## 1. The problem this fixes

| Reported | What was actually happening |
|---|---|
| "the Mission Time Machine button does nothing" | It navigated to a **separate screen**. On a deployment where mission history is a protected read, that screen loaded, showed one line, and the operator was now one screen away from the mission they had been looking at, with a back link they had to find. |
| "the video option doesn't play anything" | Correct, and not a bug in the player. `.media/` is **gitignored generated output** (`.gitignore`: *"a generated video/audio file is not reproducible by any test and must not be committed as if it were evidence of a call this repo can re-run"*). The one real Veo/Lyria pass wrote its bytes to a laptop on 2026-08-21. A Cloud Run revision has never had them, so `/api/media/verified-evidence` correctly reported `available: false` and the panel correctly stayed hidden. Correct behaviour, and a Media Lab that could not show media. |
| "the bonus models look bolted on" | The Media Lab sat below the consequence preview, at the very bottom of the page, after eleven other panels. |

## 2. What was built

`scripts/build_demo_media.py` renders a **deterministic local bundle** from
`evidence/media/grounded-brief-20260820T092845Z.json` — the exact grounded
brief `media/grounding.py` built from the 12 checkpoints
`command_os/checkpoint.py` actually persisted for `mission_628ee1fb5b`.

It reaches no network, resolves no credential, and calls no model.
`tests/test_demo_media.py::test_the_generator_reaches_no_network_and_no_model`
enforces that structurally, by refusing the import of any Google client,
HTTP library or socket module in that file. **That property is the entire
reason these bytes may be committed when `.media/` may not:** a fresh clone
regenerates them from committed input alone.

Nothing in the bundle is presented as model output. Every player carries the
label `PLAYS NOW · deterministic local render of mission_628ee1fb5b's 12
persisted checkpoints — NOT a VEO generation` in the same string that builds
the player, so the two cannot be rendered apart.

## 3. The committed bytes

| file | bytes | sha256 |
|---|---:|---|
| `manifest.json` | 869 | `54c2a28d6abb57c899641e776ae5923f7e572435e91fbb26a0db19cd98140109` |
| `mission-narration.txt` | 1,217 | `c65da3174ae930f4e84dba8cbab5a57cbe9b8bd35f45c626b7ea4270ab814c23` |
| `mission-replay-poster.jpg` | 96,793 | `e86096c22097d1d35ef11a7571dd39a82716f6040cbd4ed45d95e03a63b0041c` |
| `mission-replay.mp4` | 1,106,882 | `c900d13cb9ab678b64d36feabb326d5e5ada8b1d33b10eb5cdb94a10d8f6c38b` |
| `mission-replay.webm` | 1,155,652 | `b252de165e98755f0ac0285b8685dc36584cadf413d74e89f93707ccaa1d376f` |
| `mission-signal.wav` | 3,087,044 | `927a005df5328b0a2b7d36c6019806450547fcfd382a4712c9072f28accfaa7a` |

Served from `web/static/media/`, which `.gcloudignore` explicitly keeps in the
Cloud Run upload (*"web/static/ — the API serves the operator UI from it"*), so
these bytes reach the deployment. `GET /api/media/model-roster` reports the
bundle and only lists a file it has confirmed is on disk.

## 4. The video decodes — two containers, one render

```
mission-replay.webm
  Duration: 00:00:35.01, bitrate: 264 kb/s
  Stream #0:0: Video: vp9 (Profile 0), yuv420p(tv, progressive), 1280x720, 24 fps
  Stream #0:1: Audio: opus, 48000 Hz, mono

mission-replay.mp4
  Duration: 00:00:35.00, bitrate: 253 kb/s
  Stream #0:0: Video: h264 (High) (avc1), yuv420p(progressive), 1280x720, 24 fps
  Stream #0:1: Audio: aac (LC) (mp4a), 44100 Hz, mono
```

**Two containers is not belt-and-braces.** The first pass shipped MP4 only and
the headless Chromium this repository's own browser evidence runs in refused it
with `MEDIA_ERR_SRC_NOT_SUPPORTED` (error code 4) — that build has no
proprietary codecs. Safari and iOS are the mirror case and need the H.264/AAC.
Both files come from **one** pass over the frames, so they are the same
artefact in two wrappers, and the page emits them as ordered `<source>`
children for the browser to choose between.

## 5. The audio is audible for its whole length

Not "a WAV exists" — RMS measured over every two-second window, because a
single loud click at the start would pass a peak check and leave 34 seconds of
silence behind it.

```
 t= 0s  rms= 2404   -22.7 dBFS   peak= 8813      t=18s  rms= 8175   -12.1 dBFS   peak=26555
 t= 2s  rms= 9164   -11.1 dBFS   peak=19957      t=20s  rms= 8114   -12.1 dBFS   peak=25725
 t= 4s  rms= 9181   -11.1 dBFS   peak=23931      t=22s  rms= 8958   -11.3 dBFS   peak=27551
 t= 6s  rms= 8509   -11.7 dBFS   peak=26231      t=24s  rms= 9611   -10.7 dBFS   peak=24510
 t= 8s  rms= 8188   -12.0 dBFS   peak=27167      t=26s  rms= 9161   -11.1 dBFS   peak=24360
 t=10s  rms= 8228   -12.0 dBFS   peak=25331      t=28s  rms= 8202   -12.0 dBFS   peak=21481
 t=12s  rms= 8985   -11.2 dBFS   peak=29162      t=30s  rms= 7511   -12.8 dBFS   peak=21795
 t=14s  rms= 8842   -11.4 dBFS   peak=28825      t=32s  rms= 7955   -12.3 dBFS   peak=22235
 t=16s  rms= 8502   -11.7 dBFS   peak=25888      t=34s  rms= 2868   -21.2 dBFS   peak=10884
```

17 windows. Quietest −22.7 dBFS (the fade-in), loudest −10.7 dBFS. Nothing
approaching silence anywhere in the file.
`tests/test_demo_media.py::test_audio_is_audible_for_its_whole_duration` runs
this same measurement in CI with a −30 dBFS floor.

**What the sound actually is.** One drone for the whole mission, detuned by the
mission's closing drift band (`ELEVATED` → 0.9 Hz, so it beats slowly against
itself); one struck note per checkpoint climbing a minor pentatonic ladder; and
at checkpoint 4 — `CONTAIN — fleet_recon ISOLATED` — a drop of a fifth below
the root instead of a climb. The most audible event in the piece is the most
important event in the mission. The tail resolves to the major third only
because that mission closed `verified: true`.

## 6. A real browser actually played both

`evidence/browser/verify_timemachine_and_media.py`, run against a live server
with the Firestore emulator — **55/55 checks passed**
(`browser-verification-20260825T040721Z.log`, full log in this directory):

```
== THE COMMITTED RENDER PLAYS, WITH NO CREDENTIAL ==
  PASS  gemini: player is inside its own card
  PASS  gemini: labelled a local render, not a generation
  PASS  veo: player is inside its own card
  PASS  veo: labelled a local render, not a generation
  PASS  lyria: player is inside its own card
  PASS  lyria: labelled a local render, not a generation
  PASS  VIDEO really plays — decoded frames, clock advancing — 1280x720 at t=2.89s · mission-replay.webm
  PASS  AUDIO really plays — unmuted, clock advancing — 35.0s track at t=2.91s · mission-signal.wav
  PASS  GEMINI card shows its zero-model mission intelligence — 1187 chars
```

`videoWidth = 1280` proves frames were **decoded**, not that a container was
parsed. `currentTime > 0` with `error === null` and `muted === false` proves
playback **ran**, not that a file loaded. Those are the two things a size check
cannot tell you.

And in the same run, on the same page, unchanged:

```
  PASS  all three CONFIGURED_NOT_EXERCISED
  PASS  no fake LIVE claim
  PASS  note explains fail-closed
  PASS  gemini returns NOT_CONFIGURED     PASS  veo NOT_CONFIGURED, no fake video
  PASS  reason is real                    PASS  lyria NOT_CONFIGURED, no fake audio
  PASS  panel honestly stays hidden — no local .media/ artefacts in this environment
```

The committed render did not make the live-call path dishonest. Both are on
screen, labelled differently, saying different things.

## 7. The Time Machine button is gone; the Time Machine is not

It is now a heading at the bottom of the Agentic Command OS page, loaded with
everything else on it.

```
== MISSION TIME MACHINE (the reported bug) ==
  PASS  renders inline, with no button pressed
  PASS  no Time Machine button remains
  PASS  did not navigate away from Agentic Command OS
  PASS  mission list populated — 8 missions
  PASS  checkpoints auto-load — 13 checkpoints
  PASS  mission arc renders — 13 nodes
  PASS  current node marked
  PASS  RESUME labelled LIVE
  PASS  REPLAY honestly NOT IMPLEMENTED
  PASS  checkpoint detail opens

== NO NAVIGATION HAPPENED ==
  PASS  still on Agentic Command OS after opening a checkpoint
  PASS  the Media Lab is still on screen alongside it
```

Two consequences of inlining a panel that used to be reached by a button, both
handled rather than discovered later:

- Its mission-history read is authenticated. Firing on page load, it raised the
  page-level `NOT AUTHENTICATED — every mutating endpoint refuses an anonymous
  caller` banner at every anonymous visitor, for a passive read they never
  asked for. Those three reads now pass `quietAuth`; the Time Machine still
  says NOT AUTHENTICATED **in its own panel**, where it is true and actionable.
- Its arc and checkpoint columns are always on screen now. A column rendering
  nothing is indistinguishable from a column that failed, so every terminal
  state fills them in (`mtmPlaceholder`) instead of leaving them blank.

## 8. Every model is visible, with what a real call did

`GET /api/media/model-roster` joins the model IDs from `lib/config.py` — the
only file allowed to hold one — to the statuses in the newest
`evidence/models/verification-*.json`, which is written by a script that made
the call. Neither half is typed into the page.

| family | model | status | evidence |
|---|---|---|---|
| Gemini | `gemini-3.6-flash` | LIVE_VERIFIED | real call returned in 6,530 ms |
| Gemini | `gemini-3.5-flash-lite` | UNVERIFIED | no verification pass names this exact string |
| Gemma | *(see `lib/config.py`)* | UNAVAILABLE | Google's verbatim 404: publisher model not found for this project/region |
| Veo | `veo-3.1-generate-001` | LIVE_VERIFIED | real call returned in 86,125 ms |
| Lyria | `lyria-002` | LIVE_VERIFIED | real call returned in 38,469 ms |

**3 of 5 model strings have a recorded live call.** The page says exactly that,
including the two that do not. A status is only accepted when the verification
record names the *same* string `lib/config.py` currently pins — a green tick
carried over from a previously-pinned ID would be a claim about a model this
build does not use.

## 9. Screenshots

| | |
|---|---|
| `shots/04-page-top-no-button.png` | Top of the page. No Time Machine button. The model stack and all three players are above the fold. |
| `shots/01-model-stack-playing.png` | The five model chips and the three cards, audio transport mid-playback. |
| `shots/02-veo-card-playing.png` | The Veo card at t≈13 s, showing checkpoint 8 rendered in amber because that checkpoint is `SIMULATED`. |
| `shots/03-time-machine-inline.png` | The Time Machine as a section of the same page: arc, current mission state, resume panel. |

## 10. Reproducing all of it

```bash
python scripts/build_demo_media.py          # re-renders the bundle byte-for-byte
python -m pytest tests/test_demo_media.py   # 9 passed
python -m pytest -q                         # 645 passed, 1 skipped
ruff check . && ruff format --check .       # clean

./infra/emulator.sh &
FIRESTORE_EMULATOR_HOST=localhost:8080 UNWIND_DEV_PRINCIPAL="human::kim@ops.example" \
  python -m uvicorn services.api.main:app --port 8099 &
python evidence/browser/verify_timemachine_and_media.py   # 55/55
```

## 11. What is still not true

- **No Veo or Lyria call was made for this change.** No GCP credential existed
  in the environment it was built in. The 2026-08-21 pass remains the only real
  media generation this project has run, its bytes are still gitignored, and
  the panel that would play them still stays hidden wherever they are absent.
- **This does not deploy itself.** The bytes are committed and `.gcloudignore`
  carries `web/static/` into the upload, so they go live on the next
  `gcloud run deploy`. Until that runs, the deployed revision is unchanged.
