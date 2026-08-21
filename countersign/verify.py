"""Countersign the verb: run the verifier, apply the collusion guard, and
wire the result into `warrant/ledger.py`'s minting gate.

Three outcomes, the same "unavailable is a class, not an exception" honesty
`judgment/model.py:UnavailableT2Model` already established for T2:

    AGREE       -> the case's countersign record is written; MINT may proceed.
    DISAGREE    -> the countersign record is written AND a CHALLENGE event
                   freezes minting for this case; it is flagged for a human.
    UNAVAILABLE -> nothing is written at all. `warrant.ledger.mint` already
                   refuses without a valid countersign record, so silence
                   here is the safe default -- never a silent AGREE.

ZERO-MODEL CHALLENGER, LABELLED, AND ABLE TO DISAGREE
--------------------------------------------------------
When `lib.simulation.SimulationPolicy.simulated_countersign` is set, this
module runs `_zero_model_challenge` instead of calling Gemma: a
deterministic, reproducible, credential-free INDEPENDENT RE-DERIVATION from
the presented evidence. It is not a stand-in that always agrees -- it has
five named grounds for DISAGREE and exercises the real CHALLENGE ->
mint-freeze path (see that function's docstring for what changed and why it
mattered).

The policy is passed in EXPLICITLY (`policy=`), never read from a mutable
process-wide environment variable inside the call. `lib/simulation.py`
explains the defect that motivated the change; the short version is that
the flag protecting the authority path used to be settable by the code the
authority path constrains. `warrant.ledger` applies the matching clamp:
under `UNWIND_ENV=production` a simulated countersign can never satisfy
MINT, whatever any environment variable says.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass

from lib.config import get_config
from lib.simulation import SimulationPolicy, resolve_policy
from lib.telemetry import model_call_span
from lib.vertex import VertexDisabledError
from warrant.ledger import family_root

#: The countersigner's own principal. MUST differ from any judging-side
#: principal it is ever asked to check against -- `assert_independent`
#: enforces this the same way `lib.principals.assert_agent_is_distinct`
#: enforces role separation one layer up.
COUNTERSIGN_PRINCIPAL = "countersign-gemma@0.1.0"


class CollusionError(RuntimeError):
    """A countersign attempt whose model family or principal matches the
    judging side it was meant to check independently."""


def assert_independent(
    *,
    countersign_family: str,
    countersign_principal: str,
    judging_family: str,
    judging_principal: str,
) -> None:
    """Refuse a countersign that cannot possibly be independent.

    Two ways to collide, either one is disqualifying:
      - FAMILY: `family_root` normalizes both strings (e.g. `lib.config`'s
        `MODEL_FAST` and `MODEL_DEEP` -- two different Gemini point
        releases -- both root to the same family) -- a same-family
        countersign proves nothing about independent verification even if the
        exact model string differs.
      - PRINCIPAL: the countersigner must not BE the party whose judgement it
        is checking, the identical reasoning `lib.principals.assert_agent_is_distinct`
        already applies to a delegated worker acting as its own arbiter.
    """
    cs_family = family_root(countersign_family)
    j_family = family_root(judging_family)
    if cs_family == j_family:
        raise CollusionError(
            f"countersign family {countersign_family!r} (root {cs_family!r}) shares a "
            f"family with the judging side {judging_family!r} (root {j_family!r}): "
            "independence requires a DIFFERENT family, not merely a different string."
        )
    if countersign_principal == judging_principal:
        raise CollusionError(
            f"countersign principal {countersign_principal!r} is the same principal as "
            f"the judging side {judging_principal!r}: a verifier that is also the party "
            "being verified is not independent verification, it is the same actor twice."
        )


@dataclass(frozen=True)
class CountersignOutcome:
    """Everything needed to audit one countersign attempt."""

    available: bool
    agrees: bool | None
    family: str
    ground: str
    simulated: bool
    model: str
    reason_unavailable: str | None = None


def _material_prompt(case_id: str, material: dict) -> str:
    lines = [f"Case: {case_id}"]
    for key, value in material.items():
        lines.append(f"{key}: {value}")
    return "\n".join(lines)


def _parse_verdict(text: str) -> tuple[bool, str]:
    """Deterministic parse of the two-line reply `countersign/agent.py`'s
    instruction demands. Raises rather than guessing: a reply this cannot
    parse must not silently become an AGREE or a DISAGREE with nothing behind
    it -- the caller treats a parse failure as UNAVAILABLE.
    """
    verdict_match = re.search(r"VERDICT:\s*(AGREE|DISAGREE)", text, re.IGNORECASE)
    if not verdict_match:
        raise ValueError(f"could not parse a VERDICT line from Gemma's reply: {text!r}")
    agrees = verdict_match.group(1).upper() == "AGREE"
    ground_match = re.search(r"GROUND:\s*(.+)", text, re.IGNORECASE)
    ground = ground_match.group(1).strip() if ground_match else "(no ground line returned)"
    return agrees, ground


def _run_coro_sync(coro):
    """Run a coroutine to completion, whether or not a loop is already running.

    `asyncio.run()` alone raises `RuntimeError: asyncio.run() cannot be
    called from a running event loop` when the caller is `command_os/
    mission.py`'s mission flow, which executes inside a FastAPI `async def`
    route. A plain top-level script (no loop running) still takes the
    direct `asyncio.run()` path; only the in-a-loop case needs its own
    thread with its own fresh loop. Same fix as `media/adapters.py`'s
    `_run_gemini`, which hit this for real once Gemini went live
    (2026-08-21) -- kept local rather than shared, since `countersign/` and
    `media/` do not import each other.
    """
    import concurrent.futures  # noqa: PLC0415

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


async def _run_gemma_async(case_id: str, material: dict) -> str:
    """Execute the single-turn agent for real.

    DISCOVERED DURING WIRING, STATED HONESTLY: `mode="single_turn"` cannot be
    the ROOT of an ADK `Runner` invocation -- ADK raises
    `ValueError: LlmAgent as root agent must have mode='chat'` if you try,
    whether passed as `agent=` or `node=` directly. The mode's own docstring
    says why: single_turn's home is "as a node in a workflow". So the SAME
    `countersign_agent` object `countersign/agent.py:countersign_tool` wraps
    is executed here as the one node of a one-node ADK 2 `Workflow` --
    `Workflow(edges=[Edge(from_node=START, to_node=countersign_agent)])` --
    the identical `Workflow`/`Edge`/`START` idiom `tower/gateway.py` already
    uses, run through `InMemoryRunner(node=...)`. This was verified against
    live Vertex AI in this session: the call reaches Vertex, authenticates,
    and returns a real (non-mock) response -- see `countersign/DESIGN.md`
    for the exact result.
    """
    from google.adk.runners import InMemoryRunner
    from google.adk.workflow import START, Edge, Workflow
    from google.genai import types

    from countersign.agent import countersign_agent

    workflow = Workflow(
        name="countersign_verification",
        description="One node: the single-turn Gemma verifier.",
        edges=[Edge(from_node=START, to_node=countersign_agent)],
    )
    runner = InMemoryRunner(node=workflow, app_name="unwind-countersign")
    session = await runner.session_service.create_session(
        app_name="unwind-countersign", user_id="countersign"
    )
    message = types.Content(
        role="user", parts=[types.Part(text=_material_prompt(case_id, material))]
    )

    text_parts: list[str] = []
    async for event in runner.run_async(
        user_id="countersign", session_id=session.id, new_message=message
    ):
        if event.content and event.content.parts:
            for part in event.content.parts:
                if part.text:
                    text_parts.append(part.text)
    return "".join(text_parts)


#: The zero-model challenger's family. `family_root` reduces it to `"zero"`,
#: which collides with neither `"gemini"` (the judging side) nor `"gemma"`,
#: so `assert_independent` and `warrant.ledger`'s non-Gemini-family MINT
#: precondition both hold for it on their own terms rather than by exemption.
_SIMULATED_FAMILY = "zero-model-challenger"

#: Legacy alias. The previous name claimed to be a stand-in for Gemma; it was
#: not one -- it read a marker. Kept only so an already-written Firestore
#: countersign record still deserialises and still reads as simulated.
_LEGACY_SIMULATED_FAMILY = "gemma-simulated"

#: [ASSUMPTION] Thresholds for the zero-model challenge below. Chosen to be
#: demo-legible and stated as chosen, the same discipline `hyperion/risk.py`'s
#: weight table and `singularity/behavior.py`'s baselines already use for
#: themselves -- not measured from production traffic that does not exist in
#: this repository.
_STALE_EVIDENCE_SECONDS = 3600
_MIN_COMPLETENESS_FOR_HIGH_RISK = 0.75
_UNRESOLVED_DRIFT_BANDS = {"DRIFT", "CRITICAL"}
_MUTATING_SCOPE_MARKERS = ("write", "create", "delete", "mutate", "execute", "secret")


def _zero_model_challenge(case_id: str, material: dict) -> CountersignOutcome:
    """A REAL independent check, computed from the evidence -- not a marker lookup.

    WHAT CHANGED, AND WHY IT MATTERED
    ------------------------------------
    The previous implementation agreed unless `material["class"] ==
    "adversarial"`. `command_os/mission.py` never set that key, so the
    mission's "an independent verifier confirmed the block" step was
    tautologically AGREE on every run, forever. A verifier that cannot
    disagree is not a verifier.

    This function re-derives its own verdict from the same evidence the
    proposing side saw, by a DIFFERENT procedure than any other component
    in the repository:

      - `hyperion/risk.py` scores the Gateway's *reason code*.
      - `singularity/behavior.py` scores an *observation* against a baseline.
      - This scores the *proposal against its own evidence*: does the
        evidence presented actually support the authority being requested?

    Five independent grounds for DISAGREE, each individually sufficient and
    each named in the returned `ground` so the record says why:

      1. AUTHORITY EXCEEDS EVIDENCE -- the requested authority cost is not
         covered by the balance the proposal itself reports.
      2. UNRESOLVED DRIFT -- behaviour is still DRIFT/CRITICAL and the
         proposal nonetheless requests a mutating scope.
      3. STALE EVIDENCE -- the evidence behind a mutating action is older
         than `_STALE_EVIDENCE_SECONDS`.
      4. INCOMPLETE EVIDENCE -- a HIGH/CRITICAL-risk proposal rests on
         evidence below `_MIN_COMPLETENESS_FOR_HIGH_RISK` coverage.
      5. DECLARED ADVERSARIAL -- the material is explicitly labelled
         adversarial or forged (the original rule, kept: an explicitly
         declared forgery should still be caught).

    Deterministic, no I/O, no clock beyond what the caller supplied in
    `material`, no model. The same evidence always produces the same verdict.
    """
    grounds: list[str] = []

    balance_bp = material.get("warrant_balance_bp")
    cost_bp = material.get("authority_cost_bp")
    if isinstance(balance_bp, int) and isinstance(cost_bp, int) and cost_bp > balance_bp:
        grounds.append(
            f"AUTHORITY EXCEEDS EVIDENCE: the proposal requests {cost_bp}bp of "
            f"authority against a reported balance of {balance_bp}bp"
        )

    drift_band = str(material.get("drift_band", "")).upper()
    requested_scope = material.get("requested_scope") or []
    scope_text = " ".join(str(s).lower() for s in requested_scope)
    mutating = any(marker in scope_text for marker in _MUTATING_SCOPE_MARKERS)
    if drift_band in _UNRESOLVED_DRIFT_BANDS and mutating:
        grounds.append(
            f"UNRESOLVED DRIFT: behaviour is {drift_band} and the proposal still "
            f"requests the mutating scope {sorted(requested_scope)!r}"
        )

    age = material.get("evidence_age_seconds")
    if isinstance(age, (int, float)) and age > _STALE_EVIDENCE_SECONDS and mutating:
        grounds.append(
            f"STALE EVIDENCE: the evidence behind a mutating action is {age:.0f}s old, "
            f"over the {_STALE_EVIDENCE_SECONDS}s floor"
        )

    completeness = material.get("evidence_completeness")
    risk_level = str(material.get("risk_level", "")).upper()
    if (
        isinstance(completeness, (int, float))
        and risk_level in {"HIGH", "CRITICAL"}
        and completeness < _MIN_COMPLETENESS_FOR_HIGH_RISK
    ):
        grounds.append(
            f"INCOMPLETE EVIDENCE: {risk_level}-risk proposal rests on "
            f"{completeness:.0%} evidence coverage, under the "
            f"{_MIN_COMPLETENESS_FOR_HIGH_RISK:.0%} floor"
        )

    if str(material.get("class", "")).lower() == "adversarial" or bool(material.get("forged")):
        grounds.append("DECLARED ADVERSARIAL: material is explicitly labelled adversarial/forged")

    agrees = not grounds
    ground = (
        "; ".join(grounds)
        if grounds
        else (
            "independent re-derivation from the presented evidence found no "
            "unbacked authority, unresolved drift, staleness or coverage gap"
        )
    )
    return CountersignOutcome(
        available=True,
        agrees=agrees,
        family=_SIMULATED_FAMILY,
        ground=ground,
        simulated=True,
        model=_SIMULATED_FAMILY,
    )


def run_countersign(
    case_id: str,
    material: dict,
    *,
    judging_family: str,
    judging_principal: str,
    principal: str = COUNTERSIGN_PRINCIPAL,
    policy: SimulationPolicy | None = None,
) -> CountersignOutcome:
    """The verb. Applies the collusion guard, then either runs the zero-model
    challenger or the real Gemma agent, and returns an outcome -- never
    writes anywhere. `verify_and_record` (below) is what wires a returned
    outcome into the Memory Bank and the warrant ledger.

    `policy` is EXPLICIT. It used to be read from `UNWIND_COUNTERSIGN_SIMULATED`
    inside this function, which meant any caller that had mutated that
    variable -- and `command_os/mission.py` mutated it on itself -- silently
    changed what "independent verification" meant here. Passing it in makes
    the mode a visible argument at every call site; `resolve_policy()` is the
    default only when a caller genuinely has no opinion.
    """
    cfg = get_config()
    policy = policy or resolve_policy()

    if policy.simulated_countersign:
        # Still checked: a simulated run that would have collided is not a
        # meaningful rehearsal of the real guard.
        assert_independent(
            countersign_family=_SIMULATED_FAMILY,
            countersign_principal=principal,
            judging_family=judging_family,
            judging_principal=judging_principal,
        )
        return _zero_model_challenge(case_id, material)

    if cfg.vertex_disabled:
        return CountersignOutcome(
            available=False,
            agrees=None,
            family=cfg.gemma_model,
            ground="",
            simulated=False,
            model=cfg.gemma_model,
            reason_unavailable="UNWIND_VERTEX_DISABLED=1",
        )

    assert_independent(
        countersign_family=cfg.gemma_model,
        countersign_principal=principal,
        judging_family=judging_family,
        judging_principal=judging_principal,
    )

    with model_call_span(cfg.gemma_model, purpose="countersign", case_id=case_id) as span:
        try:
            text = _run_coro_sync(_run_gemma_async(case_id, material))
            agrees, ground = _parse_verdict(text)
            span.set_attribute("unwind.countersign_agrees", agrees)
            span.set_attribute("unwind.model_available", True)
            return CountersignOutcome(
                available=True,
                agrees=agrees,
                family=cfg.gemma_model,
                ground=ground,
                simulated=False,
                model=cfg.gemma_model,
            )
        except VertexDisabledError as exc:
            span.set_attribute("unwind.model_available", False)
            return CountersignOutcome(
                available=False,
                agrees=None,
                family=cfg.gemma_model,
                ground="",
                simulated=False,
                model=cfg.gemma_model,
                reason_unavailable=str(exc),
            )
        except Exception as exc:  # noqa: BLE001
            # Genuinely unreachable (missing credentials, network, the model
            # string not deployed in this project) is reported honestly as
            # UNAVAILABLE -- never silently turned into an AGREE. This is the
            # identical shape `judgment/model.py:UnavailableT2Model` uses for
            # "I could not determine this" being a real, non-guessing answer.
            span.set_attribute("unwind.model_available", False)
            span.set_attribute("unwind.error", f"{type(exc).__name__}: {exc}")
            return CountersignOutcome(
                available=False,
                agrees=None,
                family=cfg.gemma_model,
                ground="",
                simulated=False,
                model=cfg.gemma_model,
                reason_unavailable=f"{type(exc).__name__}: {exc}",
            )


def verify_and_record(
    *,
    case_id: str,
    material: dict,
    agent,
    capability: str,
    risk_class: str,
    judging_family: str,
    judging_principal: str,
    principal: str = COUNTERSIGN_PRINCIPAL,
    policy: SimulationPolicy | None = None,
) -> CountersignOutcome:
    """Run Countersign and wire the result into the Memory Bank / warrant
    ledger. AGREE writes a countersign record and stops there -- `mint`
    still separately checks a human-concurrence record exists. DISAGREE
    writes the record AND appends a CHALLENGE, freezing minting for
    `case_id` permanently (see `warrant/ledger.py:mint`'s precondition
    check and `warrant/FAILURE_MODES.md`'s note on no unfreeze path).
    UNAVAILABLE writes nothing -- `mint` will refuse for lack of a record,
    which is the safe default, not a special case this function has to
    implement itself.
    """
    outcome = run_countersign(
        case_id,
        material,
        judging_family=judging_family,
        judging_principal=judging_principal,
        principal=principal,
        policy=policy,
    )
    if not outcome.available:
        return outcome

    from warrant.ledger import challenge, record_countersign

    record_countersign(
        case_id,
        agrees=bool(outcome.agrees),
        family=outcome.family,
        simulated=outcome.simulated,
        note=outcome.ground,
    )
    if not outcome.agrees:
        challenge(
            case_id=case_id,
            principal=agent.principal,
            capability=capability,
            risk_class=risk_class,
            reason=f"countersign disagreed: {outcome.ground}",
        )
    return outcome


__all__ = [
    "COUNTERSIGN_PRINCIPAL",
    "CHALLENGER_FAMILY",
    "CollusionError",
    "CountersignOutcome",
    "assert_independent",
    "run_countersign",
    "verify_and_record",
]

#: Public name for the zero-model challenger family, for callers that need
#: to record or display it without importing a private symbol.
CHALLENGER_FAMILY = _SIMULATED_FAMILY
