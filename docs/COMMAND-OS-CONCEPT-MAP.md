# The 15-name concept map

These 15 names appear in the hackathon integration brief this project worked
from. **A repository-wide search finds zero hits for any of them** -- none
existed in this codebase before this document, as code, as a UI card, or as
a prior doc mention. There is therefore nothing to "integrate" under these
names; the only honest move is a mapping from each buzzword to the real
module that already provides that functional purpose, each with its own
truthful status.

Single source of truth: `command_os/concept_map.py` (this table is generated
from it, not maintained by hand in two places). Served live at
`GET /api/command-os/concept-map`.

| Name | Maps to | Real module | Status |
| --- | --- | --- | --- |
| FleetGuard | Governance + AgentOps | `tower/gateway.py (the one choke point), hyperion/guard.py` | LIVE |
| AutoAudit | Continuous Audit | `hyperion/immune_memory.py, singularity/mesh_memory.py (append-only logs + aggregates)` | LIVE |
| Self-Repairing Fleet | Self-Healing Engine | `command_os/mission.py stage 9 (re-negotiated genome + real re-mint via warrant/ledger.py)` | LIVE |
| Cross-Department Orchestrator | Master Orchestrator | `command_os/mission.py` | LIVE (orchestration) / DESIGNED (department-level routing) |
| Overlord AI | Supervisor / Policy Engine | `tower/gateway.py:evaluate_gateway` | LIVE |
| Phoenix | Repair + Recovery | `command_os/mission.py stages 9-10, resumable via command_os/checkpoint.py` | LIVE -- checkpoint-aware: resumes from the last completed stage regardless of what interrupted the mission, not just a scripted stage sequence |
| ShadowAudit | Continuous Compliance / Audit | `hyperion/immune_memory.py, singularity/mesh_memory.py` | LIVE |
| OmniFleet | Cross-Department Fleet | `singularity/fleet.py (7-role reference topology)` | REFERENCE -- static topology, not a running fleet |
| Chronos-9 | Dynamic Agent Factory | `singularity/fleet.py:full_fleet()` | SIMULATED -- static roster, no live agent spawning |
| Aegis-Neuro | Distributed Defense | `hyperion/guard.py, hyperion/risk.py` | LIVE |
| Chronos-Void | Digital Twin / Simulation | `none -- command_os/checkpoint.py's Mission Time Machine is a DIFFERENT, related capability (historical-state inspection, not a forecasting twin); see docs/mission-state.md` | DESIGNED -- not built, no simulation/forecasting engine exists |
| Pandora | Autonomous Red Team / Chaos Testing | `tests/test_adversarial.py` (20 attacks, asserted defences) + `fleet/data/incident/` (the evidence a mission actually reacts to) | LIVE (TEST SUITE) -- 20 attacks with asserted defences plus one declared undefended gap; still no autonomous red agent that improvises |
| Vigilante AI | Rogue Agent Detection | `singularity/behavior.py:detect_drift` | LIVE |
| Nexus Command | Command Center / Executive Control | `web/static (Agentic Command OS screen) + command_os/mission.py's report` | LIVE |
| Nebula OS | Autonomous DevOps Fleet | `infra/deploy.sh, Makefile deploy targets` | DESIGNED -- deploy is scripted, not agent-driven |

## Why fifteen cards were not built

A UI card with no function behind it is worse than no card: it is a claim
a judge cannot verify by clicking on it. The six cards that already existed
(UNWIND, WARRANT, CONTROL TOWER, COUNTERSIGN, HYPERION-ZERO, SINGULARITY-MESH)
stay exactly as they are -- see `docs/architecture.md` for how the Agentic
Command OS mission sequences real calls into several of the modules this
table names.

## 2026-08-19 update

Two statuses genuinely changed with the Continuous Mission State pass
(`docs/mission-state.md`), not cosmetically: **Phoenix** went from a
scripted repair sequence to checkpoint-aware recovery -- it now resumes
from the last completed stage after ANY interruption, not just the one
scripted attack path. **Chronos-Void stays DESIGNED** -- the new Mission
Time Machine is a real, LIVE capability, but it is historical-state
inspection, not a forecasting digital twin, and the two are kept explicitly
distinct rather than letting one borrow the other's status.
