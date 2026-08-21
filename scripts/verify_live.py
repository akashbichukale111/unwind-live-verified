"""`make verify-live` — everything that needs real credentials, in one command.

Branch B of Task 5 §5.0: credentials live on the maintainer's machine, not in
the build container. This script is what they run there. It does, in order:

    1. asserts credentials exist and FAILS LOUDLY if they do not
    2. makes one real Vertex call and prints the raw response
    3. runs the parser-only vs parser-plus-Gemini recall comparison
    4. runs T2 over the undecidable queue with the real model
    5. writes docs/LIVE-VERIFICATION.md
    6. prints a summary short enough to paste back

⚠ IT NEVER FALLS BACK TO THE STUB. Every failure path here exits non-zero with
the specific reason. A verification script that silently degrades to a scripted
model produces a document full of numbers that look measured, which is worse
than producing nothing at all.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

os.environ.setdefault("UNWIND_OTEL_CONSOLE", "0")

EXIT_NO_CREDENTIALS = 2
EXIT_VERTEX_UNREACHABLE = 3
EXIT_STUB_REFUSED = 4


def fail(code: int, headline: str, *lines: str) -> None:
    print("", file=sys.stderr)
    print("=" * 70, file=sys.stderr)
    print(f"VERIFY-LIVE FAILED: {headline}", file=sys.stderr)
    print("=" * 70, file=sys.stderr)
    for line in lines:
        print(line, file=sys.stderr)
    print("", file=sys.stderr)
    print(
        "Nothing was written. This script does not fall back to the scripted "
        "model, because a document of stub numbers that reads as measured is "
        "worse than no document.",
        file=sys.stderr,
    )
    raise SystemExit(code)


def main() -> int:
    from lib.config import get_config
    from lib.vertex import materialise_credentials

    # ---- 1. credentials ---------------------------------------------------
    materialise_credentials()
    cfg = get_config()

    if cfg.vertex_disabled:
        fail(
            EXIT_NO_CREDENTIALS,
            "UNWIND_VERTEX_DISABLED is set",
            "This run is explicitly forbidden from calling a model.",
            "Unset UNWIND_VERTEX_DISABLED and run again.",
        )

    if cfg.project_id == "unwind-local":
        fail(
            EXIT_NO_CREDENTIALS,
            "no GCP project resolved",
            f"project_id resolved to {cfg.project_id!r}, which is the no-account default.",
            "",
            "Set ONE of these and run again:",
            "  export UNWIND_PROJECT_ID=<your-project>       # if using ADC / gcloud",
            "  export GOOGLE_APPLICATION_CREDENTIALS=<key.json>",
            "  export GOOGLE_APPLICATION_CREDENTIALS_JSON='<key contents>'",
        )

    print("=" * 70)
    print("UNWIND — live verification")
    print("=" * 70)
    print(f"project  : {cfg.project_id}")
    print(f"location : {cfg.vertex_location}")
    print(f"model    : {cfg.model_fast}")
    print("-" * 70)

    # ---- 2. one real call -------------------------------------------------
    from lib.vertex import get_vertex_client

    print("[1/4] one real Vertex call ...")
    try:
        raw = get_vertex_client().generate_text(
            "In one sentence: what does cache invalidation have to do with "
            "decisions that rest on facts which later change?"
        )
    except Exception as exc:  # noqa: BLE001
        fail(
            EXIT_VERTEX_UNREACHABLE,
            f"{type(exc).__name__}",
            str(exc),
            "",
            "Credentials resolved but the endpoint refused. Check that the",
            "Vertex AI API is enabled and the principal holds roles/aiplatform.user.",
        )
    if not raw.strip():
        fail(EXIT_VERTEX_UNREACHABLE, "Vertex returned an empty response")

    print("  RAW RESPONSE:")
    for line in raw.strip().splitlines():
        print(f"    {line}")
    print("")

    # ---- 3. the headline measurement --------------------------------------
    from judgment.cli import _artifacts
    from judgment.model import VertexT2Model
    from judgment.recall_compare import StubRefusedError, compare, render_markdown

    model = VertexT2Model(model_id=cfg.model_fast)
    artifacts = _artifacts()
    as_of = datetime(2026, 7, 6, 9, 0, tzinfo=UTC)

    print(f"[2/4] recall comparison over {len(artifacts)} artifacts ...")
    try:
        comparison = compare(artifacts, model=model, as_of=as_of)
    except StubRefusedError as exc:
        fail(EXIT_STUB_REFUSED, "the model refused to be measured", str(exc))

    print(f"  parser only      : {_pct(comparison.parser_recall)}")
    print(f"  parser + Gemini  : {_pct(comparison.combined_recall)}")
    print(f"  delta            : {_pp(comparison.delta)}")
    print("")

    # ---- 4. T2 over the undecidable queue ---------------------------------
    print("[3/4] T2 over the undecidable queue ...")
    t2_summary = _run_t2(model, as_of)
    print(f"  queue            : {t2_summary['queue_size']}")
    print(f"  resolved         : {t2_summary['resolved']}")
    print(f"  still unresolved : {t2_summary['unresolved']}")
    print("")

    # ---- 5. write the document -------------------------------------------
    print("[4/4] writing docs/LIVE-VERIFICATION.md ...")
    ran_at = datetime.now(UTC)
    body = render_markdown(comparison, ran_at=ran_at, project=cfg.project_id)
    body += _t2_section(t2_summary)
    body += _raw_section(raw, cfg)
    out = REPO / "docs" / "LIVE-VERIFICATION.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(body, encoding="utf-8")
    print(f"  wrote {out.relative_to(REPO)}")
    print("")

    # ---- 6. the pasteable summary ----------------------------------------
    print("=" * 70)
    print("PASTE THIS BACK")
    print("=" * 70)
    print(
        json.dumps(
            {
                "branch": "B (credentialed run on maintainer machine)",
                "project": cfg.project_id,
                "location": cfg.vertex_location,
                "model": cfg.model_fast,
                "vertex_call": "OK",
                "raw_response_first_line": raw.strip().splitlines()[0][:200],
                "parser_only_recall": comparison.parser_recall,
                "parser_plus_gemini_recall": comparison.combined_recall,
                "delta": comparison.delta,
                "gold_claims": comparison.gold,
                "by_class_delta": {
                    label: c.delta for label, c in sorted(comparison.by_class.items())
                },
                "t2": t2_summary,
                "model_errors": len(comparison.model_errors),
            },
            indent=2,
            sort_keys=True,
        )
    )
    print("=" * 70)
    return 0


#: How much of the queue a live run assesses. Each node is two model calls
#: (re-derive, then assess), so the whole queue would be ~350 calls and several
#: minutes. The cap keeps `make verify-live` a thing a person will actually run.
T2_LIMIT = 60


def _run_t2(model, as_of: datetime) -> dict:
    """Drive the EXISTING T2 path with the real model. No new capability.

    Deliberately mirrors `judgment.cli t2` call for call -- `build_bundle`, then
    `re_derive`, then `assess` with the original value supplied only to the
    assessor. Re-implementing the sequence here would let this script quietly
    disagree with the path it claims to be verifying, and the obvious way to get
    it wrong is to hand the re-deriver the answer.
    """
    from judgment.assessor import assess
    from judgment.rederive import build_bundle, re_derive
    from lib.schema import Regime
    from spine.cascade import CorpusStore, run_cascade

    store = CorpusStore.from_repo(REPO)
    result = run_cascade(
        store=store,
        claim_id="clm_000000",
        source_id="src_supplier_K",
        new_value=20,
        reason="live verification",
        triggered_at=as_of,
    )
    queue = [v for v in result.radius.values() if v.regime is Regime.UNRESOLVED]

    outcomes: dict[str, int] = {}
    errors: list[str] = []
    # ⚠ MEASURE WHY, DO NOT NARRATE IT. `assess()` returns UNRESOLVED before the
    # model's answer is consulted whenever the original commitment carries no
    # numeric term. If that is why the queue resolves nothing, the run is a
    # NON-TEST rather than a model result, and the document must say which.
    no_numeric_term = 0
    for verdict in sorted(queue, key=lambda v: v.conclusion_id)[:T2_LIMIT]:
        conclusion = store.get_conclusion(verdict.conclusion_id)
        if conclusion is not None and conclusion.committed_lead_days is None:
            no_numeric_term += 1
        premises: dict[str, object] = {}
        if conclusion:
            for premise_id in conclusion.premise_ids:
                claim = store.get_claim(premise_id)
                if claim:
                    premises[claim.canonical] = claim.value
        try:
            bundle = build_bundle(
                decision_kind=conclusion.kind.value if conclusion else "unknown",
                premises=premises,
                correlation_id=verdict.conclusion_id,
            )
            derivation = re_derive(bundle, model, now=as_of)
            assessment = assess(
                derivation,
                original_committed_lead_days=(
                    conclusion.committed_lead_days if conclusion else None
                ),
                now=as_of,
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{verdict.conclusion_id}: {type(exc).__name__}: {exc}")
            continue
        outcome = assessment.verdict.outcome.value
        outcomes[outcome] = outcomes.get(outcome, 0) + 1

    unresolved = outcomes.get("unresolved", 0)
    attempted = min(len(queue), T2_LIMIT)
    queue_without_numeric_term = sum(
        1
        for v in queue
        if (c := store.get_conclusion(v.conclusion_id)) is not None
        and c.committed_lead_days is None
    )
    return {
        "queue_size": len(queue),
        "attempted": attempted,
        "outcomes": outcomes,
        "resolved": attempted - unresolved - len(errors),
        "unresolved": unresolved,
        "errors": errors[:5],
        "attempted_without_numeric_term": no_numeric_term,
        "queue_without_numeric_term": queue_without_numeric_term,
        "is_non_test": no_numeric_term == attempted and attempted > 0,
    }


def _t2_section(summary: dict) -> str:
    lines = [
        "",
        "## T2 over the undecidable queue",
        "",
        "The nodes T1 could not decide arithmetically, run against the live model.",
        "",
        f"- Queue size: **{summary['queue_size']}**",
        f"- Attempted (capped): **{summary['attempted']}**",
        f"- Resolved by the model: **{summary['resolved']}**",
        f"- Still UNRESOLVED: **{summary['unresolved']}**",
        f"- Exceptions: **{len(summary['errors'])}**",
        "",
    ]

    if summary.get("is_non_test"):
        # The honest reading, derived from the data rather than assumed.
        lines += [
            "### ⚠ This is a NON-TEST, not a model result",
            "",
            f"All **{summary['attempted_without_numeric_term']} of "
            f"{summary['attempted']}** attempted nodes carry "
            "`committed_lead_days = None` "
            f"({summary['queue_without_numeric_term']} of "
            f"{summary['queue_size']} across the whole queue).",
            "",
            "`judgment/assessor.py` returns UNRESOLVED whenever the original",
            "commitment carries no numeric term, and that branch executes **before**",
            "**the model's answer is consulted**. So the outcome was fixed by the",
            "corpus, not decided by Gemini. A different sample behaves identically.",
            "",
            "**Zero resolved is neither success nor failure here.** What the run does",
            "establish: the T2 path executes end to end against a live Vertex model",
            f"with {len(summary['errors'])} exceptions across {summary['attempted']} nodes",
            f"({summary['attempted'] * 2} model calls). Orchestration verified;",
            "**judgement quality remains unmeasured.**",
            "",
            "See `docs/T2-MEASUREMENT.md` for why a fair fixture was not built.",
            "",
        ]
    else:
        lines += [
            "UNRESOLVED remaining is not automatically a failure. The assessor",
            "under-reports by design: a thin margin returns UNRESOLVED rather than",
            "escalating, because an obligation an owner rejects burns the attention",
            "the real ones need. But note how many nodes could have resolved at all:",
            "",
            f"- Attempted nodes with NO numeric term (cannot resolve by construction): "
            f"**{summary.get('attempted_without_numeric_term', 0)}**",
            "",
        ]

    if summary["errors"]:
        lines.append("Errors encountered:")
        lines.append("")
        for err in summary["errors"]:
            lines.append(f"- `{err}`")
        lines.append("")
    return "\n".join(lines)


def _raw_section(raw: str, cfg) -> str:
    return "\n".join(
        [
            "",
            "## The raw Vertex response",
            "",
            "One real call, pasted verbatim. This is the artifact that proves the",
            "mandatory Gemini-via-Vertex requirement is satisfied by running code.",
            "",
            "```",
            raw.strip(),
            "```",
            "",
            f"Model `{cfg.model_fast}`, project `{cfg.project_id}`, location "
            f"`{cfg.vertex_location}`.",
            "",
            "### Why Flash and not Pro",
            "",
            "As of 2026-08-12 no Gemini 3.x **Pro** model is GA -- the 3.x Pro line is",
            "preview only. Both models this repository uses are GA, which is a deliberate",
            "choice for live-demo reliability: a preview model can change or throttle",
            "underneath a demo, and the delta above does not need Pro to be persuasive.",
            "",
        ]
    )


def _pct(value: float | None) -> str:
    return "unmeasured" if value is None else f"{value * 100:.1f}%"


def _pp(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:+.1f} pp"


if __name__ == "__main__":
    raise SystemExit(main())
