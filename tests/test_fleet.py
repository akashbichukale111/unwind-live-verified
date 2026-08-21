"""The fleet: five bounded identities, a planner that diverges, a validator
that cannot be talked past, and tools that parse genuinely messy input.

The tests split by what they need. Everything about roles, planning,
validation and parsing is pure and needs no emulator; only the
scope-enforcement tests touch the registry and the real Gateway.
"""

from __future__ import annotations

import ast
import os
import socket
from pathlib import Path

import pytest

from fleet.planner import (
    MAX_PLAN_STEPS,
    PlanRejected,
    build_plan,
    classify_objective,
    deterministic_plan,
    replan_after_refusal,
    validate_plan,
)
from fleet.roles import ALL_ROLES, BY_AGENT_ID, RECON, REMEDIATION, SPECIALISTS, VERIFIER
from fleet.schema import ObjectiveClass, PlanProvenance
from fleet.tools import TOOL_REGISTRY, recon_extract_claims, risk_probe
from warrant.economics import ActionKind

REPO = Path(__file__).resolve().parents[1]


def _emulator_up() -> bool:
    host = os.environ.get("FIRESTORE_EMULATOR_HOST", "localhost:8080")
    hostname, _, port = host.partition(":")
    try:
        with socket.create_connection((hostname, int(port or 8080)), timeout=1.0):
            return True
    except OSError:
        return False


requires_emulator = pytest.mark.skipif(
    not _emulator_up(), reason="Firestore emulator not running; start it with `make emulator`"
)


# ===========================================================================
# Roles: bounded identity
# ===========================================================================


def test_there_are_five_distinct_agent_identities() -> None:
    assert len(ALL_ROLES) == 5
    assert len({r.agent_id for r in ALL_ROLES}) == 5
    assert len({r.principal for r in ALL_ROLES}) == 5
    assert len({r.agent_role for r in ALL_ROLES}) == 5


def test_read_only_roles_hold_no_write_scope() -> None:
    """The property the whole permission model rests on. Asserted on the
    registry data, not on a comment."""
    for role in (RECON, VERIFIER):
        assert not any(".write" in s for s in role.authority_scope), (
            f"{role.agent_id} holds a write scope; it is meant to be read-only"
        )


def test_only_remediation_can_mutate_and_it_holds_no_secret_scope() -> None:
    writers = [r for r in SPECIALISTS if any(".write" in s for s in r.authority_scope)]
    assert writers == [REMEDIATION]
    assert not any("secret" in s for s in REMEDIATION.authority_scope)


def test_no_specialist_may_propose_a_secret_or_production_action() -> None:
    for role in SPECIALISTS:
        assert ActionKind.SECRET_ACCESS not in role.permitted_actions
        assert ActionKind.PRODUCTION_MUTATION not in role.permitted_actions


def test_the_orchestrator_cannot_be_delegated_to() -> None:
    """A planner that can assign work to itself is a single point of total
    authority -- the separation `lib/principals.py` enforces one layer down."""
    assert all(r.agent_id != "fleet_orchestrator" for r in SPECIALISTS)


def test_planner_menu_is_generated_from_the_same_constants_the_registry_uses() -> None:
    """The menu cannot promise a scope the registry does not grant, because
    both are built from `ALL_ROLES`."""
    from fleet.roles import planner_menu

    menu = {m["role"]: m for m in planner_menu()}
    for role in SPECIALISTS:
        assert menu[role.agent_role.value]["authority_scope"] == list(role.authority_scope)


@requires_emulator
def test_recon_cannot_write_even_if_asked_to() -> None:
    """The refusal comes from the UNMODIFIED Gateway, not from the planner
    having behaved. This is the test that makes a prompt-injected plan
    harmless."""
    from fleet.roles import ensure_registered
    from tower.gateway import evaluate_gateway
    from tower.registry import get_agent

    ensure_registered()
    recon = get_agent(RECON.agent_id)
    decision = evaluate_gateway(
        recon,
        task="write to the sandbox (should be refused)",
        requested_scope=["sandbox.write"],
        requested_cost=1,
        risk_class="LOW",
        capability="research",
    )
    assert decision.allowed is False
    assert decision.reason_code.value == "SCOPE_EXCEEDED"


@requires_emulator
def test_remediation_cannot_read_secrets_even_though_it_can_write() -> None:
    from fleet.roles import ensure_registered
    from tower.gateway import evaluate_gateway
    from tower.registry import get_agent

    ensure_registered()
    remediation = get_agent(REMEDIATION.agent_id)
    decision = evaluate_gateway(
        remediation,
        task="read finance secrets (should be refused)",
        requested_scope=["finance.secret_read"],
        requested_cost=1,
        risk_class="HIGH",
        capability="remediation",
    )
    assert decision.allowed is False
    assert decision.reason_code.value == "SCOPE_EXCEEDED"


# ===========================================================================
# Planner: divergence
# ===========================================================================


@pytest.mark.parametrize(
    "objective,expected",
    [
        (
            "Investigate an anomalous finance capability request.",
            ObjectiveClass.SECURITY_INVESTIGATION,
        ),
        ("Audit a repository for credential exposure.", ObjectiveClass.CREDENTIAL_AUDIT),
        ("Trace the impact of a changed operational premise.", ObjectiveClass.PREMISE_IMPACT_TRACE),
        ("Review the policy controls for compliance.", ObjectiveClass.COMPLIANCE_REVIEW),
        ("Say hello.", ObjectiveClass.GENERAL_OPERATIONS),
    ],
)
def test_classification_is_deterministic_and_legible(objective, expected) -> None:
    assert classify_objective(objective) is expected
    assert classify_objective(objective) is classify_objective(objective.upper())


def test_different_objectives_create_different_plans() -> None:
    """The claim the previous architecture could not make at all."""
    objectives = [
        "Investigate an anomalous finance capability request.",
        "Audit a repository for credential exposure and prepare remediation.",
        "Trace the impact of a changed operational premise.",
        "Review the policy controls for compliance.",
        "Summarise today's operations.",
    ]
    fingerprints = {o: build_plan(o, allow_model=False).fingerprint() for o in objectives}
    assert len(set(fingerprints.values())) == len(objectives), (
        f"plans did not diverge: {fingerprints}"
    )


def test_orchestrator_selects_different_agents_per_objective() -> None:
    investigation = build_plan("Investigate an anomalous request.", allow_model=False)
    trace = build_plan("Trace the impact of a changed premise.", allow_model=False)
    assert set(investigation.roles) != set(trace.roles)
    # A trace is read-only work: no remediation specialist appears at all.
    assert REMEDIATION.agent_role not in trace.roles
    assert REMEDIATION.agent_role in investigation.roles


def test_a_read_only_objective_class_plans_no_write_scope() -> None:
    for objective in (
        "Trace the impact of a changed operational premise.",
        "Audit a repository for credential exposure.",
    ):
        plan = deterministic_plan(objective)
        for step in plan:
            assert not any(".write" in s for s in step.requested_scope), (
                f"{objective!r} planned a write scope in step {step.seq}"
            )


def test_zero_model_plan_is_labelled_zero_model_never_gemini() -> None:
    plan = build_plan("anything", allow_model=False)
    assert plan.provenance is PlanProvenance.ZERO_MODEL
    assert plan.model == "unwind-deterministic-planner@1"
    assert "gemini" not in plan.model.lower()
    assert plan.notes  # the reason the model was not used is stated, not blank


def test_plan_records_the_hash_of_the_exact_input() -> None:
    a = build_plan("objective one", allow_model=False)
    b = build_plan("objective two", allow_model=False)
    assert a.input_hash != b.input_hash
    assert build_plan("objective one", allow_model=False).input_hash == a.input_hash


# ===========================================================================
# The validator: the tool boundary
# ===========================================================================


def _raw(**overrides):
    base = {
        "role": "WORKER_DOCUMENT",
        "tool": "recon.extract_claims",
        "action_kind": "READ_INTERNAL",
        "intent": "gather",
        "requested_scope": ["evidence.read"],
        "risk_class": "LOW",
    }
    base.update(overrides)
    return base


def test_validator_accepts_a_well_formed_plan_without_clamping() -> None:
    steps, clamps = validate_plan([_raw()])
    assert len(steps) == 1
    assert clamps == []


def test_validator_drops_an_unknown_role() -> None:
    steps, clamps = validate_plan([_raw(), _raw(role="WORKER_SUPERUSER")])
    assert len(steps) == 1
    assert any("unknown role" in c for c in clamps)


def test_validator_drops_an_unknown_tool() -> None:
    steps, clamps = validate_plan([_raw(), _raw(tool="shell.exec")])
    assert len(steps) == 1
    assert any("unknown tool" in c for c in clamps)


def test_validator_drops_a_tool_not_registered_to_that_role() -> None:
    steps, clamps = validate_plan([_raw(), _raw(tool="remediation.execute")])
    assert len(steps) == 1
    assert any("not registered to" in c for c in clamps)


def test_validator_rejects_the_whole_plan_on_an_unpriceable_action() -> None:
    """Fatal on purpose: an action nobody costed must never execute at a
    default price."""
    with pytest.raises(PlanRejected, match="cannot be priced"):
        validate_plan([_raw(action_kind="EXFILTRATE_EVERYTHING")])


def test_validator_clamps_an_action_the_role_may_not_propose() -> None:
    steps, clamps = validate_plan([_raw(action_kind="CREATE_TICKET")])
    assert steps[0].action_kind == "ANALYZE"
    assert any("not permitted" in c for c in clamps)


def test_validator_intersects_scope_with_what_the_registry_granted() -> None:
    """A plan can only ever ask for scope the registry already granted. This
    is the anti-escalation property, and it is enforced here rather than
    hoped for in the prompt."""
    steps, clamps = validate_plan(
        [_raw(requested_scope=["evidence.read", "sandbox.write", "finance.secret_read"])]
    )
    assert steps[0].requested_scope == ["evidence.read"]
    assert any("outside" in c and "removed" in c for c in clamps)


def test_validator_never_leaves_a_step_with_empty_scope() -> None:
    steps, _ = validate_plan([_raw(requested_scope=["totally.invented"])])
    assert steps[0].requested_scope, "a step with no scope would be unauthorizable"


def test_validator_caps_plan_length() -> None:
    steps, clamps = validate_plan([_raw() for _ in range(MAX_PLAN_STEPS + 5)])
    assert len(steps) == MAX_PLAN_STEPS
    assert any("truncated" in c for c in clamps)


def test_validator_rejects_a_plan_where_nothing_survives() -> None:
    with pytest.raises(PlanRejected, match="no step survived"):
        validate_plan([_raw(role="NONSENSE"), _raw(tool="nonsense")])


def test_validator_clamps_an_unknown_risk_class() -> None:
    steps, clamps = validate_plan([_raw(risk_class="OMEGA")])
    assert steps[0].risk_class == "LOW"
    assert any("unknown risk class" in c for c in clamps)


# ===========================================================================
# Replanning
# ===========================================================================


def test_replan_retries_a_scope_refusal_at_the_narrowest_held_scope() -> None:
    """Asserted on the SCOPE, which is what a scope refusal is about.

    `fingerprint()` deliberately captures role/tool/action only -- it is the
    plan's shape, used to prove two objectives produce different plans. A
    scope narrowing does not change the shape, so asserting on the
    fingerprint here would test the wrong field and pass for the wrong
    reason.
    """
    plan = build_plan("Investigate an anomalous request.", allow_model=False)
    before = next(s for s in plan.steps if s.seq == 2)
    revised, revisions = replan_after_refusal(plan, failed_seq=2, reason_code="SCOPE_EXCEEDED")
    assert revisions
    after = next(s for s in revised.steps if s.tool == before.tool)
    assert after.requested_scope != before.requested_scope
    assert after.risk_class == "LOW"


def test_replan_downgrades_unaffordable_mutations_to_analysis() -> None:
    plan = build_plan("Investigate an anomalous request.", allow_model=False)
    revised, revisions = replan_after_refusal(
        plan, failed_seq=1, reason_code="WARRANT_INSUFFICIENT"
    )
    assert any("downgraded" in r for r in revisions)
    assert all(s.action_kind != "CREATE_TICKET" for s in revised.steps)


def test_replan_narrows_everything_to_read_only_under_critical_drift() -> None:
    plan = build_plan("Investigate an anomalous request.", allow_model=False)
    revised, revisions = replan_after_refusal(
        plan, failed_seq=1, reason_code="WORKER_FAULT", drift_band="CRITICAL"
    )
    assert any("read-only" in r for r in revisions)
    for step in revised.steps:
        assert not any(".write" in s for s in step.requested_scope)


def test_replan_records_its_revisions_on_the_plan() -> None:
    plan = build_plan("Investigate an anomalous request.", allow_model=False)
    revised, revisions = replan_after_refusal(plan, failed_seq=2, reason_code="SCOPE_EXCEEDED")
    for revision in revisions:
        assert revision in revised.clamps


# ===========================================================================
# Tools: genuinely messy input
# ===========================================================================


def test_recon_reports_real_coverage_not_a_claim_of_completeness() -> None:
    """The committed fixture contains four records that cannot be parsed. If
    coverage ever reads 100%, the parser has started guessing."""
    out = recon_extract_claims()
    assert out["total"] > out["parsed"] > 0
    assert 0.0 < out["completeness"] < 1.0
    kinds = {a["kind"] for a in out["anomalies"]}
    assert "UNPARSEABLE_REQUEST_ROW" in kinds
    assert "INCOMPLETE_PREMISE_RECORD" in kinds


def test_recon_finds_the_real_contradictions() -> None:
    out = recon_extract_claims()
    claim_ids = {c["claim_id"] for c in out["contradictions"]}
    assert "clm_supplier_K_lead_time" in claim_ids
    assert "clm_tariff_rate_K" in claim_ids
    lead_time = next(
        c for c in out["contradictions"] if c["claim_id"] == "clm_supplier_K_lead_time"
    )
    assert sorted(lead_time["values"]) == ["11", "20"]
    assert lead_time["most_recent_value"] == 20


def test_recon_mines_the_free_text_handover_note() -> None:
    out = recon_extract_claims()
    labels = {h["label"] for h in out["note_signals"]}
    assert "tool_call_escalation" in labels
    assert any(a["kind"] == "NO_DEPENDENCY_INDEX" for a in out["anomalies"])


def test_recon_never_invents_a_timestamp_for_an_unparseable_one() -> None:
    """Guessing `now` for a corrupt timestamp would make stale evidence read
    as fresh -- the single most dangerous silent failure in this parser."""
    out = recon_extract_claims()
    bad = [a for a in out["anomalies"] if "NOT_A_TIMESTAMP" in a.get("detail", "")]
    assert bad, "the corrupt-timestamp row was not reported as unparseable"


def test_risk_probe_grounds_escalation_in_the_registry_not_in_an_opinion() -> None:
    recon = recon_extract_claims()
    scopes = {r.agent_id: list(r.authority_scope) for r in ALL_ROLES}
    risk = risk_probe(recon=recon, fleet_scopes=scopes)
    assert risk["verdict"] == "ESCALATION_FOUND"
    worst = risk["worst_escalation"]
    assert worst["agent_id"] in BY_AGENT_ID
    assert worst["requested_scope"] not in scopes[worst["agent_id"]]


def test_risk_probe_finds_nothing_when_there_is_nothing(tmp_path: Path) -> None:
    empty = risk_probe(
        recon={"requests": [], "anomalies": [], "contradictions": []}, fleet_scopes={}
    )
    assert empty["verdict"] == "NO_ESCALATION_FOUND"
    assert empty["worst_escalation"] is None


def test_every_registered_tool_is_reachable_from_some_role() -> None:
    reachable = {t for r in ALL_ROLES for t in r.tools}
    assert reachable == set(TOOL_REGISTRY), (
        "a tool nobody can run, or a role referencing a tool that does not exist"
    )


# ===========================================================================
# The zero-model boundary, extended to the fleet's tools
# ===========================================================================

FORBIDDEN = {"lib.vertex", "google.genai", "google.adk", "vertexai", "openai", "anthropic"}
#: `fleet/agents.py` is the ONE module allowed to reach a model. Everything
#: else in the package -- roles, tools, schema, and the planner's validator --
#: must stay model-free, or "the model proposes, arithmetic decides" is only
#: an aspiration.
MODEL_ALLOWED = {"fleet.agents"}


def _imports(path: Path, *, module_level_only: bool) -> set[str]:
    """Imports in one file.

    `module_level_only` matters: `fleet/planner.py` legitimately reaches the
    framework, but only from INSIDE `_run_planner_async`, so importing
    `fleet.planner` costs nothing to a caller that never asks for a
    model-authored plan. A walker that cannot tell those apart would either
    forbid the deferred import (wrong) or permit a module-level one (also
    wrong). Module-level means "in `tree.body`", not "anywhere in the tree".
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    nodes = tree.body if module_level_only else list(ast.walk(tree))
    found: set[str] = set()
    for node in nodes:
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            found.add(node.module)
    return found


def test_fleet_tools_and_roles_import_no_model_client() -> None:
    """Stricter than module-level: these three may not reach a model client
    ANYWHERE, deferred or not. They are the deterministic half of the fleet."""
    for name in ("fleet/tools.py", "fleet/roles.py", "fleet/schema.py"):
        imports = _imports(REPO / name, module_level_only=False)
        offending = {i for i in imports if any(i == f or i.startswith(f + ".") for f in FORBIDDEN)}
        assert not offending, f"{name} imports {offending}"


def test_only_fleet_agents_may_import_the_framework() -> None:
    for path in sorted((REPO / "fleet").glob("*.py")):
        module = f"fleet.{path.stem}"
        if module in MODEL_ALLOWED:
            continue
        imports = _imports(path, module_level_only=True)
        top_level = {i for i in imports if any(i == f or i.startswith(f + ".") for f in FORBIDDEN)}
        assert not top_level, (
            f"{module} imports {top_level} at module level; only {MODEL_ALLOWED} may. "
            "A deferred import inside a function is how fleet/planner.py reaches the "
            "model without making the whole package model-dependent."
        )
