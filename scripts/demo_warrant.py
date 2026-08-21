"""Card 0's demo moment, staged end-to-end against a real Firestore emulator.

Two acts, both real calls into `warrant/ledger.py` and `tower/gateway.py` --
nothing here is printed without having actually happened:

  ACT 1 (~25s, one state change, no narration needed): a seeded veteran agent
  has HIGH-risk coverage. A human overturns one of its judgements -> BURN.
  The agent's HIGH-risk balance drops below the risk-class line. The VERY
  NEXT HIGH-risk case for that agent routes to a human: banner
  WARRANT_INSUFFICIENT. No cache -- see `warrant/ledger.py:spend_or_refuse`.

  ACT 2 (cold start, earning up live): a rookie agent starts at exactly zero
  warrant. A human concurrence and a (SIMULATED -- labelled, never claimed
  real) countersign are recorded on this run. MINT crosses the LOW-risk
  threshold. The agent's first-ever delegation is permitted, live, on this
  run -- not seeded.

Every balance this script prints is labelled SYNTHETIC or EARNED, matching
exactly what `tower.schema.WarrantSlot.provenance` would show on a real
dashboard -- this script does not invent a second labelling convention.

Usage:
    make emulator                     # one terminal
    python scripts/demo_warrant.py    # another (also see demo_warrant.sh)
"""

from __future__ import annotations

import os
import sys
import uuid
import warnings
from datetime import UTC, datetime, timedelta

#: Cosmetic only, scoped to this demo script: the emulator client's
#: positional-filter deprecation warning would otherwise interleave with
#: the narrated output a presenter is meant to read live.
warnings.filterwarnings("ignore", message="Detected filter using positional arguments")

os.environ.setdefault("UNWIND_OTEL_CONSOLE", "0")
os.environ.setdefault("FIRESTORE_EMULATOR_HOST", "localhost:8080")
#: The demo's cold-start act genuinely needs a countersign record to mint.
#: Real Gemma verification is a later prompt; this run's countersign is
#: SIMULATED and says so on every line it appears on.
os.environ.setdefault("UNWIND_COUNTERSIGN_SIMULATED", "1")

from lib.config import reset_config_cache  # noqa: E402
from tower.gateway import evaluate_gateway  # noqa: E402
from tower.registry import make_entry, put_agent  # noqa: E402
from warrant.ledger import (  # noqa: E402
    EventKind,
    burn,
    current_balance,
    mint,
    record_countersign,
    record_human_concurrence,
    write_synthetic_seed_event,
)
from warrant.ledger import reset_for_test as reset_ledger  # noqa: E402

reset_config_cache()

BAR = "=" * 78


def _banner(title: str) -> None:
    print()
    print(BAR)
    print(title)
    print(BAR)


def _seed_veteran_history(agent) -> None:
    """[SYNTHETIC] A fabricated eight-week history. Single-author demo
    corpus -- every event here is explicitly labelled SYNTHETIC, in the
    ledger and in this script's own output, never presented as earned.
    """
    now = datetime.now(UTC)
    week = timedelta(days=7)
    events = [
        (EventKind.MINT, "LOW", 500, now - 8 * week, "week 1: validated extraction, LOW"),
        (EventKind.MINT, "HIGH", 150, now - 7 * week, "week 2: validated extraction, HIGH"),
        (EventKind.SPEND, "LOW", 100, now - 6 * week, "week 3: routine LOW delegation"),
        (EventKind.MINT, "HIGH", 150, now - 5 * week, "week 4: validated extraction, HIGH"),
        (EventKind.MINT, "LOW", 500, now - 4 * week, "week 5: validated extraction, LOW"),
        (EventKind.MINT, "HIGH", 150, now - 3 * week, "week 6: validated extraction, HIGH"),
        (EventKind.SPEND, "HIGH", 120, now - 2 * week, "week 7: routine HIGH delegation"),
        (EventKind.SPEND, "LOW", 100, now - 1 * week, "week 8: routine LOW delegation"),
    ]
    for kind, risk_class, amount, at, reason in events:
        write_synthetic_seed_event(
            principal=agent.principal,
            capability="extract",
            risk_class=risk_class,
            kind=kind,
            amount_bp=amount,
            case_id=None,
            reason=reason,
            at=at,
        )


def act_one() -> None:
    _banner("ACT 1 -- BURN drops a risk-class bar below the routing line")

    veteran = make_entry(
        "extractor_veteran",
        capabilities=["extract"],
        max_budget=10_000,
        authority_scope=["claim.read"],
        risk_class_thresholds={"LOW": 5000, "HIGH": 1000},
        warrant_mint_schedule={"LOW": 500, "HIGH": 150},
        warrant_spend_schedule={"LOW": 100, "HIGH": 120},
    )
    reset_ledger(principal=veteran.principal)
    put_agent(veteran)
    _seed_veteran_history(veteran)

    balance_high = current_balance(veteran.principal, "extract", "HIGH")
    print(f"[SYNTHETIC seeded history] extractor_veteran HIGH-risk warrant: {balance_high}bp")

    case_1 = f"case_{uuid.uuid4().hex[:8]}"
    decision_1 = evaluate_gateway(
        veteran,
        task="review a HIGH-risk retraction",
        requested_scope=["claim.read"],
        requested_cost=1,
        risk_class="HIGH",
        capability="extract",
        case_id=case_1,
    )
    print(
        f"case {case_1}: gateway decision = {decision_1.reason_code.value} (allowed={decision_1.allowed})"
    )

    # Re-read live: the ALLOWED decision above already SPENT against this
    # balance, so the number immediately before the burn is not the one
    # printed before the gateway call -- no cache means no stale narration
    # either.
    balance_just_before_burn = current_balance(veteran.principal, "extract", "HIGH")
    print()
    print(">>> A human overturns this agent's judgement on that case. BURN. <<<")
    burn(
        agent=veteran,
        capability="extract",
        risk_class="HIGH",
        amount_bp=200,
        case_id=case_1,
        reason="human overturned the HIGH-risk judgement on this case",
        acting_principal=veteran.principal,
    )
    balance_after = current_balance(veteran.principal, "extract", "HIGH")
    print(
        f"[EARNED -- real BURN, this run] extractor_veteran HIGH-risk warrant: {balance_after}bp "
        f"(was {balance_just_before_burn}bp)"
    )

    case_2 = f"case_{uuid.uuid4().hex[:8]}"
    decision_2 = evaluate_gateway(
        veteran,
        task="review the NEXT HIGH-risk retraction",
        requested_scope=["claim.read"],
        requested_cost=1,
        risk_class="HIGH",
        capability="extract",
        case_id=case_2,
    )
    print(
        f"case {case_2}: gateway decision = {decision_2.reason_code.value} (allowed={decision_2.allowed})"
    )
    if decision_2.reason_code.value == "WARRANT_INSUFFICIENT":
        print(
            ">>> WARRANT_INSUFFICIENT -- routed to a human, no cache, visible on the very next call. <<<"
        )
    else:
        print("!! demo assumption violated: expected WARRANT_INSUFFICIENT on the very next call !!")


def act_two() -> None:
    _banner("ACT 2 -- cold start, earning up, live on this run")

    rookie = make_entry(
        "extractor_rookie",
        capabilities=["extract"],
        max_budget=10_000,
        authority_scope=["claim.read"],
        risk_class_thresholds={"LOW": 5000, "HIGH": 1000},
        warrant_mint_schedule={"LOW": 500, "HIGH": 150},
        warrant_spend_schedule={"LOW": 100, "HIGH": 120},
    )
    reset_ledger(principal=rookie.principal)
    put_agent(rookie)

    balance_before = current_balance(rookie.principal, "extract", "LOW")
    print(f"[cold start, no seeding at all] extractor_rookie LOW-risk warrant: {balance_before}bp")

    case = f"case_{uuid.uuid4().hex[:8]}"
    decision_before = evaluate_gateway(
        rookie,
        task="a first LOW-risk delegation attempt",
        requested_scope=["claim.read"],
        requested_cost=1,
        risk_class="LOW",
        capability="extract",
        case_id=case,
    )
    print(
        f"case {case}: gateway decision = {decision_before.reason_code.value} "
        f"(allowed={decision_before.allowed})"
    )

    print()
    print(">>> A human grants concurrence on camera. <<<")
    record_human_concurrence(
        case, principal="human::demo_operator", note="Approved on camera, live run."
    )

    simulated = os.environ.get("UNWIND_COUNTERSIGN_SIMULATED") == "1"
    label = "SIMULATED -- Gemma countersign is not wired up yet (Card 3)" if simulated else "REAL"
    print(f">>> Countersign recorded [{label}]. <<<")
    record_countersign(
        case, agrees=True, family="gemma-simulated", simulated=simulated, note="on-camera demo run"
    )

    event = mint(
        agent=rookie,
        capability="extract",
        risk_class="LOW",
        case_id=case,
        reason="first validated outcome",
    )
    balance_after = current_balance(rookie.principal, "extract", "LOW")
    print(
        f"[EARNED -- real MINT, this run] extractor_rookie LOW-risk warrant: {balance_after}bp "
        f"(+{event.amount_bp}bp)"
    )

    decision_after = evaluate_gateway(
        rookie,
        task="the SAME agent's first permitted LOW-risk delegation",
        requested_scope=["claim.read"],
        requested_cost=1,
        risk_class="LOW",
        capability="extract",
        case_id=case,
    )
    print(
        f"case {case}: gateway decision = {decision_after.reason_code.value} "
        f"(allowed={decision_after.allowed})"
    )
    if decision_after.allowed:
        print(">>> Threshold crossed live. First delegation permitted, on camera. <<<")
    else:
        print("!! demo assumption violated: expected ALLOWED after a validated mint !!")


def main() -> int:
    act_one()
    act_two()
    _banner("Next: python scripts/rederive_warrant.py -- proves nothing drifted.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
