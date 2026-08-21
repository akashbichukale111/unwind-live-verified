"""Card 2: the long-running durable runtime.

Skipped unless a Firestore emulator is answering:

    make emulator     # one terminal
    make test         # another

`test_case_resumes_after_a_simulated_one_week_gap_and_a_process_restart` is
the test the prompt asked for by name: pause, then resume after a frozen
clock says a week has passed, in a SEPARATE process from the one that opened
and paused the case -- so "durable" cannot be quietly satisfied by anything
still sitting in memory.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _emulator_up() -> bool:
    host = os.environ.get("FIRESTORE_EMULATOR_HOST", "localhost:8080")
    hostname, _, port = host.partition(":")
    try:
        with socket.create_connection((hostname, int(port or 8080)), timeout=1.0):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not _emulator_up(), reason="Firestore emulator not running; start it with `make emulator`"
)


@pytest.fixture(scope="module", autouse=True)
def _emulator_project():
    os.environ.setdefault("FIRESTORE_EMULATOR_HOST", "localhost:8080")
    os.environ["UNWIND_PROJECT_ID"] = "unwind-tower-runtime-test"
    from lib import firestore as fs
    from lib.config import reset_config_cache

    reset_config_cache()
    fs.reset_client()
    yield
    fs.reset_client()
    reset_config_cache()


def test_case_status_machine_rejects_an_invalid_transition() -> None:
    from tower.runtime import InvalidCaseTransitionError, close_case, open_case, reset_for_test

    case_id = f"case_{uuid.uuid4().hex[:8]}"
    reset_for_test(case_id)
    open_case(case_id, first_step="intake")
    close_case(case_id)
    with pytest.raises(InvalidCaseTransitionError):
        close_case(case_id)  # closed -> closed is not a valid edge


def test_pause_then_resume_preserves_step_and_state() -> None:
    from tower.runtime import (
        advance_step,
        get_case,
        open_case,
        pause_case,
        reset_for_test,
        resume_case,
    )
    from tower.schema import CaseStatus

    case_id = f"case_{uuid.uuid4().hex[:8]}"
    reset_for_test(case_id)
    open_case(case_id, first_step="intake", step_state={"n": 0})
    advance_step(case_id, step="triage", step_state={"n": 1})
    pause_case(case_id)
    assert get_case(case_id).status is CaseStatus.PAUSED

    resumed = resume_case(case_id)
    assert resumed.status is CaseStatus.RESUMED
    assert resumed.current_step == "triage"
    assert resumed.step_state == {"n": 1}


def test_pause_case_for_human_returns_immediately_pending() -> None:
    """The long-running tool's wrapped function never blocks -- it records
    AWAITING_HUMAN and returns, the same shape LongRunningFunctionTool
    expects: an immediate result, with the real answer arriving later."""
    from tower.runtime import get_case, open_case, pause_case_for_human, reset_for_test
    from tower.schema import CaseStatus

    case_id = f"case_{uuid.uuid4().hex[:8]}"
    reset_for_test(case_id)
    open_case(case_id, first_step="review")
    result = pause_case_for_human(case_id, "needs signature")
    assert result["status"] == "pending"
    assert get_case(case_id).status is CaseStatus.AWAITING_HUMAN


def test_pause_tool_is_a_real_long_running_tool() -> None:
    from google.adk.tools.long_running_tool import LongRunningFunctionTool

    from tower.runtime import case_pause_tool

    assert isinstance(case_pause_tool, LongRunningFunctionTool)
    assert case_pause_tool.is_long_running is True


def test_case_resumes_after_a_simulated_one_week_gap_and_a_process_restart() -> None:
    """Three processes: one opens+advances+pauses, a second (a week later, by
    the clock the code is given, not by wall time) resumes, a third reads
    back the final record. None share process memory with any other.
    """
    case_id = f"case_{uuid.uuid4().hex[:8]}"
    env = {
        **os.environ,
        "FIRESTORE_EMULATOR_HOST": os.environ.get("FIRESTORE_EMULATOR_HOST", "localhost:8080"),
        "UNWIND_PROJECT_ID": "unwind-tower-runtime-test",
        "UNWIND_OTEL_CONSOLE": "0",
    }

    opener = f"""
import sys
sys.path.insert(0, {str(REPO)!r})
from datetime import datetime, UTC
from tower.runtime import open_case, advance_step, pause_case
t0 = datetime(2026, 8, 15, 9, 0, tzinfo=UTC)
open_case({case_id!r}, first_step="intake", step_state={{"claim": "supplier_K"}}, now=t0)
advance_step({case_id!r}, step="awaiting_correction_draft", step_state={{"claim": "supplier_K", "drafted": True}}, now=t0)
pause_case({case_id!r}, now=t0)
print(t0.isoformat())
"""
    r1 = subprocess.run(
        [sys.executable, "-c", opener],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r1.returncode == 0, r1.stderr
    t0_iso = r1.stdout.strip().splitlines()[-1]

    resumer = f"""
import sys
sys.path.insert(0, {str(REPO)!r})
from datetime import datetime, timedelta, UTC
from tower.runtime import resume_case
t0 = datetime.fromisoformat({t0_iso!r})
one_week_later = t0 + timedelta(days=7)
resumed = resume_case({case_id!r}, now=one_week_later)
print(resumed.current_step)
"""
    r2 = subprocess.run(
        [sys.executable, "-c", resumer],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r2.returncode == 0, r2.stderr
    assert r2.stdout.strip().splitlines()[-1] == "awaiting_correction_draft"

    reader = f"""
import json, sys
sys.path.insert(0, {str(REPO)!r})
from tower.runtime import get_case
c = get_case({case_id!r})
print(json.dumps({{
    "status": c.status.value,
    "step": c.current_step,
    "state": c.step_state,
    "gap_days": (c.resumed_at - c.paused_at).days,
}}))
"""
    r3 = subprocess.run(
        [sys.executable, "-c", reader],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r3.returncode == 0, r3.stderr
    out = json.loads(r3.stdout.strip().splitlines()[-1])
    assert out["status"] == "resumed"
    assert out["step"] == "awaiting_correction_draft"
    assert out["state"] == {"claim": "supplier_K", "drafted": True}
    assert out["gap_days"] == 7
