"""The 15-name concept map: FleetGuard, AutoAudit, Self-Repairing Fleet,
Cross-Department Orchestrator, Overlord AI, Phoenix, ShadowAudit, OmniFleet,
Chronos-9, Aegis-Neuro, Chronos-Void, Pandora, Vigilante AI, Nexus Command,
Nebula OS -> what each one actually maps to in this repository.

WHY THIS MODULE EXISTS
------------------------
None of the 15 names above appear anywhere else in this codebase -- a
repository-wide search turns up zero hits. There is therefore nothing to
"integrate" under those names; the only honest move is a documented mapping
from each buzzword to the real module that already provides that
functionality, each with its own truthful status. This table is that
mapping, in one place, single source of truth for `docs/COMMAND-OS-CONCEPT-MAP.md`
-- not scattered across 15 fake UI cards.
"""

from __future__ import annotations

from typing import TypedDict


class ConceptMapping(TypedDict):
    name: str
    maps_to: str
    module: str
    status: str


CONCEPT_MAP: list[ConceptMapping] = [
    {
        "name": "FleetGuard",
        "maps_to": "Governance + AgentOps",
        "module": "tower/gateway.py (the one choke point), hyperion/guard.py",
        "status": "LIVE",
    },
    {
        "name": "AutoAudit",
        "maps_to": "Continuous Audit",
        "module": "hyperion/immune_memory.py, singularity/mesh_memory.py (append-only logs + aggregates)",
        "status": "LIVE",
    },
    {
        "name": "Self-Repairing Fleet",
        "maps_to": "Self-Healing Engine",
        "module": "command_os/mission.py stage 9 (re-negotiated genome + real re-mint via warrant/ledger.py)",
        "status": "LIVE",
    },
    {
        "name": "Cross-Department Orchestrator",
        "maps_to": "Master Orchestrator",
        "module": "command_os/mission.py",
        "status": "LIVE (orchestration) / DESIGNED (department-level routing)",
    },
    {
        "name": "Overlord AI",
        "maps_to": "Supervisor / Policy Engine",
        "module": "tower/gateway.py:evaluate_gateway",
        "status": "LIVE",
    },
    {
        "name": "Phoenix",
        "maps_to": "Repair + Recovery",
        "module": "command_os/mission.py stages 9-10, resumable via command_os/checkpoint.py",
        "status": "LIVE -- checkpoint-aware: resumes from the last completed stage regardless of "
        "what interrupted the mission, not just a scripted stage sequence",
    },
    {
        "name": "ShadowAudit",
        "maps_to": "Continuous Compliance / Audit",
        "module": "hyperion/immune_memory.py, singularity/mesh_memory.py",
        "status": "LIVE",
    },
    {
        "name": "OmniFleet",
        "maps_to": "Cross-Department Fleet",
        "module": "singularity/fleet.py (7-role reference topology)",
        "status": "REFERENCE -- static topology, not a running fleet",
    },
    {
        "name": "Chronos-9",
        "maps_to": "Dynamic Agent Factory",
        "module": "singularity/fleet.py:full_fleet()",
        "status": "SIMULATED -- static roster, no live agent spawning",
    },
    {
        "name": "Aegis-Neuro",
        "maps_to": "Distributed Defense",
        "module": "hyperion/guard.py, hyperion/risk.py",
        "status": "LIVE",
    },
    {
        "name": "Chronos-Void",
        "maps_to": "Digital Twin / Simulation",
        "module": "none -- command_os/checkpoint.py's Mission Time Machine is a DIFFERENT, "
        "related capability (historical-state inspection, not a forecasting twin); see "
        "docs/mission-state.md",
        "status": "DESIGNED -- not built, no simulation/forecasting engine exists",
    },
    {
        "name": "Pandora",
        "maps_to": "Autonomous Red Team / Chaos Testing",
        "module": "command_os/mission.py stage 4 (scripted adversarial observation)",
        "status": "SIMULATED -- one scripted scenario per run, no autonomous red agent",
    },
    {
        "name": "Vigilante AI",
        "maps_to": "Rogue Agent Detection",
        "module": "singularity/behavior.py:detect_drift",
        "status": "LIVE",
    },
    {
        "name": "Nexus Command",
        "maps_to": "Command Center / Executive Control",
        "module": "web/static (Agentic Command OS screen) + command_os/mission.py's report",
        "status": "LIVE",
    },
    {
        "name": "Nebula OS",
        "maps_to": "Autonomous DevOps Fleet",
        "module": "infra/deploy.sh, Makefile deploy targets",
        "status": "DESIGNED -- deploy is scripted, not agent-driven",
    },
]
