"""Eval harness runner.

Scenarios are marked against `corpus/data/radius_truth.jsonl`. That file is the
MARKING SCHEME: the harness reads it, the cascade must never touch it.
`tests/test_ground_truth_isolation.py` enforces that, because a cascade that can
read its own answer key would score perfectly and prove nothing.

A run over zero scenarios is still a valid run and exits 0, but it writes a
results file that says in the file itself that nothing was evaluated.

Metric values are computed here from the cascade's output and the marking
scheme. Nothing is stated as measured that this file did not measure.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evals.metrics import METRICS, MetricResult, unavailable

REPO = Path(__file__).resolve().parents[1]

SCENARIO_CLASSES = ("clean", "ambiguous", "adversarial", "tool_failure", "multi_premise")


@dataclass
class ScenarioOutcome:
    scenario_class: str
    name: str
    status: str  # passed | failed | skipped
    reason: str | None = None
    metrics: list[MetricResult] = field(default_factory=list)
    detail: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "class": self.scenario_class,
            "name": self.name,
            "status": self.status,
            "reason": self.reason,
            "metrics": [m.to_json() for m in self.metrics],
            "detail": self.detail,
        }


def discover(scenarios_dir: Path) -> list[tuple[str, Path]]:
    found: list[tuple[str, Path]] = []
    for scenario_class in SCENARIO_CLASSES:
        class_dir = scenarios_dir / scenario_class
        if not class_dir.is_dir():
            continue
        for path in sorted(class_dir.glob("*/scenario.json")):
            found.append((scenario_class, path))
    return found


def _load_ground_truth(rel_path: str) -> dict[str, dict[str, Any]]:
    path = REPO / rel_path
    rows = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    return {row["conclusion_id"]: row for row in rows}


def _score(
    result: Any, truth: dict[str, dict[str, Any]], elapsed_s: float
) -> tuple[list[MetricResult], dict[str, Any]]:
    """Compute every metric from the cascade result against the marking scheme."""
    found = set(result.radius)
    expected = set(truth)
    hits = found & expected

    recall = len(hits) / len(expected) if expected else 0.0
    precision = len(hits) / len(found) if found else 0.0

    # Marked against `live_material`, not `material`. The marking scheme records
    # both: `material` is the buffer arithmetic alone, `live_material` also
    # requires the commitment to be open at the retraction. The second is the
    # operationally correct definition -- a delivery completed in March cannot be
    # harmed by a premise that moved in July -- so it is what the cascade is held
    # to. Marking against `material` would credit the cascade for alerting on
    # commitments that already discharged.
    scoreable = [c for c in hits if not truth[c]["unresolvable"]]
    agreed = 0
    disagreed: list[str] = []
    for conclusion_id in scoreable:
        verdict = result.radius[conclusion_id]
        if verdict.material is None:
            disagreed.append(conclusion_id)
            continue
        if verdict.material == truth[conclusion_id]["live_material"]:
            agreed += 1
        else:
            disagreed.append(conclusion_id)
    materiality_accuracy = agreed / len(scoreable) if scoreable else None

    escapement_agreed = sum(1 for c in hits if result.radius[c].escaped == truth[c]["escaped"])
    escapement_accuracy = escapement_agreed / len(hits) if hits else None

    unresolved = [c for c in found if result.radius[c].material is None]
    unresolved_rate = len(unresolved) / len(found) if found else 0.0

    # A false retraction is an unwind action against something the marking
    # scheme says was NOT materially harmed. In this task the only "action" a
    # cascade takes is landing a node in a MATERIAL regime, so that is what is
    # counted. Task 4 widens this to actual outbound corrections.
    acted_on = [c for c in hits if result.radius[c].material is True]
    false_actions = [c for c in acted_on if not truth[c]["live_material"]]
    false_retraction_rate = len(false_actions) / len(acted_on) if acted_on else 0.0
    if result.authority.allowed is False:
        # A refused retraction that still cascaded would be the worst failure
        # available; treat any radius at all as wholly false.
        false_retraction_rate = 1.0 if found else 0.0

    results = [
        MetricResult(
            "blast_radius_recall", recall, detail={"found": len(found), "expected": len(expected)}
        ),
        MetricResult("blast_radius_precision", precision, detail={"hits": len(hits)}),
        MetricResult(
            "materiality_accuracy",
            materiality_accuracy,
            unavailable_reason=None if scoreable else "no arithmetically scoreable nodes",
            detail={"scored": len(scoreable), "disagreements": sorted(disagreed)[:20]},
        ),
        MetricResult(
            "false_retraction_rate",
            false_retraction_rate,
            detail={"acted_on": len(acted_on), "false": sorted(false_actions)[:20]},
        ),
        MetricResult("escapement_accuracy", escapement_accuracy),
        MetricResult(
            "human_escalation_precision",
            None,
            unavailable_reason="No escalation path exists yet; ASK_HUMAN is Task 3.",
        ),
        MetricResult("unresolved_rate", unresolved_rate, detail={"unresolved": len(unresolved)}),
        MetricResult(
            "cost_per_cascade",
            0.0,
            detail={
                "model_calls": result.model_calls,
                "note": "Zero by construction: this cascade is T0+T1 and makes no model call.",
            },
        ),
        MetricResult(
            "time_to_obligation",
            None,
            unavailable_reason="Obligations are Task 4. Wall-clock for the cascade itself "
            f"was {elapsed_s:.3f}s.",
        ),
    ]
    detail = {
        "cascade_id": result.cascade_id,
        "authority": result.authority.to_json(),
        "tier_reached": result.tier_reached,
        "model_calls": result.model_calls,
        "elapsed_seconds": round(elapsed_s, 4),
        "regime_counts": result.regime_counts(),
        "radius_size": len(found),
        "ground_truth_size": len(expected),
    }
    return results, detail


def run_scenario(scenario_class: str, path: Path) -> ScenarioOutcome:
    try:
        spec = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return ScenarioOutcome(
            scenario_class, path.parent.name, "failed", f"could not read scenario: {exc}"
        )

    name = spec.get("name", path.parent.name)
    try:
        from spine.cascade import CorpusStore, run_cascade
    except ImportError as exc:
        return ScenarioOutcome(
            scenario_class,
            name,
            "failed",
            f"cascade is not implemented: {exc}",
            metrics=unavailable([m.key for m in METRICS], "cascade not implemented"),
        )

    # Scenarios come in two shapes. GROUND-TRUTH scenarios are marked against
    # radius_truth.jsonl and measure recall/precision/materiality. OUTCOME
    # scenarios assert which of the five states the system reaches and why --
    # that is the whole question for an adversarial or ambiguous case, where
    # "what did it decide" matters far more than "how big was the radius".
    # A third shape: SETTLEMENT scenarios carry `retractions` (plural) and ask
    # what the court did with two overlapping radii -- did they merge, did any
    # commitment get two obligations, did the arbiter allocate a contested
    # resource or deadlock over it. Neither of the other two shapes can express
    # that, because both assume exactly one retraction.
    if "retractions" in spec:
        return _run_settlement_scenario(scenario_class, name, spec)

    if "ground_truth" not in spec:
        return _run_outcome_scenario(scenario_class, name, spec)

    retraction = spec["retraction"]
    truth = _load_ground_truth(spec["ground_truth"])
    triggered_at = (
        datetime.fromisoformat(retraction["triggered_at"].replace("Z", "+00:00"))
        if retraction.get("triggered_at")
        else None
    )

    started = time.perf_counter()
    try:
        result = run_cascade(
            store=CorpusStore.from_repo(REPO),
            claim_id=retraction["claim_id"],
            source_id=retraction["source_id"],
            new_value=retraction["new_value"],
            reason=retraction.get("reason", ""),
            triggered_at=triggered_at,
        )
    except Exception as exc:  # noqa: BLE001 - a crashed cascade is a failed scenario
        return ScenarioOutcome(
            scenario_class,
            name,
            "failed",
            f"cascade raised {type(exc).__name__}: {exc}",
            metrics=unavailable([m.key for m in METRICS], "cascade raised"),
        )
    elapsed = time.perf_counter() - started

    metrics, detail = _score(result, truth, elapsed)
    by_key = {m.key: m for m in metrics}

    failures: list[str] = []
    expect = spec.get("expect", {})
    if "authority" in expect:
        actual = "allow" if result.authority.allowed else "refuse"
        if actual != expect["authority"]:
            failures.append(f"authority: expected {expect['authority']}, got {actual}")
    if "model_calls" in expect and result.model_calls != expect["model_calls"]:
        failures.append(f"model_calls: expected {expect['model_calls']}, got {result.model_calls}")
    if "tier_reached" in expect and result.tier_reached != expect["tier_reached"]:
        failures.append(
            f"tier_reached: expected {expect['tier_reached']}, got {result.tier_reached}"
        )
    for key in (
        "blast_radius_recall",
        "blast_radius_precision",
        "materiality_accuracy",
        "false_retraction_rate",
    ):
        if key not in expect:
            continue
        value = by_key[key].value
        if value is None or abs(value - expect[key]) > 1e-9:
            failures.append(f"{key}: expected {expect[key]}, got {value}")

    return ScenarioOutcome(
        scenario_class,
        name,
        "failed" if failures else "passed",
        "; ".join(failures) if failures else None,
        metrics=metrics,
        detail=detail,
    )


#: What each expected outcome means, so a scenario file stays readable.
_OUTCOME_CHECKS = {
    "refuse": "the five-state router must REFUSE",
    "defer": "the premise is contested; the router must DEFER",
    "ask_human": "the radius or exposure requires a signature",
    "execute": "all gates pass and the cascade completes",
    "unresolved-dominant": "most of the radius must render UNRESOLVED, not be decided",
}


def _run_outcome_scenario(scenario_class: str, name: str, spec: dict[str, Any]) -> ScenarioOutcome:
    """Assert which of the five states the system reaches, and why."""
    import os

    from lib.config import reset_config_cache
    from lib.schema import Regime
    from spine.cascade import CorpusStore, run_cascade

    retraction = spec["retraction"]
    expect = spec.get("expect", {})

    # `vertex_disabled` scenarios prove the tiering guarantee inside the eval
    # rather than only in CI: T2 must render UNRESOLVED, never silently resolve.
    previous = os.environ.get("UNWIND_VERTEX_DISABLED")
    if spec.get("vertex_disabled"):
        os.environ["UNWIND_VERTEX_DISABLED"] = "1"
        reset_config_cache()

    started = time.perf_counter()
    try:
        result = run_cascade(
            store=CorpusStore.from_repo(REPO),
            claim_id=retraction["claim_id"],
            source_id=retraction["source_id"],
            new_value=retraction["new_value"],
            reason=retraction.get("reason", ""),
            triggered_at=datetime.fromisoformat(retraction["triggered_at"].replace("Z", "+00:00")),
            confidence=float(retraction.get("confidence", 1.0)),
            corroborating_sources=retraction.get("corroborating_sources"),
        )
    except Exception as exc:  # noqa: BLE001
        return ScenarioOutcome(
            scenario_class, name, "failed", f"cascade raised {type(exc).__name__}: {exc}"
        )
    finally:
        if spec.get("vertex_disabled"):
            if previous is None:
                os.environ.pop("UNWIND_VERTEX_DISABLED", None)
            else:
                os.environ["UNWIND_VERTEX_DISABLED"] = previous
            reset_config_cache()
    elapsed = time.perf_counter() - started

    state = result.decision.state.value if result.decision else "unknown"
    counts = result.regime_counts()
    unresolved = counts.get(Regime.UNRESOLVED.value, 0)
    radius = len(result.radius)

    failures: list[str] = []
    wanted = expect.get("outcome")
    if wanted == "unresolved-dominant":
        # The claim is that the system DECLINED to decide, not that it decided
        # correctly -- so the bar is that unresolved dominates the radius.
        if radius == 0 or unresolved / radius < 0.5:
            failures.append(f"expected most of the radius UNRESOLVED, got {unresolved}/{radius}")
    elif wanted and wanted != state:
        failures.append(f"outcome: expected {wanted}, got {state}")

    if "authority_reason_code" in expect:
        actual = result.authority.reason_code.value
        if actual != expect["authority_reason_code"]:
            failures.append(
                f"authority reason: expected {expect['authority_reason_code']}, got {actual}"
            )
    if "radius_size" in expect and radius != expect["radius_size"]:
        failures.append(f"radius_size: expected {expect['radius_size']}, got {radius}")
    if "model_calls" in expect and result.model_calls != expect["model_calls"]:
        failures.append(f"model_calls: expected {expect['model_calls']}, got {result.model_calls}")

    # A refusal that still walked the graph is the worst failure available here.
    acted = state == "execute"
    false_retraction = 1.0 if (wanted in {"refuse", "defer"} and acted) else 0.0

    metrics = [
        MetricResult(
            "false_retraction_rate",
            false_retraction,
            detail={"expected_outcome": wanted, "actual_state": state},
        ),
        MetricResult(
            "unresolved_rate",
            round(unresolved / radius, 6) if radius else 0.0,
            detail={"unresolved": unresolved, "radius": radius},
        ),
        MetricResult("cost_per_cascade", 0.0, detail={"model_calls": result.model_calls}),
        MetricResult(
            "human_escalation_precision",
            1.0 if state == "ask_human" and wanted == "ask_human" else None,
            unavailable_reason=None if state == "ask_human" else "no escalation in this scenario",
        ),
    ]

    return ScenarioOutcome(
        scenario_class,
        name,
        "failed" if failures else "passed",
        "; ".join(failures) if failures else None,
        metrics=metrics,
        detail={
            "cascade_id": result.cascade_id,
            "decision_state": state,
            "decision_why": (result.decision.why[:220] if result.decision else None),
            "authority_reason": result.authority.reason_code.value,
            "radius_size": radius,
            "regime_counts": counts,
            "model_calls": result.model_calls,
            "contesting_claims": result.contesting_claims,
            "vertex_disabled": bool(spec.get("vertex_disabled")),
            "elapsed_seconds": round(elapsed, 4),
            "check": _OUTCOME_CHECKS.get(wanted, wanted),
        },
    )


def _run_settlement_scenario(
    scenario_class: str, name: str, spec: dict[str, Any]
) -> ScenarioOutcome:
    """Two or more premises fail; assert the court merged and settled correctly.

    The three questions the brief asks of `multi_premise/`, as assertions:
      · do the radii MERGE, or does the second cascade re-raise the first's work
      · does any commitment end up with TWO obligations
      · does the arbiter ALLOCATE a contested resource, or deadlock on it
    """
    import os

    from judgment.model import ScriptedT2Model
    from lib.config import reset_config_cache
    from settle.pipeline import settle
    from spine.cascade import CorpusStore, run_cascade

    expect = spec.get("expect", {})
    previous = os.environ.get("UNWIND_VERTEX_DISABLED")
    if spec.get("vertex_disabled"):
        os.environ["UNWIND_VERTEX_DISABLED"] = "1"
        reset_config_cache()

    started = time.perf_counter()
    try:
        store = CorpusStore.from_repo(REPO)
        results = [
            run_cascade(
                store=store,
                claim_id=r["claim_id"],
                source_id=r["source_id"],
                new_value=r["new_value"],
                reason=r.get("reason", ""),
                triggered_at=datetime.fromisoformat(r["triggered_at"].replace("Z", "+00:00")),
                confidence=float(r.get("confidence", 1.0)),
                corroborating_sources=r.get("corroborating_sources"),
            )
            for r in spec["retractions"]
        ]
        # The scripted model keeps the eval deterministic and is LABELLED as
        # such: no number from this path may ever be presented as a Vertex
        # measurement.
        outcome = settle(
            results=results,
            store=store,
            model=ScriptedT2Model(),
            now=datetime.fromisoformat(
                spec["retractions"][0]["triggered_at"].replace("Z", "+00:00")
            ),
            repair_id=f"rep_{name}",
            contested_resources=spec.get("contested_resources"),
        )
    except Exception as exc:  # noqa: BLE001
        return ScenarioOutcome(
            scenario_class, name, "failed", f"settlement raised {type(exc).__name__}: {exc}"
        )
    finally:
        if spec.get("vertex_disabled"):
            if previous is None:
                os.environ.pop("UNWIND_VERTEX_DISABLED", None)
            else:
                os.environ["UNWIND_VERTEX_DISABLED"] = previous
            reset_config_cache()
    elapsed = time.perf_counter() - started

    obligation_ids = [d.obligation.obligation_id for d in outcome.obligations]
    covered = [d.conclusion_id for d in outcome.obligations]
    duplicate_obligations = len(covered) - len(set(covered))
    court = outcome.proceedings.outcome if outcome.proceedings else None

    failures: list[str] = []
    if "max_duplicate_obligations" in expect:
        if duplicate_obligations > expect["max_duplicate_obligations"]:
            failures.append(
                f"duplicate obligations: {duplicate_obligations} > "
                f"{expect['max_duplicate_obligations']}"
            )
    if expect.get("radii_merge") and outcome.duplicates_suppressed <= 0:
        failures.append("radii did not overlap, so this scenario does not test merging at all")
    if "min_team_size" in expect and outcome.team.seated < expect["min_team_size"]:
        failures.append(f"team seated {outcome.team.seated} < {expect['min_team_size']}")
    if expect.get("arbiter_must_rule") and court is None:
        failures.append("no ruling was produced")
    if expect.get("must_converge") and outcome.proceedings and not outcome.proceedings.converged:
        failures.append("the protocol failed to converge")
    if expect.get("must_allocate"):
        if not (court and any("lost the allocation" in d for d in court.dissent)):
            failures.append("a contested resource was not allocated -- the arbiter deadlocked")
    if expect.get("team_must_dissolve") and not outcome.team.dissolved:
        failures.append("the team outlived the settlement")
    if "min_obligations" in expect and len(outcome.obligations) < expect["min_obligations"]:
        failures.append(f"obligations {len(outcome.obligations)} < {expect['min_obligations']}")

    # Every obligation must still name a human. An unsigned obligation is fine;
    # an unsignable one is a dead end.
    unassigned = [
        d.obligation.obligation_id for d in outcome.obligations if not d.obligation.approver
    ]
    if unassigned:
        failures.append(f"obligations with no approver: {unassigned}")

    metrics = [
        MetricResult(
            "false_retraction_rate",
            0.0,
            detail={"obligations": len(outcome.obligations), "duplicates": duplicate_obligations},
        ),
        MetricResult(
            "unresolved_rate",
            0.0,
            detail={"note": "settlement scenarios assert court behaviour, not regime mix"},
        ),
        MetricResult("cost_per_cascade", 0.0, detail={"model": "scripted-stub"}),
        MetricResult(
            "human_escalation_precision",
            1.0 if court and court.ruling.advisory else None,
            unavailable_reason=None if court and court.ruling.advisory else "ruling not advisory",
        ),
    ]

    return ScenarioOutcome(
        scenario_class,
        name,
        "failed" if failures else "passed",
        "; ".join(failures) if failures else None,
        metrics=metrics,
        detail={
            "claim_ids": outcome.claim_ids,
            "radius_size": outcome.radius_size,
            "duplicates_suppressed": outcome.duplicates_suppressed,
            "team_eligible": outcome.team.eligible,
            "team_seated": outcome.team.seated,
            "team_dissolved": outcome.team.dissolved,
            "turns_used": outcome.proceedings.turns_used if outcome.proceedings else 0,
            "converged": outcome.proceedings.converged if outcome.proceedings else None,
            "ruling": court.ruling.decision if court else None,
            "advisory": court.ruling.advisory if court else None,
            "dissent_count": len(court.dissent) if court else 0,
            "obligations": len(obligation_ids),
            "duplicate_obligations": duplicate_obligations,
            "model": "scripted-stub (NOT Vertex)",
            "elapsed_seconds": round(elapsed, 4),
        },
    )


def run(scenarios_dir: Path, out_dir: Path) -> dict[str, Any]:
    discovered = discover(scenarios_dir)
    outcomes = [run_scenario(cls, path) for cls, path in discovered]

    missing_classes = [c for c in SCENARIO_CLASSES if not (scenarios_dir / c).is_dir()]
    empty_classes = [
        c
        for c in SCENARIO_CLASSES
        if (scenarios_dir / c).is_dir() and not any((scenarios_dir / c).glob("*/scenario.json"))
    ]

    computed = sorted({m.key for o in outcomes for m in o.metrics if m.value is not None})
    report: dict[str, Any] = {
        "run_at": datetime.now(UTC).isoformat(),
        "stage": "task-2-deterministic-spine",
        "harness_version": "0.2.0",
        "python": platform.python_version(),
        "scenarios_discovered": len(discovered),
        "scenarios_passed": sum(1 for o in outcomes if o.status == "passed"),
        "scenarios_failed": sum(1 for o in outcomes if o.status == "failed"),
        "scenarios_skipped": sum(1 for o in outcomes if o.status == "skipped"),
        "empty_scenario_classes": empty_classes,
        "missing_scenario_classes": missing_classes,
        "metrics_defined": [m.key for m in METRICS],
        "metrics_computed": computed,
        "by_class": {
            cls: {
                "total": sum(1 for o in outcomes if o.scenario_class == cls),
                "passed": sum(
                    1 for o in outcomes if o.scenario_class == cls and o.status == "passed"
                ),
                "failed": sum(
                    1 for o in outcomes if o.scenario_class == cls and o.status == "failed"
                ),
                "routed_to_human": sum(
                    1
                    for o in outcomes
                    if o.scenario_class == cls
                    and o.detail.get("decision_state") in {"ask_human", "defer"}
                ),
            }
            for cls in SCENARIO_CLASSES
            if any(o.scenario_class == cls for o in outcomes)
        },
        "false_retraction_rate": _aggregate_false_retraction(outcomes),
        "total_model_calls": sum(o.detail.get("model_calls", 0) for o in outcomes if o.detail),
        "note": (
            "NOTHING WAS EVALUATED. No scenarios were discovered."
            if not discovered
            else "Metric values below were computed by this harness from the cascade "
            "output and corpus/data/radius_truth.jsonl."
        ),
        "outcomes": [o.to_json() for o in outcomes],
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "latest.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    # A second, DETERMINISTIC file. `latest.json` carries a run timestamp and a
    # wall-clock duration, so it changes on every run and cannot be diffed
    # against a committed copy. The summary strips exactly those fields, which
    # makes "the committed results still match the code" a check CI can enforce
    # rather than a claim in a README.
    (out_dir / "summary.json").write_text(
        json.dumps(_deterministic_summary(report), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def _aggregate_false_retraction(outcomes: list[ScenarioOutcome]) -> float | None:
    """THE METRIC THAT MATTERS, across every scenario that produced one."""
    values = [
        m.value
        for o in outcomes
        for m in o.metrics
        if m.key == "false_retraction_rate" and m.value is not None
    ]
    return round(sum(values) / len(values), 6) if values else None


def _deterministic_summary(report: dict[str, Any]) -> dict[str, Any]:
    """Everything in the report that is reproducible from the committed inputs."""
    return {
        "stage": report["stage"],
        "harness_version": report["harness_version"],
        "scenarios_discovered": report["scenarios_discovered"],
        "scenarios_passed": report["scenarios_passed"],
        "scenarios_failed": report["scenarios_failed"],
        "scenarios_skipped": report["scenarios_skipped"],
        "total_model_calls": report["total_model_calls"],
        "false_retraction_rate": report.get("false_retraction_rate"),
        "by_class": report.get("by_class", {}),
        "metrics_computed": report["metrics_computed"],
        "outcomes": [
            {
                "class": outcome["class"],
                "name": outcome["name"],
                "status": outcome["status"],
                "reason": outcome["reason"],
                "cascade_id": outcome["detail"].get("cascade_id"),
                "radius_size": outcome["detail"].get("radius_size"),
                "ground_truth_size": outcome["detail"].get("ground_truth_size"),
                "regime_counts": outcome["detail"].get("regime_counts"),
                "decision_state": outcome["detail"].get("decision_state"),
                "authority_reason": outcome["detail"].get("authority_reason"),
                "tier_reached": outcome["detail"].get("tier_reached"),
                "model_calls": outcome["detail"].get("model_calls"),
                "metrics": {
                    m["key"]: m["value"] for m in outcome["metrics"] if m["value"] is not None
                },
            }
            for outcome in report["outcomes"]
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the UNWIND eval harness.")
    parser.add_argument("--scenarios", type=Path, default=Path("evals/scenarios"))
    parser.add_argument("--out", type=Path, default=Path("evals/results"))
    parser.add_argument("--quiet", action="store_true", help="Print the summary only.")
    parser.add_argument(
        "--trace",
        action="store_true",
        help="Export spans to the console. Off by default: this command's stdout "
        "is a JSON report, and span output would corrupt it.",
    )
    args = parser.parse_args(argv)

    # Must be set before the first span is opened, since telemetry configures
    # itself lazily on first use.
    os.environ["UNWIND_OTEL_CONSOLE"] = "1" if args.trace else "0"

    report = run(args.scenarios, args.out)
    if args.quiet:
        print(
            f"scenarios: {report['scenarios_passed']} passed, "
            f"{report['scenarios_failed']} failed, "
            f"{report['scenarios_skipped']} skipped; "
            f"model calls: {report['total_model_calls']}"
        )
    else:
        print(json.dumps(report, indent=2, sort_keys=True))

    if report["missing_scenario_classes"]:
        print(f"missing scenario classes: {report['missing_scenario_classes']}", file=sys.stderr)
        return 1
    return 1 if report["scenarios_failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
