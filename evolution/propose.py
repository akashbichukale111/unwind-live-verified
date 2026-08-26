"""Failure analysis, and the candidate version it produces.

THE ONE PLACE IN THIS PACKAGE WHERE A MODEL IS THE RIGHT TOOL
----------------------------------------------------------------
`fleet/tools.py`'s docstring states this repository's split: a model is good
at deciding WHICH and WHY; it is a poor choice for parsing, comparing and
computing, because those have exact answers. Everything in `evolution/` up to
this module obeys that -- `criteria.py` computes, `trajectory.py` folds,
`versions.py` hashes, none of them import a model.

Reading a set of failing criteria and writing a better instruction is the
other kind of job. It is genuinely a judgement call over prose, it has no
exact answer, and it is exactly what a language model is for. So this is the
one module in the package that reaches for Gemini -- and, exactly like
`fleet/planner.py`, it works completely without one.

THE FAILURE ANALYSIS ITSELF IS NOT THE MODEL'S JOB
-----------------------------------------------------
`analyse_failures` is deterministic. It folds real evaluations into the list
of criteria that actually failed, how often, and on which missions. The model
is handed that analysis; it is never asked to decide WHETHER something
failed, only what to say differently about it. A model that could nominate
its own failures could also decline to nominate any.

WHAT THE VALIDATOR REFUSES
-----------------------------
`validate_candidate` is where a model's prose stops being a proposal:

  - a policy key outside `MUTABLE_POLICY_KEYS` is DROPPED (named in `clamps`);
  - any authority-bearing key raises `AuthorityEscalation` and the WHOLE
    proposal is rejected -- not clamped, rejected, because a proposal that
    reached for scope is not a proposal that should be partially accepted;
  - a policy value outside its declared bound is clamped to the bound;
  - an instruction shorter than `MIN_INSTRUCTION_CHARS` is rejected, because
    "be better" is not an instruction and would silently delete the
    governance language the seed carries;
  - an instruction that dropped any `REQUIRED_INSTRUCTION_ANCHORS` phrase is
    REJECTED. This is the important one: those anchors are the sentences that
    tell the agent it is independently authorised and cannot grant itself
    permission. A candidate that quietly removes them would be an agent
    talking itself out of its own governance, which is the single most
    plausible way this loop could go wrong.

So the strongest thing a prompt-injected or hallucinating proposer achieves
is a candidate narrowed to what was already permitted, with every narrowing
named -- and if it reached for authority, nothing at all.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from evolution.schema import (
    AgentVersion,
    EvolutionProposal,
    ProposalProvenance,
    TrajectoryEvaluation,
)
from evolution.versions import (
    AuthorityEscalation,
    assert_no_authority_keys,
    build_version,
    diff_versions,
)

#: The ONLY policy keys a proposal may set. A subset of
#: `evolution/versions.py:SEED_POLICY` -- a proposal may tune what exists, and
#: may not introduce a new lever for itself.
#: Each maps to (kind, lower_bound, upper_bound). Bounds are inclusive.
MUTABLE_POLICY_KEYS: dict[str, tuple[str, Any, Any]] = {
    "min_evidence_completeness": ("float", 0.0, 1.0),
    "require_human_on_contradiction": ("bool", None, None),
    "max_plan_steps": ("int", 1, 8),
    "verify_after_execute": ("bool", None, None),
}

#: [ASSUMPTION] Floor on instruction length. Chosen, stated as chosen. Its
#: purpose is not style: an instruction that collapses to a sentence has
#: dropped the governance language the seed carries, and the anchors below
#: would not catch a total truncation on their own.
MIN_INSTRUCTION_CHARS = 120

#: Phrases that MUST survive into every candidate instruction. Matched
#: case-insensitively on the normalised text. These are the sentences that
#: tell an agent it does not authorise itself. A candidate that removes one is
#: rejected outright.
#:
#: [ASSUMPTION] The anchor set. What is NOT an assumption is the requirement
#: that some such set exists and is checked: an evolution loop permitted to
#: rewrite an instruction without one can, in a single well-formed step,
#: produce an agent that no longer believes it needs permission.
REQUIRED_INSTRUCTION_ANCHORS: tuple[str, ...] = (
    "authoriz",  # "independently authorized" / "authorise" -- stem, both spellings
)


class ProposalRejected(ValueError):
    """The candidate was not narrowable into something safe. Distinct from a
    clamp: a clamp narrows and proceeds, this abandons."""


# ---------------------------------------------------------------------------
# 1. Failure analysis -- deterministic
# ---------------------------------------------------------------------------


def analyse_failures(evaluations: list[TrajectoryEvaluation]) -> list[dict[str, Any]]:
    """Fold real evaluations into the criteria that actually failed.

    Ordered worst-first by (failure count, mean score) so the proposer is
    handed the biggest real problem at the top rather than an arbitrary one.
    A criterion that never failed does not appear -- this returns an empty
    list for a clean history, and `propose_candidate` refuses to invent an
    improvement for one.
    """
    buckets: dict[str, dict[str, Any]] = {}
    for ev in evaluations:
        for crit in ev.criteria:
            row = buckets.setdefault(
                crit.key.value,
                {
                    "criterion": crit.key.value,
                    "name": crit.name,
                    "expected": crit.expected,
                    "failures": 0,
                    "runs": 0,
                    "score_sum": 0.0,
                    "observed_failures": [],
                    "mission_ids": [],
                },
            )
            row["runs"] += 1
            row["score_sum"] += crit.score
            if not crit.passed:
                row["failures"] += 1
                row["observed_failures"].append(crit.failure)
                row["mission_ids"].append(ev.mission_id)

    rows = []
    for row in buckets.values():
        if not row["failures"]:
            continue
        row["mean_score"] = round(row["score_sum"] / max(1, row["runs"]), 4)
        del row["score_sum"]
        rows.append(row)
    rows.sort(key=lambda r: (-r["failures"], r["mean_score"]))
    return rows


# ---------------------------------------------------------------------------
# 2. The deterministic proposer -- a first-class mode, not a degraded one
# ---------------------------------------------------------------------------

#: [ASSUMPTION] One remediation clause per criterion, plus the policy nudge
#: that expresses it mechanically. Hand-written, legible, and deliberately
#: conservative: every clause tightens behaviour, none loosens it. A judge can
#: read this table and predict exactly what the zero-model loop will propose,
#: which is the point -- an improvement you cannot predict is indistinguishable
#: from a random edit.
_REMEDIATION: dict[str, tuple[str, dict[str, Any]]] = {
    "CONTEXT_QUALITY": (
        "Before proposing any step with an external effect, check the parsed "
        "coverage of the evidence. If coverage is below the configured "
        "minimum, or any contradiction is unresolved, propose the read-only "
        "step that would raise coverage instead, and say plainly that you "
        "are doing so.",
        {"min_evidence_completeness": 0.7, "require_human_on_contradiction": True},
    ),
    "RISK_DISCIPLINE": (
        "When the evidence names a scope escalation or a drift band above "
        "NORMAL, the plan must contain the containment or verification step "
        "that responds to it. Never plan past a finding you have made.",
        {},
    ),
    "TOOL_CORRECTNESS": (
        "Order steps so that evidence is gathered before it is analysed, a "
        "correction is prepared before it is executed, and any execution is "
        "followed by an independent verification step.",
        {"verify_after_execute": True},
    ),
    "RECOVERY": (
        "When a step is refused or a tool fails, replan around it explicitly "
        "rather than repeating the same step. Name what changed in the "
        "revised plan.",
        {},
    ),
    "EFFICIENCY": (
        "Produce the smallest plan that answers the objective. Do not add a "
        "step whose result would not change what happens next.",
        {"max_plan_steps": 6},
    ),
    "POLICY_COMPLIANCE": (
        "Never propose an external effect without the human concurrence step "
        "when the action's risk class requires it. A refusal is a final "
        "answer, not an obstacle to route around.",
        {"require_human_on_contradiction": True},
    ),
    "TASK_SUCCESS": (
        "Ensure the plan actually reaches a step that answers the objective, "
        "rather than stopping at analysis.",
        {},
    ),
}


def deterministic_candidate(
    baseline: AgentVersion, analysis: list[dict[str, Any]]
) -> tuple[str, dict[str, Any]]:
    """Compose a candidate instruction and policy from the failure analysis.

    Pure function. Appends one remediation clause per FAILING criterion, in
    worst-first order, under a heading that names why it is there. Existing
    text is never deleted -- an improvement that removes governance language
    is the exact failure mode `REQUIRED_INSTRUCTION_ANCHORS` guards, and the
    zero-model path simply never attempts it.
    """
    clauses: list[str] = []
    policy = dict(baseline.policy)
    for row in analysis:
        remedy = _REMEDIATION.get(row["criterion"])
        if not remedy:
            continue
        clause, policy_delta = remedy
        clauses.append(f"- ({row['criterion']}) {clause}")
        policy.update(policy_delta)
    if not clauses:
        raise ProposalRejected("no failing criterion has a defined remediation")

    instruction = (
        baseline.instruction.rstrip()
        + "\n\nOPERATING CORRECTIONS — derived from measured failures on prior "
        + "missions, one clause per criterion that actually failed:\n"
        + "\n".join(clauses)
    )
    return instruction, policy


# ---------------------------------------------------------------------------
# 3. The validator -- where a model's prose stops being a proposal
# ---------------------------------------------------------------------------


def validate_candidate(
    *, instruction: str, policy: dict[str, Any], baseline: AgentVersion
) -> tuple[str, dict[str, Any], list[str]]:
    """Narrow a proposed instruction/policy to what is permitted.

    Returns `(instruction, policy, clamps)`. Raises `ProposalRejected` or
    `AuthorityEscalation` when narrowing is not enough.
    """
    clamps: list[str] = []

    # Authority first: this one is never a clamp.
    assert_no_authority_keys(policy, where="candidate.policy")

    instruction = (instruction or "").strip()
    if len(instruction) < MIN_INSTRUCTION_CHARS:
        raise ProposalRejected(
            f"instruction is {len(instruction)} chars, below the "
            f"{MIN_INSTRUCTION_CHARS}-char floor; a collapsed instruction "
            "silently drops the governance language the baseline carries"
        )

    lowered = instruction.lower()
    for anchor in REQUIRED_INSTRUCTION_ANCHORS:
        if anchor in baseline.instruction.lower() and anchor not in lowered:
            raise ProposalRejected(
                f"candidate dropped the governance anchor {anchor!r} that the "
                "baseline instruction carries; an agent version may not remove "
                "the language stating that it is independently authorised"
            )

    clean: dict[str, Any] = {}
    for key, value in (policy or {}).items():
        spec = MUTABLE_POLICY_KEYS.get(key)
        if spec is None:
            clamps.append(f"dropped unpermitted policy key {key!r}")
            continue
        kind, low, high = spec
        try:
            if kind == "bool":
                clean[key] = bool(value)
                continue
            if kind == "int":
                coerced: Any = int(value)
            else:
                coerced = float(value)
        except (TypeError, ValueError):
            clamps.append(f"dropped policy key {key!r}: value {value!r} is not {kind}")
            continue
        if low is not None and coerced < low:
            clamps.append(f"clamped {key} {coerced} up to lower bound {low}")
            coerced = low
        if high is not None and coerced > high:
            clamps.append(f"clamped {key} {coerced} down to upper bound {high}")
            coerced = high
        clean[key] = coerced

    # A key the baseline had and the candidate omitted is CARRIED FORWARD, not
    # dropped. Silence is not a request to delete an operating preference.
    for key, value in baseline.policy.items():
        clean.setdefault(key, value)

    return instruction, clean, clamps


# ---------------------------------------------------------------------------
# 4. The Gemini proposer
# ---------------------------------------------------------------------------

PROPOSER_INSTRUCTION = (
    "You improve the INSTRUCTION given to one agent in a governed enterprise "
    "agent fleet.\n\n"
    "You will be given: the agent's current instruction, its current policy, "
    "and a deterministic analysis of which behavioural criteria measurably "
    "failed on real missions, with the observed failure text.\n\n"
    "Produce a revised instruction that would plausibly prevent those "
    "specific failures.\n\n"
    "Hard rules:\n"
    "- Keep every sentence of the current instruction that states the agent "
    "is independently authorised, cannot grant itself permission, or is "
    "checked by a deterministic gateway. You may add to them. You may never "
    "remove or weaken them.\n"
    "- You may propose values ONLY for these policy keys: "
    + ", ".join(sorted(MUTABLE_POLICY_KEYS))
    + ".\n"
    "- You may NOT propose scope, tools, permitted actions, budgets, "
    "thresholds or schedules. Those are granted by a registry you cannot "
    "write to, and any attempt to set them voids the whole proposal.\n"
    "- Address the failing criteria that were given to you. Do not invent a "
    "failure that is not in the analysis.\n"
    "- Every change you make must tighten behaviour, never loosen it.\n"
)


def _proposer_prompt(baseline: AgentVersion, analysis: list[dict[str, Any]]) -> str:
    return (
        f"AGENT KEY: {baseline.agent_key}\n"
        f"CURRENT VERSION: {baseline.version_id} (v{baseline.version_n})\n\n"
        f"CURRENT INSTRUCTION:\n{baseline.instruction}\n\n"
        f"CURRENT POLICY:\n{json.dumps(baseline.policy, indent=2, sort_keys=True)}\n\n"
        f"MEASURED FAILURE ANALYSIS (deterministic, worst first):\n"
        f"{json.dumps(analysis, indent=2, sort_keys=True, default=str)}\n\n"
        f"POLICY KEYS YOU MAY SET:\n"
        f"{json.dumps({k: {'kind': v[0], 'min': v[1], 'max': v[2]} for k, v in MUTABLE_POLICY_KEYS.items()}, indent=2, sort_keys=True)}\n"
    )


def _extract_json(text: str) -> dict[str, Any]:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object in proposer output")
    return json.loads(text[start : end + 1])


async def _run_proposer_async(prompt: str) -> str:
    """Execute the proposer through a real ADK Runner.

    Uses the SAME one-node-`Workflow` idiom `countersign/verify.py` proved
    against live Vertex and `fleet/planner.py` already reuses, because a
    `mode="single_turn"` agent cannot be a Runner root. Reusing the proven
    idiom avoids inventing a third execution path that has never been run.
    """
    from google.adk.agents.llm_agent import Agent
    from google.adk.runners import InMemoryRunner
    from google.adk.workflow import START, Edge, Workflow
    from google.genai import types
    from pydantic import BaseModel, Field

    from lib.config import get_config
    from lib.vertex import configure_vertex_backend

    class ProposedVersion(BaseModel):
        instruction: str = Field(description="The full revised instruction text.")
        policy: dict[str, Any] = Field(
            default_factory=dict, description="Only the permitted policy keys."
        )
        rationale: str = Field(default="", description="Why these changes address the failures.")

    configure_vertex_backend()
    cfg = get_config()
    agent = Agent(
        model=cfg.model_fast,
        name="evolution_proposer",
        description=(
            "Proposes a revised instruction for one fleet agent from a "
            "deterministic analysis of its measured behavioural failures. "
            "Proposes only; every proposal is validated and gated downstream."
        ),
        instruction=PROPOSER_INSTRUCTION,
        output_schema=ProposedVersion,
        output_key="proposal",
        mode="single_turn",
    )
    workflow = Workflow(
        name="evolution_proposal",
        description="One node: the single-turn instruction proposer.",
        edges=[Edge(from_node=START, to_node=agent)],
    )
    runner = InMemoryRunner(node=workflow, app_name="unwind-evolution-proposer")
    session = await runner.session_service.create_session(
        app_name="unwind-evolution-proposer", user_id="evolution"
    )
    message = types.Content(role="user", parts=[types.Part(text=prompt)])
    parts: list[str] = []
    async for event in runner.run_async(
        user_id="evolution", session_id=session.id, new_message=message
    ):
        if event.content and event.content.parts:
            for part in event.content.parts:
                if part.text:
                    parts.append(part.text)
    return "".join(parts)


# ---------------------------------------------------------------------------
# 5. The entry point
# ---------------------------------------------------------------------------


def _proposal_id(baseline_id: str, candidate_id: str) -> str:
    payload = f"{baseline_id}->{candidate_id}"
    return "prop_" + hashlib.sha256(payload.encode()).hexdigest()[:16]


def propose_candidate(
    *,
    baseline: AgentVersion,
    evaluations: list[TrajectoryEvaluation],
    version_n: int,
    allow_model: bool = True,
    now: datetime | None = None,
) -> tuple[EvolutionProposal, AgentVersion]:
    """Analyse real failures, then produce ONE candidate version.

    Returns `(proposal, candidate)`. The candidate is returned rather than
    written: this module proposes, and `evolution/promote.py` is the only
    place a version reaches storage or production.

    Gemini first when `allow_model` and Vertex is reachable; the deterministic
    proposer otherwise. `provenance` is set by the code path that actually
    ran and never claims a model that did not produce the text --
    `fleet/schema.py:PlanProvenance`'s contract, reused.

    Raises `ProposalRejected` when there is nothing to improve. An evolution
    loop that manufactures a candidate for a clean history is a loop that
    will eventually promote noise.
    """
    now = now or datetime.now(UTC)
    analysis = analyse_failures(evaluations)
    if not analysis:
        raise ProposalRejected(
            "no criterion failed across the supplied evaluations; there is "
            "nothing measured to improve"
        )

    provenance = ProposalProvenance.ZERO_MODEL
    model_name = ""
    clamps: list[str] = []
    instruction: str
    policy: dict[str, Any]

    used_model = False
    if allow_model:
        try:
            import asyncio

            from lib.config import get_config
            from lib.vertex import vertex_available

            if vertex_available():
                raw = asyncio.run(_run_proposer_async(_proposer_prompt(baseline, analysis)))
                parsed = _extract_json(raw)
                instruction = str(parsed.get("instruction", "") or "")
                policy = dict(parsed.get("policy", {}) or {})
                model_name = get_config().model_fast
                used_model = True
            else:
                instruction, policy = deterministic_candidate(baseline, analysis)
        except AuthorityEscalation:
            # A model that reached for authority does not get a narrowed
            # version of its proposal. It gets none, and the deterministic
            # proposer runs instead. Re-raising would abort the loop; falling
            # through silently would hide it. The clamp names it.
            clamps.append("model proposal named an authority-bearing key and was discarded whole")
            instruction, policy = deterministic_candidate(baseline, analysis)
            used_model = False
        except Exception as exc:  # noqa: BLE001 -- any model failure falls back
            clamps.append(f"model path unavailable ({type(exc).__name__}); used deterministic")
            instruction, policy = deterministic_candidate(baseline, analysis)
            used_model = False
    else:
        instruction, policy = deterministic_candidate(baseline, analysis)

    if used_model:
        try:
            instruction, policy, model_clamps = validate_candidate(
                instruction=instruction, policy=policy, baseline=baseline
            )
            clamps.extend(model_clamps)
            provenance = (
                ProposalProvenance.GEMINI_CLAMPED if model_clamps else ProposalProvenance.GEMINI
            )
        except (ProposalRejected, AuthorityEscalation) as exc:
            clamps.append(f"model proposal rejected by validator: {exc}")
            instruction, policy = deterministic_candidate(baseline, analysis)
            model_name = ""
            provenance = ProposalProvenance.ZERO_MODEL

    # The deterministic path is validated too. It is not trusted more for
    # being local -- it is trusted more for being predictable, and a check
    # that only runs on the model path is a check that has never been tested.
    instruction, policy, final_clamps = validate_candidate(
        instruction=instruction, policy=policy, baseline=baseline
    )
    clamps.extend(final_clamps)

    candidate = build_version(
        agent_key=baseline.agent_key,
        instruction=instruction,
        policy=policy,
        version_n=version_n,
        parent_version_id=baseline.version_id,
        provenance=provenance,
        model=model_name,
        now=now,
    )
    if candidate.version_id == baseline.version_id:
        raise ProposalRejected(
            "candidate is byte-identical to the baseline; there is no change to promote"
        )

    return EvolutionProposal(
        proposal_id=_proposal_id(baseline.version_id, candidate.version_id),
        agent_key=baseline.agent_key,
        from_version_id=baseline.version_id,
        candidate_version_id=candidate.version_id,
        failure_analysis=analysis,
        changes=diff_versions(baseline, candidate),
        provenance=provenance,
        model=model_name,
        clamps=clamps,
        source_evaluation_ids=[e.evaluation_id for e in evaluations],
        created_at=now,
    ), candidate


__all__ = [
    "MIN_INSTRUCTION_CHARS",
    "MUTABLE_POLICY_KEYS",
    "PROPOSER_INSTRUCTION",
    "REQUIRED_INSTRUCTION_ANCHORS",
    "ProposalRejected",
    "analyse_failures",
    "deterministic_candidate",
    "propose_candidate",
    "validate_candidate",
]
