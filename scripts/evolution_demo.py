"""Run the governed evolution loop end to end and record what happened.

Everything printed below is computed by the same code the API serves. This
script adds no numbers of its own -- it runs `evolution/` against the real
committed evidence bundle and prints what came back, including the refusals.

    UNWIND_VERTEX_DISABLED=1 python scripts/evolution_demo.py

Needs no credentials and no Firestore: every call here is in-memory
(`persist=False`), so the loop can be reproduced on a cold clone.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from evolution.promote import evaluate_promotion, promote  # noqa: E402
from evolution.propose import ProposalRejected, propose_candidate  # noqa: E402
from evolution.replay import SCENARIOS, replay_version  # noqa: E402
from evolution.versions import build_version, seed_versions  # noqa: E402

HUMAN = "human::demo-operator@example.com"


def _rule(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


def _means_table(label: str, means: dict[str, float]) -> None:
    print(f"  {label}")
    for key, value in means.items():
        print(f"    {key:<20} {value:.4f}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", type=Path, help="also write the raw result here")
    args = parser.parse_args()

    seed = next(v for v in seed_versions() if v.agent_key == "orchestrator")

    # An agent with the governance switched off. Not a straw man: it is the
    # SAME instruction text, with the policy levers set to the values an
    # ordinary autonomous agent effectively runs with -- act on whatever
    # evidence you have, do not require a human, do not verify afterwards.
    ungoverned = build_version(
        agent_key="orchestrator",
        instruction=seed.instruction,
        policy={
            "min_evidence_completeness": 0.0,
            "require_human_on_contradiction": False,
            "max_plan_steps": 8,
            "verify_after_execute": False,
        },
        version_n=1,
    )
    assert ungoverned.instruction == seed.instruction, "only the policy differs"

    record: dict[str, object] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "scenarios": [s.key for s in SCENARIOS],
    }

    # -- 1. Measure both, over the same real evidence ----------------------
    _rule("1. BASELINE vs GOVERNED, over the committed evidence bundle")
    print(f"  dataset: {len(SCENARIOS)} scenarios -- {', '.join(s.key for s in SCENARIOS)}")
    ungoverned_result = replay_version(ungoverned)
    governed_result = replay_version(seed)

    print(f"\n  UNGOVERNED composite {ungoverned_result.composite}")
    _means_table("per criterion:", ungoverned_result.criterion_means())
    print(f"\n  GOVERNED (seed v1) composite {governed_result.composite}")
    _means_table("per criterion:", governed_result.criterion_means())

    print("\n  The point of the table above:")
    print(
        f"    TASK_SUCCESS  ungoverned {ungoverned_result.criterion_means()['TASK_SUCCESS']:.2f}"
        f"  >  governed {governed_result.criterion_means()['TASK_SUCCESS']:.2f}"
    )
    print("    An evaluation that reads only the final status ranks the UNGOVERNED")
    print("    agent first: it completed every mission. It completed them by acting")
    print("    on thin and contested evidence with nobody in the loop.")
    record["ungoverned"] = {
        "composite": ungoverned_result.composite,
        "criterion_means": ungoverned_result.criterion_means(),
        "statuses": [r["status"] for r in ungoverned_result.reports],
        "external_actions": [r["external_action"] for r in ungoverned_result.reports],
    }
    record["governed"] = {
        "composite": governed_result.composite,
        "criterion_means": governed_result.criterion_means(),
        "statuses": [r["status"] for r in governed_result.reports],
        "external_actions": [r["external_action"] for r in governed_result.reports],
    }

    # -- 2. The promotion the loop exists to make --------------------------
    _rule("2. PROMOTION: ungoverned -> governed")
    governed_candidate = build_version(
        agent_key="orchestrator",
        instruction=seed.instruction,
        policy=dict(seed.policy),
        version_n=2,
        parent_version_id=ungoverned.version_id,
    )
    decision = evaluate_promotion(ungoverned, governed_candidate)
    print(f"  outcome: {decision.outcome.value}")
    print(f"  composite: {decision.baseline_composite} -> {decision.candidate_composite}")
    for reason in decision.reasons:
        print(f"    - {reason}")
    record["promotion_ungoverned_to_governed"] = decision.model_dump(mode="json")

    # -- 3. The reverse trade must be refused ------------------------------
    _rule("3. REFUSAL: a candidate that trades safety for completions")
    loosened = build_version(
        agent_key="orchestrator",
        instruction=seed.instruction,
        policy={
            **seed.policy,
            "require_human_on_contradiction": False,
            "verify_after_execute": False,
        },
        version_n=3,
        parent_version_id=governed_candidate.version_id,
    )
    refusal = evaluate_promotion(governed_candidate, loosened, human_principal=HUMAN)
    print(f"  outcome: {refusal.outcome.value}")
    for reason in refusal.reasons:
        print(f"    - {reason}")
    record["promotion_safety_traded_away"] = refusal.model_dump(mode="json")

    # -- 4. A model cannot promote itself ----------------------------------
    _rule("4. SELF-PROMOTION: refused before any measurement runs")
    try:
        promote(
            ungoverned,
            governed_candidate,
            human_principal="agent::fleet_orchestrator",
            persist=False,
        )
        print("  UNEXPECTED: the promotion was not refused")
        record["self_promotion_refused"] = False
    except Exception as exc:
        print(f"  {type(exc).__name__}: {exc}")
        record["self_promotion_refused"] = True

    # -- 5. Proposing from a clean history ---------------------------------
    _rule("5. PROPOSAL from a clean history: refused, not invented")
    try:
        propose_candidate(baseline=seed, evaluations=[], version_n=2, allow_model=False)
        print("  UNEXPECTED: a candidate was generated with nothing measured")
        record["clean_history_refused"] = False
    except ProposalRejected as exc:
        print(f"  ProposalRejected: {exc}")
        record["clean_history_refused"] = True

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")
        print(f"\nraw result written to {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
