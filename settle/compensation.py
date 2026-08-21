"""Compensation path synthesis. [DESIGNED] — deliberately not built.

Task 4's brief named this as the first thing to cut if time is short, and said
plainly: say so rather than half-building it. This file is that statement.

WHAT IT WOULD DO
    Where no native undo exists, synthesise a reverse path: the sequence of
    operations that discharges an obligation a connector cannot itself reverse.

WHY IT IS NOT BUILT
    A half-built synthesiser is worse than an absent one. It would emit reverse
    paths that look executable, and the surrounding machinery -- the broker, the
    obligation, the dry-run flag -- would carry them to a human who reasonably
    assumes a proposed path was checked. The honest version of "we did not build
    this" is an object that refuses, not a generator that guesses.

THE CONSTRAINTS IT WOULD SHIP UNDER, recorded now so they are not re-litigated:
    · MAY generate. MAY NEVER execute.
    · Dry-run is mandatory and is not a flag the caller can unset.
    · Every synthesised path goes to the approval broker before anything moves.
    · Nothing generated here reaches production without a human signature.

Until then `synthesise()` raises. `settle.irreversibility` already routes
compensable effects above the threshold to the broker, so the absence of this
module costs coverage, not safety.
"""

from __future__ import annotations

from dataclasses import dataclass

from lib.schema import ExternalEffect

STATUS = "DESIGNED"


class CompensationNotBuiltError(NotImplementedError):
    """Raised on any attempt to synthesise a compensation path."""


@dataclass(frozen=True)
class CompensationPath:
    """The shape the built version would return. No instance is ever produced."""

    effect_ref: str
    steps: list[str]
    dry_run: bool = True


def synthesise(effect: ExternalEffect) -> CompensationPath:
    """Not built. Raises, loudly, naming what to do instead."""
    raise CompensationNotBuiltError(
        f"compensation path synthesis is [DESIGNED], not [BUILT]; no reverse path "
        f"was generated for {effect.connector}.{effect.op} ({effect.ref}). This "
        "effect must be routed to the approval broker as an unrecoverable item "
        "and handled by a human. See settle/compensation.py for why this refuses "
        "rather than guessing."
    )
