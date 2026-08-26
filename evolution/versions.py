"""Agent versions: immutable, content-addressed, and seeded from what is
actually serving today.

WHY THE SEED IS NOT A PLACEHOLDER
------------------------------------
Version 1 of every agent is the instruction text that `fleet/roles.py`
ALREADY carries and that `fleet/agents.py` ALREADY hands to a real
`LlmAgent`. The evolution loop therefore starts from production rather than
from a fixture, and "promote version 2" genuinely means "change what the
serving agent is told". If the seed were invented here, the whole loop would
be a simulation of itself.

WHAT A VERSION MAY CARRY -- AND THE LINE THIS PACKAGE NEVER CROSSES
----------------------------------------------------------------------
An `AgentVersion` carries an `instruction` (prose handed to a model) and a
`policy` (a small dict of bounded operating preferences). It carries NO
scope, NO tool list, NO warrant schedule, NO risk threshold. Those live in
`fleet/roles.py` and are enforced by `tower/gateway.py:check_scope`, which
this package neither imports nor writes to.

The consequence is the property that makes a self-modifying agent safe to
run at all: **the evolution loop can change what an agent is TOLD, and can
never change what an agent is ALLOWED.** A candidate version that has
somehow been talked into requesting `sandbox.write` still meets exactly the
same Gateway, holding exactly the same registered scope, as version 1 did.
`tests/test_evolution_promote.py::test_candidate_carrying_scope_cannot_even_be_constructed`
proves the refusal, and
`tests/test_evolution_versions.py::test_version_cannot_carry_authority_keys`
proves it cannot even be constructed.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from evolution.schema import AgentVersion, ProposalProvenance, VersionStatus

#: Keys a version's `policy` dict may never contain, at any nesting level.
#: These name AUTHORITY, and authority is the registry's to grant, not the
#: evolution loop's. Checked by `assert_no_authority_keys`, which runs on
#: every construction path -- proposal, promotion and direct build.
FORBIDDEN_POLICY_KEYS = frozenset(
    {
        "authority_scope",
        "data_scope",
        "scope",
        "scopes",
        "tools",
        "tool",
        "permitted_actions",
        "risk_class_thresholds",
        "warrant_mint_schedule",
        "warrant_spend_schedule",
        "max_budget",
        "principal",
        "agent_id",
    }
)


class AuthorityEscalation(ValueError):
    """Raised when a version tries to carry something only the registry may
    grant. Deliberately its own type so a caller cannot catch it by accident
    while catching ordinary validation errors."""


def assert_no_authority_keys(policy: dict[str, Any], *, where: str = "policy") -> None:
    """Refuse any authority-bearing key, at any depth.

    Recursive on purpose: `{"limits": {"tools": [...]}}` is the same
    escalation attempt as `{"tools": [...]}` wearing a hat.
    """
    stack: list[tuple[str, Any]] = [(where, policy)]
    while stack:
        path, node = stack.pop()
        if isinstance(node, dict):
            for key, value in node.items():
                if str(key).lower() in FORBIDDEN_POLICY_KEYS:
                    raise AuthorityEscalation(
                        f"{path}.{key} names authority; authority is granted by "
                        "fleet/roles.py and enforced by tower/gateway.py, and can "
                        "never be set by an agent version"
                    )
                stack.append((f"{path}.{key}", value))
        elif isinstance(node, list):
            for i, value in enumerate(node):
                stack.append((f"{path}[{i}]", value))


def compute_version_id(agent_key: str, instruction: str, policy: dict[str, Any]) -> str:
    """Content address. Two versions with identical text ARE one version.

    This is what makes an evaluation permanently attributable: a score
    computed for `v_a1b2...` can only ever refer to that exact instruction
    and policy, because changing either produces a different id rather than
    mutating this one.
    """
    payload = json.dumps(
        {"agent_key": agent_key, "instruction": instruction, "policy": policy},
        sort_keys=True,
    )
    return "v_" + hashlib.sha256(payload.encode()).hexdigest()[:16]


def build_version(
    *,
    agent_key: str,
    instruction: str,
    policy: dict[str, Any] | None = None,
    version_n: int,
    parent_version_id: str | None = None,
    status: VersionStatus = VersionStatus.CANDIDATE,
    provenance: ProposalProvenance | str = ProposalProvenance.ZERO_MODEL,
    model: str = "",
    now: datetime | None = None,
) -> AgentVersion:
    """The ONLY constructor. Every path that makes a version comes through
    here, so the authority check cannot be skipped by a new caller."""
    policy = dict(policy or {})
    assert_no_authority_keys(policy)
    if not instruction.strip():
        raise ValueError("an agent version with an empty instruction is not a version")
    return AgentVersion(
        version_id=compute_version_id(agent_key, instruction, policy),
        agent_key=agent_key,
        version_n=version_n,
        instruction=instruction,
        policy=policy,
        status=status,
        parent_version_id=parent_version_id,
        provenance=(
            provenance.value if isinstance(provenance, ProposalProvenance) else str(provenance)
        ),
        model=model,
        created_at=now or datetime.now(UTC),
    )


#: [ASSUMPTION] The seed policy. Small, bounded, and every key is something
#: an instruction could legitimately express as a preference -- never a
#: permission. `MUTABLE_POLICY_KEYS` in `evolution/propose.py` is a subset of
#: these, and a proposal may not introduce a key outside it.
SEED_POLICY: dict[str, Any] = {
    #: Refuse to propose an external effect below this parsed-evidence
    #: coverage. A preference: the Gateway still independently decides.
    "min_evidence_completeness": 0.5,
    #: Ask for human concurrence when contradictions are unresolved.
    "require_human_on_contradiction": True,
    #: Upper bound on plan length this agent will propose. Never above
    #: `fleet/planner.py:MAX_PLAN_STEPS`, which clamps it regardless.
    "max_plan_steps": 8,
    #: Prefer to verify after any external effect.
    "verify_after_execute": True,
}


def seed_versions(now: datetime | None = None) -> list[AgentVersion]:
    """Version 1 for every fleet role, taken from the LIVE instruction text.

    Reads `fleet/roles.py` at call time rather than copying its strings, so
    this can never drift from what is actually serving. If someone edits a
    role's instruction, the seed's `version_id` changes with it -- which is
    correct: it is a different version.
    """
    from fleet.roles import ALL_ROLES

    now = now or datetime.now(UTC)
    seeds: list[AgentVersion] = []
    for role in ALL_ROLES:
        instruction = (role.instruction or "").strip()
        if not instruction:
            # A role with no instruction is not an evolvable agent. Skipped
            # honestly rather than seeded with invented prose.
            continue
        version = build_version(
            agent_key=role.key,
            instruction=instruction,
            policy=dict(SEED_POLICY),
            version_n=1,
            parent_version_id=None,
            status=VersionStatus.ACTIVE,
            provenance=ProposalProvenance.SEED,
            model="",
            now=now,
        )
        # The seed is ACTIVE by definition: it is what is serving. It is the
        # one version in the system that no human promoted, because no human
        # had to -- nothing replaced anything.
        seeds.append(version.model_copy(update={"promoted_at": now, "promoted_by": "SEED"}))
    return seeds


def diff_versions(baseline: AgentVersion, candidate: AgentVersion) -> list[dict[str, Any]]:
    """Field-by-field change list, so a human reviewer diffs a list rather
    than two prose blobs. Instruction changes are reported as a line diff
    summary, not a character diff -- a reviewer approving a promotion needs
    to see WHAT rule changed, not which byte."""
    changes: list[dict[str, Any]] = []

    base_lines = [ln.strip() for ln in baseline.instruction.splitlines() if ln.strip()]
    cand_lines = [ln.strip() for ln in candidate.instruction.splitlines() if ln.strip()]
    added = [ln for ln in cand_lines if ln not in base_lines]
    removed = [ln for ln in base_lines if ln not in cand_lines]
    if added or removed:
        changes.append(
            {
                "field": "instruction",
                "lines_added": added,
                "lines_removed": removed,
                "chars_before": len(baseline.instruction),
                "chars_after": len(candidate.instruction),
            }
        )

    for key in sorted(set(baseline.policy) | set(candidate.policy)):
        before = baseline.policy.get(key)
        after = candidate.policy.get(key)
        if before != after:
            changes.append({"field": f"policy.{key}", "before": before, "after": after})
    return changes


__all__ = [
    "FORBIDDEN_POLICY_KEYS",
    "SEED_POLICY",
    "AuthorityEscalation",
    "assert_no_authority_keys",
    "build_version",
    "compute_version_id",
    "diff_versions",
    "seed_versions",
]
