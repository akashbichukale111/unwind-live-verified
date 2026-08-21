"""Fleet topology: reference data describing the Sentinel Shield /
Orchestrator / Worker Fleet architecture Singularity-Mesh's UI renders.

REFERENCE DATA, NOT A RUNNING FLEET
---------------------------------------
Every entry below is static Python data describing the intended topology --
nothing here spawns a process, calls a model, or executes a task. No agent
in this module "runs" anything; `singularity/genome.py` and
`singularity/behavior.py` are the two live, callable decision engines this
card actually ships. See `singularity/DESIGN.md` for the full built-vs-
architecture accounting the UI's status badges are drawn from.
"""

from __future__ import annotations

from typing import TypedDict


class FleetAgent(TypedDict):
    agent_id: str
    role: str
    title: str
    responsibility: str
    inputs: list[str]
    outputs: list[str]
    security_responsibility: str
    relationship: str
    status: str


SENTINEL_SHIELD: FleetAgent = {
    "agent_id": "sentinel-shield",
    "role": "SENTINEL",
    "title": "Sentinel Shield — Policy Enforcement Agent",
    "responsibility": "Input Immunity: screens every incoming request for prompt injection, "
    "tool poisoning, malicious requests, and suspicious instructions before it reaches "
    "the Orchestrator.",
    "inputs": ["raw user/agent request", "tool-call payloads"],
    "outputs": ["SAFE / SUSPICIOUS verdict", "ALLOW / BLOCK decision"],
    "security_responsibility": "First checkpoint. Nothing crosses into planning or execution "
    "until Sentinel has classified it.",
    "relationship": "Sits in front of the Orchestrator; every request the Orchestrator plans "
    "against has already passed Sentinel.",
    "status": "ARCHITECTURE",
}

ORCHESTRATOR: FleetAgent = {
    "agent_id": "orchestrator",
    "role": "ORCHESTRATOR",
    "title": "Orchestrator — Plan → Delegate → Monitor → Validate → Recover",
    "responsibility": "Understands the request, plans the approach, selects the right data/"
    "source, checks permissions via the Capability Genome, delegates to the Worker "
    "Fleet, monitors execution, validates results, and recovers on failure.",
    "inputs": ["Sentinel-cleared request", "Capability Genome for this task", "Knowledge Catalog"],
    "outputs": ["worker task assignments", "validated result", "recovery actions"],
    "security_responsibility": "Never grants an agent more than its computed genome allows for "
    "this task; re-checks risk before delegating.",
    "relationship": "Receives from Sentinel, delegates to the Worker Fleet, reports back "
    "through Observability.",
    "status": "ARCHITECTURE",
}

WORKER_FLEET: list[FleetAgent] = [
    {
        "agent_id": "worker-01",
        "role": "WORKER_SQL",
        "title": "Worker #01 — SQL Analysis",
        "responsibility": "Runs governed, read-scoped SQL against approved datasets via MCP.",
        "inputs": ["delegated SQL task", "capability genome (sql_read/sql_aggregate)"],
        "outputs": ["query result", "execution trace"],
        "security_responsibility": "Executes only inside its granted genome; no direct DB "
        "credentials.",
        "relationship": "Reports to the Orchestrator; isolated from other workers.",
        "status": "ARCHITECTURE",
    },
    {
        "agent_id": "worker-02",
        "role": "WORKER_PYTHON",
        "title": "Worker #02 — Python Analysis",
        "responsibility": "Runs generated analysis code inside an isolated sandbox.",
        "inputs": ["delegated analysis task", "dataset reference"],
        "outputs": ["analysis result", "sandbox execution log"],
        "security_responsibility": "Generated code is untrusted by default; runs isolated, "
        "never against production credentials directly.",
        "relationship": "Reports to the Orchestrator; sandboxed independently of other workers.",
        "status": "ARCHITECTURE",
    },
    {
        "agent_id": "worker-03",
        "role": "WORKER_DOCUMENT",
        "title": "Worker #03 — Document Processing",
        "responsibility": "Extracts and structures fields from governed documents.",
        "inputs": ["delegated document task", "document reference"],
        "outputs": ["extracted fields", "confidence/notes"],
        "security_responsibility": "Read-only against the Knowledge Catalog's document scope.",
        "relationship": "Reports to the Orchestrator.",
        "status": "ARCHITECTURE",
    },
    {
        "agent_id": "worker-04",
        "role": "WORKER_BROWSER",
        "title": "Worker #04 — Browser / Research",
        "responsibility": "Fetches and reads external pages for research tasks.",
        "inputs": ["delegated research task", "URL/query"],
        "outputs": ["page content", "extracted summary"],
        "security_responsibility": "Outbound-only, read-only; the fleet's designated attack "
        "surface in the 3-minute demo's compromised-worker scenario.",
        "relationship": "Reports to the Orchestrator; the worker isolated in the "
        "attack → block → isolate → recover walkthrough.",
        "status": "ARCHITECTURE",
    },
    {
        "agent_id": "worker-05",
        "role": "WORKER_COMPLIANCE",
        "title": "Worker #05 — Compliance",
        "responsibility": "Checks a task or result against governed policy before it is accepted.",
        "inputs": ["delegated compliance check", "policy reference"],
        "outputs": ["pass/flag verdict"],
        "security_responsibility": "Read-only against policy data; cannot itself grant an "
        "exception.",
        "relationship": "Reports to the Orchestrator.",
        "status": "ARCHITECTURE",
    },
]


def full_fleet() -> list[FleetAgent]:
    return [SENTINEL_SHIELD, ORCHESTRATOR, *WORKER_FLEET]
