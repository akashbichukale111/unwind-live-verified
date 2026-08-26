"""The coverage auditor. THE HONESTY INSTRUMENT.

It measures what extraction actually caught against a labelled corpus and writes
the answer to `docs/COVERAGE.md`, including the class it is worst at. Its whole
purpose is to make the gaps visible rather than let them be inferred from a
cascade that quietly reached less than it should have.

ONE RULE, ENFORCED IN CODE
--------------------------
    IT MAY MARK A DECISION `unresolved`. IT MAY NEVER MARK ONE `safe`.

A decision whose premises were under-extracted has not been shown to be
unharmed; it has been shown to be unexamined. Those are opposite claims and the
difference is the entire product. `mark_coverage()` therefore has no code path
that returns a clean status, and
`tests/test_judgment.py::test_the_never_safe_guard_catches_a_clean_status` is a
vacuity case asserting the guard would catch one if it appeared.

RELATIVE DATES GET THEIR OWN ROW
--------------------------------
"within 30 days of order" and "next quarter" fail differently, and averaging
them hides the second. The matrix reports relative-date resolution separately.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from lib.config import Tier
from lib.schema import ConclusionStatus
from lib.telemetry import tool_call_span
from spine.extract import extract

AUDITOR_ID = "coverage-auditor@0.3.0"

#: Below this recall, decisions resting on the claim type are marked UNRESOLVED.
#: [ASSUMPTION] A judgement about when coverage is too thin to reason from.
COVERAGE_FLOOR = 0.80


class CoverageOverreach(RuntimeError):
    """The auditor was asked to declare something safe. It cannot."""


@dataclass
class ClassCoverage:
    """One row of the confusion matrix."""

    label: str
    gold: int = 0
    extracted: int = 0
    correct: int = 0
    wrong_value: int = 0
    missed: int = 0
    spurious: int = 0

    @property
    def recall(self) -> float | None:
        return round(self.correct / self.gold, 4) if self.gold else None

    @property
    def precision(self) -> float | None:
        return round(self.correct / self.extracted, 4) if self.extracted else None


@dataclass
class CoverageReport:
    as_of: datetime
    by_class: dict[str, ClassCoverage] = field(default_factory=dict)
    artifacts_audited: int = 0
    #: Artifacts where recognised attributes produced no value -- the honest
    #: "we saw something and could not read it" bucket.
    unresolved_attributes: int = 0
    injection_artifacts: int = 0

    @property
    def overall_recall(self) -> float | None:
        gold = sum(c.gold for c in self.by_class.values())
        correct = sum(c.correct for c in self.by_class.values())
        return round(correct / gold, 4) if gold else None

    @property
    def worst_class(self) -> ClassCoverage | None:
        scored = [c for c in self.by_class.values() if c.gold and c.recall is not None]
        return min(scored, key=lambda c: (c.recall, c.label), default=None)

    def under_covered(self, floor: float = COVERAGE_FLOOR) -> list[str]:
        return sorted(
            label
            for label, cov in self.by_class.items()
            if cov.gold and cov.recall is not None and cov.recall < floor
        )


def audit(artifacts: list[dict], as_of: datetime) -> CoverageReport:
    """Run extraction over the labelled set and score it. No model call."""
    with tool_call_span("coverage_audit", Tier.T1, artifacts=len(artifacts)) as span:
        report = CoverageReport(as_of=as_of, artifacts_audited=len(artifacts))
        rows: dict[str, ClassCoverage] = defaultdict(lambda: ClassCoverage(label=""))

        def row(label: str) -> ClassCoverage:
            if not rows[label].label:
                rows[label] = ClassCoverage(label=label)
            return rows[label]

        for artifact in sorted(artifacts, key=lambda a: a["artifact_id"]):
            received = datetime.fromisoformat(artifact["received_at"].replace("Z", "+00:00"))
            result = extract(
                artifact_id=artifact["artifact_id"],
                text=artifact["text"],
                subject=artifact["subject"],
                source_id=artifact["source_id"],
                authority_scope=[artifact["source_id"]],
                received_at=received,
            )
            if result.unresolved_attributes:
                report.unresolved_attributes += 1
            if "IGNORE ALL PREVIOUS" in artifact["text"].upper():
                report.injection_artifacts += 1

            gold = {g["suffix"]: g for g in artifact["gold_claims"]}
            found = {e.claim.canonical.rsplit(".", 1)[-1]: e for e in result.extractions}

            for suffix, expected in gold.items():
                label = _label_for(suffix, found.get(suffix))
                entry = row(label)
                entry.gold += 1
                extraction = found.get(suffix)
                if extraction is None:
                    entry.missed += 1
                elif abs(float(extraction.claim.value) - float(expected["value"])) < 1e-6:
                    entry.correct += 1
                    entry.extracted += 1
                else:
                    entry.wrong_value += 1
                    entry.extracted += 1

            for suffix, extraction in found.items():
                if suffix not in gold:
                    entry = row(_label_for(suffix, extraction))
                    entry.spurious += 1
                    entry.extracted += 1

        report.by_class = dict(sorted(rows.items()))
        span.set_attribute("unwind.overall_recall", report.overall_recall or 0.0)
        return report


def _label_for(suffix: str, extraction) -> str:
    """Bucket a claim into a matrix row. Relative dates get their own."""
    if extraction is not None and extraction.used_relative_resolution:
        return "temporal:relative-date"
    if suffix.endswith("_days"):
        return "temporal:absolute-duration"
    if suffix.endswith("_pct"):
        return "numeric:percentage"
    if suffix.endswith("_usd"):
        return "numeric:currency"
    return "numeric:quantity"


def mark_coverage(
    current: ConclusionStatus, claim_type_labels: list[str], report: CoverageReport
) -> tuple[ConclusionStatus, str | None]:
    """Mark a decision's status from coverage. UNRESOLVED or unchanged. NEVER safe.

    There is deliberately no branch that returns a clean status. The worst this
    function can do to a healthy decision is leave it exactly as it found it, and
    the best it can do for an under-covered one is say so.
    """
    under = set(report.under_covered())
    hit = sorted(under.intersection(claim_type_labels))
    if not hit:
        return current, None

    reason = (
        f"Extraction recall is below {COVERAGE_FLOOR:.0%} for {', '.join(hit)}. "
        "This decision's premises may be incompletely extracted, so it has not "
        "been shown to be unharmed -- it has been shown to be unexamined. "
        "Marked UNRESOLVED."
    )
    return ConclusionStatus.UNRESOLVED, reason


def assert_never_marks_safe(status: ConclusionStatus) -> None:
    """Guard used by the vacuity test. Any 'clean' status from here is a bug."""
    if status in {ConclusionStatus.CORRECTED, ConclusionStatus.SUPERSEDED}:
        raise CoverageOverreach(
            f"The coverage auditor produced {status.value!r}. It may mark a "
            "decision UNRESOLVED or leave it alone; declaring one settled is a "
            "claim about the world that a recall measurement cannot support."
        )


def render_markdown(report: CoverageReport, model_note: str) -> str:
    """The committed artifact. Names the worst class rather than burying it."""
    worst = report.worst_class
    lines = [
        "# Extraction coverage",
        "",
        "Produced by `make coverage` (`judgment/coverage.py`) against the labelled",
        "artifact set in `corpus/data/artifacts.jsonl`. Regenerated in CI; a drift",
        "fails the build.",
        "",
        f"- Artifacts audited: **{report.artifacts_audited}**",
        f"- Overall recall: **{_pct(report.overall_recall)}**",
        f"- Artifacts with a recognised attribute but no readable value: "
        f"**{report.unresolved_attributes}** (these become UNRESOLVED, never 'no premise')",
        f"- Prompt-injection artifacts in the set: **{report.injection_artifacts}** "
        "(the parser has no instruction surface, so they yield nothing)",
        "",
        "## Confusion matrix",
        "",
        "| Class | Gold | Correct | Wrong value | Missed | Spurious | Recall | Precision |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for cov in report.by_class.values():
        lines.append(
            f"| `{cov.label}` | {cov.gold} | {cov.correct} | {cov.wrong_value} | "
            f"{cov.missed} | {cov.spurious} | {_pct(cov.recall)} | {_pct(cov.precision)} |"
        )

    lines += [
        "",
        "## ⚠ Worst-performing class",
        "",
    ]
    if worst is None:
        lines.append("No class carried gold labels, so nothing can be ranked.")
    else:
        lines.append(
            f"**`{worst.label}` — recall {_pct(worst.recall)}** "
            f"({worst.correct}/{worst.gold} correct, {worst.missed} missed)."
        )
        lines.append("")
        lines.append(
            "Decisions resting on this class are marked `unresolved` by "
            f"`mark_coverage()` while recall is under {COVERAGE_FLOOR:.0%}. The "
            "auditor may mark a decision unresolved; it may never mark one safe."
        )

    under = report.under_covered()
    lines += [
        "",
        f"Under-covered classes (recall < {COVERAGE_FLOOR:.0%}): "
        + (", ".join(f"`{u}`" for u in under) if under else "none"),
        "",
        "## What these numbers do and do not mean",
        "",
        "**They measure this parser against this corpus.** The artifacts and the",
        "extraction lexicon were written by the same author, so a recall of 1.0",
        "would have meant nothing. The corpus therefore includes phrasings the",
        "lexicon was deliberately not built around — spelled-out numerals, unlisted",
        'synonyms such as "turnaround" and "cycle time", and values referred to',
        "but stated elsewhere. The misses below are real misses of this parser.",
        "",
        "**They say nothing about real supplier email.** No claim is made that this",
        "distribution resembles production text.",
        "",
        model_note,
        "",
    ]
    return "\n".join(lines)


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value:.1%}"


def write_report(report: CoverageReport, path: Path, model_note: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_markdown(report, model_note), encoding="utf-8")
    return path
