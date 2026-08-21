"""Team formation: the repair team is composed at runtime, from a radius.

THERE IS NO DESIGN-TIME TOPOLOGY. The set of parties to a repair is discovered
when a premise dies, from a blast radius that did not exist a second earlier.
Team size is a function of the radius, not of configuration -- which is exactly
why this is an ADK 2 dynamic pattern and not a static graph of agents wired up
in advance.

Two bounds keep that from becoming unbounded work, and both are structural:

    MAX_TEAM        a hard ceiling on parties, so a 2,594-node radius cannot
                    convene a 2,594-party hearing.
    exposure order  when the ceiling binds, the seats go to the commitments
                    with the most at stake, deterministically ranked by
                    `spine.cartography` so ties do not break on luck.

Teams dissolve on settlement. A team that outlives its repair is a set of
agents holding authority over a question nobody asked.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from lib.config import Tier
from lib.telemetry import agent_decision_span

#: [ASSUMPTION] The most parties one hearing may have. Chosen as a cost bound,
#: not a modelling claim: every party is at least one T2 call per turn, so this
#: multiplied by the turn cap is the worst-case model spend of a single repair.
MAX_TEAM = 12


class TeamDissolvedError(RuntimeError):
    """Something addressed a team after it settled."""


@dataclass(frozen=True)
class TeamMember:
    """One seat at the hearing: a principal, and the commitment it speaks for."""

    owner_id: str
    conclusion_id: str
    exposure: float
    depth: int


@dataclass
class RepairTeam:
    repair_id: str
    claim_id: str
    members: list[TeamMember] = field(default_factory=list)
    #: The radius this team was drawn from. Kept so "size is a function of the
    #: radius" is inspectable after the fact rather than asserted.
    radius_size: int = 0
    eligible: int = 0
    dissolved: bool = False
    #: How many seats the team actually had. Kept separately from `members`
    #: because dissolution empties that list, and a report written after
    #: settlement would otherwise say the hearing had nobody in it.
    seated: int = 0

    @property
    def size(self) -> int:
        return len(self.members)

    @property
    def owner_ids(self) -> list[str]:
        return [m.owner_id for m in self.members]

    @property
    def capped(self) -> bool:
        """Whether the ceiling bound, i.e. some eligible commitment got no seat."""
        return self.eligible > len(self.members)

    def require_live(self) -> None:
        if self.dissolved:
            raise TeamDissolvedError(
                f"repair {self.repair_id} has settled; its team no longer holds "
                "authority over anything."
            )

    def dissolve(self) -> None:
        """Settlement. The team stops existing as an authority."""
        self.dissolved = True
        self.members = []


def form_team(result: Any, repair_id: str, owner_lookup: Callable[[str], str | None]) -> RepairTeam:
    """Compose a team from whatever survived T0 and T1.

    Eligibility is exactly the alert cell -- MATERIAL and ESCAPED. The other
    three regimes are already settled without argument: immaterial dies quietly,
    and not-escaped is corrected in place with nobody to apologise to. Convening
    a hearing for them would be theatre.

    `owner_lookup` is passed in rather than read off the result, so team
    formation depends on the radius and a lookup and on nothing else -- which is
    what lets a test drive it with two synthetic radii and observe two sizes.
    """
    with agent_decision_span("team-formation", Tier.T0) as span:
        alerts = result.alerts()
        seen: set[str] = set()
        eligible: list[TeamMember] = []
        for verdict in alerts:
            owner = owner_lookup(verdict.conclusion_id)
            if owner is None:
                continue
            key = verdict.conclusion_id
            if key in seen:
                continue
            seen.add(key)
            eligible.append(
                TeamMember(
                    owner_id=owner,
                    conclusion_id=verdict.conclusion_id,
                    exposure=verdict.exposure,
                    depth=verdict.depth,
                )
            )

        team = RepairTeam(
            repair_id=repair_id,
            claim_id=result.claim_id,
            # `alerts()` is already in deterministic exposure order, so the
            # truncation is reproducible rather than whichever N arrived first.
            members=eligible[:MAX_TEAM],
            radius_size=len(result.radius),
            eligible=len(eligible),
            seated=len(eligible[:MAX_TEAM]),
        )
        span.set_attribute("unwind.radius_size", team.radius_size)
        span.set_attribute("unwind.team_eligible", team.eligible)
        span.set_attribute("unwind.team_size", team.size)
        span.set_attribute("unwind.team_capped", team.capped)
        return team
