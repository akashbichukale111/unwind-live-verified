"""Output contracts: what a worker must return before the mission believes it.

THE GAP THIS CLOSES, STATED PLAINLY
--------------------------------------
`tower/gateway.py:check_worker_fault` already rejects a worker whose output
is not a `dict`. That catches free text and it catches `None`. It does not
catch the failure that actually matters for an agent fleet: **output with
the right shape and the wrong contents**. A worker that returns

    {"parsed": 97, "total": 3, "completeness": 1.0, "claims": [...]}

is a `dict`, passes `check_worker_fault`, and would have flowed straight
into `warrant/economics.py`'s uncertainty tax as *perfect evidence* -- the
exact number that decides how expensive the next action is. There is no
model in this repository capable of emitting that today; the point is that
`fleet/agents.py` exists so that one day there is, and a boundary that only
exists once a model is wired in is a boundary nobody has tested.

So every tool declares a contract, and the contract is checked in
`command_os/mission.py` BEFORE the output is allowed to write anything into
the mission context.

THE THREE KINDS OF CHECK, AND WHY THE THIRD IS THE ONE THAT MATTERS
----------------------------------------------------------------------
1. **SHAPE** -- required keys present, of the declared type. Catches a
   truncated or renamed result.
2. **SELF-CONSISTENCY** -- the numbers a result reports must agree with each
   other. `completeness` must equal `parsed / total` to within a rounding
   step, because a coverage figure that does not follow from the counts
   beside it is a self-report, and a self-report is the one input this
   system never accepts (`command_os/trust.py` states the same rule for
   trust, `settle/loadrating.py` for source weight).
3. **GROUNDING IN THE INPUT** -- a finding may only name entities that were
   present in what the worker was given. `risk.probe` may not report an
   escalation by an `agent_id` that appears nowhere in recon's parsed
   requests; `remediation.prepare` may not target a `request_id` that no
   evidence mentions. This is the check that has no cheaper substitute: it
   is the difference between "the output looks right" and "the output is
   about the evidence".

WHAT A VIOLATION DOES
------------------------
Nothing silent. `validate_tool_output` returns a list of violations; the
mission turns a non-empty list into a `WORKER_FAULT` stage with the
violations recorded in the checkpoint, the output is DISCARDED rather than
merged into `ctx`, and the orchestrator replans. A rejected result can
therefore never price an action, never reach the Gateway, and never reach
`command_os/external.py`.

NO MODEL, NO CLOCK, NO NETWORK
---------------------------------
Pure functions of `(tool, output, inputs)`. `tests/test_fleet.py::test_fleet_tools_and_roles_import_no_model_client` walks
this module's import graph with the rest of the deterministic half of the
fleet.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

#: Tolerance for the derived-number check. `recon_extract_claims` rounds
#: `completeness` to 4 decimal places, so anything inside half a unit of the
#: last kept place is the same number and anything outside it is a different
#: claim about the evidence.
_DERIVED_TOLERANCE = 5e-5


@dataclass(frozen=True)
class ContractViolation:
    """One named failure. Carries the check that failed so a checkpoint reads
    as a diagnosis rather than as `False`."""

    tool: str
    check: str
    field: str
    detail: str

    def as_record(self) -> dict[str, str]:
        return {
            "tool": self.tool,
            "check": self.check,
            "field": self.field,
            "detail": self.detail,
        }


#: Required key -> accepted python type(s), per tool. Deliberately a plain
#: table rather than a pydantic model: the tools return open dicts carrying
#: diagnostics that legitimately vary, and a closed model would force every
#: new diagnostic field through a schema change. What must not vary is the
#: load-bearing subset, which is exactly what this table names.
_SHAPE: dict[str, dict[str, tuple[type, ...]]] = {
    "recon.extract_claims": {
        "claims": (list,),
        "requests": (list,),
        "contradictions": (list,),
        "anomalies": (list,),
        "parsed": (int,),
        "total": (int,),
        "completeness": (int, float),
        "newest_age_seconds": (int, float),
    },
    "risk.probe": {
        "escalations": (list,),
        "hypotheses": (list,),
        "verdict": (str,),
    },
    "remediation.prepare": {
        "action": (str,),
        "reversible": (bool,),
    },
    "remediation.execute": {
        "staged": (bool,),
    },
    "verify.check": {
        "verified": (bool,),
        "mismatches": (list,),
    },
    "reconcile.adjudicate": {
        "resolutions": (list,),
        "disputes": (list,),
        "verdict": (str,),
    },
}

#: Closed vocabularies. A verdict outside its vocabulary is not a new state,
#: it is a worker inventing one -- and every branch downstream compares
#: against these exact strings.
_VERDICTS: dict[str, frozenset[str]] = {
    "risk.probe": frozenset({"ESCALATION_FOUND", "NO_ESCALATION_FOUND"}),
    "reconcile.adjudicate": frozenset(
        {"NO_CONTRADICTIONS", "RESOLVED", "DISPUTED", "RESOLVED_WITH_DISPUTES"}
    ),
}


def _shape_violations(tool: str, output: dict[str, Any]) -> list[ContractViolation]:
    violations: list[ContractViolation] = []
    for key, types in _SHAPE.get(tool, {}).items():
        if key not in output:
            violations.append(
                ContractViolation(tool, "SHAPE", key, f"required key {key!r} is missing")
            )
            continue
        value = output[key]
        # `bool` is a subclass of `int`; a contract asking for an int must not
        # accept True. Checked explicitly rather than relying on isinstance.
        if bool in types:
            if not isinstance(value, bool):
                violations.append(
                    ContractViolation(
                        tool, "SHAPE", key, f"{key!r} is {type(value).__name__}, expected bool"
                    )
                )
            continue
        if isinstance(value, bool) or not isinstance(value, types):
            names = "/".join(t.__name__ for t in types)
            violations.append(
                ContractViolation(
                    tool, "SHAPE", key, f"{key!r} is {type(value).__name__}, expected {names}"
                )
            )
    return violations


def _recon_violations(output: dict[str, Any]) -> list[ContractViolation]:
    """Coverage must follow from the counts, and claims must be claims."""
    tool = "recon.extract_claims"
    out: list[ContractViolation] = []
    parsed = output.get("parsed")
    total = output.get("total")
    completeness = output.get("completeness")

    if isinstance(parsed, int) and isinstance(total, int):
        if parsed < 0 or total < 0:
            out.append(
                ContractViolation(
                    tool, "SELF_CONSISTENCY", "parsed", f"negative counts: {parsed}/{total}"
                )
            )
        elif parsed > total:
            out.append(
                ContractViolation(
                    tool,
                    "SELF_CONSISTENCY",
                    "parsed",
                    f"claims {parsed} parsed of {total} encountered: more parsed than seen",
                )
            )
        elif isinstance(completeness, (int, float)) and not isinstance(completeness, bool):
            expected = (parsed / total) if total else 0.0
            if abs(float(completeness) - expected) > _DERIVED_TOLERANCE:
                out.append(
                    ContractViolation(
                        tool,
                        "SELF_CONSISTENCY",
                        "completeness",
                        (
                            f"reports completeness {completeness} but {parsed}/{total} "
                            f"is {expected:.4f}: the coverage figure does not follow from "
                            "the counts it is stated beside"
                        ),
                    )
                )

    if isinstance(completeness, (int, float)) and not isinstance(completeness, bool):
        if not 0.0 <= float(completeness) <= 1.0:
            out.append(
                ContractViolation(
                    tool, "RANGE", "completeness", f"{completeness} is outside [0.0, 1.0]"
                )
            )
    age = output.get("newest_age_seconds")
    if isinstance(age, (int, float)) and not isinstance(age, bool) and float(age) < 0:
        out.append(
            ContractViolation(
                tool, "RANGE", "newest_age_seconds", f"{age} is negative: evidence from the future"
            )
        )

    claims = output.get("claims")
    if isinstance(claims, list):
        for i, claim in enumerate(claims):
            if not isinstance(claim, dict):
                out.append(
                    ContractViolation(
                        tool, "SHAPE", f"claims[{i}]", f"{type(claim).__name__}, expected dict"
                    )
                )
                continue
            missing = [
                f for f in ("claim_id", "subject", "predicate", "value", "source") if f not in claim
            ]
            if missing:
                out.append(
                    ContractViolation(
                        tool,
                        "SHAPE",
                        f"claims[{i}]",
                        f"claim is missing {missing!r}: an untraceable claim is not a claim",
                    )
                )

    # A contradiction must be about claims this same output carries. A
    # contradiction over a claim_id nobody extracted is a finding with no
    # evidence under it.
    claim_ids = {
        str(c.get("claim_id"))
        for c in (claims if isinstance(claims, list) else [])
        if isinstance(c, dict)
    }
    contradictions = output.get("contradictions")
    if isinstance(contradictions, list) and claim_ids:
        for i, item in enumerate(contradictions):
            if not isinstance(item, dict):
                continue
            cid = str(item.get("claim_id"))
            if cid not in claim_ids:
                out.append(
                    ContractViolation(
                        tool,
                        "GROUNDING",
                        f"contradictions[{i}]",
                        f"names claim {cid!r}, which this extraction did not produce",
                    )
                )
    return out


def _risk_violations(output: dict[str, Any], inputs: dict[str, Any]) -> list[ContractViolation]:
    """An escalation may only name an agent the evidence actually recorded."""
    tool = "risk.probe"
    out: list[ContractViolation] = []
    verdict = output.get("verdict")
    allowed = _VERDICTS[tool]
    if isinstance(verdict, str) and verdict not in allowed:
        out.append(
            ContractViolation(
                tool, "VOCABULARY", "verdict", f"{verdict!r} is not one of {sorted(allowed)}"
            )
        )

    recon = inputs.get("recon") or {}
    known_agents = {
        str(r.get("agent_id"))
        for r in recon.get("requests", [])
        if isinstance(r, dict) and r.get("agent_id")
    }
    known_requests = {
        str(r.get("request_id"))
        for r in recon.get("requests", [])
        if isinstance(r, dict) and r.get("request_id")
    }

    escalations = output.get("escalations")
    if isinstance(escalations, list):
        for i, esc in enumerate(escalations):
            if not isinstance(esc, dict):
                out.append(
                    ContractViolation(
                        tool, "SHAPE", f"escalations[{i}]", f"{type(esc).__name__}, expected dict"
                    )
                )
                continue
            for field in ("agent_id", "requested_scope"):
                if not str(esc.get(field, "")).strip():
                    out.append(
                        ContractViolation(
                            tool, "SHAPE", f"escalations[{i}].{field}", f"{field!r} is empty"
                        )
                    )
            agent_id = str(esc.get("agent_id", ""))
            if known_agents and agent_id and agent_id not in known_agents:
                out.append(
                    ContractViolation(
                        tool,
                        "GROUNDING",
                        f"escalations[{i}].agent_id",
                        (
                            f"names {agent_id!r}, which appears in no parsed capability "
                            "request: a finding about an agent the evidence never mentioned"
                        ),
                    )
                )
            request_id = str(esc.get("request_id", ""))
            if known_requests and request_id and request_id not in known_requests:
                out.append(
                    ContractViolation(
                        tool,
                        "GROUNDING",
                        f"escalations[{i}].request_id",
                        f"names request {request_id!r}, which the evidence does not contain",
                    )
                )

    # Verdict and findings must agree. "NO_ESCALATION_FOUND" beside a
    # non-empty escalation list is the shape of a summary written separately
    # from the work.
    if isinstance(escalations, list) and isinstance(verdict, str) and verdict in allowed:
        expected = "ESCALATION_FOUND" if escalations else "NO_ESCALATION_FOUND"
        if verdict != expected:
            out.append(
                ContractViolation(
                    tool,
                    "SELF_CONSISTENCY",
                    "verdict",
                    f"{verdict!r} with {len(escalations)} escalation(s) listed; expected {expected!r}",
                )
            )

    worst = output.get("worst_escalation")
    if worst is not None and not isinstance(worst, dict):
        out.append(
            ContractViolation(
                tool,
                "SHAPE",
                "worst_escalation",
                f"{type(worst).__name__}, expected dict or None",
            )
        )
    elif isinstance(worst, dict) and isinstance(escalations, list) and escalations:
        if worst not in escalations:
            out.append(
                ContractViolation(
                    tool,
                    "GROUNDING",
                    "worst_escalation",
                    "the escalation singled out as worst is not one of the escalations listed",
                )
            )
    return out


def _remediation_violations(
    output: dict[str, Any], inputs: dict[str, Any]
) -> list[ContractViolation]:
    """A correction must target something the evidence named, and be reversible."""
    tool = "remediation.prepare"
    out: list[ContractViolation] = []
    action = str(output.get("action", "")).strip()
    if not action:
        out.append(ContractViolation(tool, "SHAPE", "action", "action is empty"))
    if action and action != "NO_ACTION_REQUIRED":
        if not str(output.get("idempotency_key", "")).strip():
            out.append(
                ContractViolation(
                    tool,
                    "SHAPE",
                    "idempotency_key",
                    "a mutating proposal with no idempotency key cannot be replayed safely",
                )
            )
        if not str(output.get("reversal", "")).strip():
            out.append(
                ContractViolation(
                    tool,
                    "SHAPE",
                    "reversal",
                    "a proposal claiming reversibility must state the reversal path",
                )
            )
        risk = inputs.get("risk") or {}
        known_requests = {
            str(e.get("request_id"))
            for e in risk.get("escalations", [])
            if isinstance(e, dict) and e.get("request_id")
        }
        target = str(output.get("target_request_id", ""))
        if known_requests and target and target not in known_requests:
            out.append(
                ContractViolation(
                    tool,
                    "GROUNDING",
                    "target_request_id",
                    (
                        f"targets request {target!r}, which risk analysis did not "
                        "find an escalation for"
                    ),
                )
            )
        if known_requests and not target:
            out.append(
                ContractViolation(
                    tool,
                    "GROUNDING",
                    "target_request_id",
                    "a mutating proposal names no target request",
                )
            )
    if output.get("reversible") is False and action != "NO_ACTION_REQUIRED":
        out.append(
            ContractViolation(
                tool,
                "POLICY",
                "reversible",
                "an irreversible correction is outside what this fleet may prepare",
            )
        )
    return out


def _verify_violations(output: dict[str, Any]) -> list[ContractViolation]:
    tool = "verify.check"
    out: list[ContractViolation] = []
    verified = output.get("verified")
    mismatches = output.get("mismatches")
    if isinstance(verified, bool) and isinstance(mismatches, list):
        if verified and mismatches:
            out.append(
                ContractViolation(
                    tool,
                    "SELF_CONSISTENCY",
                    "verified",
                    f"claims verified=True while listing {len(mismatches)} mismatch(es)",
                )
            )
        if not verified and not mismatches:
            out.append(
                ContractViolation(
                    tool,
                    "SELF_CONSISTENCY",
                    "verified",
                    "claims verified=False with no mismatch named: an unexplained failure",
                )
            )
    return out


def _reconcile_violations(
    output: dict[str, Any], inputs: dict[str, Any]
) -> list[ContractViolation]:
    """A reconciliation may only rule on contradictions recon actually found."""
    tool = "reconcile.adjudicate"
    out: list[ContractViolation] = []
    verdict = output.get("verdict")
    allowed = _VERDICTS[tool]
    if isinstance(verdict, str) and verdict not in allowed:
        out.append(
            ContractViolation(
                tool, "VOCABULARY", "verdict", f"{verdict!r} is not one of {sorted(allowed)}"
            )
        )

    recon = inputs.get("recon") or {}
    known = {
        str(c.get("claim_id"))
        for c in recon.get("contradictions", [])
        if isinstance(c, dict) and c.get("claim_id")
    }
    for bucket in ("resolutions", "disputes"):
        rows = output.get(bucket)
        if not isinstance(rows, list):
            continue
        for i, row in enumerate(rows):
            if not isinstance(row, dict):
                out.append(
                    ContractViolation(
                        tool, "SHAPE", f"{bucket}[{i}]", f"{type(row).__name__}, expected dict"
                    )
                )
                continue
            cid = str(row.get("claim_id", ""))
            if known and cid not in known:
                out.append(
                    ContractViolation(
                        tool,
                        "GROUNDING",
                        f"{bucket}[{i}].claim_id",
                        f"rules on claim {cid!r}, which recon reported no contradiction for",
                    )
                )
            if bucket == "resolutions" and not str(row.get("chosen_source", "")).strip():
                out.append(
                    ContractViolation(
                        tool,
                        "SHAPE",
                        f"resolutions[{i}].chosen_source",
                        "a resolution must name the source it chose",
                    )
                )
    return out


def validate_tool_output(
    tool: str, output: Any, *, inputs: dict[str, Any] | None = None
) -> list[ContractViolation]:
    """Every violation, in declaration order. Empty list means the output may
    be believed.

    `inputs` carries what the worker was GIVEN -- `recon` for `risk.probe`,
    `risk` for `remediation.prepare`. Grounding checks are skipped, not
    faked, when the corresponding input is absent: a check that cannot be
    performed must not report a pass.
    """
    inputs = inputs or {}
    if not isinstance(output, dict):
        return [
            ContractViolation(
                tool,
                "SHAPE",
                "<root>",
                f"worker returned {type(output).__name__}, not a structured result",
            )
        ]
    if tool not in _SHAPE:
        return [
            ContractViolation(
                tool,
                "REGISTRY",
                "<tool>",
                f"{tool!r} has no declared output contract; an unverifiable result is refused",
            )
        ]

    violations = _shape_violations(tool, output)
    if tool == "recon.extract_claims":
        violations += _recon_violations(output)
    elif tool == "risk.probe":
        violations += _risk_violations(output, inputs)
    elif tool == "remediation.prepare":
        violations += _remediation_violations(output, inputs)
    elif tool == "verify.check":
        violations += _verify_violations(output)
    elif tool == "reconcile.adjudicate":
        violations += _reconcile_violations(output, inputs)
    return violations


#: One sentence per tool naming what its findings must be grounded in. Kept
#: beside the checks rather than in a document, so a new grounding rule has
#: one place to be described and it is the place it is enforced.
_GROUNDING_NOTES: dict[str, str] = {
    "recon.extract_claims": (
        "coverage must equal parsed/total; every contradiction must be about a "
        "claim this extraction produced"
    ),
    "risk.probe": (
        "every escalation must name an agent_id and request_id present in the parsed "
        "evidence; the verdict must agree with the findings listed"
    ),
    "remediation.prepare": (
        "a mutating proposal must target a request risk analysis actually escalated, "
        "and must carry an idempotency key and a stated reversal path"
    ),
    "verify.check": "verified=True and a non-empty mismatch list cannot both be true",
    "reconcile.adjudicate": (
        "every ruling must be about a contradiction recon reported, and a resolution "
        "must name the source it chose"
    ),
}


def contract_summary() -> list[dict[str, Any]]:
    """The declared contracts, for the API and the architecture surface.

    Generated from the same tables the checks read, so the documentation of
    a contract and the enforcement of it cannot drift apart.
    """
    return [
        {
            "tool": tool,
            "required_keys": {k: "/".join(t.__name__ for t in v) for k, v in sorted(shape.items())},
            "closed_vocabulary": sorted(_VERDICTS[tool]) if tool in _VERDICTS else [],
            "grounding": _GROUNDING_NOTES.get(tool, ""),
        }
        for tool, shape in sorted(_SHAPE.items())
    ]


__all__ = [
    "ContractViolation",
    "contract_summary",
    "validate_tool_output",
]
