"""One resolver for "is this run simulated, and may a simulated result count".

THE DEFECT THIS REPLACES
---------------------------
`command_os/mission.py:run_mission` used to open with

    os.environ.setdefault("UNWIND_COUNTERSIGN_SIMULATED", "1")

-- a request handler mutating PROCESS-WIDE state. On Cloud Run that means
the first mission request permanently flips the whole container into
simulation mode, including `warrant/ledger.py`'s check for whether a
simulated countersign may satisfy a MINT precondition. The label discipline
was honestly implemented and then quietly undermined by the application
switching it on for itself.

TWO SEPARATE QUESTIONS, DELIBERATELY NOT ONE FLAG
-----------------------------------------------------
`simulated_countersign` -- "run the deterministic zero-model challenger
instead of calling Gemma". This is a legitimate operating mode: it is how
the eval harness, the offline demo and CI get a reproducible challenge with
no credentials.

`simulated_mint_permitted` -- "may a countersign produced that way satisfy
`warrant.ledger.mint`'s independent-verification precondition". This is an
AUTHORITY question, and it is the one that must never be true in
production.

Collapsing them into one flag is exactly how simulated evidence becomes
earned evidence. They are separate fields here, and:

    UNWIND_ENV=production  =>  simulated_mint_permitted is False, always,
                               regardless of every other variable.

That is a hard branch in `resolve_policy`, asserted by
`tests/test_simulation_isolation.py::test_simulation_never_becomes_earned_in_production`.

NOTHING IN THIS MODULE WRITES TO os.environ.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

ENV_SIMULATED = "UNWIND_COUNTERSIGN_SIMULATED"
ENV_ALLOW_SIMULATED_MINT = "UNWIND_ALLOW_SIMULATED_MINT"
ENV_ENV = "UNWIND_ENV"


def is_production() -> bool:
    return os.environ.get(ENV_ENV, "").strip().lower() == "production"


@dataclass(frozen=True)
class SimulationPolicy:
    """Resolved, immutable, passed explicitly down the call chain."""

    simulated_countersign: bool
    simulated_mint_permitted: bool
    production: bool

    @property
    def label(self) -> str:
        """The status string the UI and `/api/command-os/status` must show."""
        if not self.simulated_countersign:
            return "LIVE"
        return "SIMULATED" if self.simulated_mint_permitted else "SIMULATED (NON-MINTING)"

    @classmethod
    def from_record(cls, record: dict) -> SimulationPolicy:
        """Rebuild from `as_record()`, ignoring the derived `label` field.

        `as_record` is what gets checkpointed and served over the API, and it
        deliberately includes the human-readable `label` so a reader of a
        stored checkpoint does not have to re-derive it. `label` is a
        property, not a field, so round-tripping through the constructor
        needs this rather than `cls(**record)`.
        """
        return cls(
            simulated_countersign=bool(record["simulated_countersign"]),
            simulated_mint_permitted=bool(record["simulated_mint_permitted"]),
            production=bool(record["production"]),
        )

    def as_record(self) -> dict[str, object]:
        return {
            "simulated_countersign": self.simulated_countersign,
            "simulated_mint_permitted": self.simulated_mint_permitted,
            "production": self.production,
            "label": self.label,
        }


def _flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def resolve_policy(
    *, simulated: bool | None = None, allow_simulated_mint: bool | None = None
) -> SimulationPolicy:
    """Resolve the policy for one call.

    Explicit arguments win over environment, so a caller (a test, the eval
    harness, a mission run) can state its mode instead of reaching for a
    global. The production clamp is applied LAST and cannot be argued past:
    an explicit `allow_simulated_mint=True` in production is still False.
    """
    production = is_production()
    sim = _flag(ENV_SIMULATED, default=False) if simulated is None else simulated
    if allow_simulated_mint is None:
        allow_mint = _flag(ENV_ALLOW_SIMULATED_MINT, default=sim)
    else:
        allow_mint = allow_simulated_mint

    # THE CLAMP. Nothing below this line may re-enable it.
    if production:
        allow_mint = False

    return SimulationPolicy(
        simulated_countersign=sim,
        simulated_mint_permitted=bool(allow_mint),
        production=production,
    )


#: The offline/eval/demo policy: run the deterministic challenger, and let its
#: verdict satisfy MINT -- valid ONLY outside production, where `resolve_policy`
#: clamps it. Named so a reader sees the intent at the call site.
def offline_policy() -> SimulationPolicy:
    return resolve_policy(simulated=True, allow_simulated_mint=True)


__all__ = [
    "ENV_ALLOW_SIMULATED_MINT",
    "ENV_ENV",
    "ENV_SIMULATED",
    "SimulationPolicy",
    "is_production",
    "offline_policy",
    "resolve_policy",
]
