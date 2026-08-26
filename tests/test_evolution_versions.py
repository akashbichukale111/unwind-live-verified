"""Agent versions: content addressing, immutability, and the authority line.

The property under test throughout is the one that makes a self-modifying
agent safe to run at all: **the evolution loop can change what an agent is
TOLD, and can never change what an agent is ALLOWED.**
"""

from __future__ import annotations

import pytest

from evolution.schema import VersionStatus
from evolution.versions import (
    FORBIDDEN_POLICY_KEYS,
    SEED_POLICY,
    AuthorityEscalation,
    assert_no_authority_keys,
    build_version,
    compute_version_id,
    diff_versions,
    seed_versions,
)


@pytest.fixture
def seed():
    return next(v for v in seed_versions() if v.agent_key == "orchestrator")


# ---------------------------------------------------------------------------
# The seed is production, not a fixture
# ---------------------------------------------------------------------------


def test_the_seed_is_the_instruction_that_is_actually_serving():
    """If the seed were invented here, the whole loop would be a simulation of
    itself. Version 1 must be byte-identical to `fleet/roles.py`."""
    from fleet.roles import ALL_ROLES

    by_key = {r.key: r for r in ALL_ROLES if (r.instruction or "").strip()}
    seeded = {v.agent_key: v for v in seed_versions()}
    assert set(seeded) == set(by_key)
    for key, version in seeded.items():
        assert version.instruction == by_key[key].instruction.strip()


def test_every_seed_is_active_and_version_one():
    for version in seed_versions():
        assert version.status is VersionStatus.ACTIVE
        assert version.version_n == 1
        assert version.parent_version_id is None
        assert version.provenance == "SEED"


def test_a_role_with_no_instruction_is_skipped_not_invented():
    """Honest omission beats invented prose."""
    keys = {v.agent_key for v in seed_versions()}
    from fleet.roles import ALL_ROLES

    for role in ALL_ROLES:
        if not (role.instruction or "").strip():
            assert role.key not in keys


# ---------------------------------------------------------------------------
# Content addressing
# ---------------------------------------------------------------------------


def test_identical_text_is_identically_addressed(seed):
    twin = build_version(
        agent_key=seed.agent_key,
        instruction=seed.instruction,
        policy=dict(seed.policy),
        version_n=99,  # not part of the address
    )
    assert twin.version_id == seed.version_id


def test_any_text_change_changes_the_address(seed):
    changed = build_version(
        agent_key=seed.agent_key,
        instruction=seed.instruction + " ",
        policy=dict(seed.policy),
        version_n=2,
    )
    assert changed.version_id != seed.version_id


def test_any_policy_change_changes_the_address(seed):
    changed = build_version(
        agent_key=seed.agent_key,
        instruction=seed.instruction,
        policy={**seed.policy, "max_plan_steps": 4},
        version_n=2,
    )
    assert changed.version_id != seed.version_id


def test_the_address_is_stable_across_key_ordering(seed):
    """A dict that round-trips through JSON storage may come back reordered.
    If ordering changed the address, every stored evaluation would stop
    matching its version after one read."""
    reordered = dict(reversed(list(seed.policy.items())))
    assert compute_version_id(seed.agent_key, seed.instruction, reordered) == seed.version_id


# ---------------------------------------------------------------------------
# The authority line
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("key", sorted(FORBIDDEN_POLICY_KEYS))
def test_version_cannot_carry_authority_keys(seed, key):
    with pytest.raises(AuthorityEscalation):
        build_version(
            agent_key=seed.agent_key,
            instruction=seed.instruction,
            policy={**seed.policy, key: ["anything"]},
            version_n=2,
        )


def test_authority_keys_are_refused_at_any_nesting_depth():
    with pytest.raises(AuthorityEscalation):
        assert_no_authority_keys({"a": {"b": [{"tools": ["shell"]}]}})


def test_the_forbidden_set_covers_every_authority_field_on_a_fleet_role():
    """A new authority field added to `FleetRole` must not silently become
    something an agent version may set."""
    from fleet.roles import ORCHESTRATOR

    authority_fields = {
        "authority_scope",
        "data_scope",
        "tools",
        "permitted_actions",
        "risk_class_thresholds",
        "warrant_mint_schedule",
        "warrant_spend_schedule",
        "max_budget",
        "agent_id",
    }
    assert authority_fields <= FORBIDDEN_POLICY_KEYS
    for field in authority_fields:
        assert hasattr(ORCHESTRATOR, field), f"{field} is no longer a FleetRole field"


def test_an_empty_instruction_is_not_a_version(seed):
    with pytest.raises(ValueError):
        build_version(agent_key=seed.agent_key, instruction="   ", policy={}, version_n=2)


# ---------------------------------------------------------------------------
# Diffing, for the human who has to approve
# ---------------------------------------------------------------------------


def test_diff_names_what_changed_field_by_field(seed):
    candidate = build_version(
        agent_key=seed.agent_key,
        instruction=seed.instruction + "\n\nA new rule, still authorized downstream.",
        policy={**seed.policy, "max_plan_steps": 5},
        version_n=2,
        parent_version_id=seed.version_id,
    )
    changes = {c["field"]: c for c in diff_versions(seed, candidate)}
    assert "policy.max_plan_steps" in changes
    assert changes["policy.max_plan_steps"]["before"] == SEED_POLICY["max_plan_steps"]
    assert changes["policy.max_plan_steps"]["after"] == 5
    assert "A new rule, still authorized downstream." in changes["instruction"]["lines_added"]


def test_an_unchanged_version_diffs_to_nothing(seed):
    assert diff_versions(seed, seed) == []
