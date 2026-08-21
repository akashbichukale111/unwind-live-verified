"""The impact cartographer -- orders the radius by exposure, deterministically.

A blast radius arrives as an unordered set of thousands. Nothing downstream can
consume that: the budgeter needs to know how bad this is, the operator needs to
see the worst first, and a later tier that can only afford to look at fifty
nodes needs the right fifty.

So exposure is a total order, computed from facts already on the node, with no
model and no tie-breaking by luck. Ties break on conclusion id so two runs
produce the same list, not merely the same set.

WHAT COUNTS AS EXPOSURE, AND WHY EACH TERM IS THERE
---------------------------------------------------
  money        what is already committed in cash terms
  irreversible how hard the effect is to take back at all
  escaped      whether it is outside the company yet
  material     whether it is actually harmed
  load         how much else was built on top of it
  age          how long it has been standing, unchallenged

`age` is the term most systems would leave out, and it is the one that matters
most here: a commitment made in January and never revisited is more dangerous
than the same commitment made last week, because everything downstream has had
six months to be built on it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from lib.config import Tier
from lib.schema import Conclusion
from lib.telemetry import tool_call_span
from spine.escapement import EscapementVerdict
from spine.materiality import MaterialityVerdict

#: Weights are stated here rather than scattered, so the ordering can be argued
#: with. [ASSUMPTION] These are judgement, not measurement -- they set the shape
#: of the ranking, and no claim is made that they are calibrated to anything.
W_MONEY = 0.40
W_IRREVERSIBILITY = 0.20
W_ESCAPED = 0.15
W_MATERIAL = 0.15
W_LOAD = 0.05
W_AGE = 0.05

#: Money is compressed logarithmically: the gap between $0 and $10k matters far
#: more than the gap between $500k and $510k.
MONEY_SCALE_MINOR = 1_000_000.0  # USD 10,000.00
AGE_SCALE_DAYS = 365.0


@dataclass(frozen=True)
class ExposureScore:
    conclusion_id: str
    exposure: float
    money_minor: int
    irreversibility: float
    escaped: bool
    material: bool | None
    depth: int
    age_days: float
    #: Every term, so a ranking can be explained rather than trusted.
    terms: dict[str, float]


def _log1p_scaled(value: float, scale: float) -> float:
    """Compress to roughly 0..1 without ever exceeding 1 for sane inputs."""
    import math

    if value <= 0:
        return 0.0
    return min(1.0, math.log1p(value / scale) / math.log1p(10.0))


def score_exposure(
    conclusion: Conclusion | None,
    conclusion_id: str,
    depth: int,
    materiality: MaterialityVerdict,
    escapement: EscapementVerdict,
    load_weight: float,
    as_of: datetime,
) -> ExposureScore:
    money = escapement.amount_minor_at_risk
    irreversibility = escapement.worst_irreversibility
    age_days = 0.0
    if conclusion is not None:
        age_days = max(0.0, (as_of - conclusion.decided_at).total_seconds() / 86400.0)

    terms = {
        "money": W_MONEY * _log1p_scaled(money, MONEY_SCALE_MINOR),
        "irreversibility": W_IRREVERSIBILITY * irreversibility,
        "escaped": W_ESCAPED * (1.0 if escapement.escaped else 0.0),
        "material": W_MATERIAL * (1.0 if materiality.material else 0.0),
        "load": W_LOAD * min(1.0, load_weight / 10.0),
        "age": W_AGE * min(1.0, age_days / AGE_SCALE_DAYS),
    }
    return ExposureScore(
        conclusion_id=conclusion_id,
        exposure=round(sum(terms.values()), 6),
        money_minor=money,
        irreversibility=irreversibility,
        escaped=escapement.escaped,
        material=materiality.material,
        depth=depth,
        age_days=round(age_days, 2),
        terms={k: round(v, 6) for k, v in terms.items()},
    )


def rank(scores: list[ExposureScore]) -> list[ExposureScore]:
    """Highest exposure first. Ties break on conclusion id, never on chance."""
    with tool_call_span("impact_cartographer", Tier.T1, nodes=len(scores)) as span:
        ordered = sorted(scores, key=lambda s: (-s.exposure, s.conclusion_id))
        if ordered:
            span.set_attribute("unwind.top_exposure", ordered[0].exposure)
        return ordered
