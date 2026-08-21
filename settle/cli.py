"""Command line entry points for the court and settlement.

    python -m settle.cli settle --claim clm_000000 --source src_supplier_K --new-value 20
    python -m settle.cli obligation          # one full obligation, rendered
    python -m settle.cli golden              # the deterministic court transcript

Everything here runs with no GCP account. With `UNWIND_VERTEX_DISABLED=1` the
court still sits: owners plead from arithmetic, the arbiter rules on the tally,
and only the PROSE degrades to the no-model fallback. That is the tier
discipline working, not a workaround.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]

#: The instant the committed corpus is built around, so two runs agree.
CORPUS_RETRACTION_AT = "2026-07-06T09:00:00Z"


def _when(raw: str) -> datetime:
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


def _run(args: argparse.Namespace) -> Any:
    from judgment.model import ScriptedT2Model, get_model
    from settle.pipeline import settle
    from spine.cascade import CorpusStore, run_cascade

    store = CorpusStore.from_repo(REPO)
    now = _when(args.at)

    retractions = [(args.claim, args.source, args.new_value)]
    if args.also_claim:
        retractions.append((args.also_claim, args.also_source, args.also_new_value))

    results = [
        run_cascade(
            store=store,
            claim_id=claim,
            source_id=source,
            new_value=value,
            reason=args.reason,
            triggered_at=now,
        )
        for claim, source, value in retractions
    ]

    # `--scripted` pins a deterministic model so the golden transcript is stable
    # even where credentials exist. It is labelled in the output; a number that
    # came from a stub must never look like a number that came from Vertex.
    model = ScriptedT2Model() if args.scripted else get_model()

    contested: dict[str, str] = {}
    if args.contest:
        # Two commitments made to contend for one finite thing, named on the
        # command line so the multi-premise allocation path is exercisable.
        for pair in args.contest.split(","):
            if ":" in pair:
                cid, resource = pair.split(":", 1)
                contested[cid] = resource

    return (
        store,
        results,
        settle(
            results=results,
            store=store,
            model=model,
            now=now,
            repair_id=args.repair_id,
            contested_resources=contested,
        ),
    )


def cmd_settle(args: argparse.Namespace) -> int:
    _, results, settlement = _run(args)
    outcome = settlement.proceedings.outcome if settlement.proceedings else None

    report: dict[str, Any] = {
        "claim_ids": settlement.claim_ids,
        "radius_size": settlement.radius_size,
        "duplicates_suppressed": settlement.duplicates_suppressed,
        "team": {
            "repair_id": settlement.team.repair_id,
            "seated": settlement.team.seated,
            "eligible": settlement.team.eligible,
            "capped": settlement.team.capped,
            "dissolved": settlement.team.dissolved,
        },
        "cascades": [
            {
                "claim_id": r.claim_id,
                "status": r.status.value,
                "decision": r.decision_state,
                "radius": len(r.radius),
                "alerts": len(r.alerts()),
            }
            for r in results
        ],
    }
    if settlement.proceedings and outcome:
        report["court"] = {
            "turns_used": settlement.proceedings.turns_used,
            "converged": settlement.proceedings.converged,
            "budget_allowance": settlement.proceedings.ledger.allowance,
            "budget_spent": settlement.proceedings.ledger.spent,
            "decision": outcome.ruling.decision,
            "advisory": outcome.ruling.advisory,
            "preserved": len(outcome.preserved),
            "amended": len(outcome.amended),
            "conceded": len(outcome.conceded),
            "dissent_count": len(outcome.dissent),
        }
    report["obligations"] = [
        {
            "obligation_id": d.obligation.obligation_id,
            "conclusion_id": d.conclusion_id,
            "counterparties": len(d.obligation.counterparties),
            "reversible": len(d.obligation.reversible_actions),
            "unrecoverable": len(d.unrecoverable),
            "exposure_low": d.obligation.residual_exposure.low,
            "exposure_high": d.obligation.residual_exposure.high,
            "unpriced_effects": d.obligation.residual_exposure.unpriced_effects,
            "approver": d.obligation.approver,
            "status": d.obligation.status.value,
        }
        for d in settlement.obligations
    ]
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def cmd_obligation(args: argparse.Namespace) -> int:
    """One complete obligation, rendered as a human would read it."""
    _, _, settlement = _run(args)
    if not settlement.obligations:
        print(
            "No obligation was raised: nothing in the radius was both material "
            "and escaped, or the court preserved every commitment.",
            file=sys.stderr,
        )
        return 1

    chosen = settlement.obligations[0]
    if args.pick:
        for drafted in settlement.obligations:
            if drafted.conclusion_id == args.pick:
                chosen = drafted
                break
    print(chosen.render())
    # The request that belongs to THIS obligation. Printing requests[0]
    # regardless would show a signature routed for a different commitment.
    for request in settlement.requests:
        if request.obligation_id == chosen.obligation.obligation_id:
            print()
            print(request.render())
            break
    return 0


def cmd_golden(args: argparse.Namespace) -> int:
    """The deterministic court transcript, for regression against drift."""
    _, _, settlement = _run(args)
    lines: list[str] = []
    add = lines.append
    proceedings = settlement.proceedings
    outcome = proceedings.outcome if proceedings else None

    add("UNWIND court transcript (golden)")
    add(f"claims          : {','.join(settlement.claim_ids)}")
    add(f"radius          : {settlement.radius_size}")
    add(f"duplicates      : {settlement.duplicates_suppressed}")
    add(f"team eligible   : {settlement.team.eligible}")
    add(f"team seated     : {settlement.team.seated}")
    add(f"team dissolved  : {settlement.team.dissolved}")
    if proceedings:
        add(f"turns used      : {proceedings.turns_used}")
        add(f"converged       : {proceedings.converged}")
        add(f"budget          : {proceedings.ledger.spent}/{proceedings.ledger.allowance}")
        add("")
        add("-- PLEAS " + "-" * 58)
        for plea in proceedings.repair.pleas:
            add(
                f"  {plea.member_owner_id} :: {plea.conclusion_id} :: "
                f"{plea.stance.value} :: evidence={len(plea.evidence)}"
            )
        add("")
        add("-- CHALLENGES " + "-" * 53)
        for challenge in proceedings.repair.challenges:
            add(
                f"  {challenge.challenger_owner_id} -> {challenge.target_owner_id} "
                f"over {challenge.contested_resource}"
            )
        if not proceedings.repair.challenges:
            add("  (none)")
    if outcome:
        add("")
        add("-- RULING " + "-" * 57)
        add(f"  arbiter  : {outcome.ruling.arbiter_id}")
        add(f"  decision : {outcome.ruling.decision}")
        add(f"  advisory : {outcome.ruling.advisory}")
        add("")
        add("-- DISSENT " + "-" * 56)
        for note in outcome.dissent:
            add(f"  {note}")
        if not outcome.dissent:
            add("  (none)")
    add("")
    add("-- OBLIGATIONS " + "-" * 52)
    for drafted in settlement.obligations:
        exposure = drafted.obligation.residual_exposure
        add(
            f"  {drafted.obligation.obligation_id} :: "
            f"counterparties={len(drafted.obligation.counterparties)} :: "
            f"reversible={len(drafted.obligation.reversible_actions)} :: "
            f"unrecoverable={len(drafted.unrecoverable)} :: "
            f"exposure={exposure.low}-{exposure.high} :: "
            f"unpriced={exposure.unpriced_effects}"
        )
    if not settlement.obligations:
        add("  (none)")

    text = "\n".join(lines) + "\n"
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


def main(argv: list[str] | None = None) -> int:
    os.environ.setdefault("UNWIND_OTEL_CONSOLE", "0")
    parser = argparse.ArgumentParser(prog="settle.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--claim", default="clm_000000")
        p.add_argument("--source", default="src_supplier_K")
        p.add_argument("--new-value", type=int, default=20)
        p.add_argument("--also-claim", default=None)
        p.add_argument("--also-source", default=None)
        p.add_argument("--also-new-value", type=int, default=None)
        p.add_argument("--reason", default="supplier notified a revised lead time")
        p.add_argument("--at", default=CORPUS_RETRACTION_AT)
        p.add_argument("--repair-id", default="rep_demo")
        p.add_argument("--contest", default=None, help="conclusion_id:resource,...")
        p.add_argument("--scripted", action="store_true", help="pin the deterministic stub")

    p_settle = sub.add_parser("settle", help="run the court and print a JSON report")
    common(p_settle)
    p_settle.set_defaults(func=cmd_settle)

    p_ob = sub.add_parser("obligation", help="render one full correction obligation")
    common(p_ob)
    p_ob.add_argument("--pick", default=None, help="render this conclusion's obligation")
    p_ob.set_defaults(func=cmd_obligation)

    p_gold = sub.add_parser("golden", help="write the deterministic court transcript")
    common(p_gold)
    p_gold.add_argument("--out", default="evals/golden/court.txt")
    p_gold.set_defaults(func=cmd_golden)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
