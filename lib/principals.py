"""Who is allowed to be whom, enforced across a whole bench rather than a pair.

Task 3 needed one separation: the assessor must not grade a re-derivation it
produced. Task 4's court needs the general form, because ruling 1.10 is
non-negotiable and the failure it prevents is the one that would hollow out the
entire project:

    IF THE ARBITER SHARES A PRINCIPAL WITH AN OWNER, AN ASSESSOR OR A
    RE-DERIVER, THIS IS NOT A MULTI-AGENT SYSTEM. It is one model talking to
    itself in different voices, and the separation of arguing party from
    deciding party -- the reason courts are not run by the defendant -- is
    decoration.

So separation is checked over a SET of role assignments, not a pair, and a
collision anywhere in the bench raises. The check is total, it is cheap, and
`tests/test_court.py` includes a vacuity case for every role pair that matters:
a guard nobody has ever seen fire is a guard nobody should trust (Task 3,
ruling 1.6).

This module deliberately imports nothing from `judgment/`, `court/` or
`spine/`. It is the shared vocabulary those three agree on, so putting it in
any of them would make the other two import a peer.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from enum import Enum


class PrincipalSeparationError(RuntimeError):
    """Two roles that must be held by different principals are held by one.

    Canonical for the whole repository. `judgment.assessor` re-exports it so a
    caller catching the assessor's error also catches the court's -- two
    exception types for one concept is how a handler silently misses half the
    cases.
    """


class NonTransferableError(RuntimeError):
    """A warrant balance was accessed by a principal it is not keyed to.

    Card 2 (Control Tower) registers the slot this guards; Card 0 (WARRANT)
    fills in the mint/burn/decay arithmetic in a later prompt. The guard
    exists now because "balances are per principal and cannot move" is a
    property of WHO may touch a balance, not of the numbers inside it -- so it
    is enforceable before a single unit of warrant has ever been minted.
    """


class Role(str, Enum):
    """The roles whose separation is load-bearing.

    OWNER is plural: a repair has N of them, discovered at runtime. AGENT is
    Card 2's addition: every registry entry (tower/registry.py) binds to a
    principal, and that principal must never collide with a court or
    judgment role -- an agent that is also the arbiter it answers to is the
    same hollowing-out ruling 1.10 already forbids, one layer up.
    """

    REDERIVER = "rederiver"
    ASSESSOR = "assessor"
    ARBITER = "arbiter"
    OWNER = "owner"
    AGENT = "agent"


#: Pairs that must never collapse into one principal, with the reason each
#: exists. Stated as data so the error message can explain WHY rather than just
#: reporting that two strings matched.
_WHY: dict[frozenset[Role], str] = {
    frozenset({Role.ARBITER, Role.OWNER}): (
        "an owner ruling on its own commitment is the defendant judging the case"
    ),
    frozenset({Role.ARBITER, Role.ASSESSOR}): (
        "the arbiter would be ratifying the materiality call it is meant to weigh"
    ),
    frozenset({Role.ARBITER, Role.REDERIVER}): (
        "the arbiter would be ruling on an alternative it authored itself"
    ),
    frozenset({Role.ASSESSOR, Role.REDERIVER}): (
        "grading your own re-derivation makes 'nothing changed' the cheapest "
        "self-consistent answer, and that answer is invisible when wrong"
    ),
    frozenset({Role.ASSESSOR, Role.OWNER}): (
        "an owner grading its own commitment's materiality has an interest in finding it immaterial"
    ),
    frozenset({Role.REDERIVER, Role.OWNER}): (
        "an owner re-deriving its own commitment will re-derive the answer it already holds"
    ),
    frozenset({Role.AGENT, Role.ARBITER}): (
        "a delegated worker that is also the arbiter grades its own dispatch, "
        "which is ruling 1.10's failure one layer up the stack"
    ),
    frozenset({Role.AGENT, Role.OWNER}): (
        "a delegated worker acting as the commitment owner it was dispatched to "
        "serve has an interest in its own task succeeding"
    ),
    frozenset({Role.AGENT, Role.ASSESSOR}): (
        "a delegated worker grading its own output is the same self-consistency "
        "failure as an assessor re-deriving its own commitment"
    ),
    frozenset({Role.AGENT, Role.REDERIVER}): (
        "a delegated worker that is also the re-deriver it was meant to check "
        "collapses two roles the blindness boundary requires apart"
    ),
}


def assert_separate_principals(bench: Mapping[Role, str | Iterable[str]]) -> None:
    """Every role in `bench` must be held by a principal no other role holds.

    `bench` maps a role to one principal, or -- for OWNER -- to many. Roles the
    caller does not supply are simply not checked, so a court that has no
    assessor in play does not have to invent one.

    Raises `PrincipalSeparationError` naming both roles, the shared principal,
    and why that particular collision matters.
    """
    holders: dict[Role, set[str]] = {}
    for role, value in bench.items():
        principals = {value} if isinstance(value, str) else set(value)
        # An empty owner set is legitimate: a radius with no surviving material
        # commitment convenes no court. It is not a separation failure.
        if principals:
            holders[role] = principals

    roles = sorted(holders, key=lambda r: r.value)
    for i, left in enumerate(roles):
        for right in roles[i + 1 :]:
            shared = holders[left] & holders[right]
            if shared:
                why = _WHY.get(frozenset({left, right}), "these roles must stay distinct")
                raise PrincipalSeparationError(
                    f"{left.value} and {right.value} are both held by {sorted(shared)!r}: {why}."
                )

    # Two owners sharing a principal is FINE and must not raise -- one team can
    # legitimately own several commitments. Only cross-role collisions matter.


def assert_arbiter_is_third(
    arbiter: str,
    *,
    owners: Iterable[str],
    assessor: str | None = None,
    rederiver: str | None = None,
) -> None:
    """Ruling 1.10 as a single call, for the common case.

    Convenience over `assert_separate_principals`, not a second implementation:
    it builds the bench and delegates, so there is one rule and one place to fix.
    """
    bench: dict[Role, str | Iterable[str]] = {Role.ARBITER: arbiter, Role.OWNER: list(owners)}
    if assessor is not None:
        bench[Role.ASSESSOR] = assessor
    if rederiver is not None:
        bench[Role.REDERIVER] = rederiver
    assert_separate_principals(bench)


def assert_agent_is_distinct(
    agent: str,
    *,
    arbiter: str | None = None,
    owners: Iterable[str] = (),
    assessor: str | None = None,
    rederiver: str | None = None,
) -> None:
    """Card 2: a registry entry's principal must hold no other role.

    Called at registration time (`tower/registry.py`) and again at dispatch
    time, because a registry entry that was clean when it was created and
    later gets assigned an arbiter's principal is exactly the drift ruling
    1.10 exists to catch -- checking once at creation is not the same
    guarantee as checking on every use.
    """
    bench: dict[Role, str | Iterable[str]] = {Role.AGENT: agent}
    if arbiter is not None:
        bench[Role.ARBITER] = arbiter
    if owners:
        bench[Role.OWNER] = list(owners)
    if assessor is not None:
        bench[Role.ASSESSOR] = assessor
    if rederiver is not None:
        bench[Role.REDERIVER] = rederiver
    assert_separate_principals(bench)


def assert_warrant_access(*, balance_principal: str, acting_principal: str) -> None:
    """Card 0's balances are keyed by principal and MUST NEVER move.

    This is not warrant arithmetic -- there is none yet, CARD 0 mints and
    burns in a later prompt. It is the access guard those balances will sit
    behind: a warrant slot belongs to exactly the principal it was minted
    for, so reading or spending it as any other principal is not a transfer
    request to evaluate, it is a request that cannot be well-formed. Raising
    here means the non-transferability is enforced before there is a single
    unit of warrant to steal.
    """
    if balance_principal != acting_principal:
        raise NonTransferableError(
            f"warrant balance held by {balance_principal!r} cannot be accessed or "
            f"moved by {acting_principal!r}: warrants are non-transferable across "
            "principals by construction, not by policy."
        )
