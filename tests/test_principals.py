"""Card 2's extension of `lib/principals.py`: agent identity + warrant non-transfer.

Task 3/4 needed owner/assessor/arbiter/re-deriver separation; Card 2 adds a
fifth role (AGENT) for the registry, and a second, distinct guarantee that is
not a principal-separation question at all: a warrant balance belongs to
exactly the principal it is keyed to, and reading or spending it as anyone
else is not merely disallowed, it raises `NonTransferableError` -- see
`lib/principals.py:assert_warrant_access`.
"""

from __future__ import annotations

import pytest

from lib.principals import (
    NonTransferableError,
    PrincipalSeparationError,
    Role,
    assert_agent_is_distinct,
    assert_warrant_access,
)

# ---------------------------------------------------------------------------
# (a) no agent principal equals an arbiter/owner/assessor/re-deriver principal
# ---------------------------------------------------------------------------


def test_agent_distinct_from_arbiter_raises() -> None:
    with pytest.raises(PrincipalSeparationError, match="agent.*arbiter|arbiter.*agent"):
        assert_agent_is_distinct("shared", arbiter="shared")


def test_agent_distinct_from_owner_raises() -> None:
    with pytest.raises(PrincipalSeparationError):
        assert_agent_is_distinct("shared", owners=["shared"])


def test_agent_distinct_from_assessor_raises() -> None:
    with pytest.raises(PrincipalSeparationError):
        assert_agent_is_distinct("shared", assessor="shared")


def test_agent_distinct_from_rederiver_raises() -> None:
    with pytest.raises(PrincipalSeparationError):
        assert_agent_is_distinct("shared", rederiver="shared")


def test_agent_with_no_overlap_is_fine() -> None:
    # Must not raise.
    assert_agent_is_distinct(
        "agent::worker_a",
        arbiter="human::lead",
        owners=["principal_x"],
        assessor="assessor::1",
        rederiver="rederiver::1",
    )


def test_two_different_agents_do_not_collide_with_each_other() -> None:
    """AGENT is not in the OWNER-style 'plural is fine' carve-out, but two
    SEPARATE calls for two separate agents naturally do not interact --
    there is no global state here to leak between them."""
    assert_agent_is_distinct("agent::a")
    assert_agent_is_distinct("agent::b")  # must not raise about "a"


def test_vacuity_the_guard_actually_fires_on_a_known_bad_fixture() -> None:
    """A guard nobody has seen fire is a guard nobody should trust (ruling 1.6,
    restated in Card 2 terms). Deliberately construct a violating bench and
    confirm the raise happens, not merely that a clean bench does not raise.
    """
    with pytest.raises(PrincipalSeparationError):
        assert_agent_is_distinct("dual_role", arbiter="dual_role", owners=["other"])


# ---------------------------------------------------------------------------
# (b) warrant balances are keyed by principal; any transfer attempt raises
# ---------------------------------------------------------------------------


def test_same_principal_access_is_fine() -> None:
    assert_warrant_access(balance_principal="agent::a", acting_principal="agent::a")  # no raise


def test_cross_principal_access_raises_non_transferable() -> None:
    with pytest.raises(NonTransferableError):
        assert_warrant_access(balance_principal="agent::a", acting_principal="agent::b")


def test_non_transferable_error_is_distinct_from_principal_separation_error() -> None:
    """These guard two different things (identity collision vs. balance
    ownership) and a caller catching one must not silently swallow the other."""
    assert not issubclass(NonTransferableError, PrincipalSeparationError)
    assert not issubclass(PrincipalSeparationError, NonTransferableError)


def test_vacuity_warrant_guard_fires_on_a_known_bad_fixture() -> None:
    with pytest.raises(
        NonTransferableError, match="agent::victim.*agent::attacker|agent::attacker.*agent::victim"
    ):
        assert_warrant_access(balance_principal="agent::victim", acting_principal="agent::attacker")


# ---------------------------------------------------------------------------
# Role enum sanity -- AGENT must actually be a distinct role, not an alias.
# ---------------------------------------------------------------------------


def test_agent_role_is_distinct_value() -> None:
    assert Role.AGENT.value == "agent"
    assert Role.AGENT not in (Role.OWNER, Role.ARBITER, Role.ASSESSOR, Role.REDERIVER)
