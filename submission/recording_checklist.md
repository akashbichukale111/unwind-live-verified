# Recording checklist — video v1

Follow in order. This checklist exists so the mandatory Stage One
requirements (live unedited execution, visual proof of Google Cloud, public
on YouTube/Vimeo, English) are satisfied by the recording itself, not fixed
in post.

## Before you hit record

- [ ] **Cold-start avoidance:** hit the deployed URL **twice** —
      `curl -s -o /dev/null -w "%{http_code}\n" https://unwind-hgeodtazqq-uc.a.run.app/api/healthz`
      (or just load it in a browser tab and reload once) — before recording.
      A cold Cloud Run instance adds several seconds of dead air the first
      time it's hit; the second hit is warm.
- [ ] Open the **Cloud Run console** tab in advance: Console → Cloud Run →
      `unwind` service → `us-central1` — this is the visual proof of Google
      Cloud the rules require. Have it ready to switch to at 0:00, not
      hunted for on camera.
- [ ] Open a second tab on the deployed UI itself:
      `https://unwind-hgeodtazqq-uc.a.run.app`
- [ ] Open a terminal window sized to be legible at 1080p, for the CUTAWAY
      shots in `submission/demo_script.md` (`pytest tests/test_zero_model.py
      -v`, `make deploy-verify`, `docs/LIVE-VERIFICATION.md`).
- [ ] Close anything with notifications (Slack, email, OS banners) — an
      unrelated popup mid-recording is grounds for a re-take, not an edit.
- [ ] Rehearse the voiceover in `submission/demo_script.md` once at real
      speaking pace with a timer. 392 words should land at roughly 2:30–2:50
      of actual speech inside a 4:00 video, leaving room for the silent
      ~15-second cull-counter shot Act 1 calls for.

## Capture tool settings

- **Resolution:** 1920×1080 minimum. Browser window / OS display scaled so
  UI text is legible at that resolution — test by scrubbing to the honesty
  panel (Act 3) and confirming the 66.7% figure is readable.
- **Frame rate:** 30fps or 60fps (60 preferred — the field animates at 60fps
  per `docs/evidence/README.md`, and a lower capture rate can visually
  undersell it).
- **Audio:** record voiceover live during capture, not dubbed after — this
  keeps the video an honest record of one continuous take per the "live
  unedited execution" requirement. A wired or headset mic beats a laptop's
  built-in mic for clarity.
- **Cursor visibility:** turn ON cursor highlighting / click visualization
  in the capture tool. A judge needs to see exactly where you clicked and
  typed — the parse echo, the refusal, pressing H — without narrating every
  mouse movement.
- **Window capture, not full desktop:** capture the browser window (and the
  terminal window for cutaways) directly, not the whole desktop, to avoid
  exposing unrelated tabs, files, or notifications.

## The Cloud Run console shot

- [ ] At 0:00–0:15 (Act 1 of `submission/demo_script.md`), the Cloud Run
      console must be on screen showing: service name `unwind`, region
      `us-central1`, and a ready/serving status — this is the visual proof
      of Google Cloud the Stage One rules require. A URL bar showing
      `*.run.app` alone is not sufficient; the console page must be visible
      at least once.
- [ ] Optionally repeat the Cloud Run console as a CUTAWAY later if there's
      a natural beat for it (e.g. confirming the revision is still healthy
      after the cascade runs) — not required, but strengthens the proof.

## Recording

- [ ] Record in one continuous take per the script's Acts — CUTAWAY shots
      are separate unedited clips (a second live artifact, not a slide),
      not compositing within a LIVE shot.
- [ ] If the live run fails mid-recording: say so on camera, per
      `docs/DEMO.md`'s "If the live run fails" section, and either restart
      the take or fall back to `make golden`'s deterministic replay with the
      UI's own "REPLAY" banner visible. Never conceal a failure with an
      edit.
- [ ] Stay at or under 4:00 total runtime. Time the recording as you go.

## After recording — upload steps

- [ ] Upload to **YouTube** (or Vimeo).
- [ ] Visibility: **Public** (not Unlisted, not Private) — Stage One
      requires the video be publicly viewable without a login or a request.
- [ ] Title: in **English**, naming the project — e.g. "UNWIND —
      Consequence Clearing (Google All Things Agentic Hackathon)".
- [ ] Description: paste the elevator pitch from `submission/devpost.md`,
      plus the repo URL and deployed URL.
- [ ] After publishing, verify the public link works in an incognito /
      logged-out browser window — confirms no access restriction survived
      the upload.
- [ ] Paste the final YouTube/Vimeo URL into `submission/devpost.md`
      (replacing the `[YouTube URL — placeholder...]` marker) and into the
      Devpost submission form's video field.
