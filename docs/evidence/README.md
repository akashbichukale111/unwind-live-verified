# Evidence

Artifacts from runs that actually happened, with what each one does and does not
prove. Nothing in this directory is a projection or a target.

---

## 1. Live Vertex verification — 2026-08-13

**Command run** (on the maintainer's authenticated GitHub Codespace, not in the
build container):

```bash
export UNWIND_PROJECT_ID=project-895d4ca8-d301-447d-916
export UNWIND_VERTEX_LOCATION=global
make verify-live
```

### Configuration

| | |
| --- | --- |
| Project | `project-895d4ca8-d301-447d-916` |
| Location | `global` |
| Model | `gemini-3.5-flash-lite` (GA) |
| Vertex call | **OK** |
| Model errors | **0** |

### The headline measurement

| | Recall |
| --- | --- |
| Parser only | **81.8%** (36 / 44) |
| Parser + Gemini | **100.0%** (44 / 44) |
| **Delta** | **+18.2 percentage points** |

Gold claims scored: **44**.

**By claim type — only one class moved:**

| Class | Gold | Parser | + Gemini | Delta |
| --- | ---: | ---: | ---: | ---: |
| `numeric:currency` | 4 | 100.0% | 100.0% | 0.0 |
| `numeric:percentage` | 4 | 100.0% | 100.0% | 0.0 |
| `numeric:quantity` | 8 | 100.0% | 100.0% | 0.0 |
| **`temporal:absolute-duration`** | **24** | **66.7%** | **100.0%** | **+33.3 pp** |
| `temporal:relative-date` | 4 | 100.0% | 100.0% | 0.0 |

### What this proves

1. **Gemini 3.5+ via Vertex AI is running.** One real call, raw response
   captured in `docs/LIVE-VERIFICATION.md`. The mandatory hackathon requirement
   is satisfied by executing code, not by written intent.
2. **The second-pass architecture is the right shape, and the delta measures
   it.** The deterministic parser is 100% on four of five classes and 66.7% on
   the fifth. Gemini was shown *only* the artifacts the parser missed, and
   closed exactly that gap. The four classes where the parser was already
   perfect show a delta of zero — because nothing in them was ever sent to the
   model.

### What this does NOT prove — read before quoting the 100%

- **The model's own denominator is 8, not 44.** The parser missed 8 claims;
  Gemini was shown those 8 and got 8 right. "100% recall" is a property of the
  *combined pipeline over 44 claims*, not a claim that the model is
  100% accurate at extraction.
- **44 gold claims is a small sample** from a synthetic corpus whose artifacts
  and extraction lexicon were written by the same author. `docs/COVERAGE.md`
  states this at length. The corpus deliberately includes phrasings the lexicon
  was not built around ("ten working days", "turnaround", "cycle time"), which
  is why the parser misses them and why the misses are real — but it is still
  not production supplier email.
- **It says nothing about precision on adversarial text.** Injection resistance
  comes from the parser having no instruction-following surface; that property
  is unchanged by this run and is tested separately.

### T2 — attempted, and it resolved nothing

| | |
| --- | --- |
| Queue size | 174 |
| Attempted | 60 |
| Resolved | **0** |
| Still unresolved | **60** |
| Exceptions | 0 |

**This is not a success and it is not a model failure. It is a non-test, and
the reason is structural.**

All 174 nodes in the T2 queue have `committed_lead_days = None` — they are the
clause-governed conclusions whose governing premise states a mechanism rather
than a period. `judgment/assessor.py` short-circuits to UNRESOLVED when the
original commitment carries no numeric term:

```python
if original_committed_lead_days is None:
    return _unresolved(..., "The original commitment carries no numeric term,
                             so there is nothing to compare the re-derivation
                             against.")
```

That branch is reached **before the model's answer is used**. So the sampled 60
could not have resolved regardless of what Gemini returned, and a different
sample of the same queue would behave identically — verified: 0 of all 174 carry
a numeric term.

What the run therefore does establish: the T2 path executes end-to-end against
a live Vertex model with **zero exceptions** across 60 nodes (120 model calls —
one re-derivation and one assessment each). Plumbing verified. **Judgement
quality: still unmeasured.**

See "Remaining work" in the root README for what would close this.

### Screenshot — NOT IN THIS REPOSITORY

The terminal screenshot of the live run exists only as a chat attachment. It was
never present on the filesystem of the machine that authored this commit, so it
**could not be copied in**, and no substitute was generated. There is no file at
`docs/evidence/live-vertex-verification.png`.

**The authoritative evidence for this run is
[`docs/LIVE-VERIFICATION.md`](../LIVE-VERIFICATION.md)**, written by
`make verify-live` itself.

To add the image, save the original capture from the Codespace to exactly:

```
docs/evidence/live-vertex-verification.png
```

then `git add` it and update this section. Until then this index deliberately
links to nothing, rather than shipping a broken reference or a recreated image.

---

## 2. Interface measurement

`scripts/measure_ui.py` (`make ui-check`) drives the real interface in a real
Chromium and writes `docs/shots/*.png`. Those screenshots are committed and are
regenerated by the script, not hand-captured.

| | |
| --- | --- |
| Nodes rendered | 4,206 |
| Frame rate | **60 fps median** (three 2-second samples, all 60) |
| Cull counter vs cascade | **78 = 78**, asserted equal |
| Horizontal scroll at 380px | none |
| App-origin console errors | 0 |

Measured in the build container on software rendering (SwiftShader). Frame rate
on the demo machine will differ; re-run `make ui-check` there.

---

## 3. Determinism and regression

| Artifact | What it fixes in place |
| --- | --- |
| `evals/results/summary.json` | 41 scenarios, committed; CI fails on drift |
| `evals/golden/court.txt` | the court transcript; CI fails on drift |
| `docs/COVERAGE.md` | the confusion matrix; CI regenerates and diffs |
| `corpus/data/MANIFEST.sha256` | the corpus is byte-reproducible from its seed |

---

## 4. Cloud Run deployment — verified live

**Command run** (on the maintainer's authenticated GitHub Codespace):

```bash
export UNWIND_PROJECT_ID=project-895d4ca8-d301-447d-916
make deploy-check                                  # preflight, no credentials
./infra/deploy.sh                                   # gcloud run deploy --source .
make deploy-verify URL=https://unwind-hgeodtazqq-uc.a.run.app
```

Preflight screenshot: [`deploy-preflight-passed.png`](deploy-preflight-passed.png)
— `make deploy-check`, `PASS` on every check, captured before any credentialed step ran. The suite has since grown to 20 checks; the screenshot shows the 19 that existed when it was taken.

### Configuration

| | |
| --- | --- |
| Service | `unwind` |
| Project | `project-895d4ca8-d301-447d-916` |
| Region | `us-central1` |
| URL | `https://unwind-hgeodtazqq-uc.a.run.app` |
| Traffic | 100% to the latest ready revision |

### deploy-verify result: 5/5 PASS, exit code 0

```
[1/5] healthz OK  stage=task-5-interface        (GET /api/healthz)
      model=gemini-3.5-flash-lite  location=global  vertex_disabled=False
[2/5] UI served from the same origin (canvas + 2 static assets)
[3/5] running one real cascade against the deployed API ...
      radius announced : 2594
      node events sent : 2594
      done.sent        : 2594
      material         : 78
      model calls      : 0
[3/5] counter integrity OK — announced = delivered = reported
[4/5] adversarial refusal OK — source_outside_claim_scope, radius 0
[5/5] driving the deployed UI in a real browser ...
      nodes rendered   : 4206
      counter on screen: 78
      cascade material : 78

DEPLOYMENT VERIFIED — it renders AND it computes.
```

### What step 1 found, and the fix

The first live run of `deploy-verify` failed at step 1: `/healthz` returned a
Google-branded 404 with no `Google Frontend` response header, while every
sibling path (`/`, `/api/*`, `/health`, `/_ah/health`) reached the FastAPI app
correctly. Cloud Run request logs confirmed the request never arrived at the
container — Cloud Run's Knative queue-proxy reserves the exact literal path
`/healthz` for its own internal platform health checking and intercepts public
requests to it before they reach user code. The endpoint was moved to
`/api/healthz` (matching the existing `/api/*` convention); every caller —
`deploy_verify.py`, `tests/test_api.py`, `measure_ui.py`, `infra/dev.sh`,
this README, `docs/DEPLOY.md` — was updated to match, and the fix redeployed
cleanly. This is a Cloud Run platform constraint, not a defect in
`infra/deploy.sh`'s IAM, API-enablement, or build configuration.

### Step 5's browser

The headless-browser check needs a local Chromium the deploy-verify script can
launch; `services/api/main.py` and the deployed service are unaffected by
whether it's present. It is not vendored in this repository (no binaries, no
`node_modules`) — install it locally with:

```bash
PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers .venv/bin/playwright install chromium
sudo .venv/bin/playwright install-deps chromium     # OS shared libraries
```

`scripts/deploy_verify.py` and `scripts/measure_ui.py` locate it via the
`UNWIND_CHROME` env var (default `/opt/pw-browsers/chromium-1194/chrome-linux/chrome`);
the exact revision folder name depends on the installed `playwright` package
version, so set `UNWIND_CHROME` to the path Playwright actually reports if it
differs. Step 5 is `SKIPPED`, not failed, when no browser is found — it never
reports a false pass.

### What this proves

The deployed service is the real FastAPI app, not a fixture: the cascade
numbers in step 3 and the on-screen counter in step 5 both come from one real
traversal over the committed corpus, and step 5 asserts they agree with each
other rather than trusting either in isolation.
