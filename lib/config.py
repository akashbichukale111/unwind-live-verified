"""Single source of configuration truth for UNWIND.

The Gemini model string appears HERE AND NOWHERE ELSE in this repository.
`make lint` is not what enforces that -- tests/test_config_singleton.py does,
by grepping the tree. If you need a model name somewhere else, import it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache

# ---------------------------------------------------------------------------
# Models + region. THE ONLY MODEL STRINGS IN THE REPO.
# ---------------------------------------------------------------------------
# Two models, because the workload genuinely has two shapes and the split is a
# cost and reliability decision rather than a preference:
#
#   MODEL_FAST  high-volume, low-stakes. Whatever survives T1 and still needs
#               reading -- parsing, the ambiguous-materiality cull. May touch
#               hundreds of nodes in one cascade.
#   MODEL_DEEP  low-volume, high-stakes. Re-derivation on survivors,
#               arbitration, and drafting a correction that reaches a
#               counterparty. Touches dozens.
#
# GA STATUS, re-verified 2026-08-12 against Google Cloud / Google AI model
# documentation:
#   gemini-3.5-flash-lite  GA. Positioned for low-latency, high-volume agentic
#                          subagent work.
#   gemini-3.6-flash       GA since 2026-07-21. Currently the strongest GA
#                          Gemini on Vertex AI.
#
# ⚠ MODEL_DEEP IS NOT A PRO MODEL, AND THAT IS DELIBERATE. As of 2026-08-12 no
# Gemini 3.x Pro is generally available on Vertex AI -- gemini-3.1-pro is
# PREVIEW. The instruction was that both strings be verified GA, and a GA-only
# constraint currently excludes the entire Pro line. When 3.1 Pro reaches GA,
# promoting MODEL_DEEP to it is a one-line change here and nowhere else.
#
# ⚠ RE-VERIFY BOTH STRINGS ARE STILL GA BEFORE SUBMISSION.
MODEL_FAST = "gemini-3.5-flash-lite"
MODEL_DEEP = "gemini-3.6-flash"

#: Default when a caller has no opinion. Deliberately the cheap one: a code path
#: that silently wanted the expensive model should have to say so.
GEMINI_MODEL = MODEL_FAST

# ---------------------------------------------------------------------------
# Gemma (Card 3, Countersign). A SEPARATE model family, deliberately -- the
# whole point of Countersign is that its verdict comes from a family that
# cannot share Gemini's blind spots. `warrant/ledger.py`'s MINT precondition
# refuses a same-family countersign outright (see `family_root` below), so a
# Gemma string quietly drifting to a Gemini one would be self-defeating in a
# way none of the other model config in this file is.
#
# [UNVERIFIED — NOT RE-CHECKED AGAINST LIVE VERTEX MODEL GARDEN LISTINGS IN
# THIS SESSION.] `gemma-3-27b-it` is the instruction-tuned, largest-available
# open-weight Gemma 3 checkpoint as commonly published on Vertex AI Model
# Garden. Unlike MODEL_FAST/MODEL_DEEP above, this string has NOT been
# re-verified against a live GA listing in this environment (no GCP
# credentials were available -- see `docs/LIVE-VERIFICATION.md` and
# `countersign/DESIGN.md`). Treat it the same way as any other unverified
# claim in this repository: re-check before a live demo, and the honesty
# panel says so rather than implying otherwise.
GEMMA_MODEL = "gemma-3-27b-it"

# ---------------------------------------------------------------------------
# Media models (Mission Media Lab). Presentation layer ONLY -- see
# `media/DESIGN.md`. Neither of these strings may ever reach an authority
# decision: `tests/test_media.py::test_media_is_not_in_the_authority_path`
# walks the import graph to prove `tower/`, `warrant/` and `hyperion/` never
# import `media/`.
#
# ⚠ VERSION CURRENCY MATTERS HERE AND WAS CHECKED, NOT ASSUMED.
# `veo-3.0-generate-001` and `veo-3.0-fast-generate-001` are DEPRECATED with a
# shutdown date of 2026-06-30 -- already past as of this writing -- so pinning
# them would ship a model ID that returns 404 on the first real call. The
# current generally-available generation is Veo 3.1.
#
# [UNVERIFIED AGAINST A LIVE MODEL GARDEN LISTING IN THIS ENVIRONMENT --
# same standing caveat as GEMMA_MODEL above: no GCP credentials were
# available, so these were taken from Google's published model
# documentation rather than confirmed by a successful call. The Media Lab
# reports CONFIGURED_NOT_EXERCISED for exactly this reason, and the first
# real call is what will confirm or refute them.]
VEO_MODEL = "veo-3.1-generate-001"

# Lyria 2 (`lyria-002`) is the GA music-generation model: max 32.8s per clip,
# 48kHz, audio/wav. Lyria 3 exists but is public preview at time of writing,
# and this repository's convention is to pin GA over preview unless the
# preview capability is actually needed -- a 30-second mission signal does
# not need Lyria 3 Pro's three-minute compositions.
LYRIA_MODEL = "lyria-002"

#: Lyria 2's hard ceiling, from its published model card. Stated here rather
#: than in `media/lyria.py` so the request builder cannot drift past a limit
#: the API will reject.
LYRIA_MAX_SECONDS = 32

# Vertex AI location. Pinned, not inferred from ambient environment, so a cascade
# cannot silently move jurisdictions between runs.
#
# `global`, not a region, and this is a measurement rather than a preference: it
# is the location the smoke test actually passed on (Vertex request, Gemini tool
# call, echo_tier(T0), final response, no 401/403/404). A regional endpoint was
# tried first and is NOT the verified configuration, so the committed value is
# the one with evidence behind it.
VERTEX_LOCATION = "global"


class Tier(str, Enum):
    """Tiered degradation (locked decision 1.2).

    T0 and T1 must survive a total Vertex outage. Membership is a property of
    the code path, declared here, so the guarantee is structural rather than a
    convention someone remembers.
    """

    T0 = "T0"  # blast-radius traversal over the reverse index. No model.
    T1 = "T1"  # arithmetic materiality on numeric/temporal claims. No model.
    T2 = "T2"  # ambiguous materiality, arbitration, drafting. Model required.


#: Tiers that are forbidden from making a model call, ever.
MODEL_FREE_TIERS: frozenset[Tier] = frozenset({Tier.T0, Tier.T1})


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Config:
    """Resolved runtime configuration."""

    project_id: str
    vertex_location: str
    gemini_model: str
    model_fast: str
    model_deep: str
    gemma_model: str
    veo_model: str
    lyria_model: str
    lyria_max_seconds: int

    firestore_emulator_host: str | None
    firestore_database: str

    # When true, no Vertex client may be constructed. This is how the T0/T1
    # degradation guarantee gets *tested* in Task 2 rather than asserted.
    vertex_disabled: bool

    # When true, Pub/Sub uses the in-process shim instead of the real service.
    pubsub_local: bool

    pubsub_topics: tuple[str, ...] = field(default=())

    otel_service_name: str = "unwind"
    otel_console_export: bool = True

    @property
    def uses_emulator(self) -> bool:
        return self.firestore_emulator_host is not None

    @property
    def has_gcp_credentials(self) -> bool:
        """Can this process actually authenticate to Google right now?

        THIS USED TO BE A FALSE NEGATIVE FOR THE MAIN SUPPORTED SETUP.
        The previous implementation tested only GOOGLE_APPLICATION_CREDENTIALS
        and GOOGLE_CLOUD_PROJECT. `gcloud auth application-default login`
        sets NEITHER -- it writes a well-known JSON file -- so an operator
        who had authenticated correctly was still told there were no
        credentials, with no hint why. On a Google Cloud project whose org
        policy disallows API keys, ADC is the ONLY permitted mechanism, so
        that false negative blocked the only supported path.

        Now delegated to `lib/gcp_auth.resolve_auth`, which asks
        `google.auth.default()` -- the same resolver google-genai uses, and
        the one that already knows about the ADC file, an explicit service
        account, and Cloud Run's metadata-server service identity.
        """
        from lib.gcp_auth import resolve_auth  # noqa: PLC0415

        return resolve_auth().available


# ---------------------------------------------------------------------------
# Pub/Sub topic names (locked list, brief 4.4)
# ---------------------------------------------------------------------------
TOPIC_CLAIM_RETRACTED = "claim.retracted"
TOPIC_NODE_REDERIVE = "node.rederive"
TOPIC_NODE_SCORED = "node.scored"
TOPIC_REPAIR_CONVENED = "repair.convened"
TOPIC_OBLIGATION_RAISED = "obligation.raised"
TOPIC_UNWIND_EXECUTED = "unwind.executed"

ALL_TOPICS: tuple[str, ...] = (
    TOPIC_CLAIM_RETRACTED,
    TOPIC_NODE_REDERIVE,
    TOPIC_NODE_SCORED,
    TOPIC_REPAIR_CONVENED,
    TOPIC_OBLIGATION_RAISED,
    TOPIC_UNWIND_EXECUTED,
)

# ---------------------------------------------------------------------------
# Firestore collection names
# ---------------------------------------------------------------------------
COLLECTION_CLAIMS = "claims"
COLLECTION_CONCLUSIONS = "conclusions"
COLLECTION_REVERSE_INDEX = "reverse_index"
COLLECTION_OBLIGATIONS = "obligations"
COLLECTION_REPAIRS = "repairs"
COLLECTION_SOURCES = "sources"
COLLECTION_AGENT_TRUST = "agent_trust"
#: Runtime cascade records. Never mutates reverse_index (ruling 1.9).
COLLECTION_CASCADES = "cascades"

# ---------------------------------------------------------------------------
# Control Tower collections (Card 2). Separate from the Card 1 collections
# above: the tower is supporting infrastructure for the write path, not a
# rename of anything that already existed.
# ---------------------------------------------------------------------------
#: The executable agent registry. tower/registry.py.
COLLECTION_AGENTS = "agents"
#: Append-only decision-memory chain. tower/memory.py.
COLLECTION_DECISION_MEMORY = "decision_memory"
#: Long-running case state (open/paused/awaiting_human/resumed/closed). tower/runtime.py.
COLLECTION_CASES = "cases"

# ---------------------------------------------------------------------------
# WARRANT (Card 0): a fully separate ledger from settle/loadrating.py.
# Deliberately its own collection, not a reuse of COLLECTION_AGENT_TRUST or
# anything settle/ touches -- warrant/DESIGN.md and
# tests/test_warrant_separation.py assert this ledger shares no storage and
# no code path with source standing.
# ---------------------------------------------------------------------------
#: Append-only warrant events: MINT, BURN, SPEND, DECAY, CHALLENGE. warrant/ledger.py.
COLLECTION_WARRANT_LEDGER = "warrant_ledger"

# ---------------------------------------------------------------------------
# HYPERION (immune layer over Card 2's Gateway). A read of the SAME
# `tower.gateway.evaluate_gateway` decision every other caller already gets,
# scored and logged -- not a second authority path. Its own collection, never
# folded into `decision_memory`: those entries are caused BY a decision
# elsewhere (spine/court/judgment/settle write them); a Hyperion event is
# caused by a Gateway CHECK, which may run far more often and is not itself
# part of any case's causal chain.
# ---------------------------------------------------------------------------
#: Append-only risk-scored log of Gateway decisions. hyperion/immune_memory.py.
COLLECTION_HYPERION_EVENTS = "hyperion_events"

# ---------------------------------------------------------------------------
# SINGULARITY-MESH (Card 5): the zero-trust autonomous agent fleet framework.
# Its own collection for the two live, deterministic decision engines this
# card actually implements -- Capability Genome negotiation and Behavioral
# DNA drift detection (singularity/genome.py, singularity/behavior.py). Never
# folded into hyperion_events or decision_memory: a mesh event is caused by a
# capability-genome or behavioral-drift computation, a distinct concern from
# either of those. See singularity/DESIGN.md for what is built vs. reference
# architecture only.
# ---------------------------------------------------------------------------
#: Append-only log of capability-genome and behavioral-DNA decisions. singularity/mesh_memory.py.
COLLECTION_SINGULARITY_EVENTS = "singularity_mesh_events"

#: Subcollection under reverse_index/{claim_id}
SUBCOLLECTION_DEPENDENTS = "dependents"
#: Subcollection under cascades/{cascade_id}
SUBCOLLECTION_NODES = "nodes"

ALL_COLLECTIONS: tuple[str, ...] = (
    COLLECTION_CLAIMS,
    COLLECTION_CONCLUSIONS,
    COLLECTION_REVERSE_INDEX,
    COLLECTION_OBLIGATIONS,
    COLLECTION_REPAIRS,
    COLLECTION_SOURCES,
    COLLECTION_AGENT_TRUST,
    COLLECTION_CASCADES,
    COLLECTION_AGENTS,
    COLLECTION_DECISION_MEMORY,
    COLLECTION_CASES,
    COLLECTION_WARRANT_LEDGER,
    COLLECTION_HYPERION_EVENTS,
    COLLECTION_SINGULARITY_EVENTS,
)


@lru_cache(maxsize=1)
def get_config() -> Config:
    """Resolve configuration once per process.

    Defaults are chosen so that a cold clone with no GCP account runs: emulator
    Firestore, in-process Pub/Sub, console telemetry.
    """
    emulator_host = os.environ.get("FIRESTORE_EMULATOR_HOST") or None
    project_id = (
        os.environ.get("UNWIND_PROJECT_ID")
        or os.environ.get("GOOGLE_CLOUD_PROJECT")
        or "unwind-local"
    )
    return Config(
        project_id=project_id,
        vertex_location=os.environ.get("UNWIND_VERTEX_LOCATION", VERTEX_LOCATION),
        gemini_model=GEMINI_MODEL,
        model_fast=MODEL_FAST,
        model_deep=MODEL_DEEP,
        gemma_model=GEMMA_MODEL,
        veo_model=VEO_MODEL,
        lyria_model=LYRIA_MODEL,
        lyria_max_seconds=LYRIA_MAX_SECONDS,
        firestore_emulator_host=emulator_host,
        firestore_database=os.environ.get("UNWIND_FIRESTORE_DATABASE", "(default)"),
        vertex_disabled=_env_flag("UNWIND_VERTEX_DISABLED", default=False),
        pubsub_local=_env_flag("UNWIND_PUBSUB_LOCAL", default=emulator_host is not None),
        pubsub_topics=ALL_TOPICS,
        otel_service_name=os.environ.get("UNWIND_OTEL_SERVICE", "unwind"),
        otel_console_export=_env_flag("UNWIND_OTEL_CONSOLE", default=True),
    )


def reset_config_cache() -> None:
    """Test hook. Configuration is otherwise resolved once."""
    get_config.cache_clear()
