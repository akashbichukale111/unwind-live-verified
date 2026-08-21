"""Run Countersign over the existing eval scenarios and publish the measured
agreement rate verbatim -- the house rule (README "The honesty map"): a
number is either produced by a committed script or labelled as not measured.

Attempts a REAL Gemma call for the first scenario as a live-reachability
probe; if Vertex is unreachable (as it is in this repository's own dev
environment -- no billing project has Gemma model access, see
`countersign/DESIGN.md`), the run falls through to the SAME scripted
simulator `tests/test_countersign_verify.py` exercises
(`UNWIND_COUNTERSIGN_SIMULATED=1`), and every line of output says so. This
is not a fallback that hides the gap -- it is the gap, reported.

Usage:
    python scripts/run_countersign_eval.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("UNWIND_OTEL_CONSOLE", "0")

REPO = Path(__file__).resolve().parents[1]
SCENARIOS_DIR = REPO / "evals" / "scenarios"
OUT = REPO / "evidence" / "countersign"

sys.path.insert(0, str(REPO))

#: The judging side for every scenario in this run: the arbiter that would
#: rule on a repair court proceeding over these cascades. Real principal
#: constant, not invented for this script.
from court.arbiter import ARBITER_PRINCIPAL  # noqa: E402
from lib.config import get_config  # noqa: E402
from warrant.ledger import family_root  # noqa: E402


def _discover() -> list[tuple[str, dict]]:
    found = []
    for path in sorted(SCENARIOS_DIR.glob("*/*/scenario.json")):
        scenario = json.loads(path.read_text(encoding="utf-8"))
        found.append((str(path.relative_to(REPO)), scenario))
    return found


def _material(scenario: dict) -> dict:
    expect = scenario.get("expect", {})
    retraction = scenario.get("retraction", {})
    return {
        "class": scenario.get("class", "unknown"),
        "description": scenario.get("description", ""),
        "claim_id": retraction.get("claim_id", ""),
        "new_value": retraction.get("new_value", ""),
        "judged_outcome": expect.get("outcome", ""),
        "judged_reason_code": expect.get("authority_reason_code", ""),
        "judged_radius_size": expect.get("radius_size", ""),
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    scenarios = _discover()
    if not scenarios:
        print("no eval scenarios found -- nothing to run.")
        return 1

    cfg = get_config()

    # ---- probe: is a real Gemma call reachable at all, right now? --------
    live_reachable = False
    live_error = None
    if not cfg.vertex_disabled and not os.environ.get("UNWIND_COUNTERSIGN_SIMULATED"):
        import countersign.verify as cv

        name, first = scenarios[0]
        try:
            probe = cv.run_countersign(
                f"probe::{name}",
                _material(first),
                judging_family=cfg.gemini_model,
                judging_principal=ARBITER_PRINCIPAL,
            )
            live_reachable = probe.available
            if not live_reachable:
                live_error = probe.reason_unavailable
        except Exception as exc:  # noqa: BLE001
            live_error = f"{type(exc).__name__}: {exc}"

    simulated_run = not live_reachable
    if simulated_run:
        os.environ["UNWIND_COUNTERSIGN_SIMULATED"] = "1"

    import importlib

    import countersign.verify as cv

    importlib.reload(cv)  # pick up the env flag if we just set it

    rows = []
    for name, scenario in scenarios:
        outcome = cv.run_countersign(
            name,
            _material(scenario),
            judging_family=cfg.gemini_model,
            judging_principal=ARBITER_PRINCIPAL,
        )
        rows.append(
            {
                "scenario": name,
                "class": scenario.get("class", "unknown"),
                "available": outcome.available,
                "agrees": outcome.agrees,
                # Family root only -- see the summary dict below for why a
                # raw version string never lands in this file.
                "family_root": family_root(outcome.family),
                "simulated": outcome.simulated,
                "ground": outcome.ground,
                "reason_unavailable": outcome.reason_unavailable,
            }
        )

    decided = [r for r in rows if r["available"]]
    agreed = [r for r in decided if r["agrees"]]
    disagreed = [r for r in decided if not r["agrees"]]
    unavailable = [r for r in rows if not r["available"]]

    agreement_rate = (len(agreed) / len(decided)) if decided else None

    summary = {
        "scenarios_total": len(rows),
        "decided": len(decided),
        "agreed": len(agreed),
        "disagreed": len(disagreed),
        "unavailable": len(unavailable),
        "agreement_rate": agreement_rate,
        "simulated_run": simulated_run,
        "live_reachability_probe": {
            "attempted": not (
                cfg.vertex_disabled
                or os.environ.get("UNWIND_COUNTERSIGN_SIMULATED") == "1"
                and not simulated_run
            ),
            "reachable": live_reachable,
            "error": live_error,
        },
        # Family roots only, not the raw version strings -- lib/config.py is
        # the one place a literal Gemini/Gemma model string may appear in
        # non-prose text (tests/test_config_singleton.py,
        # tests/test_countersign_boundary.py enforce this); the exact
        # strings are documented in README.md / countersign/DESIGN.md prose,
        # which is exempt.
        "gemma_family": family_root(cfg.gemma_model),
        "gemini_family_as_judging_side": family_root(cfg.gemini_model),
        "rows": rows,
    }

    (OUT / "results.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    label = "SIMULATED (scripted, no model call)" if simulated_run else "LIVE (real Gemma call)"
    print(f"Countersign eval run: {len(rows)} scenarios, mode = {label}")
    if live_error:
        print(f"  live-reachability probe failed: {live_error}")
    print(f"  decided:      {len(decided)}")
    print(f"  agreed:       {len(agreed)}")
    print(f"  disagreed:    {len(disagreed)}")
    print(f"  unavailable:  {len(unavailable)}")
    if agreement_rate is not None:
        print(f"  AGREEMENT RATE: {agreement_rate * 100:.1f}%  ({len(agreed)}/{len(decided)})")
    else:
        print("  AGREEMENT RATE: not measured (nothing decided)")
    print(f"  written: {OUT / 'results.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
