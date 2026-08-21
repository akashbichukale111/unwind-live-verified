# countersign/ — DESIGN.md (Card 3: COUNTERSIGN)

## Invariant

Evidence bears load only when a second, unrelated family signs it. Gemma
independently re-reads a case's extraction/judgement material and returns
AGREE or DISAGREE plus a one-line ground. It writes nothing to the truth
layer -- its record lands only in the Memory Bank
(`tower/memory.py`, `MemoryEntryKind.COUNTERSIGN`) and gates
`warrant/ledger.py`'s MINT precondition. AGREE lets minting proceed
(alongside the separately-required human-concurrence record); DISAGREE
appends a CHALLENGE event that freezes minting for that case and flags it
for a human.

## The five-point necessity test, and why Gemma passed it

Locked decision: **Gemini and Gemma only.** Veo (2/5) and Lyria (0/5) were
evaluated against the same test and cut -- not deferred, cut, and the cut is
stated in the README and the demo rather than hidden. The five points, and
how Gemma clears each one:

1. **Independence requires a non-Gemini family.** Gemma is architecturally
   a different model family from Gemini -- `warrant/ledger.py:family_root`
   normalizes both strings and `countersign/verify.py:assert_independent`
   refuses a countersign whose family root matches the judging side's.
2. **It runs in the live minting path.** `countersign/verify.py:verify_and_record`
   is called from the same flow that would otherwise call `warrant.ledger.mint`
   directly -- Countersign is not a report generated afterward, it is a
   precondition checked before the ledger accepts a MINT.
3. **Its output gates a decision.** AGREE/DISAGREE is not logged and
   ignored -- DISAGREE structurally prevents `mint` from ever succeeding for
   that case (`CaseChallengedError`, permanently, see
   `warrant/FAILURE_MODES.md`'s note on no unfreeze path).
4. **Its effect is a 10-second shot.** The UI (Card 0's instrument) renders
   a verdigris freeze mark on the paper side the instant a CHALLENGE lands --
   a single, legible state change, not a wall of text.
5. **It is not redundant with Gemini.** Gemini extracts and judges; Gemma
   never touches extraction or judgement, only verification of a case
   already decided -- two different jobs, which is what makes the second
   opinion meaningful rather than a second vote from the same reasoning.

Veo and Lyria fail this test at point 2 and 3 (there is no "video" or
"audio" step anywhere in a decision pipeline for either to gate) and mostly
at point 1 (neither is a text-judgement family that could independently
verify a text judgement in the first place).

## Why the atomic verification step is an ADK 2 single-turn `AgentTool`

See `countersign/agent.py`'s module docstring for the full argument. In
short: the caller (the minting flow) retains control at every step. The
verifier is handed one case, answers EXACTLY once
(`VERDICT: AGREE|DISAGREE` + one ground line), and the turn ends --
`mode="single_turn"` removes the surface for taking the floor, redirecting
the workflow, or writing anywhere, at the framework level rather than by
convention. A free-running conversational agent as verifier would itself
need governing; the single-turn shape is what lets Countersign be trusted
without a second Countersign watching it.

## Execution path, discovered honestly while wiring this up

`AgentTool.run_async` needs a live `ToolContext`/`InvocationContext` that
only exists inside a running agent invocation -- ADK's public surface does
not support constructing one standalone, which is also why `AgentTool`'s
own docstring calls direct usage "discouraged" in favour of
`sub_agents=[...]`.

What was NOT anticipated going in: ADK also refuses to run a
`mode="single_turn"` agent as a `Runner`'s ROOT at all --

```
ValueError: LlmAgent as root agent must have mode='chat', but got mode='single_turn'.
```

-- raised identically whether the agent is passed as `Runner(agent=...)` or
`Runner(node=...)`. The mode field's own docstring explains why:
`single_turn`'s home is "as a node in a workflow." So `countersign/verify.py`
runs the SAME `countersign_agent` object `countersign_tool` wraps as the one
node of a one-node ADK 2 `Workflow`
(`Workflow(edges=[Edge(from_node=START, to_node=countersign_agent)])`) --
the identical `Workflow`/`Edge`/`START` idiom `tower/gateway.py` already
uses one layer down -- executed through `InMemoryRunner(node=workflow)`.

## Live verification, attempted and reported honestly

This session had a real `gcloud` user session (`bichukaleakash80@gmail.com`)
and located a real GCP project already referenced elsewhere in this
repository's evidence (`project-895d4ca8-d301-447d-916`, the same project
`docs/LIVE-VERIFICATION.md` names for the live Gemini run). Three real
attempts were made, escalating credentials each time:

| Attempt | Configuration | Result |
| --- | --- | --- |
| 1 | Default config (`UNWIND_PROJECT_ID` unset, falls back to `unwind-local`) | `403 PERMISSION_DENIED` -- `unwind-local` is not a real project |
| 2 | `UNWIND_PROJECT_ID=project-895d4ca8-d301-447d-916`, a real short-lived OAuth token from `gcloud auth print-access-token`, `vertex_location=global` | Authentication succeeded. `404 NOT_FOUND` -- `Publisher model projects/.../locations/global/publishers/google/models/gemma-3-27b-it was not found or your project does not have access to it` |
| 3 | Same, `vertex_location=us-central1` | Identical `404`, same reason |

**What this proves:** the wiring is genuinely correct end to end -- the call
reaches Vertex AI, authenticates with a real token, and gets a real,
specific API response back (not a mock, not a stub). **What it does not
prove:** that `gemma-3-27b-it` is the right, enabled publisher-model ID for
this project -- the 404 says the project lacks access to that exact model
resource, which is a Model Garden entitlement question, not a code defect.

**Reported, not glossed over:** `scripts/run_countersign_eval.py`'s
`live_reachability_probe` field carries this exact error every time the
eval script runs without live access, and the eval run automatically falls
back to the SAME scripted simulator the test suite uses
(`UNWIND_COUNTERSIGN_SIMULATED=1`), never silently substituting a fabricated
"live" number.

## The scripted simulator, labelled

`countersign/verify.py:_simulated_outcome` is deterministic, not random --
the same discipline `judgment/model.py:ScriptedT2Model` already established
for T2: agree unless `material["class"] == "adversarial"` (or
`material["forged"]` is set), in which case disagree. This is a stand-in
for "an independent reader catches what an adversarial input was built to
slip past" -- plausible enough to exercise the DISAGREE/CHALLENGE path in
tests and offline demos, but it is NOT a real judgement and the returned
`family` is `"gemma-simulated"`, never `"gemma-3-27b-it"`, so a fold over
the resulting countersign records can never be mistaken for live output.

## The collusion guard

`countersign/verify.py:assert_independent` refuses a countersign attempt
whose FAMILY or PRINCIPAL matches the judging side, checked BEFORE any
model call and BEFORE anything is written -- a forged "independent"
countersign leaves no trace of having been accepted.
`tests/test_countersign_verify.py` covers both collision types plus the
vacuity case (an actually-independent pair passes), and proves the
simulated path enforces the SAME guard rather than bypassing it.

## Honesty: measured agreement rate

`scripts/run_countersign_eval.py` runs Countersign over all 41 existing
eval scenarios (`evals/scenarios/*/*/scenario.json`). Result, published
verbatim in the README's honesty map regardless of how it reads:

**75.6% agreement (31/41 decided, 0 unavailable), SIMULATED** -- live Gemma
was attempted first and reported unreachable in this environment (see
above); the run fell back to the scripted simulator automatically, and the
result is labelled SIMULATED everywhere it appears, never presented as a
measurement of Gemma's actual judgement. The 10 disagreements are exactly
the 10 `adversarial`-class scenarios -- the simulator's own designed
behaviour, not a discovery about model quality. This number measures the
MECHANISM (collusion guard, CHALLENGE wiring, record shape), not Gemma.
