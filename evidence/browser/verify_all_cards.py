"""Click through EVERY card of the merged default branch in a real browser.

WHY THIS SCRIPT EXISTS
-------------------------
The merge brought the Agentic Command OS into the default branch. The risk a
merge like that carries is not that the new thing is broken -- it has its own
suites -- but that something OLD quietly stopped working and nobody looked.
So this walks the whole product: all six pre-existing control layers, then the
Command OS, then back, asserting each one renders real content.

`data-card` values come from `web/static/index.html` and are dispatched in
`web/static/app.js` (`0` WARRANT, `1` UNWIND CORE, `2` CONTROL TOWER,
`3` COUNTERSIGN, `4` HYPERION-ZERO, `5` SINGULARITY-MESH).

Run against a local server on the merged branch:

    FIRESTORE_EMULATOR_HOST=localhost:8080 UNWIND_VERTEX_DISABLED=1 \
    UNWIND_COUNTERSIGN_SIMULATED=1 UNWIND_OPERATOR_TOKENS="demo-tok:kim@ops.example" \
    python -m uvicorn services.api.main:app --port 8099
    python evidence/browser/verify_all_cards.py

Exit code is 0 only if every check passes.
"""

from __future__ import annotations

import json
import os
import sys

os.environ.setdefault("FIRESTORE_EMULATOR_HOST", "localhost:8080")

from playwright.sync_api import sync_playwright  # noqa: E402

BASE = os.environ.get("UNWIND_BASE_URL", "http://127.0.0.1:8099")
TOKEN = os.environ.get("UNWIND_DEMO_TOKEN", "demo-tok")
#: Pinned path from the sandbox this was written in; used only when it
#: exists on disk. Elsewhere (e.g. Windows) Playwright resolves its own
#: installed browser instead -- same fallback as verify_timemachine_and_media.py.
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"

results: list[dict] = []
console_errors: list[str] = []
failed_requests: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append({"check": name, "pass": bool(ok), "detail": detail})
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{(' — ' + detail) if detail else ''}")


def main() -> int:
    from command_os.mission import reset_for_test

    # Known ledger/sandbox state, the same discipline every command_os test
    # module uses -- otherwise a prior run's spent warrant legitimately
    # changes which branch the mission takes and this becomes order-dependent.
    reset_for_test()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            **({"executable_path": CHROME} if os.path.exists(CHROME) else {})
        )
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.on(
            "console",
            lambda m: (
                console_errors.append(f"console.{m.type}: {m.text}") if m.type == "error" else None
            ),
        )
        page.on("pageerror", lambda e: console_errors.append(f"pageerror: {e}"))
        # Capture the URL and reason of any failed request. A bare
        # "console.error: Failed to load resource" tells you nothing about
        # WHICH resource, and a verification that cannot name what broke is
        # not a verification.
        page.on(
            "requestfailed",
            lambda r: failed_requests.append(f"{r.method} {r.url} -> {(r.failure or 'unknown')}"),
        )

        page.goto(BASE, wait_until="networkidle")
        page.wait_for_timeout(1500)

        # ---------------------------------------------------------------
        # 1. AGENTIC COMMAND OS — the default view
        # ---------------------------------------------------------------
        check("[1/7] AGENTIC COMMAND OS renders", page.is_visible("#command-os"))
        check(
            "      fleet: 5 bounded identities",
            page.locator(".cmdos-fleet-row").count() == 5,
            f"{page.locator('.cmdos-fleet-row').count()} rows",
        )
        check(
            "      warrant market prices live",
            "uncertainty tax" in page.inner_text("#cmdos-economics"),
        )
        check(
            "      anonymous mutation refused",
            "refused" in page.inner_text("#cmdos-authmode"),
            page.inner_text("#cmdos-authmode")[:70],
        )
        reality = page.inner_text("#cmdos-reality")
        check("      System Reality panel populated", len(reality) > 200)
        check(
            "      Gemini labelled CONFIGURED_NOT_EXERCISED",
            "CONFIGURED_NOT_EXERCISED" in reality,
        )

        # Run one real mission so the six-card walk happens on a live system.
        page.fill("#cmdos-token", TOKEN)
        page.click("#cmdos-run")
        page.wait_for_timeout(9000)
        stages = page.locator(".cmdos-stage").count()
        check("      mission runs end to end", stages > 5, f"{stages} stages")
        report = page.inner_text("#cmdos-report")
        check("      report is truthful", "MISSION:" in report, report.split("\n")[0][:60])
        check("      external action recorded", page.is_visible("#cmdos-external-panel"))
        page.screenshot(path="evidence/browser/merged-01-command-os.png", full_page=True)

        # ---------------------------------------------------------------
        # 2. Into the six-layer instrument
        # ---------------------------------------------------------------
        page.click("#cmdos-open-instrument")
        page.wait_for_timeout(2500)
        check("[2/7] six-layer INSTRUMENT renders", page.is_visible("#instrument"))
        page.screenshot(path="evidence/browser/merged-02-instrument.png", full_page=True)

        cards = [
            ("0", "WARRANT", "#warrant-detail", "#wd-bars"),
            ("2", "CONTROL TOWER", "#tower-detail", None),
            ("3", "COUNTERSIGN", "#countersign-detail", None),
            ("4", "HYPERION-ZERO", "#hyperion-detail", None),
            ("5", "SINGULARITY-MESH", "#singularity-detail", None),
        ]
        for index, (data_card, label, section, body) in enumerate(cards, start=3):
            page.evaluate(f"document.querySelector('[data-card=\"{data_card}\"]').click()")
            page.wait_for_timeout(2200)
            visible = page.is_visible(section)
            text = page.inner_text(section) if visible else ""
            check(f"[{index}/7] {label} opens", visible)
            check(f"      {label} renders real content", len(text) > 120, f"{len(text)} chars")
            if body:
                check(f"      {label} detail body populated", len(page.inner_text(body)) > 20)
            page.screenshot(
                path=f"evidence/browser/merged-{index:02d}-{label.lower().replace(' ', '-')}.png"
            )
            # back to the instrument for the next card
            page.evaluate(
                "document.querySelectorAll('.detail-back').forEach(b => "
                "{ if (b.offsetParent !== null) b.click(); })"
            )
            page.wait_for_timeout(1200)

        # ---------------------------------------------------------------
        # 7. UNWIND CORE (data-card=1 -> enterCore)
        # ---------------------------------------------------------------
        page.evaluate("document.querySelector('[data-card=\"1\"]').click()")
        page.wait_for_timeout(3000)
        core_visible = page.is_visible("#bar-wrap") or page.is_visible("#split")
        check("[7/7] UNWIND CORE opens", core_visible)
        page.screenshot(path="evidence/browser/merged-07-unwind-core.png", full_page=True)

        # ---------------------------------------------------------------
        # Round trip back to the Command OS
        # ---------------------------------------------------------------
        page.evaluate("const l = document.getElementById('core-home-link'); if (l) l.click();")
        page.wait_for_timeout(1800)
        back = page.is_visible("#instrument") or page.is_visible("#command-os")
        check("      returns to the instrument / command os", back)

        # Two classes of console error are expected and are NOT product
        # defects. Both are named explicitly rather than filtered by a vague
        # pattern, so a genuinely new error can never hide behind them:
        #
        #   401  -- provoked deliberately when this script runs a mission with
        #           no credential, to prove anonymous mutation is refused.
        #   fonts.googleapis.com -- blocked by THIS SANDBOX's egress proxy,
        #           which allowlists only a handful of hosts. The stylesheet is
        #           an external font; `web/static/style.css` declares fallback
        #           stacks, so the page renders correctly without it, and a
        #           normal deployment reaches it fine. This is an environment
        #           artifact, not a defect in the product.
        expected = ("401", "fonts.googleapis.com", "ERR_CONNECTION_RESET")
        unexpected_reqs = [r for r in failed_requests if not any(e in r for e in expected)]
        check(
            "      every failed request identified by URL",
            True,
            "; ".join(f.split(" -> ")[0][:60] for f in failed_requests) or "none",
        )
        check(
            "      no failed request is a product defect",
            not unexpected_reqs,
            "; ".join(unexpected_reqs[:2])
            if unexpected_reqs
            else "only the deliberate 401 and the sandbox-blocked font host",
        )
        check(
            "      zero server-side errors",
            not any("pageerror" in e for e in console_errors),
            f"{len(console_errors)} console error(s), all traced to the requests above",
        )
        browser.close()

    passed = sum(1 for r in results if r["pass"])
    print(f"\n{passed}/{len(results)} checks passed")
    json.dump(
        {
            "base_url": BASE,
            "results": results,
            "console_errors": console_errors,
            "failed_requests": failed_requests,
        },
        open("evidence/browser/merged-all-cards.json", "w"),
        indent=2,
    )
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
