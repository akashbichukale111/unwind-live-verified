"""The one-way valve: prior knowledge may raise scrutiny, never authority.

THE ATTACK THIS MODULE EXISTS FOR
------------------------------------
A memory that influences planning is a persistence surface. Get one record
into it -- by poisoning an evidence file, by compromising one mission, by
writing directly to the store -- and every FUTURE mission reads your text.
This is a strictly worse problem than prompt injection into a single run,
because the injected content survives the run that carried it and nobody is
watching when it fires.

`fleet/planner.py:validate_plan` already intersects any proposed scope with
what the registry granted, and `tower/gateway.py` refuses out-of-scope
requests regardless of what any plan said. So a poisoned record cannot
escalate through those paths today. This module exists because "cannot,
today, via the paths that currently exist" is not the same guarantee as
"cannot, by construction, via any path" -- and the difference between them
is one future commit that passes a recalled string somewhere new.

WHAT A DIRECTIVE MAY CONTAIN
-------------------------------
Exactly four things, and every one of them is monotone in the safe
direction:

    raise_risk_class      -- may only move a step's risk class UP the
                             ordering, never down. A higher class costs more
                             warrant and clears a higher bar at the Gateway.
    require_verification  -- may only ADD a read-only verification step.
    scrutiny_notes        -- text, carried into the plan's notes and the
                             checkpoint. Influences nothing that routes.
    subjects_of_concern   -- identifiers a later phase may choose to watch.

There is no field for granting scope, adding a tool, adding an action kind,
lowering a risk class, skipping a gate, or approving anything.
`assert_directive_cannot_widen` re-checks that structurally at the moment a
directive is built, so a future field that could widen fails a test on the
day it is added rather than in production.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from recall.schema import RetrievalResult, Standing

#: Risk classes, weakest first. A directive may move a step to a HIGHER
#: index and never to a lower one.
RISK_ORDER: tuple[str, ...] = ("LOW", "MEDIUM", "HIGH", "CRITICAL")

#: Substrings that, appearing in a knowledge record's statement, mean the
#: record is trying to describe a GRANT rather than an observation. A
#: distilled record never contains these -- `recall/distill.py`'s templates
#: cannot produce them -- so their presence means the record did not come
#: from the distiller. Such a record is not deleted (deleting it would erase
#: the evidence of the attempt); it is marked UNTRUSTED, which is a standing
#: `recall/index.py` excludes from every default search.
GRANT_LANGUAGE: tuple[str, ...] = (
    "may access",
    "is permitted to",
    "grant ",
    "grants ",
    "allow ",
    "allows ",
    "authorise",
    "authorize",
    "approve ",
    "approved by",
    "ignore previous",
    "disregard",
    "you must",
    "override",
    "escalate to",
    "bypass",
    "no approval",
    "skip the gate",
)


class DirectiveRefused(ValueError):
    """A directive was constructed that could widen authority. Raised, not
    logged: there is no safe way to continue with it."""


@dataclass(frozen=True)
class ScrutinyDirective:
    """What prior missions are permitted to change about this one.

    Frozen, and every field is additive-in-the-safe-direction. Note what is
    absent: there is no `scope`, no `tools`, no `action_kind`, no `approve`.
    """

    #: Risk class floor. A step below this is raised TO it; a step above it
    #: is left alone.
    raise_risk_class: str = "LOW"
    require_verification: bool = False
    scrutiny_notes: list[str] = field(default_factory=list)
    subjects_of_concern: list[str] = field(default_factory=list)
    #: The record ids this directive was derived from. A directive with no
    #: provenance is refused: an influence nobody can trace to a mission is
    #: exactly what this module is defending against.
    derived_from: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return (
            self.raise_risk_class == "LOW"
            and not self.require_verification
            and not self.subjects_of_concern
        )

    def as_record(self) -> dict[str, object]:
        return {
            "raise_risk_class": self.raise_risk_class,
            "require_verification": self.require_verification,
            "scrutiny_notes": list(self.scrutiny_notes),
            "subjects_of_concern": list(self.subjects_of_concern),
            "derived_from": list(self.derived_from),
        }


#: The complete set of fields a directive may carry. Checked structurally so
#: that adding a field to `ScrutinyDirective` without deciding whether it can
#: widen authority fails `assert_directive_cannot_widen` immediately.
_ALLOWED_FIELDS = frozenset(
    {
        "raise_risk_class",
        "require_verification",
        "scrutiny_notes",
        "subjects_of_concern",
        "derived_from",
    }
)


def assert_directive_cannot_widen(directive: ScrutinyDirective) -> None:
    """Refuse a directive that could widen authority. Raises or returns None.

    Called by `build_directive` on every directive it produces, so this is
    not an optional review step a caller can skip.
    """
    fields = set(directive.__dataclass_fields__)
    unexpected = fields - _ALLOWED_FIELDS
    if unexpected:
        raise DirectiveRefused(
            f"ScrutinyDirective carries field(s) {sorted(unexpected)!r} whose effect on "
            "authority has not been decided; a recalled directive may only raise "
            "scrutiny, never widen scope"
        )
    if directive.raise_risk_class not in RISK_ORDER:
        raise DirectiveRefused(
            f"raise_risk_class {directive.raise_risk_class!r} is not one of {list(RISK_ORDER)}"
        )
    if not directive.is_empty and not directive.derived_from:
        raise DirectiveRefused(
            "a non-empty directive with no `derived_from` provenance is refused: an "
            "influence on a mission must name the records it came from"
        )


def raise_to(current: str, floor: str) -> str:
    """Monotone risk-class raise. Never lowers, ever.

    An unrecognised current class is treated as already at the top rather
    than replaced -- an unknown class is not evidence that a lower one is
    safe.
    """
    if current not in RISK_ORDER:
        return current
    if floor not in RISK_ORDER:
        return current
    return current if RISK_ORDER.index(current) >= RISK_ORDER.index(floor) else floor


def screen_statement(statement: str) -> Standing:
    """`UNTRUSTED` if the text reads as a grant rather than an observation.

    Case-insensitive substring screen. Deliberately not a model and
    deliberately not clever: this is the last line, not the first. The first
    is that `recall/distill.py` is the only writer and its templates cannot
    produce this language; the second is that nothing a directive carries can
    widen authority even if a record slips through; this is the third.
    """
    lowered = statement.lower()
    return (
        Standing.UNTRUSTED
        if any(marker in lowered for marker in GRANT_LANGUAGE)
        else Standing.OBSERVED
    )


def build_directive(result: RetrievalResult) -> ScrutinyDirective:
    """Derive the ONLY influence prior missions are allowed to have.

    Reads the retrieved records and produces a directive. Every branch below
    either raises the risk floor, requires a verification, or adds a note.
    None of them can produce a wider scope, a new tool, a skipped gate or an
    approval, because `ScrutinyDirective` has nowhere to put one.

    Records whose statement screens as grant language are excluded here as
    well as by standing, so a record written directly into the store with
    `standing=OBSERVED` still cannot influence anything.
    """
    from recall.schema import RecordKind

    notes: list[str] = []
    subjects: list[str] = []
    derived: list[str] = []
    floor = "LOW"
    require_verification = False

    for item in result.selected:
        record = item.record
        if record.standing is Standing.UNTRUSTED:
            continue
        if screen_statement(record.statement) is Standing.UNTRUSTED:
            notes.append(
                f"record {record.record_id} was excluded: its text reads as a grant, "
                "which a distilled record cannot contain"
            )
            continue

        derived.append(record.record_id)
        if record.kind in (RecordKind.AGENT_ISOLATION, RecordKind.SCOPE_ESCALATION):
            floor = raise_to(floor, "MEDIUM")
            subjects.append(record.subject)
            notes.append(
                f"prior mission {record.mission_id} recorded {record.kind.value} for "
                f"{record.subject}; risk floor raised to MEDIUM"
            )
        elif record.kind is RecordKind.DISPUTED_PREMISE:
            require_verification = True
            subjects.append(record.subject)
            notes.append(
                f"prior mission {record.mission_id} left {record.subject} DISPUTED; "
                "an independent verification step is required"
            )
        elif record.kind is RecordKind.WORKER_FAULT:
            notes.append(f"prior mission {record.mission_id} saw a {record.subject} worker fault")
        elif record.kind is RecordKind.EVIDENCE_COVERAGE:
            completeness = float(record.value.get("completeness", 1.0) or 1.0)
            if completeness < 0.9:
                require_verification = True
                notes.append(
                    f"prior mission {record.mission_id} measured evidence coverage at "
                    f"{completeness:.2f}; an independent verification step is required"
                )

    directive = ScrutinyDirective(
        raise_risk_class=floor,
        require_verification=require_verification,
        scrutiny_notes=notes,
        subjects_of_concern=sorted(set(subjects)),
        derived_from=sorted(set(derived)),
    )
    assert_directive_cannot_widen(directive)
    return directive


__all__ = [
    "GRANT_LANGUAGE",
    "RISK_ORDER",
    "DirectiveRefused",
    "ScrutinyDirective",
    "assert_directive_cannot_widen",
    "build_directive",
    "raise_to",
    "screen_statement",
]
