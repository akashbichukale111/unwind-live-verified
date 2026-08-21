"""Hyperion's demo moment, staged end-to-end against a real Firestore emulator.

Two acts, both real calls into `hyperion/guard.py` (which itself calls the
real, unmodified `tower.gateway.evaluate_gateway`) -- nothing here is printed
without having actually happened:

  ACT 1 (nominal): an agent scoped to `claim.read` requests exactly that.
  ALLOWED, scored LOW. One clean event in the log.

  ACT 2 (scope escalation): the SAME agent then requests a claim's
  confidential settlement terms -- outside its granted scope. The real
  Gateway refuses it as SCOPE_EXCEEDED before any work happens; Hyperion
  scores it HIGH/CRITICAL and logs it. The fleet summary printed at the end
  is a real aggregate over both events, not a fabricated demo number.

Usage:
    make emulator                     # one terminal
    python scripts/demo_hyperion.py   # another
"""

from __future__ import annotations

import os
import sys
import warnings

warnings.filterwarnings("ignore", message="Detected filter using positional arguments")

os.environ.setdefault("UNWIND_OTEL_CONSOLE", "0")
os.environ.setdefault("FIRESTORE_EMULATOR_HOST", "localhost:8080")

from hyperion.guard import evaluate_with_hyperion  # noqa: E402
from hyperion.immune_memory import aggregate_fleet_summary  # noqa: E402
from hyperion.immune_memory import reset_for_test as reset_hyperion  # noqa: E402
from lib.config import reset_config_cache  # noqa: E402
from tower.registry import make_entry, put_agent  # noqa: E402
from tower.registry import reset_for_test as reset_registry  # noqa: E402

reset_config_cache()

BAR = "=" * 78


def _banner(title: str) -> None:
    print()
    print(BAR)
    print(title)
    print(BAR)


def main() -> None:
    reset_registry()
    reset_hyperion()

    sentinel = make_entry(
        "hyperion_sentinel",
        capabilities=["extract"],
        max_budget=100,
        authority_scope=["claim.read"],
        data_scope=[],
        risk_class_thresholds={"LOW": 100, "HIGH": 20},
    )
    put_agent(sentinel)

    _banner("ACT 1 -- nominal request, in scope")
    decision_1, assessment_1 = evaluate_with_hyperion(
        sentinel,
        task="read claim status for a routine reverse-index lookup",
        requested_scope=["claim.read"],
        requested_cost=1,
        risk_class="LOW",
        capability="extract",
        case_id="hyperion_demo_act1",
    )
    print(
        f"decision = {decision_1.reason_code.value} (allowed={decision_1.allowed}) | "
        f"risk = {assessment_1.risk_score}/100 {assessment_1.risk_level.value} "
        f"({assessment_1.threat_type})"
    )

    _banner("ACT 2 -- scope escalation: confidential terms, outside granted scope")
    decision_2, assessment_2 = evaluate_with_hyperion(
        sentinel,
        task="retrieve claim's confidential settlement terms",
        requested_scope=["claim.confidential_terms"],
        requested_cost=1,
        risk_class="HIGH",
        capability="extract",
        case_id="hyperion_demo_act2",
    )
    print(
        f"decision = {decision_2.reason_code.value} (allowed={decision_2.allowed}) | "
        f"risk = {assessment_2.risk_score}/100 {assessment_2.risk_level.value} "
        f"({assessment_2.threat_type})"
    )
    if decision_2.reason_code.value != "SCOPE_EXCEEDED":
        print("!! demo assumption violated: expected SCOPE_EXCEEDED on the out-of-scope request !!")
        sys.exit(1)
    print(">>> BLOCKED before any work happened. The Gateway's choke point, unchanged. <<<")

    _banner("FLEET SUMMARY -- real aggregate over both events above")
    summary = aggregate_fleet_summary()
    for key in (
        "agents_protected",
        "agents_observed",
        "events_total",
        "threats_detected",
        "blocked_actions",
        "fleet_health_pct",
        "risk_band_counts",
    ):
        print(f"{key}: {summary[key]}")


if __name__ == "__main__":
    main()
