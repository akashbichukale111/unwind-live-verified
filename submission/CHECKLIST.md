# Pre-submission checklist

One exact command or URL per line. Check nothing off without actually
running the command or opening the URL. **SUBMIT NO LATER THAN 30 AUG 2026**
— a one-day buffer before the true deadline (31 Aug 2026, 5:00 PM Pacific).
[JUDGEMENT, not a rule the hackathon states — leaving margin for an upload
failure, a Devpost outage, or a last-minute fix.]

---

## Video

- [ ] Recorded per `submission/demo_script.md` v2 — every LIVE segment a
      single unedited take, ≤4:00 total.
- [ ] Uploaded to YouTube, **Public** visibility:
      `⟨FILL — paste the exact watch URL here once uploaded⟩`
- [ ] Language set to **English**.
- [ ] Shows **live unedited execution** (Act 1 and Act 3 against the
      deployed URL) **and visual Google Cloud proof** (Cloud Run console,
      shot 1.1).
- [ ] Contains the spoken disclosure that Act 2 runs locally (shot 2.1) —
      confirm by watching the uploaded copy once, end to end.
- [ ] Watched once, signed out, to confirm public playability:
      `⟨FILL — date/time watched⟩`

## Repository

- [ ] Public: `https://github.com/akashbichukale111/unwind` — confirm by
      opening the URL in a private/incognito window.
- [ ] Default branch contains this work. Verify:
      `git log --oneline -3` (expect the warrant/countersign/instrument
      commits at the top) run against the URL above, not this local clone.
- [ ] `git tag submission-final` created and pushed, pointing at the exact
      commit submitted:
      `git tag submission-final <commit-sha> && git push origin submission-final`
      — **not yet run this pass; the commit to tag is**
      `ae027ac` — the commit whose source is what's actually running at
      revision `unwind-00007-2cn` (or later, if more fixes land before
      submission; re-check `gcloud run services describe unwind ...` against
      `git log` before tagging).

## Architecture diagram

- [ ] Reachable from `README.md` § Architecture:
      `open README.md` (renders `assets/architecture.svg` inline on GitHub)
- [ ] Shows all four cards solid, all six ADK constructs labelled with
      `file:line`, and the zero-model boundary drawn as a line — confirm by
      opening `assets/architecture.png` directly.
- [ ] Linked on Devpost (Links section) once the Devpost draft is live.

## Quickstart

- [ ] Verified in a clean clone **today** (re-run before submitting, not
      relying on this pass's 2026-08-17 run):
      `git clone https://github.com/akashbichukale111/unwind /tmp/unwind-check && cd /tmp/unwind-check && make install && make test`
      — expect **369 passed** with `make emulator` running in another
      terminal first, or **325 passed, 44 skipped** without.
- [ ] Record the date and exit code here: `⟨FILL — date + exit code of the
      command above⟩`

## Hosted URL

- [x] **Redeployed 2026-08-17.** Cards 0–3 and the four-card instrument are
      live at `https://unwind-hgeodtazqq-uc.a.run.app`, revision
      `unwind-00007-2cn`. First redeploy that pass surfaced and fixed a real
      gap (a missing Firestore composite index) — see
      `evidence/firestore/deploy-2026-08-17.md`. A later pass the same day
      fixed the instrument's default-landing-view CSS/JS (raw-looking
      controls on first load) and redeployed again — see
      `evidence/deploy/ui-premium-fix-2026-08-17.md`.
- [ ] Live: `bash scripts/health_check.sh` against
      `https://unwind-hgeodtazqq-uc.a.run.app` — must print **PASS**.
      Timestamp of last PASS: **2026-08-17 02:31:33 UTC**
      (`evidence/health/health-20260817T023133Z.md`). Re-run within one
      hour of submitting and record the new timestamp: `⟨FILL⟩`.
- [ ] `make deploy-verify` against the same URL — must print **5/5 PASS**.
      Last verified: **2026-08-17**, this pass (`evidence/deploy/deploy-verify-*.md`).

## Devpost

- [ ] Every field in `submission/devpost.md` copied into the actual Devpost
      form — Project name, tagline, category, description, features,
      technologies, data sources, findings, "Built with" tags, links.
- [ ] The three `⟨FILL⟩` placeholders in `submission/devpost.md` resolved:
      demo video URL, architecture diagram URL (branch-confirmed), and any
      team/submitter field Devpost requires outside this repo.
- [ ] `submission/devpost.md`'s numbers cross-checked against
      `evidence/INDEX.md` — same command, same page.

## Blog (+0.2 bonus)

- [ ] `submission/blog.md` published at a public URL:
      `⟨FILL — published URL⟩`
- [ ] Zero unbacked numbers — every figure in the post traces to a row in
      `evidence/INDEX.md`. Spot-check: the "75/100" mentioned in the post
      is quoted as a REJECTED, removed defect from an earlier draft, not
      claimed as a current score — confirm this reads that way on
      re-read, not as an actual self-grade.

## Social (+0.2 bonus)

- [ ] Posted from `submission/social.md`'s primary post, with both
      `⟨FILL⟩` URLs resolved to the real video and repo links.
- [ ] Contains `#AllThingsAgenticHackathon` exactly.
- [ ] Live post URL: `⟨FILL⟩`

## Verification scripts (all pass before submitting)

- [ ] `bash scripts/verify_adk_mapping.sh` — expect **10/10 PASS**.
- [ ] `python -m pytest -q` (with `make emulator` running) — expect **369
      passed**.
- [ ] `python scripts/rederive_warrant.py` — expect **4/4 PASS**.
- [ ] `python scripts/run_countersign_eval.py` — expect **75.6% (31/41)**,
      labelled `SIMULATED` unless Model Garden access has since been
      granted, in which case re-verify the label flips honestly to a real
      measurement.
- [ ] `python scripts/check_contrast.py` — expect a clean pass, no eighth
      colour.
- [ ] `ruff check . && ruff format --check .` — expect clean.
- [ ] `git diff --stat stage-one-floor -- spine/ court/ judgment/ settle/`
      — expect **empty output**. Frozen dirs untouched across the entire
      build, not just this pass.

## Final tag

- [ ] After every box above is checked and the redeployment decision
      (Hosted URL section) is made: `git tag submission-final && git push
      origin submission-final`. Do this LAST, after the video is uploaded
      and its URL is in this file — a tag pointing at a commit whose demo
      script references a not-yet-uploaded video is a tag pointing at an
      incomplete submission.
