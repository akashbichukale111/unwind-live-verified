"""Command line entry points for the deterministic spine.

    python -m spine.cli cascade --claim clm_000000 --source src_supplier_K --new-value 20
    python -m spine.cli cascade --source src_broker_Z --new-value 34     # refused
    python -m spine.cli debt

Both run with no GCP account and no model. `--persist` additionally writes the
cascade and its nodes to Firestore, which needs the emulator running.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]

#: The instant the committed corpus is built around. Using it by default keeps
#: the CLI reproducible; "already closed out" is a time-dependent verdict, so a
#: wall-clock default would make two runs disagree.
CORPUS_RETRACTION_AT = "2026-07-06T09:00:00Z"


def _when(raw: str) -> datetime:
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


def cmd_cascade(args: argparse.Namespace) -> int:
    from spine.cascade import CorpusStore, run_cascade

    store = CorpusStore.from_repo(REPO)
    result = run_cascade(
        store=store,
        claim_id=args.claim,
        source_id=args.source,
        new_value=args.new_value,
        reason=args.reason,
        triggered_at=_when(args.at),
        confidence=args.confidence,
        corroborating_sources=[s for s in args.corroborating.split(",") if s] or None,
    )

    report: dict[str, Any] = {
        "cascade_id": result.cascade_id,
        "status": result.status.value,
        "authority": result.authority.to_json(),
        "model_calls": result.model_calls,
    }

    report["decision"] = (
        {"state": result.decision.state.value, "why": result.decision.why}
        if result.decision
        else None
    )
    if result.contesting_claims:
        report["contesting_claims"] = result.contesting_claims
    if result.echo is not None:
        report["echo_back"] = result.echo.to_json()

    if result.status.value == "refused":
        report["note"] = (
            "Refused before a single edge was walked. The radius is empty because "
            "the traversal never ran."
        )
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0

    counts = result.regime_counts()
    alerts = result.alerts()
    report.update(
        {
            "radius_size": len(result.radius),
            "traversal": {
                "max_depth": result.traversal.max_depth if result.traversal else 0,
                "claims_visited": result.traversal.claims_visited if result.traversal else 0,
                "cycles_detected": len(result.traversal.cycles_detected) if result.traversal else 0,
                "dangling_edges": len(result.traversal.dangling_edges) if result.traversal else 0,
            },
            "regimes": counts,
            "budget": {
                "policy_tier": result.budget.policy_tier.value if result.budget else None,
                "tier_reached": result.tier_reached,
                "stopped_reason": result.budget.stopped_reason if result.budget else None,
                "rationale": result.budget.rationale if result.budget else [],
            },
            "temporal_truth": {
                "prior": result.retraction.prior.to_json() if result.retraction else None,
                "invalidated_at": (
                    result.retraction.retracted.invalidated_at.isoformat()
                    if result.retraction and result.retraction.retracted.invalidated_at
                    else None
                ),
                "invalidation_reason": (
                    result.retraction.retracted.invalidation_reason if result.retraction else None
                ),
            },
            "top_alerts": [
                {
                    "conclusion_id": v.conclusion_id,
                    "depth": v.depth,
                    "exposure": v.exposure,
                    "slack_days": v.slack_days,
                    "shock_days": v.shock_days,
                    "reason": v.reason,
                }
                for v in alerts[: args.top]
            ],
        }
    )

    if args.persist:
        from lib import firestore as fs

        scored_at = result.triggered_at or datetime.now(UTC)
        fs.put_cascade(result.to_cascade_doc())
        written = fs.put_cascade_nodes(
            result.cascade_id,
            (v.to_cascade_node(result.cascade_id, scored_at) for v in result.radius.values()),
        )
        report["persisted"] = {"cascade_nodes_written": written}

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def cmd_debt(args: argparse.Namespace) -> int:
    from spine.cascade import CorpusStore
    from spine.debt import score_causal_debt

    store = CorpusStore.from_repo(REPO)
    report = score_causal_debt(
        claims=list(store.claims.values()),
        conclusions=list(store.conclusions.values()),
        as_of=_when(args.at),
        top_n=args.top,
    )
    payload = report.score.model_dump(mode="json")
    payload["contributions_recorded"] = len(report.contributions)
    payload["contributions_dropped_below_threshold"] = report.dropped_below_threshold
    payload["dropped_total"] = report.dropped_total
    if report.contributions:
        heaviest = max(report.contributions, key=lambda c: c.contribution)
        payload["heaviest_single_contribution"] = heaviest.model_dump(mode="json")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="UNWIND deterministic spine.")
    parser.add_argument("--trace", action="store_true", help="Export spans to the console.")
    sub = parser.add_subparsers(dest="command", required=True)

    c = sub.add_parser("cascade", help="Run a full cascade from a retraction.")
    c.add_argument("--claim", default="clm_000000")
    c.add_argument("--source", default="src_supplier_K")
    c.add_argument("--new-value", type=float, default=20.0)
    c.add_argument("--reason", default="Supplier notified a revised standard lead time.")
    c.add_argument("--at", default=CORPUS_RETRACTION_AT)
    c.add_argument("--top", type=int, default=5)
    c.add_argument("--confidence", type=float, default=1.0)
    c.add_argument(
        "--corroborating",
        default="",
        help="Comma-separated source ids corroborating the change.",
    )
    c.add_argument(
        "--persist",
        action="store_true",
        help="Write the cascade and its nodes to Firestore (needs the emulator).",
    )
    c.set_defaults(func=cmd_cascade)

    d = sub.add_parser("debt", help="Score standing causal debt across the corpus.")
    d.add_argument("--at", default=CORPUS_RETRACTION_AT)
    d.add_argument("--top", type=int, default=10)
    d.set_defaults(func=cmd_debt)

    args = parser.parse_args(argv)
    # stdout here is JSON; span output would corrupt it.
    os.environ["UNWIND_OTEL_CONSOLE"] = "1" if args.trace else "0"
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
