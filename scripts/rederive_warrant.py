"""Rederive every registered agent's warrant balances from the live ledger
and diff them against Card 2's registry snapshot (`agents/{id}.warrant`).

Two passes, deliberately not the same call reused twice:

  1. MATERIALIZE -- any agent with no snapshot yet gets one taken now: read
     every event for each (capability, risk_class) key its registry entry is
     configured for, fold it, write the result into `warrant.balances` +
     `warrant.snapshot_as_of`.
  2. REDERIVE -- re-fetch each agent FRESH from Firestore (a new read, not
     the object step 1 already holds), re-read its ledger events FRESH, and
     re-fold at the snapshot's own `snapshot_as_of`. Compare int-for-int
     against what is stored. Any mismatch means the registry snapshot has
     drifted from the ledger it claims to summarize -- exactly the failure
     mode a UI reading the cached snapshot instead of the live fold would
     eventually hit.

This does not prove `fold_balance` is correct (the unit tests in
`tests/test_warrant_ledger.py` do that); it proves the STORED SNAPSHOT has
not drifted from the LOG, which is the specific guarantee `warrant/DESIGN.md`
promises for anything a dashboard shows instead of calling the gateway's
live path directly.

Usage:
    make emulator                      # one terminal
    python scripts/rederive_warrant.py # another

Exit codes: 0 all balances bit-equal; 1 at least one mismatch found.
"""

from __future__ import annotations

import os
import sys
import warnings
from datetime import UTC, datetime

warnings.filterwarnings("ignore", message="Detected filter using positional arguments")

os.environ.setdefault("UNWIND_OTEL_CONSOLE", "0")
os.environ.setdefault("FIRESTORE_EMULATOR_HOST", "localhost:8080")

from lib.config import reset_config_cache  # noqa: E402
from tower.registry import get_agent, list_agents, put_agent  # noqa: E402
from tower.schema import WarrantProvenance, WarrantSlot  # noqa: E402
from warrant.ledger import (  # noqa: E402
    Provenance,
    balance_key,
    fold_balance,
    parse_balance_key,
    provenance_for_fold,
    read_events,
)

reset_config_cache()


def _materialize(agent_id: str, *, as_of: datetime) -> None:
    agent = get_agent(agent_id)
    if agent is None:
        return
    risk_classes = (
        set(agent.risk_class_thresholds)
        | set(agent.warrant_mint_schedule)
        | set(agent.warrant_spend_schedule)
    )
    if not risk_classes or not agent.capabilities:
        return

    balances: dict[str, int] = {}
    any_synthetic = False
    any_events = False
    for capability in agent.capabilities:
        for risk_class in risk_classes:
            events = read_events(
                principal=agent.principal, capability=capability, risk_class=risk_class
            )
            key = balance_key(capability, risk_class)
            balances[key] = fold_balance(
                events,
                principal=agent.principal,
                capability=capability,
                risk_class=risk_class,
                as_of=as_of,
            )
            if events:
                any_events = True
            if provenance_for_fold(events) is Provenance.SYNTHETIC:
                any_synthetic = True

    provenance = (
        WarrantProvenance.SYNTHETIC
        if (any_synthetic or not any_events)
        else WarrantProvenance.EARNED
    )
    agent.warrant = WarrantSlot(balances=balances, provenance=provenance, snapshot_as_of=as_of)
    put_agent(agent)


def _rederive_and_compare(agent_id: str) -> list[dict]:
    agent = get_agent(agent_id)  # FRESH read, independent of _materialize's copy
    if agent is None or agent.warrant.snapshot_as_of is None:
        return []
    as_of = agent.warrant.snapshot_as_of
    rows = []
    for key, stored in agent.warrant.balances.items():
        capability, risk_class = parse_balance_key(key)
        events = read_events(
            principal=agent.principal, capability=capability, risk_class=risk_class
        )
        rederived = fold_balance(
            events,
            principal=agent.principal,
            capability=capability,
            risk_class=risk_class,
            as_of=as_of,
        )
        rows.append(
            {
                "agent_id": agent_id,
                "key": key,
                "stored_bp": stored,
                "rederived_bp": rederived,
                "provenance": agent.warrant.provenance.value,
                "n_events": len(events),
                "match": rederived == stored,
            }
        )
    return rows


def main() -> int:
    agents = list_agents()
    if not agents:
        print("no registered agents found -- nothing to rederive. Exit 0 (vacuously true).")
        return 0

    now = datetime.now(UTC)
    for agent in agents:
        if agent.warrant.snapshot_as_of is None:
            _materialize(agent.agent_id, as_of=now)

    all_rows: list[dict] = []
    for agent in agents:
        all_rows.extend(_rederive_and_compare(agent.agent_id))

    if not all_rows:
        print("no balance keys found across any registered agent. Exit 0 (vacuously true).")
        return 0

    print(
        f"{'agent_id':<24} {'key':<24} {'stored':>10} {'rederived':>10} {'prov':<10} {'events':>7}  match"
    )
    mismatches = 0
    for row in all_rows:
        status = "PASS" if row["match"] else "FAIL"
        if not row["match"]:
            mismatches += 1
        print(
            f"{row['agent_id']:<24} {row['key']:<24} {row['stored_bp']:>10} "
            f"{row['rederived_bp']:>10} {row['provenance']:<10} {row['n_events']:>7}  {status}"
        )

    print("-" * 100)
    if mismatches:
        print(f"RESULT: FAIL -- {mismatches}/{len(all_rows)} balance(s) do not bit-match the log.")
        return 1
    print(
        f"RESULT: PASS -- {len(all_rows)}/{len(all_rows)} balances bit-equal to a fresh fold of the log."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
