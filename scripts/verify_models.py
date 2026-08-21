"""Verify the four Google model integrations against a REAL project. Credit-safe.

RUN THIS AFTER AUTHENTICATING:

    gcloud auth application-default login
    gcloud auth application-default set-quota-project <your-project-id>
    export UNWIND_PROJECT_ID=<your-project-id>
    make verify-models                 # or: python scripts/verify_models.py

WHAT IT DOES, AND WHAT IT DELIBERATELY DOES NOT
--------------------------------------------------
Four checks, in dependency order, stopping early where a later check cannot
possibly pass. Each one makes AT MOST ONE request. There are no retries, no
loops, and no second attempt at anything expensive -- this script is designed
to be run against a project on promotional credits, and burning credits to
prove the same fact twice is a bug, not thoroughness.

    GEMINI   one text call, ~10 output tokens.        Cost: negligible.
    GEMMA    one text call, ~10 output tokens.        Cost: negligible.
    VEO      ONE video generation.                    Cost: REAL. Opt-in only.
    LYRIA    ONE audio generation.                    Cost: REAL. Opt-in only.

**The two media generations do not run unless you pass `--media`.** A bare
run verifies authentication and both text models for effectively nothing,
which is the check you want 95% of the time. Ask for media explicitly, once,
when you actually want the artefact.

WHAT IT WRITES
-----------------
`evidence/models/verification-<timestamp>.json` -- a machine-readable record
of what was attempted, what came back, and the verbatim error for anything
that failed. Never a secret: no key, no token, no credential contents.

EXIT CODE
------------
0 only if every check that was ATTEMPTED succeeded. A skipped media check
does not fail the run; a failed one does.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

#: The smallest prompt that still proves the response came from the model
#: rather than from a cache or a stub: the model must echo a token that
#: appears nowhere in this repository's committed outputs.
SENTINEL = "UNWIND_VERTEX_LIVE"
PROBE = f"Return exactly this token and nothing else: {SENTINEL}"

results: list[dict] = []


def record(name: str, status: str, detail: dict) -> dict:
    row = {"check": name, "status": status, **detail}
    results.append(row)
    mark = {"LIVE_VERIFIED": "OK  ", "SKIPPED": "SKIP"}.get(status, "FAIL")
    print(f"  [{mark}] {name}: {status}")
    for key in ("model", "auth_mode", "project", "latency_ms", "artifact", "reason"):
        if row.get(key):
            value = str(row[key])
            print(f"           {key}: {value[:160]}")
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--media",
        action="store_true",
        help="ALSO run one Veo and one Lyria generation. These cost real credits.",
    )
    args = parser.parse_args()

    # A verification run must never be silently neutered by the outage switch.
    if os.environ.get("UNWIND_VERTEX_DISABLED"):
        print("UNWIND_VERTEX_DISABLED is set; unset it to verify real models.")
        return 2

    print("=" * 72)
    print("UNWIND — Google model verification")
    print("=" * 72)

    # ---- 0. AUTH ---------------------------------------------------------
    from lib.gcp_auth import api_keys_disallowed, reset_auth_cache, resolve_auth

    reset_auth_cache()
    auth = resolve_auth(allow_api_key=not api_keys_disallowed())
    print("\n0. AUTHENTICATION")
    if not auth.available:
        record("auth", "AUTH_REQUIRED", {"reason": auth.reason})
        _write(args)
        print("\nNo credential. Nothing was called; no credits were spent.")
        return 1
    record(
        "auth",
        "LIVE_VERIFIED",
        {"auth_mode": auth.mode, "project": auth.project, "source": auth.source},
    )

    from lib.config import get_config

    cfg = get_config()

    # ---- 1. GEMINI -------------------------------------------------------
    print("\n1. GEMINI — one tiny text call")
    gemini_ok = _probe_text(
        "gemini",
        cfg.model_deep,
        lambda: _call_text(cfg.model_deep, "gemini", disable_thinking=True),
    )

    # ---- 2. GEMMA --------------------------------------------------------
    # Gemma is the independent-family verifier behind COUNTERSIGN. It is
    # checked with the same tiny probe rather than a countersign case,
    # because what needs proving here is reachability, not the verdict logic
    # (which tests/test_countersign_verify.py already covers offline).
    print("\n2. GEMMA — one tiny text call")
    _probe_text("gemma", cfg.gemma_model, lambda: _call_text(cfg.gemma_model, "gemini"))

    # ---- 3/4. MEDIA ------------------------------------------------------
    if not args.media:
        print("\n3. VEO   — SKIPPED (pass --media to spend credits on one generation)")
        record("veo", "SKIPPED", {"model": cfg.veo_model, "reason": "--media not passed"})
        print("4. LYRIA — SKIPPED (pass --media to spend credits on one generation)")
        record("lyria", "SKIPPED", {"model": cfg.lyria_model, "reason": "--media not passed"})
    elif not gemini_ok:
        # Do not spend real money probing media when the cheap text call
        # already proved the credential cannot reach this project's models.
        reason = "skipped: the free Gemini probe failed, so media would fail too"
        print(f"\n3/4. VEO + LYRIA — SKIPPED ({reason})")
        record("veo", "SKIPPED", {"model": cfg.veo_model, "reason": reason})
        record("lyria", "SKIPPED", {"model": cfg.lyria_model, "reason": reason})
    else:
        print("\n3. VEO — ONE real generation (this costs credits)")
        _probe_media("veo")
        print("\n4. LYRIA — ONE real generation (this costs credits)")
        _probe_media("lyria")

    path = _write(args)
    attempted = [r for r in results if r["status"] != "SKIPPED"]
    failed = [r for r in attempted if r["status"] != "LIVE_VERIFIED"]
    print("\n" + "=" * 72)
    print(f"{len(attempted) - len(failed)}/{len(attempted)} attempted checks verified")
    print(f"evidence: {path}")
    if failed:
        print("\nFAILED:")
        for row in failed:
            print(f"  {row['check']}: {row['status']} — {str(row.get('reason', ''))[:200]}")
    return 1 if failed else 0


def _probe_text(name: str, model: str, call) -> bool:
    from media.adapters import classify_failure

    started = time.monotonic()
    try:
        text = call()
    except Exception as exc:  # noqa: BLE001
        status, reason = classify_failure(exc)
        record(name, status.value, {"model": model, "reason": reason})
        return False
    latency = int((time.monotonic() - started) * 1000)
    # The response must actually contain the sentinel. A 200 that returns
    # something else is not a verified model call, it is a surprise.
    if SENTINEL not in text:
        record(
            name,
            "ERROR",
            {
                "model": model,
                "latency_ms": latency,
                "reason": f"responded, but without the sentinel. Got: {text[:200]!r}",
            },
        )
        return False
    record(
        name, "LIVE_VERIFIED", {"model": model, "latency_ms": latency, "echo": text.strip()[:80]}
    )
    return True


def _call_text(model: str, modality: str, *, disable_thinking: bool = False) -> str:
    """One request through the SAME client builder the product uses."""
    from google.genai import types

    from media.adapters import _client

    client = _client(modality)
    config_kwargs: dict = {"max_output_tokens": 32, "temperature": 0.0}
    if disable_thinking:
        # The configured deep Gemini model thinks by default, and thoughts count against
        # max_output_tokens -- at a 32-token cap that leaves nothing for the
        # visible answer (observed: 187 thought tokens, 0 answer tokens).
        # This probe needs verbatim echo, not reasoning, so turning thinking
        # off is strictly cheaper and makes the cap meaningful again.
        config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
    response = client.models.generate_content(
        model=model,
        contents=PROBE,
        # Hard cap. A verification probe that could return a thousand tokens
        # is a verification probe that can surprise you on the bill.
        config=types.GenerateContentConfig(**config_kwargs),
    )
    return response.text or ""


def _probe_media(modality: str) -> None:
    """One real generation via the product's own adapter."""
    from media.adapters import MediaStatus, generate_replay, generate_signal
    from media.grounding import MissionBrief, MissionMoment

    brief = MissionBrief(
        mission_id="verification",
        objective="model verification probe",
        status="COMPLETED",
        moments=[MissionMoment(seq=1, phase="PLAN", status="LIVE", summary="probe")],
        arc=["PLAN"],
        checkpoint_count=1,
    )
    result = (generate_replay if modality == "veo" else generate_signal)(brief)
    if result.status is MediaStatus.GENERATED:
        exists = Path(result.artifact_path).exists() if result.artifact_path else False
        record(
            modality,
            "LIVE_VERIFIED" if exists else "ERROR",
            {
                "model": result.model,
                "latency_ms": result.latency_ms,
                "artifact": result.artifact_path,
                "reason": "" if exists else "adapter reported GENERATED but no file exists",
            },
        )
        return
    record(modality, result.status.value, {"model": result.model, "reason": result.reason})


def _write(args) -> Path:
    directory = REPO / "evidence" / "models"
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = directory / f"verification-{stamp}.json"
    path.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(UTC).isoformat(),
                "media_requested": bool(args.media),
                "sentinel": SENTINEL,
                "results": results,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


if __name__ == "__main__":
    sys.exit(main())
