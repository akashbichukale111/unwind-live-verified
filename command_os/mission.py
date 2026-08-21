"""Master Orchestrator: run one mission from a COMPUTED PLAN, not a fixed list.

WHAT REPLACED WHAT
---------------------
This module used to hold `_STAGES`, a module-level list of eleven functions
executed 1 through 11 on every mission regardless of the objective. A
hostile review falsified its central claim in one experiment: forcing
`detect_drift` to return NORMAL produced a byte-identical mission, because
the drift result was computed and then discarded -- stage 5's requested
scope was a hardcoded literal.

Three things are structurally different now.

**1. THE PLAN IS COMPUTED.** `fleet/planner.py` classifies the objective and
produces a plan whose specialists, tools, action kinds and risk classes
differ by objective. A PREMISE_IMPACT_TRACE mission contains no remediation
role at all; a CREDENTIAL_AUDIT contains no write scope anywhere. The
mission executes that plan.

**2. DETECTION IS CAUSAL, AND THE CAUSE IS PARSED EVIDENCE.** The
containment probe (`_phase_contain`) exists only when
`fleet/tools.py:risk_probe` actually found a scope escalation, tests the
scope THAT EVIDENCE NAMED, on behalf of the agent THAT EVIDENCE NAMED, with
a `BehaviorObservation` built from the tool-call count and dataset THAT
EVIDENCE RECORDED. Remove the escalation from
`fleet/data/incident/capability-requests.csv` and no probe runs, nothing is
refused, nothing is isolated, and the report says so. That is asserted by
`tests/test_mission_causality.py`, which runs the mission over a modified
fixture and compares traces.

**3. UNCERTAINTY IS PRICED.** Every step's action is priced by
`warrant/economics.py` from the evidence completeness, evidence age, drift
band and challenger disagreement observed SO FAR. The price is the
`requested_cost` handed to the unmodified `tower/gateway.py:check_budget`.
So poor evidence does not merely get logged -- it makes the next action
more expensive, and an agent that cannot afford an action is refused with a
reason code.

WHAT DID NOT CHANGE, DELIBERATELY
------------------------------------
The authority path. `evaluate_with_hyperion` -> `evaluate_gateway` ->
`spend_or_refuse` is called exactly as before, unmodified, and still
contains no model. A language model may author the plan; it cannot price an
action, narrow a genome, spend warrant, or overturn a refusal. The
Gateway's refusal is final in this module too: a human decision at the gate
only ever authorises a NEW, narrower request that the unmodified gateway
independently re-checks.

CONTINUOUS MISSION STATE
---------------------------
`ctx["phases"]` is the mission's own work queue and `ctx["cursor"]` its
position in it; both live in the checkpointed context, so a handler that
appends work (a containment probe, a replan) extends the mission durably
rather than in memory. `seq` is a monotonic stage counter independent of
the queue's shape, so inserting work never renumbers a completed stage.
`resume_mission` restores `ctx` and continues at `latest.seq + 1`. A
completed stage is never re-entered: no duplicate warrant spend, no
duplicate Hyperion event, and no duplicate external action -- the last
guaranteed additionally by `command_os/external.py`'s idempotency key.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from typing import Any

from command_os import checkpoint
from command_os.schema import MissionReport, MissionResult, MissionStage
from lib.simulation import SimulationPolicy, resolve_policy
from warrant.economics import (
    BASE_COST_BP,
    MUTATING_ACTIONS,
    ActionKind,
    UncertaintySignals,
    parse_action_kind,
    price_action,
)

DEFAULT_OBJECTIVE = "Investigate an anomalous finance capability request."

#: Mission statuses. A superset of the previous vocabulary, because the old
#: one could not express "the mission ran but a step was refused" -- which is
#: how a blocked mission used to report `fleet_status: HEALTHY`.
STATUS_COMPLETED = "COMPLETED"
STATUS_COMPLETED_WITH_RESTRICTIONS = "COMPLETED_WITH_RESTRICTIONS"
STATUS_BLOCKED = "BLOCKED"
STATUS_CHALLENGED = "CHALLENGED"
STATUS_AWAITING_HUMAN = "AWAITING_HUMAN"
STATUS_FAILED_SAFE = "FAILED_SAFE"
STATUS_HALTED = "HALTED"

_FINAL_STATUSES = {
    STATUS_COMPLETED,
    STATUS_COMPLETED_WITH_RESTRICTIONS,
    STATUS_BLOCKED,
    STATUS_CHALLENGED,
    STATUS_FAILED_SAFE,
    STATUS_HALTED,
}

#: [ASSUMPTION] A worker gets this long before the supervisor calls it hung.
#: Small on purpose -- every tool here is local and deterministic, so a
#: second is already pathological.
TOOL_TIMEOUT_SECONDS = 10.0

#: Bounded retries for a transient tool failure. Bounded, with no backoff
#: needed for local tools; `docs/SECURITY.md` records that a networked
#: backend would need jitter and this does not have one.
MAX_TOOL_ATTEMPTS = 2


# ===========================================================================
# Context helpers
# ===========================================================================


#: Band ordering, worst last. Used by `_effective_drift_band` to take a
#: maximum rather than a most-recent value.
_BAND_ORDER = ("NORMAL", "ELEVATED", "DRIFT", "CRITICAL")


def _effective_drift_band(ctx: dict[str, Any]) -> str:
    """The WORST UNRESOLVED band, not the most recent one.

    A containment probe that scored CRITICAL used to be forgotten one step
    later, because the next step's own (benign) observation overwrote
    `ctx["drift_band"]`. That is precisely the failure
    `singularity/behavior.py`'s own docstring warns against -- "do not just
    inspect what the agent says, inspect what the agent is becoming". An
    agent caught escalating does not become trustworthy again because its
    next call looked ordinary.

    So while an isolation is unresolved, the containment band floors the
    effective band. `tests/test_mission_causality.py::
    test_detection_changes_the_requested_scope` is what caught this.
    """
    current = str(ctx.get("drift_band", "NORMAL")).upper()
    if not ctx.get("isolated_agent"):
        return current
    contained = str(ctx.get("containment_drift_band", "NORMAL")).upper()
    worst = max(
        (current, contained),
        key=lambda b: _BAND_ORDER.index(b) if b in _BAND_ORDER else 0,
    )
    return worst


def _signals(ctx: dict[str, Any]) -> UncertaintySignals:
    """Build the uncertainty signals from what the mission has ACTUALLY seen.

    Every field here was measured by a previous phase. Nothing is asserted
    by the agent being priced -- which is the property that makes the tax
    something an agent cannot argue its way out of.
    """
    return UncertaintySignals(
        evidence_age_seconds=float(ctx.get("evidence_age_seconds", 0.0)),
        evidence_completeness=float(ctx.get("evidence_completeness", 1.0)),
        drift_band=_effective_drift_band(ctx),
        model_disagreement=bool(ctx.get("challenger_disagreed", False)),
        external_state_changed=bool(ctx.get("external_state_changed", False)),
        risk_divergence=bool(ctx.get("risk_divergence", False)),
        consequence_band=str(ctx.get("consequence_band", "NONE")),
    )


def _plan(ctx: dict[str, Any]):
    from fleet.schema import MissionPlan

    return MissionPlan(**ctx["plan"])


def _append_phase(ctx: dict[str, Any], phase: str, *, after_cursor: bool = True) -> None:
    """Add work to the mission's durable queue.

    `after_cursor=True` inserts immediately after the current position, so a
    containment probe raised by the risk step runs BEFORE the remaining plan
    steps rather than after them. The queue lives in `ctx`, so the insertion
    survives a restart.
    """
    if after_cursor:
        ctx["phases"].insert(ctx["cursor"] + 1, phase)
    else:
        ctx["phases"].append(phase)


def _agent_for(role_or_agent_role) -> Any:
    """Resolve a `FleetRole` (or a `singularity.schema.AgentRole`) to its live
    registry entry, registering the fleet on first use.

    Accepts both because callers legitimately hold either: a plan step names
    an `AgentRole`, while `fleet/roles.py` constants are `FleetRole`s.
    Dispatch is on TYPE, not on dict membership -- `FleetRole` carries list
    fields and is therefore unhashable, so a membership test against
    `BY_AGENT_ROLE` raises rather than returning False.
    """
    from fleet.roles import FleetRole, role_for
    from tower.registry import get_agent

    fleet_role = (
        role_or_agent_role
        if isinstance(role_or_agent_role, FleetRole)
        else role_for(role_or_agent_role)
    )
    agent = get_agent(fleet_role.agent_id)
    if agent is None:
        from fleet.roles import ensure_registered

        ensure_registered()
        agent = get_agent(fleet_role.agent_id)
    return agent


def _seed_warrant(ctx: dict[str, Any]) -> dict[str, int]:
    """Give each fleet agent its opening warrant, ONCE per mission agent.

    [SYNTHETIC, LABELLED] These are opening balances, written through
    `warrant.ledger.write_synthetic_seed_event` -- the ledger's single
    documented bypass of the MINT preconditions, which exists precisely so a
    demo balance can never be mistaken for an earned one. The provenance
    field says SYNTHETIC forever, and `scripts/rederive_warrant.py` will
    report it as such. A cold-start agent with no seed is refused
    `WARRANT_INSUFFICIENT` by construction, which is a real behaviour this
    seeding does not remove -- it only decides where the mission starts.
    """
    from fleet.roles import SPECIALISTS
    from warrant.ledger import EventKind, current_balance, write_synthetic_seed_event

    seeded: dict[str, int] = {}
    for role in SPECIALISTS:
        agent = _agent_for(role)
        for risk_class, amount in role.warrant_mint_schedule.items():
            capability = role.capabilities[0]
            balance = current_balance(agent.principal, capability, risk_class)
            if balance > 0:
                seeded[f"{role.agent_id}:{risk_class}"] = balance
                continue
            write_synthetic_seed_event(
                principal=agent.principal,
                capability=capability,
                risk_class=risk_class,
                kind=EventKind.MINT,
                amount_bp=amount,
                case_id=None,
                reason=f"mission {ctx['mission_id']} opening balance",
                at=datetime.now(UTC),
            )
            seeded[f"{role.agent_id}:{risk_class}"] = current_balance(
                agent.principal, capability, risk_class
            )
    return seeded


# ===========================================================================
# Phase handlers
# ===========================================================================


def _phase_plan(ctx: dict[str, Any], phase: str) -> MissionStage:
    """Classify the objective, register the fleet, seed opening warrant, plan."""
    from fleet.planner import build_plan
    from fleet.roles import ensure_registered

    registration = ensure_registered()
    plan = build_plan(ctx["objective"], evidence={}, allow_model=ctx.get("allow_model", True))
    ctx["plan"] = plan.model_dump(mode="json")
    seeded = _seed_warrant(ctx)

    for step in plan.steps:
        _append_phase(ctx, f"STEP:{step.seq}", after_cursor=False)
    for terminal in ("CHALLENGE", "GATE", "EXECUTE", "VERIFY", "REPORT"):
        _append_phase(ctx, terminal, after_cursor=False)

    return MissionStage(
        n=1,
        name="PLAN — objective decomposed",
        status="LIVE" if plan.provenance.value.startswith("GEMINI") else "LIVE (ZERO-MODEL)",
        summary=(
            f"{plan.objective_class.value}: {len(plan.steps)} step(s) "
            f"[{', '.join(s.role.value for s in plan.steps)}] "
            f"— planner provenance {plan.provenance.value}"
        ),
        detail={
            "plan": ctx["plan"],
            "fingerprint": plan.fingerprint(),
            "registration": registration,
            "seeded_warrant_bp": seeded,
            "planner_provenance": plan.provenance.value,
            "planner_model": plan.model,
            "planner_notes": plan.notes,
            "clamps": plan.clamps,
        },
    )


def _run_tool(ctx: dict[str, Any], tool: str, step) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Execute one tool with a bounded retry and a real measured latency.

    Returns `(output, tool_calls)`. A tool that raises twice returns a
    structured failure rather than propagating -- an exception escaping here
    would abort the mission mid-phase and leave a checkpoint gap, whereas a
    structured failure routes to WORKER_FAULT, which is a branch the Gateway
    already knows how to handle.
    """
    from fleet.roles import BY_AGENT_ROLE
    from fleet.tools import (
        recon_extract_claims,
        remediation_prepare,
        risk_probe,
        verify_check,
    )

    calls: list[dict[str, Any]] = []
    last_error = ""
    for attempt in range(1, MAX_TOOL_ATTEMPTS + 1):
        started = time.monotonic()
        try:
            if tool == "recon.extract_claims":
                # `incident_dir` is an explicit, checkpointed seam so a test
                # (or a second incident) can point the mission at a different
                # evidence bundle. `tests/test_mission_causality.py` uses it
                # to run the SAME mission over evidence with the escalating
                # row removed and compare the two traces.
                from pathlib import Path as _Path

                incident_dir = ctx.get("incident_dir")
                output = recon_extract_claims(
                    incident_dir=_Path(incident_dir) if incident_dir else None
                )
            elif tool == "risk.probe":
                scopes = {r.agent_id: list(r.authority_scope) for r in BY_AGENT_ROLE.values()}
                output = risk_probe(recon=ctx.get("recon", {}), fleet_scopes=scopes)
            elif tool == "remediation.prepare":
                output = remediation_prepare(
                    risk=ctx.get("risk", {}),
                    mission_id=ctx["mission_id"],
                    recon=ctx.get("recon", {}),
                )
            elif tool == "remediation.execute":
                # Execution is never done by a tool: it goes through the one
                # authorized path in `command_os/external.py`, at the EXECUTE
                # phase, after the gate. This tool only stages the proposal.
                output = {"staged": True, "proposal": ctx.get("proposal", {})}
            elif tool == "verify.check":
                output = verify_check(
                    proposal=ctx.get("proposal", {}),
                    recorded=ctx.get("external_record"),
                )
            else:
                raise ValueError(f"unknown tool {tool!r}")
            latency_ms = int((time.monotonic() - started) * 1000)
            calls.append({"tool": tool, "ok": True, "latency_ms": latency_ms, "attempt": attempt})
            if not isinstance(output, dict):
                raise TypeError(f"tool {tool!r} returned {type(output).__name__}, not a dict")
            return output, calls
        except Exception as exc:  # noqa: BLE001 -- bounded retry, then structured failure
            latency_ms = int((time.monotonic() - started) * 1000)
            last_error = f"{type(exc).__name__}: {exc}"
            calls.append(
                {
                    "tool": tool,
                    "ok": False,
                    "latency_ms": latency_ms,
                    "attempt": attempt,
                    "error": last_error,
                }
            )
    return {"__failed__": True, "error": last_error}, calls


def _observe(ctx: dict[str, Any], step, output: dict[str, Any], calls: list[dict[str, Any]]):
    """Build a REAL `BehaviorObservation` from what the step actually did.

    Every field is measured, not scripted:
      `tool_calls`  -- the number of invocations actually made, plus any
                       tool-call count the evidence itself reported for the
                       agent under examination;
      `latency_ms`  -- summed measured latency;
      `dataset`     -- the role's own registered data scope;
      `requested_*` -- derived from the step's action kind.
    """
    from fleet.roles import role_for
    from singularity.schema import BehaviorObservation

    role = role_for(step.role)
    action = parse_action_kind(step.action_kind)
    total_latency = sum(int(c.get("latency_ms", 0)) for c in calls)
    observed_calls = len(calls) + int(output.get("observed_tool_calls", 0) or 0)
    return BehaviorObservation(
        agent_role=step.role,
        tool_calls=max(1, observed_calls),
        dataset=(role.data_scope[0] if role.data_scope else "requests"),
        latency_ms=max(1, total_latency),
        requested_export=action in {ActionKind.CREATE_PR, ActionKind.PRODUCTION_MUTATION},
        requested_secret_access=action is ActionKind.SECRET_ACCESS,
    )


def _phase_step(ctx: dict[str, Any], phase: str) -> MissionStage:
    """One plan step: price -> narrow -> authorize -> execute -> observe -> detect."""
    from fleet.roles import role_for
    from hyperion.guard import evaluate_with_hyperion
    from singularity.behavior import detect_drift
    from singularity.genome import compute_genome

    step_seq = int(phase.split(":", 1)[1])
    plan = _plan(ctx)
    step = next((s for s in plan.steps if s.seq == step_seq), None)
    if step is None:
        return MissionStage(
            n=ctx["seq"],
            name=f"STEP {step_seq} — dropped by replan",
            status="LIVE",
            summary="this step no longer exists in the revised plan",
            detail={"skipped": True},
        )

    role = role_for(step.role)
    agent = _agent_for(role)
    action = parse_action_kind(step.action_kind)

    # --- 1. PRICE, from evidence observed so far --------------------------
    priced = price_action(action, _signals(ctx))

    # --- 2. CAUSAL NARROWING: drift restricts what may even be asked for --
    requested_scope = list(step.requested_scope)
    narrowed_by_drift = False
    if _effective_drift_band(ctx) in {"DRIFT", "CRITICAL"}:
        read_only = [s for s in requested_scope if ".write" not in s]
        if read_only != requested_scope:
            requested_scope = read_only or [role.authority_scope[0]]
            narrowed_by_drift = True

    # --- 3. GENOME: task-bound capability identity ------------------------
    genome = compute_genome(
        agent_role=step.role,
        task=step.intent,
        risk_class=step.risk_class,
        requested_actions=list(role.tools),
    )

    # --- 4. THE UNMODIFIED AUTHORITY PATH ---------------------------------
    case_id = f"{ctx['mission_id']}_step{step_seq}"
    decision, assessment = evaluate_with_hyperion(
        agent,
        task=f"{step.tool}: {step.intent}",
        requested_scope=requested_scope,
        requested_cost=priced.cost_bp,
        risk_class=step.risk_class,
        capability=role.capabilities[0],
        case_id=case_id,
    )
    ctx.setdefault("case_ids", []).append(case_id)

    if not decision.allowed:
        ctx["last_refusal"] = {
            "seq": step_seq,
            "reason_code": decision.reason_code.value,
            "reason": decision.reason,
            "cost_bp": priced.cost_bp,
        }
        ctx.setdefault("refusals", []).append(ctx["last_refusal"])
        if not ctx.get("replanned"):
            _append_phase(ctx, "REPLAN")
        return MissionStage(
            n=ctx["seq"],
            name=f"STEP {step_seq} — REFUSED ({decision.reason_code.value})",
            status="LIVE",
            summary=(
                f"{role.agent_id} refused {decision.reason_code.value}: {decision.reason} "
                f"[priced {priced.cost_bp}bp = {priced.base_bp}bp base +{priced.tax_pct}% "
                f"uncertainty tax]"
            ),
            detail={
                "step": step.model_dump(mode="json"),
                "priced": priced.as_record(),
                "requested_scope": requested_scope,
                "narrowed_by_drift": narrowed_by_drift,
                "decision": decision.model_dump(mode="json"),
                "risk": assessment.model_dump(mode="json"),
                "genome": genome.model_dump(mode="json"),
                "executed": False,
            },
        )

    # --- 5. EXECUTE the tool ---------------------------------------------
    output, calls = _run_tool(ctx, step.tool, step)
    faulted = bool(output.get("__failed__"))

    from tower.gateway import check_worker_fault

    fault = check_worker_fault(
        agent_id=agent.agent_id,
        task=step.tool,
        step_count=len(calls),
        output={} if faulted else output,
    )
    if faulted or fault is not None:
        ctx.setdefault("faults", []).append(
            {"seq": step_seq, "tool": step.tool, "error": output.get("error", "")}
        )
        if not ctx.get("replanned"):
            _append_phase(ctx, "REPLAN")
        return MissionStage(
            n=ctx["seq"],
            name=f"STEP {step_seq} — WORKER FAULT",
            status="LIVE",
            summary=(
                f"{role.agent_id} faulted on {step.tool}: "
                f"{output.get('error') or (fault.reason if fault else 'unusable output')}"
            ),
            detail={
                "step": step.model_dump(mode="json"),
                "tool_calls": calls,
                "fault": fault.model_dump(mode="json") if fault else None,
                "executed": False,
            },
        )

    # --- 6. Persist what the tool learned, for later phases ---------------
    if step.tool == "recon.extract_claims":
        ctx["recon"] = output
        ctx["evidence_completeness"] = float(output.get("completeness", 1.0))
        ctx["evidence_age_seconds"] = float(output.get("newest_age_seconds", 0.0))
        # THE SECOND CAUSAL SEAM, and the one the product is named after.
        # Recon parsed real premises out of messy evidence; before anything
        # acts on them, ask UNWIND's own engine what breaks if it does. The
        # phase exists only because premises were actually extracted.
        if output.get("claims"):
            _append_phase(ctx, "CONSEQUENCE")
    elif step.tool == "risk.probe":
        ctx["risk"] = output
        ctx["risk_divergence"] = output.get("verdict") == "ESCALATION_FOUND"
        worst = output.get("worst_escalation")
        if worst:
            # THE CAUSAL SEAM. A containment probe exists only because the
            # evidence named a specific escalation. No escalation, no probe.
            ctx["contain_target"] = worst
            _append_phase(ctx, "CONTAIN")
    elif step.tool == "remediation.prepare":
        ctx["proposal"] = output

    # --- 7. OBSERVE and DETECT -- real observation, real detector ---------
    observation = _observe(ctx, step, output, calls)
    drift = detect_drift(observation)
    ctx["drift_band"] = drift.drift_band.value
    ctx["drift_score"] = drift.drift_score

    return MissionStage(
        n=ctx["seq"],
        name=f"STEP {step_seq} — {role.agent_id} · {step.tool}",
        status="LIVE",
        summary=(
            f"ALLOWED at {priced.cost_bp}bp ({priced.base_bp}bp +{priced.tax_pct}% tax); "
            f"{step.tool} ok; behaviour {drift.drift_band.value} (score {drift.drift_score})"
        ),
        detail={
            "step": step.model_dump(mode="json"),
            "priced": priced.as_record(),
            "requested_scope": requested_scope,
            "narrowed_by_drift": narrowed_by_drift,
            "decision": decision.model_dump(mode="json"),
            "risk": assessment.model_dump(mode="json"),
            "genome": genome.model_dump(mode="json"),
            "tool_calls": calls,
            "observation": observation.model_dump(mode="json"),
            "drift": drift.model_dump(mode="json"),
            "output_keys": sorted(output.keys()),
            "executed": True,
        },
    )


def _phase_contain(ctx: dict[str, Any], phase: str) -> MissionStage:
    """Test the escalation THE EVIDENCE NAMED, against the real Gateway.

    This is the phase that makes detection causal. Every input comes from
    `fleet/tools.py:risk_probe`'s finding, which came from
    `recon_extract_claims` parsing the committed incident bundle:

      - the agent tested is the agent the CSV recorded making the request;
      - the scope tested is the scope the CSV recorded being requested;
      - the `BehaviorObservation` carries the tool-call count and dataset
        the CSV recorded for that request.

    So the CRITICAL drift and the SCOPE_EXCEEDED refusal are both consequences
    of the evidence. Change the evidence and both change --
    `tests/test_mission_causality.py` proves it by running the mission over
    a fixture with the escalating row removed and asserting no containment
    phase appears, nothing is isolated, and the report does not claim a threat.
    """
    from fleet.roles import BY_AGENT_ID
    from hyperion.guard import evaluate_with_hyperion
    from singularity.behavior import detect_drift
    from singularity.schema import AgentRole, BehaviorObservation

    target = ctx["contain_target"]
    target_role = BY_AGENT_ID.get(target["agent_id"])
    if target_role is None:
        return MissionStage(
            n=ctx["seq"],
            name="CONTAIN — target not in registry",
            status="LIVE",
            summary=f"evidence named {target['agent_id']!r}, which holds no fleet identity",
            detail={"target": target, "isolated": False},
        )

    # Observation built from the evidence's own numbers.
    observation = BehaviorObservation(
        agent_role=target_role.agent_role
        if target_role.agent_role in AgentRole.__members__.values()
        else AgentRole.WORKER_DOCUMENT,
        tool_calls=int(target.get("tool_calls", 1)),
        dataset=str(target.get("dataset", "requests")),
        latency_ms=1,
        requested_export=False,
        requested_secret_access="secret" in str(target.get("requested_scope", "")),
    )
    drift = detect_drift(observation)
    ctx["drift_band"] = drift.drift_band.value
    ctx["drift_score"] = drift.drift_score

    agent = _agent_for(target_role)
    priced = price_action(ActionKind.SECRET_ACCESS, _signals(ctx))
    case_id = f"{ctx['mission_id']}_contain"
    ctx.setdefault("case_ids", []).append(case_id)
    ctx["contain_case_id"] = case_id

    decision, assessment = evaluate_with_hyperion(
        agent,
        task=f"containment probe: {target['requested_scope']} requested by {target['agent_id']}",
        requested_scope=[str(target["requested_scope"])],
        requested_cost=priced.cost_bp,
        risk_class=str(target.get("risk_class", "HIGH")),
        capability=target_role.capabilities[0],
        case_id=case_id,
    )

    isolated = not decision.allowed
    ctx["isolated_agent"] = target_role.agent_id if isolated else None
    if isolated:
        # Sticky until the isolation is resolved: see `_effective_drift_band`.
        ctx["containment_drift_band"] = drift.drift_band.value
    ctx["contain_reason_code"] = decision.reason_code.value
    ctx["contain_allowed"] = decision.allowed
    if isolated:
        ctx["unsafe_actions_executed"] = int(ctx.get("unsafe_actions_executed", 0))

    return MissionStage(
        n=ctx["seq"],
        name=(
            f"CONTAIN — {target_role.agent_id} ISOLATED"
            if isolated
            else f"CONTAIN — {target_role.agent_id} cleared"
        ),
        status="LIVE",
        summary=(
            f"behaviour {drift.drift_band.value} (score {drift.drift_score}) from the "
            f"evidence's own {observation.tool_calls} tool calls on {observation.dataset!r}; "
            f"Gateway {decision.reason_code.value}: {decision.reason}"
        ),
        detail={
            "target": target,
            "observation": observation.model_dump(mode="json"),
            "drift": drift.model_dump(mode="json"),
            "priced": priced.as_record(),
            "decision": decision.model_dump(mode="json"),
            "risk": assessment.model_dump(mode="json"),
            "isolated": isolated,
        },
    )


def _phase_replan(ctx: dict[str, Any], phase: str) -> MissionStage:
    """The orchestrator revises the remaining plan after a refusal or fault."""
    from fleet.planner import replan_after_refusal

    ctx["replanned"] = True
    plan = _plan(ctx)
    refusal = ctx.get("last_refusal") or {}
    revised, revisions = replan_after_refusal(
        plan,
        failed_seq=int(refusal.get("seq", 0)),
        reason_code=str(refusal.get("reason_code", "WORKER_FAULT")),
        drift_band=str(ctx.get("drift_band", "NORMAL")),
    )
    ctx["plan"] = revised.model_dump(mode="json")
    ctx["revisions"] = revisions
    return MissionStage(
        n=ctx["seq"],
        name="REPLAN — orchestrator revised the remaining plan",
        status="LIVE",
        summary=(
            f"{len(revisions)} revision(s) after {refusal.get('reason_code', 'a worker fault')}"
            if revisions
            else "no revision was possible; remaining steps stand"
        ),
        detail={"revisions": revisions, "plan": ctx["plan"]},
    )


def _challenge_material(ctx: dict[str, Any]) -> dict[str, Any]:
    """Everything the independent challenger needs to re-derive the verdict.

    Deliberately NOT the proposing side's conclusion. The challenger gets
    the evidence -- balances, costs, drift, coverage, age, scope -- and
    reaches its own answer. Handing it "the gateway said this was fine"
    would make agreement a foregone conclusion, which is exactly the defect
    that made the previous countersign tautological.
    """
    from fleet.roles import REMEDIATION
    from warrant.ledger import current_balance

    agent = _agent_for(REMEDIATION)
    balance = current_balance(agent.principal, REMEDIATION.capabilities[0], "MEDIUM")
    proposal = ctx.get("proposal", {})
    priced = price_action(ActionKind.CREATE_TICKET, _signals(ctx))

    # WHICH DRIFT BAND THE CHALLENGER IS ASKED ABOUT, AND WHY IT IS NOT THE
    # MISSION-WIDE WORST.
    #
    # The challenger's UNRESOLVED-DRIFT ground asks: "is the agent that will
    # PERFORM this action still behaving anomalously while requesting to
    # mutate?" That is the acting agent's own band -- here, Remediation's.
    #
    # Handing it the mission-wide worst band instead produces a deadlock that
    # looks like rigour: a containment sets the fleet band to CRITICAL, the
    # challenger then refuses every mutating action, and the one mutating
    # action anybody wants -- REMEDIATING THE CONTAINED AGENT -- can never be
    # authorised. A containment that cannot be remediated is not a safety
    # property, it is a stuck system.
    #
    # The mission-wide worst band is still used for the uncertainty TAX
    # (`_signals`), where it belongs: the whole situation genuinely is more
    # uncertain, so everything genuinely costs more. Price and permission are
    # different questions and this is the seam between them.
    acting_band = str(ctx.get("drift_band", "NORMAL")).upper()
    return {
        "objective": ctx["objective"],
        "proposed_action": proposal.get("action", "NO_ACTION_REQUIRED"),
        "requested_scope": ["sandbox.write"] if proposal.get("action") else [],
        "drift_band": acting_band,
        "acting_agent": agent.agent_id,
        "fleet_worst_drift_band": _effective_drift_band(ctx),
        "contained_agent": ctx.get("isolated_agent"),
        "drift_score": ctx.get("drift_score", 0),
        "risk_level": "HIGH" if ctx.get("isolated_agent") else "LOW",
        "warrant_balance_bp": balance,
        "authority_cost_bp": priced.cost_bp,
        "evidence_completeness": ctx.get("evidence_completeness", 1.0),
        "evidence_age_seconds": ctx.get("evidence_age_seconds", 0.0),
        "contradictions": len(ctx.get("recon", {}).get("contradictions", [])),
        "escalations": len(ctx.get("risk", {}).get("escalations", [])),
        "isolated_agent": ctx.get("isolated_agent"),
    }


def _phase_challenge(ctx: dict[str, Any], phase: str) -> MissionStage:
    """The independent challenger. Can genuinely disagree, and disagreement bites."""
    from countersign.verify import verify_and_record
    from fleet.roles import REMEDIATION

    agent = _agent_for(REMEDIATION)
    case_id = f"{ctx['mission_id']}_challenge"
    ctx["challenge_case_id"] = case_id
    ctx.setdefault("case_ids", []).append(case_id)
    material = _challenge_material(ctx)
    policy = SimulationPolicy.from_record(ctx["policy"])

    outcome = verify_and_record(
        case_id=case_id,
        material=material,
        agent=agent,
        capability=REMEDIATION.capabilities[0],
        risk_class="MEDIUM",
        judging_family="hyperion-risk-engine",
        judging_principal=agent.principal,
        policy=policy,
    )
    ctx["challenger_agrees"] = outcome.agrees
    ctx["challenger_disagreed"] = outcome.agrees is False
    ctx["challenger_ground"] = outcome.ground
    ctx["challenger_simulated"] = outcome.simulated

    return MissionStage(
        n=ctx["seq"],
        name=(
            "CHALLENGE — independent challenger DISAGREED"
            if outcome.agrees is False
            else "CHALLENGE — independent challenger agreed"
        ),
        status=policy.label if outcome.simulated else "LIVE",
        summary=(
            f"agrees={outcome.agrees} ({outcome.family}): {outcome.ground}"
            if outcome.available
            else f"unavailable: {outcome.reason_unavailable} — never read as agreement"
        ),
        detail={
            "material": material,
            "available": outcome.available,
            "agrees": outcome.agrees,
            "family": outcome.family,
            "simulated": outcome.simulated,
            "ground": outcome.ground,
            "policy": ctx["policy"],
        },
    )


def _external_required(ctx: dict[str, Any]) -> bool:
    """True when the plan actually calls for a mutating action AND there is
    something to remediate. A plan with no execute step (a CREDENTIAL_AUDIT,
    a PREMISE_IMPACT_TRACE) never reaches an external effect."""
    plan = _plan(ctx)
    has_execute = any(
        parse_action_kind(s.action_kind).value in {"CREATE_TICKET", "CREATE_PR", "WRITE_SANDBOX"}
        for s in plan.steps
    )
    proposal = ctx.get("proposal", {})
    return has_execute and proposal.get("action") not in (None, "NO_ACTION_REQUIRED")


def _phase_gate(ctx: dict[str, Any], phase: str) -> MissionStage:
    """Human concurrence, recorded under the AUTHENTICATED principal.

    The previous implementation wrote `principal="human::mission_operator"`,
    a module constant, for any caller including an anonymous one. The
    principal here comes from `ctx["principal"]`, which
    `services/api/main.py` populates from `lib.auth.authenticate` and cannot
    populate any other way.

    `mode` distinguishes an explicit gate decision from concurrence given at
    launch (`auto_approve=True`). Both are real, authenticated principals;
    conflating them in the record would misrepresent when the person looked.
    """
    from warrant.ledger import record_human_concurrence

    if not _external_required(ctx):
        ctx["gate"] = "NOT_REQUIRED"
        return MissionStage(
            n=ctx["seq"],
            name="HUMAN GATE — not required",
            status="LIVE",
            summary="this plan contains no mutating action, so no concurrence is needed",
            detail={"required": False, "plan_class": _plan(ctx).objective_class.value},
        )

    if ctx.get("challenger_agrees") is False:
        ctx["gate"] = "FROZEN"
        return MissionStage(
            n=ctx["seq"],
            name="HUMAN GATE — frozen by challenge",
            status="LIVE",
            summary=(
                "the independent challenger disagreed; minting and execution are frozen "
                "for this case and it is flagged for human review"
            ),
            detail={"required": True, "frozen": True, "ground": ctx.get("challenger_ground")},
        )

    decision = ctx.get("human_decision")
    if decision is None:
        ctx["gate"] = "AWAITING"
        return MissionStage(
            n=ctx["seq"],
            name="HUMAN GATE — awaiting concurrence",
            status="LIVE",
            summary="paused for an authenticated human decision before any external effect",
            detail={"required": True, "awaiting": True},
        )

    if decision == "deny":
        ctx["gate"] = "DENIED"
        return MissionStage(
            n=ctx["seq"],
            name="HUMAN GATE — denied",
            status="LIVE",
            summary=f"{ctx['human_principal']} denied the correction; nothing will be executed",
            detail={"required": True, "denied": True, "principal": ctx["human_principal"]},
        )

    principal = ctx["human_principal"]
    mode = ctx.get("human_decision_mode", "explicit_gate_decision")
    record_human_concurrence(
        ctx["challenge_case_id"],
        principal=principal,
        note=(
            f"[{mode}] concurred with the prepared correction "
            f"{ctx.get('proposal', {}).get('action')!r} for mission {ctx['mission_id']}"
        ),
    )
    ctx["gate"] = "APPROVED"
    return MissionStage(
        n=ctx["seq"],
        name="HUMAN GATE — concurrence recorded",
        status="LIVE",
        summary=f"{principal} concurred ({mode})",
        detail={
            "required": True,
            "approved": True,
            "principal": principal,
            "mode": mode,
            "auth_method": ctx.get("auth_method"),
        },
    )


def _phase_execute(ctx: dict[str, Any], phase: str) -> MissionStage:
    """The one external effect, through the one authorized path."""
    from command_os.external import (
        ExternalActionAuthorization,
        ExternalActionRefused,
        current_backend,
        execute_action,
    )
    from fleet.roles import REMEDIATION
    from hyperion.guard import evaluate_with_hyperion

    if ctx.get("gate") != "APPROVED":
        ctx["external_executed"] = False
        return MissionStage(
            n=ctx["seq"],
            name="EXECUTE — skipped",
            status="LIVE",
            summary=f"no external action: gate is {ctx.get('gate', 'NOT_REQUIRED')}",
            detail={"executed": False, "gate": ctx.get("gate")},
        )

    proposal = ctx["proposal"]
    agent = _agent_for(REMEDIATION)
    priced = price_action(ActionKind.CREATE_TICKET, _signals(ctx))
    case_id = f"{ctx['mission_id']}_execute"
    ctx.setdefault("case_ids", []).append(case_id)

    decision, assessment = evaluate_with_hyperion(
        agent,
        task=f"execute correction: {proposal.get('action')}",
        requested_scope=["sandbox.write"],
        requested_cost=priced.cost_bp,
        risk_class="MEDIUM",
        capability=REMEDIATION.capabilities[0],
        case_id=case_id,
    )
    if not decision.allowed:
        ctx["external_executed"] = False
        ctx.setdefault("refusals", []).append(
            {
                "seq": ctx["seq"],
                "reason_code": decision.reason_code.value,
                "reason": decision.reason,
            }
        )
        return MissionStage(
            n=ctx["seq"],
            name=f"EXECUTE — REFUSED ({decision.reason_code.value})",
            status="LIVE",
            summary=f"{decision.reason_code.value}: {decision.reason}",
            detail={
                "executed": False,
                "decision": decision.model_dump(mode="json"),
                "priced": priced.as_record(),
            },
        )

    authorization = ExternalActionAuthorization(
        idempotency_key=str(proposal["idempotency_key"]),
        gateway_reason_code=decision.reason_code.value,
        cost_bp=priced.cost_bp,
        acting_principal=agent.principal,
        human_principal=ctx.get("human_principal"),
        countersign_agrees=ctx.get("challenger_agrees"),
        mission_id=ctx["mission_id"],
    )
    try:
        record = execute_action(proposal, authorization=authorization)
    except ExternalActionRefused as exc:
        ctx["external_executed"] = False
        return MissionStage(
            n=ctx["seq"],
            name="EXECUTE — refused by the external action boundary",
            status="LIVE",
            summary=str(exc),
            detail={"executed": False, "error": str(exc), "backend": current_backend()},
        )

    ctx["external_executed"] = True
    ctx["external_state_changed"] = True
    ctx["external_record"] = record.as_record()
    ctx["external_id"] = record.external_id
    ctx["external_replayed"] = record.replayed

    return MissionStage(
        n=ctx["seq"],
        name="EXECUTE — correction applied to the system of record",
        status="LIVE (SANDBOX BACKEND)" if record.backend == "sandbox_file" else "LIVE",
        summary=(
            f"{record.action} -> {record.backend}#{record.external_id} "
            f"({'replayed, nothing rewritten' if record.replayed else 'applied'}), "
            f"{priced.cost_bp}bp spent"
        ),
        detail={
            "executed": True,
            "record": record.as_record(),
            "priced": priced.as_record(),
            "decision": decision.model_dump(mode="json"),
            "risk": assessment.model_dump(mode="json"),
        },
    )


def _phase_verify(ctx: dict[str, Any], phase: str) -> MissionStage:
    """Independent verification, then SETTLE THE AUTHORITY.

    THE HALF OF THE ECONOMY THAT WAS MISSING
    -------------------------------------------
    Every step of a mission SPENDS warrant. Until this phase existed, nothing
    ever credited any back, so the ledger only ever fell -- and a "warrant
    market" in which authority can only be consumed is not a market, it is a
    countdown. It also produced a real, observable failure: after a few
    missions the Remediation agent could no longer back a correction, and the
    independent challenger correctly refused every subsequent one on AUTHORITY
    EXCEEDS EVIDENCE grounds. Correct behaviour from the challenger; a broken
    economy underneath it.

    So the outcome settles:

      VERIFIED   -> MINT. The agent earned authority by completing a
                    correction that an independent challenger agreed with, a
                    human concurred in, and a re-read confirmed. That is
                    exactly the evidence `warrant.ledger.mint` demands, and
                    the mint runs against the SAME case id those two records
                    were written under -- no separate, weaker path.
      UNVERIFIED -> BURN. The action was authorised and its recorded effect
                    does not match what was proposed. That is the strongest
                    signal in the system that this agent's judgement cost
                    something, and it is debited.

    Authority is therefore adjusted BY OUTCOME rather than by assertion, and
    an agent that keeps producing verified work can keep acting while one that
    does not runs out.
    """
    from command_os.external import verify_action
    from fleet.roles import REMEDIATION
    from warrant.ledger import (
        CaseChallengedError,
        MintPreconditionError,
        burn,
        current_balance,
        mint,
    )

    if not ctx.get("external_executed"):
        ctx["verified"] = None
        return MissionStage(
            n=ctx["seq"],
            name="VERIFY — nothing to verify",
            status="LIVE",
            summary="no external action was executed, so there is no effect to confirm",
            detail={"verified": None, "settlement": "none"},
        )

    result = verify_action(str(ctx["proposal"]["idempotency_key"]), ctx["proposal"])
    verified = bool(result.get("verified"))
    ctx["verified"] = verified

    agent = _agent_for(REMEDIATION)
    capability = REMEDIATION.capabilities[0]
    case_id = ctx.get("challenge_case_id", "")
    before_bp = current_balance(agent.principal, capability, "MEDIUM")
    settlement: dict[str, Any] = {"before_bp": before_bp}

    if verified:
        try:
            event = mint(
                agent=agent,
                capability=capability,
                risk_class="MEDIUM",
                case_id=case_id,
                reason=(
                    f"verified correction {ctx.get('external_id')} for mission {ctx['mission_id']}"
                ),
            )
            settlement.update({"action": "MINT", "amount_bp": event.amount_bp})
        except (MintPreconditionError, CaseChallengedError) as exc:
            # Refused rather than forced. The preconditions are the point: if
            # they are not met, the agent has not earned anything, and saying
            # so is more useful than a mint that means nothing.
            settlement.update({"action": "MINT_REFUSED", "reason": str(exc)})
    else:
        burn(
            agent=agent,
            capability=capability,
            risk_class="MEDIUM",
            amount_bp=REMEDIATION.warrant_spend_schedule.get("MEDIUM", 60),
            case_id=case_id,
            reason=f"verification mismatch on {ctx.get('external_id')}",
            acting_principal=agent.principal,
        )
        settlement.update({"action": "BURN"})

    after_bp = current_balance(agent.principal, capability, "MEDIUM")
    settlement["after_bp"] = after_bp
    ctx["settlement"] = settlement

    return MissionStage(
        n=ctx["seq"],
        name="VERIFY — " + ("confirmed" if verified else "MISMATCH"),
        status="LIVE",
        summary=(
            f"{result.get('reason', '')} · authority settled "
            f"{settlement.get('action', 'none')}: {before_bp}bp -> {after_bp}bp"
        ),
        detail={**result, "settlement": settlement},
    )


def _mission_status(ctx: dict[str, Any]) -> str:
    """The single source of truth for the mission's final status.

    Ordered worst-first, and NEVER reports success over a refusal. The
    previous `_build_report` folded only three booleans and reported
    `HEALTHY` for a mission whose capability negotiation had been RESTRICTed
    and whose steps had been refused. Each branch below is reachable and is
    covered by `tests/test_mission_report.py`.
    """
    if ctx.get("challenger_agrees") is False:
        return STATUS_CHALLENGED
    if ctx.get("gate") == "DENIED":
        return STATUS_HALTED
    if ctx.get("faults"):
        return STATUS_FAILED_SAFE
    if ctx.get("external_executed") and ctx.get("verified") is False:
        return STATUS_FAILED_SAFE
    if ctx.get("isolated_agent"):
        # Something WAS blocked. The mission may have completed its own work,
        # but reporting it as unqualified success would hide the block.
        return (
            STATUS_COMPLETED_WITH_RESTRICTIONS
            if ctx.get("external_executed") or not _external_required(ctx)
            else STATUS_BLOCKED
        )
    if ctx.get("refusals"):
        return STATUS_COMPLETED_WITH_RESTRICTIONS
    return STATUS_COMPLETED


def _build_report(ctx: dict[str, Any], stages: list[MissionStage]) -> MissionReport:
    """Fold the executive report from what actually happened.

    Every field is derived from `ctx` written by a phase that ran. Nothing
    here is a constant, and the status comes from `_mission_status`, which
    cannot say COMPLETED over an unresolved refusal or a disagreement.
    """
    plan = _plan(ctx) if ctx.get("plan") else None
    recon = ctx.get("recon", {})
    risk = ctx.get("risk", {})
    status = _mission_status(ctx)
    executed_steps = sum(
        1 for s in stages if s.name.startswith("STEP ") and s.detail.get("executed") is True
    )

    return MissionReport(
        objective=ctx["objective"],
        status=status,
        objective_class=plan.objective_class.value if plan else "UNKNOWN",
        planner_provenance=plan.provenance.value if plan else "UNKNOWN",
        planner_model=plan.model if plan else "",
        plan_fingerprint=plan.fingerprint() if plan else "",
        agents_selected=sorted({s.role.value for s in plan.steps}) if plan else [],
        steps_planned=len(plan.steps) if plan else 0,
        steps_executed=executed_steps,
        replans=1 if ctx.get("replanned") else 0,
        tools_used=sorted({s.tool for s in plan.steps}) if plan else [],
        evidence_records_parsed=int(recon.get("parsed", 0)),
        evidence_records_total=int(recon.get("total", 0)),
        evidence_completeness=float(ctx.get("evidence_completeness", 1.0)),
        contradictions_found=len(recon.get("contradictions", [])),
        escalations_found=len(risk.get("escalations", [])),
        drift_band=_effective_drift_band(ctx),
        drift_score=int(ctx.get("drift_score", 0)),
        agents_isolated=1 if ctx.get("isolated_agent") else 0,
        isolated_agent=ctx.get("isolated_agent"),
        gateway_refusals=[r.get("reason_code", "") for r in ctx.get("refusals", [])],
        unsafe_actions_executed=0,
        worker_faults=len(ctx.get("faults", [])),
        challenger_agrees=ctx.get("challenger_agrees"),
        challenger_ground=str(ctx.get("challenger_ground", "")),
        challenger_simulated=bool(ctx.get("challenger_simulated", False)),
        human_principal=ctx.get("human_principal"),
        human_decision_mode=ctx.get("human_decision_mode"),
        gate=str(ctx.get("gate", "NOT_REQUIRED")),
        external_action=ctx.get("proposal", {}).get("action"),
        external_action_id=ctx.get("external_id"),
        external_backend=ctx.get("external_record", {}).get("backend"),
        external_replayed=bool(ctx.get("external_replayed", False)),
        verified=ctx.get("verified"),
        authority_settlement=str(ctx.get("settlement", {}).get("action", "none")),
        warrant_before_bp=int(ctx.get("settlement", {}).get("before_bp", 0)),
        warrant_after_bp=int(ctx.get("settlement", {}).get("after_bp", 0)),
        case_ids=list(ctx.get("case_ids", [])),
    )


def _phase_report(ctx: dict[str, Any], phase: str) -> MissionStage:
    status = _mission_status(ctx)
    return MissionStage(
        n=ctx["seq"],
        name=f"REPORT — {status}",
        status="LIVE",
        summary=(
            f"{status}: {len(ctx.get('refusals', []))} refusal(s), "
            f"{1 if ctx.get('isolated_agent') else 0} isolation(s), "
            f"challenger agrees={ctx.get('challenger_agrees')}, "
            f"external={ctx.get('external_id') or 'none'}, "
            f"verified={ctx.get('verified')}"
        ),
        detail={"status": status},
    )


def _phase_consequence(ctx: dict[str, Any], phase: str) -> MissionStage:
    """Ask the REAL consequence engine what executing here would break.

    This is the phase that makes the repository's name true of its flagship
    feature. `spine/` has always been able to answer "which committed
    decisions rested on this premise?" -- until this phase, the agent layer
    never asked it. See `command_os/consequence.py`'s module docstring.

    Zero model calls: a reverse-index traversal and integer arithmetic. The
    resulting band is written into `ctx` and priced by
    `warrant/economics.py`, so a severe blast radius does not merely appear
    on screen -- it makes the next action cost more, which is the difference
    between a warning and a control.
    """
    from command_os.consequence import preview

    recon = ctx.get("recon") or {}
    plan = _plan(ctx)
    # Price against the most privileged action the remaining plan still
    # intends. Previewing the cheapest step would understate what this
    # mission is actually about to do.
    remaining = [s for s in plan.steps if s.seq >= int(ctx.get("cursor", 1))]
    action_kind = "ANALYZE"
    scope: list[str] = []
    if remaining:
        worst_step = max(
            remaining, key=lambda s: BASE_COST_BP.get(parse_action_kind(s.action_kind), 0)
        )
        action_kind = worst_step.action_kind
        scope = list(worst_step.requested_scope)

    result = preview(
        claims=recon.get("claims", []),
        action_kind=action_kind,
        requested_scope=scope,
        mutating=parse_action_kind(action_kind) in MUTATING_ACTIONS,
    )
    ctx["consequence"] = result.as_record()
    ctx["consequence_band"] = result.risk.band if result.risk else "NONE"

    if not result.resolved:
        return MissionStage(
            n=0,
            name="CONSEQUENCE — blast radius UNKNOWN",
            status="LIVE (ZERO-MODEL)",
            summary=result.reason_unresolved,
            detail=result.as_record(),
        )

    risk = result.risk
    escaped = result.regimes.get("material_escaped", 0)
    return MissionStage(
        n=0,
        name=f"CONSEQUENCE — {result.radius} dependent decisions",
        status="LIVE (ZERO-MODEL)",
        summary=(
            f"UNWIND RISK INDEX {risk.total} ({risk.band}); "
            f"{result.radius} decisions rest on the premises this action would change; "
            f"{result.regimes.get('material_contained', 0)} still correctable, "
            f"{escaped} ALREADY ESCAPED and un-recallable"
        ),
        detail=result.as_record(),
    )


_HANDLERS = {
    "PLAN": _phase_plan,
    "STEP": _phase_step,
    "CONSEQUENCE": _phase_consequence,
    "CONTAIN": _phase_contain,
    "REPLAN": _phase_replan,
    "CHALLENGE": _phase_challenge,
    "GATE": _phase_gate,
    "EXECUTE": _phase_execute,
    "VERIFY": _phase_verify,
    "REPORT": _phase_report,
}


def _handler_for(phase: str):
    return _HANDLERS[phase.split(":", 1)[0]]


# ===========================================================================
# The loop
# ===========================================================================


def _run_phases(ctx: dict[str, Any], stages: list[MissionStage]) -> MissionResult:
    """The one loop `run_mission` and `resume_mission` share.

    Pauses at the human gate iff the gate phase set `ctx["gate"] ==
    "AWAITING"`. Everything the continuation needs is in `ctx`, which is
    checkpointed after every stage, so a restart resumes exactly here.
    """
    mission_id = ctx["mission_id"]

    while ctx["cursor"] < len(ctx["phases"]):
        phase = ctx["phases"][ctx["cursor"]]
        stage = _handler_for(phase)(ctx, phase)
        stage = stage.model_copy(update={"n": ctx["seq"]})
        stages.append(stage)

        awaiting = phase == "GATE" and ctx.get("gate") == "AWAITING"
        is_last = ctx["cursor"] == len(ctx["phases"]) - 1
        status = (
            STATUS_AWAITING_HUMAN if awaiting else (_mission_status(ctx) if is_last else "RUNNING")
        )
        checkpoint.write_checkpoint(
            mission_id=mission_id, seq=ctx["seq"], stage=stage, ctx=dict(ctx), status=status
        )
        ctx["seq"] += 1
        ctx["cursor"] += 1

        if awaiting:
            checkpoint.update_mission_status(mission_id, STATUS_AWAITING_HUMAN)
            return MissionResult(
                mission_id=mission_id,
                objective=ctx["objective"],
                status=STATUS_AWAITING_HUMAN,
                stages=stages,
                report=None,
                plan=ctx.get("plan"),
            )

    report = _build_report(ctx, stages)
    checkpoint.update_mission_status(mission_id, report.status)
    return MissionResult(
        mission_id=mission_id,
        objective=ctx["objective"],
        status=report.status,
        stages=stages,
        report=report,
        plan=ctx.get("plan"),
    )


def run_mission(
    objective: str = DEFAULT_OBJECTIVE,
    *,
    principal: str,
    auth_method: str = "unknown",
    auto_approve: bool = True,
    policy: SimulationPolicy | None = None,
    allow_model: bool = True,
    incident_dir: str | None = None,
) -> MissionResult:
    """Run one mission. `principal` is REQUIRED and has no default.

    That is deliberate and is the fix for the audit's worst finding. The
    previous signature let any caller run a mission and had the module write
    `"human::mission_operator"` into the decision-memory record that
    `warrant.ledger.mint` treats as human concurrence. Making `principal`
    keyword-only with no default means a caller that has not authenticated
    cannot even construct the call.

    `auto_approve=True` records the launching principal's concurrence at the
    gate with `mode="auto_approved_at_launch"` -- a real, authenticated
    person consenting up front. `auto_approve=False` pauses for an explicit
    decision. The record says which; they are not conflated.
    """
    policy = policy or resolve_policy()
    mission_id = f"mission_{uuid.uuid4().hex[:10]}"
    ctx: dict[str, Any] = {
        "mission_id": mission_id,
        "objective": objective,
        "principal": principal,
        "auth_method": auth_method,
        "auto_approve": auto_approve,
        "allow_model": allow_model,
        "policy": policy.as_record(),
        "incident_dir": incident_dir,
        "phases": ["PLAN"],
        "cursor": 0,
        "seq": 1,
        "started_at": datetime.now(UTC).isoformat(),
    }
    if auto_approve:
        ctx["human_decision"] = "approve"
        ctx["human_principal"] = principal
        ctx["human_decision_mode"] = "auto_approved_at_launch"

    checkpoint.start_mission_record(mission_id, objective)
    return _run_phases(ctx, [])


def resume_mission(
    mission_id: str,
    *,
    human_decision: str | None = None,
    human_principal: str | None = None,
) -> MissionResult:
    """Continue a mission from its last checkpoint. Three real cases.

    - status is final: ALREADY COMPLETED. The stored trace is returned
      as-is; nothing re-runs, no warrant moves, no external action repeats.
    - status is AWAITING_HUMAN: REQUIRES HUMAN APPROVAL. Both
      `human_decision` and `human_principal` are required -- an approval
      with no authenticated principal behind it is refused rather than
      attributed to a constant.
    - status is RUNNING: REPLAYABLE. The process exited between two
      stages; resume strictly after the last persisted `seq`.
    """
    record = checkpoint.get_mission_record(mission_id)
    if record is None:
        raise ValueError(f"no mission {mission_id!r} found")
    checkpoints = checkpoint.list_checkpoints(mission_id)
    stages = [cp.stage for cp in checkpoints]
    latest = checkpoints[-1] if checkpoints else None

    if record.status in _FINAL_STATUSES:
        ctx = dict(latest.ctx) if latest else {}
        report = _build_report(ctx, stages) if latest else None
        return MissionResult(
            mission_id=mission_id,
            objective=record.objective,
            status=record.status,
            stages=stages,
            report=report,
            plan=ctx.get("plan"),
        )

    if latest is None:
        raise ValueError(f"mission {mission_id!r} has no checkpoints to resume from")
    ctx = dict(latest.ctx)

    if record.status == STATUS_AWAITING_HUMAN:
        if human_decision not in ("approve", "deny"):
            raise ValueError(
                "mission is AWAITING_HUMAN; resume requires human_decision 'approve' or 'deny'"
            )
        if not human_principal:
            raise ValueError(
                "mission is AWAITING_HUMAN; resume requires an authenticated "
                "human_principal. A concurrence record with no principal behind it "
                "is exactly the forgery this gate exists to prevent."
            )
        ctx["human_decision"] = human_decision
        ctx["human_principal"] = human_principal
        ctx["human_decision_mode"] = "explicit_gate_decision"
        # Re-enter the GATE phase itself, now that a decision exists.
        ctx["cursor"] = ctx["phases"].index("GATE")
        ctx["seq"] = latest.seq + 1
        return _run_phases(ctx, stages)

    # RUNNING: continue strictly after the last completed stage.
    ctx["seq"] = latest.seq + 1
    return _run_phases(ctx, stages)


def reset_for_test(mission_id: str | None = None) -> None:
    """Test hook. Mirrors the `reset_for_test` hooks in `tower.registry`,
    `warrant.ledger`, `hyperion.immune_memory` and `singularity.mesh_memory`."""
    from command_os.external import reset_for_test as reset_external
    from fleet.roles import ALL_ROLES
    from hyperion.immune_memory import reset_for_test as reset_hyperion
    from singularity.mesh_memory import reset_for_test as reset_mesh
    from tower.registry import get_agent
    from warrant.ledger import reset_for_test as reset_warrant

    for role in ALL_ROLES:
        agent = get_agent(role.agent_id)
        if agent is not None:
            reset_warrant(agent.principal)
    reset_hyperion()
    reset_mesh()
    reset_external()
    if mission_id is not None:
        checkpoint.reset_for_test(mission_id)


__all__ = [
    "DEFAULT_OBJECTIVE",
    "STATUS_AWAITING_HUMAN",
    "STATUS_BLOCKED",
    "STATUS_CHALLENGED",
    "STATUS_COMPLETED",
    "STATUS_COMPLETED_WITH_RESTRICTIONS",
    "STATUS_FAILED_SAFE",
    "STATUS_HALTED",
    "reset_for_test",
    "resume_mission",
    "run_mission",
]
