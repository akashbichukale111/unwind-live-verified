"""System Reality: the honest LIVE / SIMULATED / REFERENCE / ARCHITECTURE /
DESIGNED status of everything the Agentic Command OS surfaces, in one place.

This module invents no new status values for content that already has an
honest label -- `singularity.lifecycle.IMPLEMENTATION_STATUS` is reused
verbatim, and the Hyperion rows below are a direct transcription of
`hyperion/DESIGN.md`'s own "What is built" / "What is NOT built" tables, not
a re-assessment. Only the Command-OS-level rows at the bottom are new, and
each one is scoped to exactly what `command_os/mission.py` does or does not
do.
"""

from __future__ import annotations

from typing import Any


def system_reality() -> list[dict[str, Any]]:
    from singularity.lifecycle import IMPLEMENTATION_STATUS

    rows: list[dict[str, Any]] = []

    for feature, status in IMPLEMENTATION_STATUS.items():
        rows.append({"area": "Singularity-Mesh", "feature": feature, "status": status})

    # Transcribed from hyperion/DESIGN.md's "What is built" / "What is NOT
    # built" tables -- not re-derived here.
    for feature, status in (
        ("risk_scoring", "LIVE"),
        ("immune_event_log", "LIVE"),
        ("mcp_tool_call_guard", "ARCHITECTURE"),
        ("shadow_sandbox", "ARCHITECTURE"),
        ("quarantine_process_isolation", "ARCHITECTURE"),
        ("fleet_threat_propagation", "ARCHITECTURE"),
    ):
        rows.append({"area": "Hyperion-Zero", "feature": feature, "status": status})

    for feature, status, note in (
        (
            "mission_planner",
            "LIVE",
            "fleet/planner.py classifies the objective and composes a plan whose "
            "specialists, tools and action kinds differ by objective "
            "(tests/test_fleet.py::test_different_objectives_create_different_plans)",
        ),
        (
            "gemini_planning",
            "CONFIGURED_NOT_EXERCISED",
            "fleet/agents.py builds a real ADK LlmAgent with a real output_schema and "
            "runs it through a real Runner; NO Google Cloud credentials were available "
            "in the session that wrote it, so it has not been executed against live "
            "Vertex. Every plan produced without it is labelled ZERO_MODEL, never GEMINI",
        ),
        (
            "agent_delegation",
            "LIVE",
            "six registered identities with distinct principals, scopes, budgets and "
            "warrant rows; the Orchestrator cannot delegate to itself and a read-only "
            "role is refused SCOPE_EXCEEDED by the unmodified Gateway",
        ),
        (
            "tool_output_contracts",
            "LIVE",
            "fleet/contracts.py checks every worker result for shape, self-consistency "
            "and GROUNDING IN THE WORKER'S OWN INPUTS before it may write into mission "
            "state; a violating result is discarded and the violations are kept in the "
            "checkpoint. See tests/test_fleet_contracts.py and "
            "tests/test_mission_failure_recovery.py::test_a_rejected_result_never_reaches_the_mission_context",
        ),
        (
            "supervised_workers",
            "LIVE",
            "every tool call runs under a real timeout with a bounded retry budget and "
            "three named failure kinds (TIMED_OUT / RAISED / CONTRACT). The timeout "
            "bounds the SUPERVISOR'S wait, not the worker's execution -- CPython cannot "
            "kill a thread, and command_os/mission.py says so rather than implying "
            "otherwise (tests/test_mission_failure_recovery.py)",
        ),
        (
            "authority_reconciliation",
            "LIVE",
            "a separately-scoped agent (fleet_reconciler) re-derives every contradicted "
            "claim from an authority ladder and compares it against the extractor's "
            "recency ruling; where the two disagree NOTHING is decided -- the claim is "
            "DISPUTED, the dispute raises the uncertainty tax and reaches the human "
            "(tests/test_reconcile.py)",
        ),
        (
            "mission_knowledge",
            "LIVE",
            "every completed mission distils what it MEASURED into atomic, provenanced, "
            "content-addressed records -- deterministically, with no model anywhere "
            "See recall/distill.py and "
            "tests/test_recall_mission.py::test_a_mission_writes_what_it_measured_into_the_knowledge_store",
        ),
        (
            "bounded_recall",
            "LIVE",
            "retrieval is a metadata filter plus a BM25-shaped lexical score, capped at "
            "5 records and 1200 characters, reporting what it dropped. NO VECTOR STORE: "
            "recall/index.py argues the case from this corpus's own properties and names "
            "the condition for revisiting it "
            "See tests/test_recall_index.py::test_retrieval_selects_rather_than_loading",
        ),
        (
            "cross_mission_learning",
            "LIVE",
            "mission N+1 plans differently because of mission N, and the PLAN checkpoint "
            "carries the risk profile before and after recall plus the records that "
            "changed it. n is small -- a handful of missions over one incident bundle -- "
            "and this is NOT a longitudinal self-improvement claim. See "
            "tests/test_recall_mission.py::test_the_second_mission_plans_differently_because_of_the_first",
        ),
        (
            "recall_one_way_valve",
            "LIVE",
            "recalled knowledge may raise a risk class or require a read-only check and "
            "can do nothing else: recall.guard.ScrutinyDirective has no field capable of "
            "granting scope, and one that gains such a field is refused at construction "
            "See tests/test_recall_guard.py::test_no_knowledge_record_can_widen_scope",
        ),
        (
            "specialist_agents",
            "LIVE",
            "Recon / Risk / Remediation / Verifier. Tool execution is deterministic "
            "(fleet/tools.py, zero-model by import-graph test); the LlmAgent objects "
            "for each role exist but their model path shares gemini_planning's status",
        ),
        (
            "causal_detection",
            "LIVE",
            "the containment probe exists only when parsed evidence names an "
            "escalation, and tests the scope and agent that evidence named "
            "(tests/test_mission_causality.py)",
        ),
        (
            "replanning",
            "LIVE",
            "deterministic revision after a refusal or worker fault: retry at narrowest "
            "held scope, downgrade unaffordable mutations, narrow to read-only under drift",
        ),
        (
            "warrant_market",
            "LIVE",
            "warrant/economics.py prices every action kind; the price is the "
            "requested_cost handed to the unmodified Gateway budget check",
        ),
        (
            "uncertainty_tax",
            "LIVE",
            "six independent signals raise the cost of acting under uncertainty; "
            "computed in warrant/, which tests/test_warrant_zero_model.py proves "
            "cannot reach a model",
        ),
        (
            "messy_data_synthesis",
            "LIVE",
            "fleet/data/incident/ is a free-text handover note, a CSV with a blank id, "
            "a missing integer and a corrupt timestamp, and a JSON feed with two "
            "contradicting records; measured coverage is 16/20, and that number feeds "
            "the uncertainty tax",
        ),
        (
            "independent_challenger",
            "LIVE (ZERO-MODEL)",
            "countersign/verify.py re-derives its own verdict from the evidence on five "
            "named grounds and can genuinely disagree; the Gemma model path is real "
            "code, but the model configured in lib/config.py returns 404 on this "
            "project (no Vertex Model Garden endpoint deployed) -- confirmed "
            "2026-08-21 across three Vertex regions with real ADC credentials. This "
            "is a deployment gap, not a credential problem: Gemini reaches the same "
            "project fine",
        ),
        (
            "mission_media_grounding",
            "LIVE",
            "media/grounding.py folds real checkpoints into the one brief all three "
            "modalities read; runs with no credentials at all, and GET "
            "/api/media/mission/{id}/brief returns the exact model input so it can be "
            "diffed against the checkpoints themselves",
        ),
        (
            "gemini_mission_synthesis",
            "LIVE",
            "media/adapters.py:_run_gemini is a real ADK Runner call against the "
            "configured Gemini model on Vertex; executed for real 2026-08-21 with "
            "genuine ADC credentials -- see evidence/models/ and "
            "evidence/INDEX.md for the run record",
        ),
        (
            "veo_mission_replay",
            "LIVE",
            "media/adapters.py:_run_veo is a real google-genai long-running-operation "
            "call against the configured Veo model; executed for real 2026-08-21, "
            "produced a genuine .mp4 (5.7MB, verified with `file`) -- see "
            "evidence/models/ and evidence/INDEX.md for the run record",
        ),
        (
            "lyria_mission_signal",
            "LIVE",
            "media/adapters.py:_run_lyria calls Vertex's Predict REST API directly "
            "(the google-genai SDK had no batch-music wrapper -- fixed 2026-08-21) "
            "against the configured Lyria model; executed for real, produced a "
            "genuine 48kHz stereo WAV (6.3MB, verified with `file`) -- see "
            "evidence/models/ and evidence/INDEX.md for the run record",
        ),
        (
            "external_action",
            "LIVE (SANDBOX BACKEND)",
            "command_os/external.py appends to a real file outside this process, keyed "
            "by an idempotency key, reversible by compensation. The GitHub backend is "
            "real code that has never been executed -- see /api/command-os/status's "
            "external_action block",
        ),
        (
            "authenticated_human_gate",
            "LIVE",
            "the concurrence record names the AUTHENTICATED principal; anonymous "
            "mutation is refused 401 and a service identity is refused 403",
        ),
        (
            "master_orchestrator",
            "LIVE",
            "command_os/mission.py executes the computed plan through the unmodified "
            "authority path; it constructs no GatewayDecision of its own",
        ),
        (
            "dynamic_agent_factory",
            "SIMULATED",
            "five roles are registered from static definitions (fleet/roles.py); no "
            "agent process is spawned at runtime",
        ),
        (
            "red_team_chaos_testing",
            "LIVE (TEST SUITE)",
            "tests/test_adversarial.py runs 20 attacks with asserted defences, plus one "
            "explicitly undefended gap (cross-tenant isolation)",
        ),
        (
            "digital_twin",
            "DESIGNED",
            "not built; no simulation or forecasting engine exists in this repository",
        ),
        (
            "cross_department_orchestration",
            "DESIGNED",
            "department names are documentation grouping only, not enforced routing",
        ),
        (
            "multi_tenancy",
            "DESIGNED",
            "no tenant dimension exists on any collection; any authenticated principal "
            "can read any mission. Stated in docs/SECURITY.md and pinned by "
            "tests/test_adversarial.py::test_known_gap_cross_tenant_isolation_is_not_implemented",
        ),
        (
            "mission_checkpoint_engine",
            "LIVE",
            "real Firestore writes per stage (command_os/checkpoint.py); the mission's "
            "own work queue and cursor live in the checkpointed context, so inserted "
            "work survives a restart",
        ),
        (
            "resumability",
            "LIVE",
            "resume distinguishes ALREADY COMPLETED / REQUIRES HUMAN APPROVAL / "
            "REPLAYABLE, and replay duplicates no spend, no Hyperion event and no "
            "external action -- measured on the ledger and the sandbox file, not on a flag",
        ),
        (
            "trusted_state",
            "LIVE",
            "categorical fold (TRUSTED/UNTRUSTED/QUARANTINED/REVOKED), never a score, "
            "keyed on what a stage recorded rather than its position",
        ),
        (
            "context_firewall",
            "LIVE (DISPLAY FILTER)",
            "three real signals (freshness, trust, relevance). It scores what a caller "
            "should treat as trusted context; it does not gate what resume_mission "
            "reconstructs, and its docstring says so",
        ),
        (
            "mission_time_machine",
            "LIVE",
            "historical checkpoint inspection, not a digital twin -- see digital_twin",
        ),
    ):
        rows.append(
            {"area": "Agentic Command OS", "feature": feature, "status": status, "note": note}
        )

    return rows
