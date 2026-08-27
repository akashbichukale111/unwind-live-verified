"""Capture ONE real, deterministic, zero-model mission trace for the Judge
Demo -- a credential-free "START JUDGE DEMO" entry point that must never send
an operator token from the frontend and must never touch a privileged
mutation endpoint anonymously.

WHY A CAPTURED TRACE, NOT A LIVE ANONYMOUS MISSION
--------------------------------------------------
`POST /api/command-os/mission` requires `require_human_principal` for a real
reason: an executed mission can reach a real (sandboxed) external write and
a real warrant mint, both of which need an accountable name in the
concurrence record. Making that endpoint anonymous -- even behind a second,
"demo-only" route -- would be exactly the privileged-mutation-made-anonymous
outcome this feature is explicitly forbidden from producing.

So the Judge Demo does not run a mission on click. It replays the ONE
mission this script runs, right now, offline, under a principal that reads
honestly as a demo identity (`human::judge-demo`) rather than impersonating
a real operator. The result is committed as evidence and served back by a
new, explicitly read-only, unauthenticated GET route
(`/api/judge-demo/mission`) -- no Firestore write, no warrant mint, no
external effect happens when a judge clicks the button; only when THIS
script runs, offline, deterministically, exactly once per capture.

TWO MISSIONS, ONE CAPTURED
---------------------------
Mission 1 seeds the knowledge store. Mission 2 -- the one actually served --
runs the SAME objective over the SAME committed evidence and recalls what
mission 1 measured, so the Judge Demo's "NEXT-MISSION ADAPTATION" node is
real, not empty. This is the exact mechanism
`tests/test_recall_mission.py::test_the_second_mission_plans_differently_because_of_the_first`
already proves; this script does not invent a new one.

Requires the Firestore emulator (`make emulator`). No model, no network
beyond Firestore, no cost.

    FIRESTORE_EMULATOR_HOST=localhost:8080 python scripts/capture_judge_demo.py
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

os.environ.setdefault("FIRESTORE_EMULATOR_HOST", "localhost:8080")
os.environ.setdefault("UNWIND_OTEL_CONSOLE", "0")
#: This script's ENTIRE purpose is a credential-free, zero-model, zero-cost
#: capture. `allow_model=False` on `run_mission()` only gates the FLEET
#: PLANNER (`fleet/planner.py`) -- it does not touch the separate Countersign
#: challenger, which `lib/simulation.py` deliberately does NOT default to
#: simulated (see that module's own docstring: a silent default is exactly
#: how simulated evidence becomes earned evidence). A capture script has no
#: such ambiguity to preserve, so it sets both explicitly, here, before
#: anything else imports either subsystem.
os.environ.setdefault("UNWIND_VERTEX_DISABLED", "1")
os.environ.setdefault("UNWIND_COUNTERSIGN_SIMULATED", "1")

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

OUT_DIR = REPO / "evidence" / "judge_demo"
OUT_PATH = OUT_DIR / "mission_trace.json"

#: Not a real credential and not a real operator. `lib/auth.py` never sees
#: this string -- it is passed directly as `run_mission(principal=...)`, the
#: same in-process parameter every command_os test uses, so the captured
#: report's `human_principal` field reads honestly as a demo identity.
DEMO_PRINCIPAL = "human::judge-demo"
OBJECTIVE = "Investigate an anomalous finance capability request."


def main() -> int:
    from command_os.mission import reset_for_test, run_mission
    from recall.store import reset_for_test as reset_recall

    reset_recall()
    reset_for_test()

    seed = run_mission(
        OBJECTIVE, principal=DEMO_PRINCIPAL, auth_method="judge_demo_capture", allow_model=False
    )
    print(f"seed mission: {seed.mission_id} -> {seed.status}")

    reset_for_test()  # fresh economy; the KNOWLEDGE store is deliberately not reset
    demo = run_mission(
        OBJECTIVE, principal=DEMO_PRINCIPAL, auth_method="judge_demo_capture", allow_model=False
    )
    print(f"captured mission: {demo.mission_id} -> {demo.status}")

    plan_detail = demo.stages[0].detail if demo.stages else {}
    recall = plan_detail.get("recall", {})
    reconcile_stage = next((s for s in demo.stages if s.name.startswith("RECONCILE")), None)
    reconciliation = (
        (reconcile_stage.detail or {}).get("reconciliation") if reconcile_stage else None
    )

    payload = {
        "captured_at": datetime.now(UTC).isoformat(),
        "captured_by": "scripts/capture_judge_demo.py",
        "note": (
            "A real, deterministic, zero-model mission trace, captured offline. "
            "The Judge Demo replays this exact JSON; it does not run a new mission, "
            "mint warrant, or touch Firestore when a judge clicks the button."
        ),
        "objective": OBJECTIVE,
        "seed_mission_id": seed.mission_id,
        "mission": demo.model_dump(mode="json"),
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")

    print(f"\nstages: {[s.name for s in demo.stages]}")
    print(
        f"recall: selected={len(recall.get('selected_records', []))} corpus={recall.get('corpus_records')}"
    )
    print(f"reconciliation: {reconciliation.get('verdict') if reconciliation else 'none'}")
    print(f"report.status: {demo.report.status if demo.report else None}")
    print(f"\nwritten: {OUT_PATH.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
