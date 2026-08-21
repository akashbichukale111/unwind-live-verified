"""Card 2: the executable agent registry, and the centerpiece test.

Skipped unless a Firestore emulator is answering:

    make emulator     # one terminal
    make test         # another

THE CENTERPIECE TEST
----------------------
`test_flipping_a_registry_field_changes_the_composed_graph` is the test the
prompt asked for by name: flip ONE registry field (drop a capability, or set
`status: suspended`) and assert the dynamic-pattern composition routes
differently. It asserts on the REAL `google.adk.workflow.Workflow` object
`compose_capability_workflow` returns -- reading node names back out of its
own `.edges` -- not on a bookkeeping function that merely claims to agree
with it. Registry -> orchestration is provable this way; a docstring alone
would only be asserted.
"""

from __future__ import annotations

import os
import socket
from pathlib import Path

import pytest
from google.adk.workflow import START

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
    os.environ["UNWIND_PROJECT_ID"] = "unwind-tower-registry-test"
    from lib import firestore as fs
    from lib.config import reset_config_cache

    reset_config_cache()
    fs.reset_client()
    yield
    fs.reset_client()
    reset_config_cache()


def _graph_node_names(workflow) -> set[str]:
    names: set[str] = set()
    for edge in workflow.edges:
        for node in (edge.from_node, edge.to_node):
            if node is not START and hasattr(node, "name"):
                names.add(node.name)
    return names


def test_registration_binds_a_distinct_principal() -> None:
    from tower.registry import make_entry, put_agent, reset_for_test

    reset_for_test()
    entry = make_entry("worker_reg_1", capabilities=["extract"])
    put_agent(entry)
    assert entry.principal == "agent::worker_reg_1"


def test_registration_time_check_is_necessary_but_not_sufficient() -> None:
    """`put_agent` alone has nothing to collide with -- registering one agent
    in isolation can never violate ruling 1.10, because a bench of one role
    has no pair to compare. That is not a gap: requirement (a) ("no agent
    principal equals an arbiter/owner/assessor/re-deriver principal") is
    enforced where the OTHER principals are actually known, at Gateway
    dispatch time -- see `tests/test_tower_gateway.py::
    test_principal_violation_when_agent_shares_principal_with_arbiter` for
    the real collision case, and `tests/test_principals.py` for the guard
    itself. This test only confirms registration-time still succeeds for the
    ordinary case, so the two test files are not silently testing the same
    thing twice.
    """
    from tower.registry import get_agent, make_entry, put_agent, reset_for_test

    reset_for_test()
    put_agent(make_entry("worker_solo", capabilities=["extract"]))
    assert get_agent("worker_solo") is not None


def test_list_eligible_agents_filters_status_and_capability() -> None:
    from tower.registry import list_eligible_agents, make_entry, put_agent, reset_for_test
    from tower.schema import RegistryStatus

    reset_for_test()
    put_agent(make_entry("w_active_match", capabilities=["extract"]))
    put_agent(make_entry("w_active_other_cap", capabilities=["draft"]))
    put_agent(make_entry("w_suspended", capabilities=["extract"], status=RegistryStatus.SUSPENDED))

    eligible = {a.agent_id for a in list_eligible_agents("extract")}
    assert eligible == {"w_active_match"}


def test_flipping_a_registry_field_changes_the_composed_graph() -> None:
    """THE centerpiece test. Two flips, two real graph diffs."""
    from tower.registry import compose_capability_workflow, make_entry, put_agent, reset_for_test
    from tower.schema import RegistryStatus

    reset_for_test()
    put_agent(make_entry("w_alpha", capabilities=["extract"]))
    put_agent(make_entry("w_beta", capabilities=["extract"]))

    before = _graph_node_names(compose_capability_workflow("extract"))
    assert before == {"w_alpha", "w_beta", "extract_join"}

    # Flip 1: suspend one agent.
    put_agent(make_entry("w_beta", capabilities=["extract"], status=RegistryStatus.SUSPENDED))
    after_suspend = _graph_node_names(compose_capability_workflow("extract"))
    assert after_suspend == {"w_alpha", "extract_join"}
    assert after_suspend != before

    # Flip 2: drop the capability instead (re-activate w_beta first).
    put_agent(make_entry("w_beta", capabilities=["draft"]))  # active again, different capability
    after_drop = _graph_node_names(compose_capability_workflow("extract"))
    assert after_drop == {"w_alpha", "extract_join"}

    # And composing for the NEW capability picks w_beta up.
    draft_graph = _graph_node_names(compose_capability_workflow("draft"))
    assert draft_graph == {"w_beta", "draft_join"}


def test_composing_with_no_eligible_agents_is_a_valid_empty_graph() -> None:
    from tower.registry import compose_capability_workflow, reset_for_test

    reset_for_test()
    wf = compose_capability_workflow("nonexistent_capability")
    names = _graph_node_names(wf)
    assert names == {"nonexistent_capability_join"}
