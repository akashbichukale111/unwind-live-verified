"""Card 2: Decision Memory -- the append-only causal chain, not a vector store.

Skipped unless a Firestore emulator is answering:

    make emulator     # one terminal
    make test         # another

Two things this file proves that a single in-process test cannot:

1. "What happened because of decision X?" is a real graph walk over
   `parent_id`, tested with a chain that branches (one decision causing two
   independent downstream entries) so a naive "just read the next `seq`"
   implementation would fail it.
2. The chain survives a genuine process restart -- a SEPARATE Python
   interpreter, not just a new in-process object -- because durability
   claimed but only tested against a live object it was written from is not
   durability, it is a cache hit.
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
    os.environ["UNWIND_PROJECT_ID"] = "unwind-tower-memory-test"
    from lib import firestore as fs
    from lib.config import reset_config_cache

    reset_config_cache()
    fs.reset_client()
    yield
    fs.reset_client()
    reset_config_cache()


def test_chain_is_append_only_and_ordered() -> None:
    from tower.memory import get_case_chain, reset_for_test, write_entry
    from tower.schema import MemoryEntryKind

    case_id = f"case_{uuid.uuid4().hex[:8]}"
    reset_for_test(case_id)
    e1 = write_entry(case_id, MemoryEntryKind.CASE, {"note": "opened"})
    e2 = write_entry(case_id, MemoryEntryKind.PREMISE, {"claim": "x"}, parent_id=e1.entry_id)
    write_entry(case_id, MemoryEntryKind.DECISION, {"d": "material"}, parent_id=e2.entry_id)

    chain = get_case_chain(case_id)
    assert [c.seq for c in chain] == [0, 1, 2]
    assert chain[0].parent_id is None
    assert chain[1].parent_id == e1.entry_id


def test_what_happened_because_of_walks_a_branching_chain() -> None:
    """One decision (e_decision) causes TWO independent downstream entries
    (a human decision and an agent action), and both, transitively, cause
    outcomes. A naive next-seq walk would miss the branch."""
    from tower.memory import reset_for_test, what_happened_because_of, write_entry
    from tower.schema import MemoryEntryKind

    case_id = f"case_{uuid.uuid4().hex[:8]}"
    reset_for_test(case_id)
    e_case = write_entry(case_id, MemoryEntryKind.CASE, {})
    e_decision = write_entry(
        case_id, MemoryEntryKind.DECISION, {"d": "material"}, parent_id=e_case.entry_id
    )
    e_human = write_entry(
        case_id, MemoryEntryKind.HUMAN_DECISION, {"h": "approved"}, parent_id=e_decision.entry_id
    )
    e_agent = write_entry(
        case_id, MemoryEntryKind.AGENT_ACTION, {"a": "drafted"}, parent_id=e_decision.entry_id
    )
    e_outcome_1 = write_entry(
        case_id, MemoryEntryKind.OUTCOME, {"o": "signed"}, parent_id=e_human.entry_id
    )
    e_outcome_2 = write_entry(
        case_id, MemoryEntryKind.OUTCOME, {"o": "sent"}, parent_id=e_agent.entry_id
    )
    # An entry NOT caused by e_decision must not appear.
    write_entry(
        case_id, MemoryEntryKind.CONSEQUENCE, {"unrelated": True}, parent_id=e_case.entry_id
    )

    downstream = what_happened_because_of(e_decision.entry_id)
    downstream_ids = {d.entry_id for d in downstream}
    assert downstream_ids == {
        e_human.entry_id,
        e_agent.entry_id,
        e_outcome_1.entry_id,
        e_outcome_2.entry_id,
    }


def test_what_happened_because_of_a_leaf_is_empty() -> None:
    from tower.memory import reset_for_test, what_happened_because_of, write_entry
    from tower.schema import MemoryEntryKind

    case_id = f"case_{uuid.uuid4().hex[:8]}"
    reset_for_test(case_id)
    leaf = write_entry(case_id, MemoryEntryKind.OUTCOME, {})
    assert what_happened_because_of(leaf.entry_id) == []


def test_chain_survives_a_new_client_instance() -> None:
    """Same idiom as `tests/test_cascade_firestore.py`'s idempotency test: a
    fresh Firestore client, same durable state."""
    from lib import firestore as fs
    from tower.memory import get_case_chain, reset_for_test, write_entry
    from tower.schema import MemoryEntryKind

    case_id = f"case_{uuid.uuid4().hex[:8]}"
    reset_for_test(case_id)
    write_entry(case_id, MemoryEntryKind.CASE, {})

    fs.reset_client()  # drop the process-wide client; the next call rebuilds it
    chain = get_case_chain(case_id)
    assert len(chain) == 1


def test_chain_survives_a_genuine_process_restart() -> None:
    """Not a new object -- a new Python interpreter. Writer and reader never
    share a single byte of process memory."""
    case_id = f"case_{uuid.uuid4().hex[:8]}"
    env = {
        **os.environ,
        "FIRESTORE_EMULATOR_HOST": os.environ.get("FIRESTORE_EMULATOR_HOST", "localhost:8080"),
        "UNWIND_PROJECT_ID": "unwind-tower-memory-test",
        "UNWIND_OTEL_CONSOLE": "0",
    }

    writer = f"""
import sys
sys.path.insert(0, {str(REPO)!r})
from tower.memory import write_entry
from tower.schema import MemoryEntryKind
e1 = write_entry({case_id!r}, MemoryEntryKind.CASE, {{}})
e2 = write_entry({case_id!r}, MemoryEntryKind.PREMISE, {{"claim": "x"}}, parent_id=e1.entry_id)
print(e1.entry_id)
"""
    result = subprocess.run(
        [sys.executable, "-c", writer],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    root_id = result.stdout.strip().splitlines()[-1]

    reader = f"""
import json, sys
sys.path.insert(0, {str(REPO)!r})
from tower.memory import get_case_chain, what_happened_because_of
chain = get_case_chain({case_id!r})
downstream = what_happened_because_of({root_id!r})
print(json.dumps({{"chain_len": len(chain), "downstream_len": len(downstream)}}))
"""
    result2 = subprocess.run(
        [sys.executable, "-c", reader],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result2.returncode == 0, result2.stderr
    out = json.loads(result2.stdout.strip().splitlines()[-1])
    assert out["chain_len"] == 2
    assert out["downstream_len"] == 1
