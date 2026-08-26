# Judge demo — four minutes, no Google Cloud account required

> **This script predates the Mission Media Lab and the Mission Time
> Machine.** The command_os.cli walkthrough below is still accurate and
> still the fastest way to see the causal seam. It does not cover the web
> UI's Media Lab (Gemini/Veo/Lyria, playable with no credential) or the
> inline Time Machine — see `README.md`'s "Agentic Command OS" section and
> [`evidence/INDEX.md` §16–19](../evidence/INDEX.md) for those. The
> "what a judge should not be told" section below is from before those
> shipped and has been corrected in place, not deleted.

Everything below runs on a cold clone against the Firestore emulator. Nothing
in this script needs credentials, and nothing in it is scripted output — every
number you will see is computed at the moment you see it.

```bash
make install
make emulator          # terminal 1 (needs Java 11+)
UNWIND_DEV_PRINCIPAL="you@example.com" make dev   # terminal 2
open http://127.0.0.1:8000
```

---

## The 30-second version, in a terminal

```bash
python -m command_os.cli "Investigate an anomalous finance capability request."
python -m command_os.cli "Trace the impact of a changed operational premise."
```

Two objectives. Two different plans, two different agent rosters, two different
outcomes. The second contains **no remediation role at all**, so it cannot
reach an external effect — that is a structural property of the plan, not a
policy someone remembered to apply.

---

## The four-minute walkthrough

### 0:00 — The Unlikely Hero (20s)

Open `fleet/data/incident/ops-note.txt`. It is a real handover note, typed in a
hurry at 06:40:

> *"supplier K lead time is NOT 11 days any more… someone needs to check which
> agents are still planning against 11… **I do not have a list. I never have a
> list.**"*

That person is the user. Not a CTO — the operations coordinator who currently
*is* the dependency index. The system parses that note, and the parser reports
`NO_DEPENDENCY_INDEX` as a finding.

### 0:20 — Anonymous is refused (20s)

Leave the **operator credential** field empty. Click **Run autonomous mission**.

> `NOT AUTHENTICATED — every mutating endpoint refuses an anonymous caller.`

That is a real 401. Before this pass, this exact request minted warrant and
wrote an audit record naming a human who was never there. Now put the token in.

### 0:40 — The plan is computed (40s)

Run it. The **Plan** panel appears *before* the trace:

```
ZERO_MODEL   SECURITY_INVESTIGATION   unwind-deterministic-planner@1
01  WORKER_DOCUMENT    recon.extract_claims    READ_INTERNAL   evidence.read
02  WORKER_COMPLIANCE  risk.probe              ANALYZE         risk.analyze
03  WORKER_PYTHON      remediation.prepare     ANALYZE         remediation.prepare
04  WORKER_PYTHON      remediation.execute     CREATE_TICKET   sandbox.write
05  SENTINEL           verify.check            READ_INTERNAL   sandbox.read
```

**Say the provenance out loud.** `ZERO_MODEL` means no model produced this
plan, because this environment has no Vertex credentials. The Gemini planner is
real code with a real `output_schema` and a real `Runner`
(`fleet/agents.py`); it has not run here, and the label says so rather than
implying otherwise. **Change the objective in the box and re-run** — the plan
changes.

### 1:20 — Messy evidence, measured honestly (30s)

Step 1 parses a free-text note, a CSV with a blank agent id / a missing integer
/ the literal string `NOT_A_TIMESTAMP`, and a JSON feed with two contradicting
records.

> `16 / 20 parsed (80%)` · `contradictions found: 2` · `escalations found: 1`

**80% is not a rounding error, it is the point.** Watch what it does to the
next step's price.

### 1:50 — The causal seam (50s) — *the most important minute*

```
04  CONTAIN — fleet_recon ISOLATED
    behaviour CRITICAL (score 100) from the evidence's own 147 tool calls on
    'finance'; Gateway SCOPE_EXCEEDED: agent 'fleet_recon' requested
    ['finance.secret_read'], which is outside its granted scope
```

Every input here came from the CSV: the agent, the scope, the tool-call count,
the dataset. Now falsify it:

```bash
make causality
```

The test runs the **same mission** over evidence with the escalating rows
removed. No containment phase. No isolation. Status `COMPLETED` instead of
`COMPLETED_WITH_RESTRICTIONS`. Committed output:
`evidence/mission/causality-*.log`.

The previous version of this system failed exactly this test — forcing drift to
NORMAL produced a byte-identical mission. That is why the test exists.

### 2:40 — Uncertainty is priced (40s)

```
05  STEP 3 — ALLOWED at 13bp (5bp +145% tax)
```

Scroll to **Warrant Market — live pricing** and move the drift selector to
`CRITICAL`. Every price changes, live, with each contribution named. This is
`warrant/economics.py`, which lives inside `warrant/` — a package
`tests/test_warrant_zero_model.py` proves cannot import a model client.

> **A model may propose an action. It can never price it, discount it, or argue
> the tax down.**

More uncertainty → higher cost → the same balance buys fewer actions → the
Gateway refuses sooner → more work reaches a human.

### 3:20 — Double consent, then one real action (40s)

The independent challenger re-derives its own verdict from the evidence on five
named grounds and **can disagree** — when it does, minting freezes and the
mission routes to a human (`test_adversarial.py::test_attack_20`).

Tick **require human approval**, re-run, and the mission stops at the gate.
Approve it. The concurrence record names *you* — the authenticated principal,
not a constant. Then:

```
EXECUTE — REVOKE_CAPABILITY_REQUEST -> sandbox_file#sbx-… (applied), 123bp spent
VERIFY  — recorded effect matches the proposal field for field ·
          authority settled MINT: 80bp -> 280bp
```

A real file was written outside this process. Check it: `cat .sandbox/actions.jsonl`.
Re-run and the replay writes **nothing** — asserted by counting lines in that
file, not by trusting a flag.

### 4:00 — The honesty panel

**System Reality** is served by `GET /api/command-os/status`, a second
independently queryable source. If it disagrees with the screen, the screen is
wrong. It reports `gemini_planning: CONFIGURED_NOT_EXERCISED`,
`veo_mission_replay: DESIGNED`, `multi_tenancy: DESIGNED`, and
`external_action: LIVE (SANDBOX BACKEND)`.

---

## If a judge wants to attack it

```bash
make redteam        # 20 attacks, asserted defences, 21 passed
```

Covers prompt injection, scope escalation, tool poisoning, anonymous approval,
forged principals, service-token escalation, simulation contamination, memory
poisoning, replay/double-spend, worker loops, hallucinated tool output, an
unavailable model read as agreement, and a challenger talked into agreeing.

It also contains one test that documents an attack the system **does not**
defend — cross-tenant isolation, because tenancy does not exist here. The full
list of gaps is `docs/SECURITY.md` §6.

---

## What a judge should not be told

- That Gemini or Gemma **ran a live model call in this local walkthrough**.
  They did not here — no credentials in this environment. (Separately, one
  real Gemini call and one real Veo/Lyria generation DID happen, on
  2026-08-21, and are `LIVE_VERIFIED` evidence — see below. Do not confuse
  "not exercised on this run" with "never happened.")
- That the deployed URL is running whatever commit HEAD happens to be at
  read time. Check `evidence/deploy/` / `evidence/firestore/` for the
  revision that was actually verified live, and the date.
- That every Veo/Lyria player on screen is a real model generation. It is
  not: the players in the Mission Media Lab are a **deterministic local
  render** of a real mission's checkpoints, labelled as such on screen, and
  they play with no credential on every deployment. The **one genuine** Veo
  generation and **one genuine** Lyria generation this project has ever run
  are real, evidenced, `LIVE_VERIFIED` — but their bytes are gitignored
  output, so the "Real Verified Evidence" panel that plays them stays
  honestly hidden on any machine that does not physically have those files.

`evidence/INDEX.md` §8 (original evidence boundary) and §13, §16–17 (the
Media Lab, the real Veo/Lyria pass, and the honesty discipline around both)
list what each claim is backed by and what is explicitly not evidenced.
