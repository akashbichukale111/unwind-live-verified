"""Fold the seven criteria over one real mission run.

WHERE THE INPUTS COME FROM
-----------------------------
`report` is `command_os/schema.py:MissionReport` as a dict -- every field of
it was measured by `command_os/mission.py` during the run. `checkpoints` are
the append-only stages `command_os/checkpoint.py` persisted. Nothing in this
module asks an agent how it thinks it did.

This module is PURE. It performs no I/O, opens no client, reads no clock it
was not handed, and imports no model. `evolution/store.py` persists what this
returns; keeping the two apart means an evaluation can be recomputed from a
stored mission record years later and must come out bit-identical.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from evolution.criteria import (
    WEIGHTS,
    context_quality,
    efficiency,
    policy_compliance,
    recovery,
    risk_discipline,
    task_success,
    tool_correctness,
)
from evolution.schema import CriterionScore, TrajectoryEvaluation


def collect_tool_calls(checkpoints: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every real tool attempt the mission made, successful or not.

    `command_os/mission.py:_run_tool` appends one entry per ATTEMPT, so a
    tool that failed once and succeeded on retry contributes two entries.
    That is exactly what `criteria.recovery` needs to tell a recovered fault
    from an unrecovered one, so the attempt-level granularity is preserved
    rather than collapsed.
    """
    calls: list[dict[str, Any]] = []
    for cp in checkpoints:
        stage = cp.get("stage", cp)
        detail = stage.get("detail", {}) or {}
        for call in detail.get("tool_calls", []) or []:
            if isinstance(call, dict):
                calls.append(call)
    return calls


def _policy_trace(
    report: dict[str, Any], checkpoints: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Every point at which the deterministic layer had a say.

    Folded from stages that actually recorded a decision -- a refusal, a
    narrowing, a gate, a challenge, a settlement. A mission where the policy
    layer never spoke produces an empty trace, honestly, rather than a
    fabricated "all clear" row.
    """
    trace: list[dict[str, Any]] = []
    for cp in checkpoints:
        stage = cp.get("stage", cp)
        detail = stage.get("detail", {}) or {}
        entry: dict[str, Any] = {}
        for key in (
            "reason_code",
            "reason",
            "narrowed_by_drift",
            "gate",
            "human_principal",
            "challenger_agrees",
            "authority_settlement",
            "genome_decision",
            "drift_band",
        ):
            if key in detail and detail[key] not in (None, "", []):
                entry[key] = detail[key]
        if entry:
            entry["stage"] = stage.get("name", "")
            entry["seq"] = cp.get("seq", stage.get("n"))
            trace.append(entry)
    for code in report.get("gateway_refusals", []) or []:
        trace.append({"stage": "REPORT", "gateway_refusal": code})
    return trace


def _context_trace(report: dict[str, Any]) -> list[dict[str, Any]]:
    """What the reasoning rested on, with its measured quality attached.

    One row per context property that the run genuinely established. These
    are the numbers `warrant/economics.py` already taxes an action by, so the
    trace is not a parallel invention -- it is a view of an input the system
    already acts on.
    """
    parsed = int(report.get("evidence_records_parsed", 0) or 0)
    total = int(report.get("evidence_records_total", 0) or 0)
    rows: list[dict[str, Any]] = []
    if total:
        rows.append(
            {
                "source": "fleet/data/incident",
                "kind": "parsed_evidence",
                "parsed": parsed,
                "total": total,
                "completeness": round(parsed / total, 4),
                "trust": "MEASURED",
            }
        )
    contradictions = int(report.get("contradictions_found", 0) or 0)
    if contradictions:
        rows.append(
            {
                "source": "fleet/data/incident",
                "kind": "contradiction",
                "count": contradictions,
                "trust": "CONTESTED",
            }
        )
    escalations = int(report.get("escalations_found", 0) or 0)
    if escalations:
        rows.append(
            {
                "source": "risk.probe",
                "kind": "scope_escalation",
                "count": escalations,
                "trust": "MEASURED",
            }
        )
    drift = str(report.get("drift_band", "") or "")
    if drift and drift != "NORMAL":
        rows.append(
            {
                "source": "singularity.behavior",
                "kind": "behavioural_drift",
                "band": drift,
                "score": report.get("drift_score", 0),
                "trust": "DEGRADED",
            }
        )
    return rows


def _evaluation_id(mission_id: str, version_id: str, criteria: list[CriterionScore]) -> str:
    """Content-addressed. Re-evaluating the same mission under the same agent
    version with the same scores yields the same id, so a duplicate write is
    an overwrite of an identical document rather than a second row that looks
    like a second measurement."""
    payload = json.dumps(
        {
            "mission_id": mission_id,
            "version_id": version_id,
            "scores": [[c.key.value, c.score] for c in criteria],
        },
        sort_keys=True,
    )
    return "eval_" + hashlib.sha256(payload.encode()).hexdigest()[:16]


def evaluate_trajectory(
    *,
    report: dict[str, Any],
    checkpoints: list[dict[str, Any]] | None = None,
    mission_id: str,
    agent_version_id: str,
    agent_key: str = "fleet_orchestrator",
    tool_registry: dict[str, str] | None = None,
    now: datetime | None = None,
) -> TrajectoryEvaluation:
    """Score one mission's BEHAVIOUR. Pure function of its arguments.

    `tool_registry` defaults to `fleet.tools.TOOL_REGISTRY`. It is injectable
    so `tests/test_evolution_criteria.py` can prove that an off-registry tool
    hard-zeroes `TOOL_CORRECTNESS` without having to actually invoke one.
    """
    if tool_registry is None:
        from fleet.tools import TOOL_REGISTRY as _registry

        tool_registry = _registry
    checkpoints = checkpoints or []
    calls = collect_tool_calls(checkpoints)

    criteria = [
        task_success(report),
        policy_compliance(report),
        tool_correctness(report, registry=tool_registry),
        context_quality(report),
        risk_discipline(report),
        recovery(report, tool_calls=calls),
        efficiency(report, tool_calls=calls),
    ]

    # Weighted mean. Weights sum to 1.0 (asserted in
    # `tests/test_evolution_criteria.py`), so no normalisation is hidden here.
    composite = round(sum(c.score * WEIGHTS[c.key] for c in criteria), 4)
    failures = [f"{c.key.value}: {c.failure}" for c in criteria if c.failure]

    return TrajectoryEvaluation(
        evaluation_id=_evaluation_id(mission_id, agent_version_id, criteria),
        mission_id=mission_id,
        agent_version_id=agent_version_id,
        agent_key=agent_key,
        objective=str(report.get("objective", "") or ""),
        objective_class=str(report.get("objective_class", "") or ""),
        criteria=criteria,
        composite=composite,
        failures=failures,
        tool_trace=calls,
        policy_trace=_policy_trace(report, checkpoints),
        context_trace=_context_trace(report),
        # Carried verbatim: an evaluation can never read better than the
        # mission it scores.
        outcome=str(report.get("status", "") or ""),
        created_at=now or datetime.now(UTC),
    )


__all__ = ["collect_tool_calls", "evaluate_trajectory"]
