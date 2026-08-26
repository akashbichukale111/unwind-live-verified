"""Generate `docs/evaluation-report.md` from real runs.

The report is GENERATED, never written by hand. Every number in it is
produced by running `evolution/replay.py` over the committed evidence bundle
at the moment of generation, so a number in the document that no longer
reproduces is a build failure rather than a stale sentence somebody forgot.

    UNWIND_VERTEX_DISABLED=1 python scripts/evaluation_report.py

`--check` regenerates and diffs without writing, for CI.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from evolution.criteria import WEIGHTS  # noqa: E402
from evolution.promote import (  # noqa: E402
    MIN_COMPOSITE_GAIN,
    SAFETY_CRITERIA,
    THROUGHPUT_CRITERIA,
    evaluate_promotion,
)
from evolution.replay import SCENARIOS, _materialise_evidence, replay_version  # noqa: E402
from evolution.versions import build_version, seed_versions  # noqa: E402

OUT = REPO / "docs" / "evaluation-report.md"

UNGOVERNED_POLICY = {
    "min_evidence_completeness": 0.0,
    "require_human_on_contradiction": False,
    "max_plan_steps": 8,
    "verify_after_execute": False,
}


def _scenario_profiles() -> list[dict]:
    import shutil

    from fleet.roles import BY_AGENT_ROLE
    from fleet.tools import recon_extract_claims, risk_probe

    scopes = {r.agent_id: list(r.authority_scope) for r in BY_AGENT_ROLE.values()}
    rows = []
    for scenario in SCENARIOS:
        directory, is_temp = _materialise_evidence(scenario)
        try:
            recon = recon_extract_claims(incident_dir=directory)
            risk = risk_probe(recon=recon, fleet_scopes=scopes)
            rows.append(
                {
                    "key": scenario.key,
                    "objective": scenario.objective,
                    "human": scenario.human_concurrence,
                    "parsed": recon["parsed"],
                    "total": recon["total"],
                    "completeness": round(recon["completeness"], 4),
                    "contradictions": len(recon.get("contradictions", []) or []),
                    "escalations": len(risk.get("escalations", []) or []),
                    "why": scenario.why,
                }
            )
        finally:
            if is_temp:
                shutil.rmtree(directory, ignore_errors=True)
    return rows


def build() -> str:
    seed = next(v for v in seed_versions() if v.agent_key == "orchestrator")
    ungoverned = build_version(
        agent_key="orchestrator",
        instruction=seed.instruction,
        policy=dict(UNGOVERNED_POLICY),
        version_n=1,
    )
    candidate = build_version(
        agent_key="orchestrator",
        instruction=seed.instruction,
        policy=dict(seed.policy),
        version_n=2,
        parent_version_id=ungoverned.version_id,
    )

    ungoverned_result = replay_version(ungoverned)
    governed_result = replay_version(seed)
    decision = evaluate_promotion(ungoverned, candidate)
    profiles = _scenario_profiles()

    base_means = ungoverned_result.criterion_means()
    gov_means = governed_result.criterion_means()

    lines: list[str] = []
    add = lines.append

    add("# UNWIND — evaluation report")
    add("")
    add(
        "**This file is generated.** `python scripts/evaluation_report.py` "
        "rebuilds it by running `evolution/replay.py` over the committed "
        "evidence bundle. Every number below was produced at generation time "
        "by the same code the API serves. A number here that no longer "
        "reproduces is a build failure, not a stale sentence."
    )
    add("")
    add(f"**Generated:** {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%SZ')}  ")
    add(
        "**Model:** none. Generated with `UNWIND_VERTEX_DISABLED=1`; the "
        "deterministic planner produced every plan. See *Limitations*."
    )
    add("")
    add("---")
    add("")

    # -- The question -----------------------------------------------------
    add("## The question this measures")
    add("")
    add(
        "`evals/` marks the cascade's ANSWER against "
        "`corpus/data/radius_truth.jsonl` — *was the retraction set right?* "
        "That is an outcome metric and it is unchanged."
    )
    add("")
    add(
        "This report measures something else: *did the agent BEHAVE well "
        "getting there?* A mission can reach a correct answer having ignored "
        "a refusal, acted on 30%-parsed evidence and skipped the human gate. "
        "An outcome metric scores that mission identically to a clean one."
    )
    add("")

    # -- Method -----------------------------------------------------------
    add("## Method")
    add("")
    add(
        "Two agent versions are run over the SAME four scenarios. Both carry "
        "**byte-identical instruction text** — they differ only in the policy "
        "`evolution/policy.py` applies. So every difference below is caused by "
        "the policy and nothing else, and no model is involved in producing it."
    )
    add("")
    add(
        "| | `min_evidence_completeness` | `require_human_on_contradiction` | `verify_after_execute` |"
    )
    add("| --- | --- | --- | --- |")
    add(
        f"| **Ungoverned baseline** | {UNGOVERNED_POLICY['min_evidence_completeness']} "
        f"| {UNGOVERNED_POLICY['require_human_on_contradiction']} "
        f"| {UNGOVERNED_POLICY['verify_after_execute']} |"
    )
    add(
        f"| **Governed (seed v1)** | {seed.policy['min_evidence_completeness']} "
        f"| {seed.policy['require_human_on_contradiction']} "
        f"| {seed.policy['verify_after_execute']} |"
    )
    add("")
    add(
        "The ungoverned baseline is not a straw man. It is the same agent with "
        "the policy levers at the values an ordinary autonomous agent "
        "effectively runs with: act on whatever evidence you have, do not "
        "require a human, do not verify afterwards."
    )
    add("")

    # -- Dataset ----------------------------------------------------------
    add("### The evaluation dataset")
    add("")
    add(
        "Four scenarios, each derived from `fleet/data/incident/` by DELETING "
        "rows — never by writing new ones, so no scenario contains a fact "
        "somebody invented. Measured properties, from the real parser over the "
        "real files at generation time:"
    )
    add("")
    add("| scenario | parsed/total | coverage | contradictions | escalations | human |")
    add("| --- | --- | --- | --- | --- | --- |")
    for row in profiles:
        add(
            f"| `{row['key']}` | {row['parsed']}/{row['total']} | "
            f"{row['completeness']:.4f} | {row['contradictions']} | "
            f"{row['escalations']} | {'yes' if row['human'] else 'no'} |"
        )
    add("")
    coverages = [r["completeness"] for r in profiles]
    add(
        f"Coverage spans **{min(coverages):.4f}–{max(coverages):.4f}**. A "
        "candidate whose `min_evidence_completeness` lands inside that band "
        "behaves measurably differently; one outside it does not, and the "
        "promotion gate reports *no measurable difference* rather than "
        "inventing one."
    )
    add("")

    # -- Result -----------------------------------------------------------
    add("## Result")
    add("")
    add("| criterion | weight | ungoverned | governed | delta |")
    add("| --- | --- | --- | --- | --- |")
    for key in sorted(set(base_means) | set(gov_means)):
        weight = next((w for k, w in WEIGHTS.items() if k.value == key), 0.0)
        delta = round(gov_means.get(key, 0) - base_means.get(key, 0), 4)
        mark = "" if delta == 0 else (" ▲" if delta > 0 else " ▼")
        add(
            f"| {key} | {weight:.2f} | {base_means.get(key, 0):.4f} | "
            f"{gov_means.get(key, 0):.4f} | {delta:+.4f}{mark} |"
        )
    add(
        f"| **composite** | 1.00 | **{ungoverned_result.composite:.4f}** | "
        f"**{governed_result.composite:.4f}** | "
        f"**{governed_result.composite - ungoverned_result.composite:+.4f}** |"
    )
    add("")

    # -- The finding ------------------------------------------------------
    add("### The finding")
    add("")
    add(
        f"**The ungoverned agent scores a perfect "
        f"{base_means['TASK_SUCCESS']:.2f} on `TASK_SUCCESS`. The governed one "
        f"scores {gov_means['TASK_SUCCESS']:.2f}.**"
    )
    add("")
    add("Per-scenario terminal status and external effect:")
    add("")
    add("| scenario | ungoverned | governed |")
    add("| --- | --- | --- |")
    for i, scenario in enumerate(SCENARIOS):
        u = ungoverned_result.reports[i]
        g = governed_result.reports[i]
        add(
            f"| `{scenario.key}` | {u['status']}"
            f"{' + ' + str(u['external_action']) if u['external_action'] else ''} "
            f"| {g['status']}"
            f"{' + ' + str(g['external_action']) if g['external_action'] else ''} |"
        )
    add("")
    add(
        "The ungoverned agent completed every mission. It completed the two it "
        "should have declined by writing to the system of record on "
        "thin and contested evidence with nobody in the loop."
    )
    add("")
    add(
        "**An evaluation that reads only the final status therefore ranks the "
        "ungoverned agent FIRST.** Trajectory evaluation ranks it last, on "
        f"a composite of {ungoverned_result.composite:.4f} against "
        f"{governed_result.composite:.4f}, and names why: "
        f"`POLICY_COMPLIANCE` {base_means['POLICY_COMPLIANCE']:.2f} → "
        f"{gov_means['POLICY_COMPLIANCE']:.2f}, `CONTEXT_QUALITY` "
        f"{base_means['CONTEXT_QUALITY']:.2f} → {gov_means['CONTEXT_QUALITY']:.2f}, "
        f"`TOOL_CORRECTNESS` {base_means['TOOL_CORRECTNESS']:.2f} → "
        f"{gov_means['TOOL_CORRECTNESS']:.2f}."
    )
    add("")
    add(
        "That gap is the entire argument for the package: an agent scored only "
        "on outcome learns to reach outcomes by any means available to it."
    )
    add("")

    # -- The gate ---------------------------------------------------------
    add("## What the promotion gate did with this")
    add("")
    add(f"Outcome: **{decision.outcome.value}**")
    add("")
    for reason in decision.reasons:
        add(f"- {reason}")
    add("")
    add(
        "The asymmetry matters and it was not the first design. A single "
        "zero-tolerance per-criterion rule REFUSED this promotion, because "
        f"`TASK_SUCCESS` fell {base_means['TASK_SUCCESS']:.2f} → "
        f"{gov_means['TASK_SUCCESS']:.2f}. It is supposed to fall. So the gate "
        "now splits:"
    )
    add("")
    add(f"- **Safety criteria** ({', '.join(sorted(SAFETY_CRITERIA))}) may never fall.")
    add(
        f"- **Throughput criteria** ({', '.join(sorted(THROUGHPUT_CRITERIA))}) may fall, "
        "but only when a safety criterion strictly improves to pay for it, and "
        "the trade is NAMED in the decision record."
    )
    add("")
    add(
        "A candidate can trade completions for compliance. It can never trade "
        "compliance for completions."
    )
    add("")

    # -- Limitations ------------------------------------------------------
    add("## Limitations — read this before quoting any number above")
    add("")
    add(
        "1. **The instruction delta is NOT measured here.** This report was "
        "generated with no model in the path, so the deterministic planner "
        "produced every plan and never read an agent's instruction text. Only "
        "the POLICY delta is reflected. `evolution/promote.py` records this as "
        "an `EXERCISE:` reason on any candidate whose instruction changed, and "
        "never scores an unexercised instruction change as an improvement. "
        "**Measuring the instruction delta against live Gemini is NOT YET "
        "MEASURED.**"
    )
    add("")
    add(
        f"2. **The dataset is small — {len(SCENARIOS)} scenarios, one incident "
        "bundle.** It is enough to demonstrate the ranking inversion above and "
        "not enough to characterise the criteria's behaviour in general. No "
        "confidence interval is offered because none would be meaningful at "
        "this n."
    )
    add("")
    add(
        "3. **The criteria weights are chosen, not derived.** They are stated "
        "as chosen in `evolution/criteria.py`. What is not arbitrary is their "
        "ORDERING, and the argument for it is in that module."
    )
    add("")
    add(
        "4. **This measures a policy difference, not a learning curve.** No "
        "claim is made that the loop discovers improvements unsupervised over "
        "time. It measures candidates and gates them. **Longitudinal "
        "improvement across many real missions is NOT YET MEASURED.**"
    )
    add("")
    add(
        "5. **Replay is offline.** The external write does not happen. That is "
        "the correct omission for evaluating a candidate before it may touch "
        "anything, and it does mean these numbers describe proposed behaviour "
        "rather than executed behaviour."
    )
    add("")
    add(
        f"6. **`MIN_COMPOSITE_GAIN` is {MIN_COMPOSITE_GAIN}**, a chosen "
        "threshold separating an improvement from rounding. It is not derived "
        "from a variance estimate, because at this dataset size there is none."
    )
    add("")
    add("---")
    add("")
    add("## Reproduce")
    add("")
    add("```bash")
    add("UNWIND_VERTEX_DISABLED=1 python scripts/evaluation_report.py   # this file")
    add("UNWIND_VERTEX_DISABLED=1 python scripts/evolution_demo.py      # the loop, end to end")
    add("python -m pytest tests/test_evolution_*.py -q                  # the assertions")
    add("```")
    add("")
    return "\n".join(lines) + "\n"


def _without_timestamp(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.startswith("**Generated:**"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="regenerate and diff, do not write")
    args = parser.parse_args()
    content = build()
    if args.check:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        # The generation timestamp changes on every run and is not a result.
        # Comparing it would make this check fail always, which is the same as
        # not having a check -- so it is normalised out and everything else,
        # every measured number included, is compared exactly.
        if _without_timestamp(current) != _without_timestamp(content):
            print("docs/evaluation-report.md is stale; run scripts/evaluation_report.py")
            return 1
        print("docs/evaluation-report.md is current (timestamp excluded)")
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(content, encoding="utf-8")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
