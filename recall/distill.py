"""Turn one finished mission into atomic, provenance-bearing knowledge.

DETERMINISTIC, AND THE REASON IS NOT PURITY
----------------------------------------------
Every statement below is generated from typed fields by a fixed template.
No model writes any of this text, and that is load-bearing twice over:

  1. `recall/index.py` scores against these statements. A retriever whose
     corpus is model-written is a retriever whose ranking moves when the
     model is re-sampled, which makes every retrieval test flaky and every
     retrieval claim unreproducible.
  2. Knowledge distilled by a model from a mission a model influenced is a
     closed loop with no external check in it. The point of this corpus is
     to carry facts the mission MEASURED -- a coverage figure, a refusal
     reason code, an isolated agent id -- forward to a later mission. A
     paraphrase of those facts is a strictly worse artefact than the facts.

WHAT IS DISTILLED, AND WHAT IS DELIBERATELY DROPPED
------------------------------------------------------
Distilled: settled and disputed premises, scope escalations, isolations,
Gateway refusals, worker faults with their failure kind, external effects,
and measured evidence coverage. Each becomes ONE record about ONE subject.

Dropped: narrative summaries, stage names, timings, and anything already
recoverable from the checkpoint chain. `command_os/checkpoint.py` is the
transcript and it is complete; this module is an INDEX over the parts of it
a future mission can act on. Duplicating the transcript here would be the
"put everything in the context" failure with an extra copy.

STANDING IS ASSIGNED HERE, ONCE
----------------------------------
A record about something that went wrong gets `CAUTION`; a measurement gets
`OBSERVED`. Nothing distilled from a mission is ever written `UNTRUSTED` --
that standing exists for records whose provenance failed a check in
`recall/guard.py`, and a distiller that could assign it would be deciding
its own trustworthiness.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from recall.schema import KnowledgeRecord, RecordKind, Standing


def _record(
    *,
    kind: RecordKind,
    subject: str,
    statement: str,
    mission_id: str,
    objective_class: str,
    observed_at: datetime,
    standing: Standing = Standing.OBSERVED,
    value: dict[str, Any] | None = None,
    checkpoint_seq: int = 0,
    agent_id: str = "",
    tool: str = "",
    source: str = "",
) -> KnowledgeRecord:
    return KnowledgeRecord(
        record_id=KnowledgeRecord.make_id(
            mission_id=mission_id,
            kind=kind,
            subject=subject,
            checkpoint_seq=checkpoint_seq,
            statement=statement,
        ),
        kind=kind,
        standing=standing,
        subject=subject,
        statement=statement,
        value=value or {},
        mission_id=mission_id,
        objective_class=objective_class,
        checkpoint_seq=checkpoint_seq,
        agent_id=agent_id,
        tool=tool,
        source=source,
        observed_at=observed_at,
    )


def distill(
    *,
    report: dict[str, Any],
    checkpoints: list[dict[str, Any]],
    mission_id: str,
    observed_at: datetime | None = None,
) -> list[KnowledgeRecord]:
    """Every knowledge record this mission earned. Ordered, deduplicated.

    Takes the report and the checkpoint chain as plain dicts -- the same
    shapes `evolution/trajectory.py` already consumes -- so this module
    imports nothing from `command_os/` and can be exercised over a stored
    mission without replaying it.
    """
    observed_at = observed_at or datetime.now(UTC)
    objective_class = str(report.get("objective_class", "UNKNOWN"))
    out: list[KnowledgeRecord] = []

    def add(**kwargs: Any) -> None:
        out.append(
            _record(
                mission_id=mission_id,
                objective_class=objective_class,
                observed_at=observed_at,
                **kwargs,
            )
        )

    # --- evidence coverage: the number that prices every later action ----
    total = int(report.get("evidence_records_total", 0))
    if total:
        parsed = int(report.get("evidence_records_parsed", 0))
        completeness = float(report.get("evidence_completeness", 0.0))
        add(
            kind=RecordKind.EVIDENCE_COVERAGE,
            subject="incident_evidence",
            statement=(
                f"Evidence coverage measured at {completeness:.2f}: {parsed} of {total} "
                f"records parsed on a {objective_class} mission."
            ),
            value={"parsed": parsed, "total": total, "completeness": completeness},
            source="fleet/data/incident",
            tool="recon.extract_claims",
            agent_id="fleet_recon",
            standing=Standing.OBSERVED if completeness >= 0.9 else Standing.CAUTION,
        )

    # --- premises: settled and disputed ----------------------------------
    for cp in checkpoints:
        stage = cp.get("stage") or {}
        detail = stage.get("detail") or {}
        reconciliation = detail.get("reconciliation")
        if not isinstance(reconciliation, dict):
            continue
        seq = int(cp.get("seq", 0))
        for res in reconciliation.get("resolutions", []):
            if not isinstance(res, dict):
                continue
            claim_id = str(res.get("claim_id", ""))
            add(
                kind=RecordKind.SETTLED_PREMISE,
                subject=claim_id,
                statement=(
                    f"Premise {claim_id} ({res.get('predicate')}) settled at "
                    f"{res.get('chosen_value')!r} on the authority of "
                    f"{res.get('chosen_authority')!r} via source {res.get('chosen_source')!r}; "
                    "the recency rule agreed."
                ),
                value={
                    "predicate": res.get("predicate"),
                    "value": res.get("chosen_value"),
                    "authority": res.get("chosen_authority"),
                    "agreed_with_recency": bool(res.get("agreed_with_recency")),
                },
                checkpoint_seq=seq,
                agent_id="fleet_reconciler",
                tool="reconcile.adjudicate",
                source=str(res.get("chosen_source", "")),
            )
        for dis in reconciliation.get("disputes", []):
            if not isinstance(dis, dict):
                continue
            claim_id = str(dis.get("claim_id", ""))
            add(
                kind=RecordKind.DISPUTED_PREMISE,
                subject=claim_id,
                statement=(
                    f"Premise {claim_id} ({dis.get('predicate')}) is DISPUTED "
                    f"({dis.get('dispute_kind')}): recency selects "
                    f"{dis.get('recency_value')!r} from {dis.get('recency_source')!r} while "
                    f"authority selects {dis.get('authority_value')!r} from "
                    f"{dis.get('authority_source')!r}. Not decided by the system."
                ),
                value={
                    "predicate": dis.get("predicate"),
                    "dispute_kind": dis.get("dispute_kind"),
                    "recency_value": dis.get("recency_value"),
                    "authority_value": dis.get("authority_value"),
                },
                standing=Standing.CAUTION,
                checkpoint_seq=seq,
                agent_id="fleet_reconciler",
                tool="reconcile.adjudicate",
                source=str(dis.get("authority_source") or dis.get("recency_source") or ""),
            )

    # --- what the deterministic layer refused or contained ---------------
    for cp in checkpoints:
        stage = cp.get("stage") or {}
        detail = stage.get("detail") or {}
        seq = int(cp.get("seq", 0))

        target = detail.get("target")
        if isinstance(target, dict) and detail.get("isolated") is True:
            agent_id = str(target.get("agent_id", ""))
            add(
                kind=RecordKind.AGENT_ISOLATION,
                subject=agent_id,
                statement=(
                    f"Agent {agent_id} was ISOLATED after requesting "
                    f"{target.get('requested_scope')!r} with {target.get('tool_calls')} tool "
                    f"calls on dataset {target.get('dataset')!r}; the Gateway refused it."
                ),
                value={
                    "requested_scope": target.get("requested_scope"),
                    "tool_calls": target.get("tool_calls"),
                    "dataset": target.get("dataset"),
                    "request_id": target.get("request_id"),
                },
                standing=Standing.CAUTION,
                checkpoint_seq=seq,
                agent_id=agent_id,
                source="fleet/data/incident/capability-requests.csv",
            )

    # --- scope escalations, from the risk step's recorded findings -------
    for cp in checkpoints:
        ctx = cp.get("ctx") or {}
        risk = ctx.get("risk")
        if not isinstance(risk, dict):
            continue
        for esc in risk.get("escalations", []):
            if not isinstance(esc, dict):
                continue
            agent_id = str(esc.get("agent_id", ""))
            add(
                kind=RecordKind.SCOPE_ESCALATION,
                subject=agent_id,
                statement=(
                    f"Agent {agent_id} requested {esc.get('requested_scope')!r}, outside its "
                    f"registered scope {esc.get('granted_scope')!r}, on request "
                    f"{esc.get('request_id')!r} at risk class {esc.get('risk_class')!r}."
                ),
                value={
                    "requested_scope": esc.get("requested_scope"),
                    "granted_scope": esc.get("granted_scope"),
                    "request_id": esc.get("request_id"),
                    "risk_class": esc.get("risk_class"),
                    "tool_calls": esc.get("tool_calls"),
                },
                standing=Standing.CAUTION,
                checkpoint_seq=int(cp.get("seq", 0)),
                agent_id=agent_id,
                tool="risk.probe",
                source="fleet/data/incident/capability-requests.csv",
            )
        break  # the first checkpoint carrying `risk` has the full finding

    # --- refusals and faults, from the report ----------------------------
    for reason_code in report.get("gateway_refusals", []) or []:
        add(
            kind=RecordKind.GATEWAY_REFUSAL,
            subject=str(reason_code),
            statement=(
                f"The Gateway refused a step with reason code {reason_code} during a "
                f"{objective_class} mission."
            ),
            value={"reason_code": reason_code},
            standing=Standing.CAUTION,
        )
    for kind_name in report.get("worker_fault_kinds", []) or []:
        add(
            kind=RecordKind.WORKER_FAULT,
            subject=str(kind_name),
            statement=(
                f"A worker fault of kind {kind_name} occurred during a {objective_class} "
                "mission and the orchestrator replanned around it."
            ),
            value={"failure": kind_name},
            standing=Standing.CAUTION,
        )

    # --- what actually left the process ----------------------------------
    external_id = report.get("external_action_id")
    if external_id:
        add(
            kind=RecordKind.EXTERNAL_EFFECT,
            subject=str(report.get("external_action") or "external_action"),
            statement=(
                f"External action {report.get('external_action')!r} was executed as "
                f"{external_id} against backend {report.get('external_backend')!r} and "
                f"verified={report.get('verified')}."
            ),
            value={
                "external_id": external_id,
                "backend": report.get("external_backend"),
                "verified": report.get("verified"),
                "replayed": report.get("external_replayed"),
            },
            agent_id="fleet_remediation",
        )

    # Deduplicate on record_id, keeping first occurrence. Two identical facts
    # from one mission are one fact; letting both through would let a single
    # mission vote twice in retrieval.
    seen: set[str] = set()
    unique: list[KnowledgeRecord] = []
    for record in out:
        if record.record_id in seen:
            continue
        seen.add(record.record_id)
        unique.append(record)
    return unique


__all__ = ["distill"]
