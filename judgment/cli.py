"""Command line entry points for the judgment tier.

    python -m judgment.cli coverage    # writes docs/COVERAGE.md
    python -m judgment.cli sentinel    # silence sweep over the corpus
    python -m judgment.cli t2          # the T2 queue, and what it does with it

None of these needs GCP credentials. `t2` runs against the scripted model unless
`--vertex` is passed, and says which it used in its own output.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CORPUS_RETRACTION_AT = "2026-07-06T09:00:00Z"

MODEL_NOTE = (
    "> **No real Vertex AI call has ever been made in this repository.** No GCP\n"
    "> credentials existed in the build environment. Extraction here is fully\n"
    "> deterministic and needs no model, so these numbers are genuine; anything\n"
    "> reported about the T2 judgement path came from the scripted stub in\n"
    "> `judgment/model.py` and is labelled as such."
)


def _when(raw: str) -> datetime:
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


def _artifacts() -> list[dict]:
    path = REPO / "corpus" / "data" / "artifacts.jsonl"
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def cmd_coverage(args: argparse.Namespace) -> int:
    from judgment.coverage import audit, write_report

    report = audit(_artifacts(), as_of=_when(args.at))
    out = write_report(report, REPO / args.out, MODEL_NOTE)
    worst = report.worst_class
    print(
        json.dumps(
            {
                "written": str(out.relative_to(REPO)),
                "artifacts_audited": report.artifacts_audited,
                "overall_recall": report.overall_recall,
                "worst_class": worst.label if worst else None,
                "worst_class_recall": worst.recall if worst else None,
                "under_covered": report.under_covered(),
                "by_class": {
                    label: {"gold": c.gold, "recall": c.recall, "precision": c.precision}
                    for label, c in report.by_class.items()
                },
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def cmd_sentinel(args: argparse.Namespace) -> int:
    from judgment.watch import sweep
    from spine.cascade import CorpusStore

    store = CorpusStore.from_repo(REPO)
    report = sweep(list(store.claims.values()), as_of=_when(args.at))
    print(json.dumps(report.to_json(), indent=2, sort_keys=True))
    return 0


def cmd_t2(args: argparse.Namespace) -> int:
    """Run the T2 queue: what T1 refused, and what judgement did with it."""
    from judgment.assessor import assess
    from judgment.model import ScriptedT2Model, get_model
    from judgment.rederive import build_bundle, re_derive
    from lib.schema import Regime
    from spine.cascade import CorpusStore, run_cascade

    at = _when(args.at)
    store = CorpusStore.from_repo(REPO)
    result = run_cascade(
        store=store,
        claim_id=args.claim,
        source_id=args.source,
        new_value=args.new_value,
        triggered_at=at,
    )

    queue = [v for v in result.radius.values() if v.regime is Regime.UNRESOLVED]

    if args.vertex:
        model = get_model(deep=True)
        model_kind = "vertex"
    else:
        # A scripted reply that is deliberately CONSERVATIVE: it declines to
        # state a commitment from a clause it cannot read, which is what an
        # honest judgement of these nodes looks like.
        model = ScriptedT2Model(
            replies={
                "blind_rederivation": json.dumps(
                    {
                        "committed_lead_days": None,
                        "confidence": 0.3,
                        "reasoning": (
                            "The governing clause states a mechanism, not a period; "
                            "no commitment can be stated from these premises alone."
                        ),
                    }
                )
            }
        )
        model_kind = "scripted-stub"

    outcomes: dict[str, int] = {}
    sample: list[dict] = []
    for verdict in sorted(queue, key=lambda v: v.conclusion_id)[: args.limit]:
        conclusion = store.get_conclusion(verdict.conclusion_id)
        premises = {}
        if conclusion:
            for premise_id in conclusion.premise_ids:
                claim = store.get_claim(premise_id)
                if claim:
                    premises[claim.canonical] = claim.value

        bundle = build_bundle(
            decision_kind=conclusion.kind.value if conclusion else "unknown",
            premises=premises,
            correlation_id=verdict.conclusion_id,
        )
        derivation = re_derive(bundle, model, now=at)
        assessment = assess(
            derivation,
            original_committed_lead_days=(conclusion.committed_lead_days if conclusion else None),
            now=at,
        )
        outcome = assessment.verdict.outcome.value
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
        if len(sample) < 3:
            sample.append(
                {
                    "conclusion_id": verdict.conclusion_id,
                    "outcome": outcome,
                    "reason": assessment.verdict.reason[:200],
                }
            )

    print(
        json.dumps(
            {
                "model": model_kind,
                "model_id": getattr(model, "model_id", "unknown"),
                "t2_queue_size": len(queue),
                "assessed": min(len(queue), args.limit),
                "outcomes": outcomes,
                "sample": sample,
                "note": (
                    "Every outcome above came from the scripted stub, not a real "
                    "model. What it demonstrates is the ORCHESTRATION: blindness, "
                    "principal separation, and that an unreadable clause produces "
                    "UNRESOLVED rather than a guess."
                    if model_kind == "scripted-stub"
                    else "Ran against Vertex AI."
                ),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="UNWIND judgment tier.")
    parser.add_argument("--trace", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    c = sub.add_parser("coverage", help="Audit extraction recall; write docs/COVERAGE.md")
    c.add_argument("--at", default=CORPUS_RETRACTION_AT)
    c.add_argument("--out", default="docs/COVERAGE.md")
    c.set_defaults(func=cmd_coverage)

    s = sub.add_parser("sentinel", help="Sweep for premises nobody has reaffirmed")
    s.add_argument("--at", default=CORPUS_RETRACTION_AT)
    s.set_defaults(func=cmd_sentinel)

    t = sub.add_parser("t2", help="Run the T2 queue over what T1 refused")
    t.add_argument("--claim", default="clm_000000")
    t.add_argument("--source", default="src_supplier_K")
    t.add_argument("--new-value", type=float, default=20.0)
    t.add_argument("--at", default=CORPUS_RETRACTION_AT)
    t.add_argument("--limit", type=int, default=50)
    t.add_argument("--vertex", action="store_true", help="Use the real model (needs credentials)")
    t.set_defaults(func=cmd_t2)

    args = parser.parse_args(argv)
    os.environ["UNWIND_OTEL_CONSOLE"] = "1" if args.trace else "0"
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
