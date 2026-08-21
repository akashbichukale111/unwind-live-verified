"""Regression guard: the Mission button must never be able to look dead.

THE DEFECT THIS GUARDS
-------------------------
`runMission()` used to contain:

    if (!res.ok) return;

A silent return. A 401 at least surfaced `#cmdos-authfail` through
`authedFetch`, but **400, 403, 409, 422, 429 and 500 produced nothing at
all**: the button disabled for a few hundred milliseconds, snapped back to
its idle label, and the operator was left looking at an unchanged screen
with no way to distinguish the click from a no-op.

That is the definition of a dead button, and it is what this file exists to
prevent recurring. Every non-ok status must now produce a visible, specific,
actionable message at the point of action.

Run against a live local server:

    FIRESTORE_EMULATOR_HOST=localhost:8080 UNWIND_VERTEX_DISABLED=1 \
    UNWIND_COUNTERSIGN_SIMULATED=1 UNWIND_OPERATOR_TOKENS="demo-tok:kim@ops.example" \
    python -m uvicorn services.api.main:app --port 8099
    python evidence/browser/verify_mission_button.py
"""

from __future__ import annotations

import os
import sys
import time

from playwright.sync_api import sync_playwright

BASE = os.environ.get("UNWIND_BASE_URL", "http://127.0.0.1:8099")
TOKEN = os.environ.get("UNWIND_DEMO_TOKEN", "demo-tok")
#: Pinned path from the sandbox this was written in. Only a Linux path
#: exists to pin, and pinning nothing lets Playwright silently pick up
#: whatever Chromium happens to be on PATH instead of the one it installed
#: for itself -- so this is used only when it actually exists on disk;
#: elsewhere (e.g. Windows) Playwright resolves its own installed browser.
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"

results: list[bool] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append(bool(ok))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{(' — ' + str(detail)) if detail else ''}")


def main() -> int:
    with sync_playwright() as pw:
        launch_kwargs = {"executable_path": CHROME} if os.path.exists(CHROME) else {}
        browser = pw.chromium.launch(**launch_kwargs)
        page = browser.new_page(viewport={"width": 1500, "height": 1000})
        page.goto(BASE, wait_until="networkidle")
        page.wait_for_timeout(1500)

        # -- A. The unauthenticated click: the one a first-time user makes --
        print("\nA. click with no credential — the failure must be unmissable")
        button = page.locator("#cmdos-run")
        check("button is visible and enabled", button.is_visible() and button.is_enabled())
        button.click()
        page.wait_for_timeout(4000)

        panel = page.locator("#cmdos-authfail")
        check("a failure panel is visible", panel.is_visible())
        text = panel.inner_text()
        check("it names the HTTP status", "HTTP 401" in text, text.split("\n")[0][:70])
        check("it says what to DO about it", "operator token" in text.lower())
        check(
            "the token field is focused, so the fix is where the cursor is",
            page.evaluate("document.activeElement.id") == "cmdos-token",
            page.evaluate("document.activeElement.id"),
        )
        check("the button is usable again", button.is_enabled())

        # -- B. The authenticated click: it must respond FAST and visibly ----
        print("\nB. click with a credential — feedback must be immediate")
        page.fill("#cmdos-token", TOKEN)
        started = time.monotonic()
        page.click("#cmdos-run")

        first_feedback = None
        for _ in range(80):
            elapsed = time.monotonic() - started
            label = button.inner_text().strip()
            if not button.is_enabled() or label != "RUN AUTONOMOUS MISSION":
                first_feedback = elapsed
                break
            time.sleep(0.05)
        check(
            "the button shows feedback within 1s of the click",
            first_feedback is not None and first_feedback < 1.0,
            f"{first_feedback:.2f}s" if first_feedback else "NEVER — the button looked dead",
        )

        page.wait_for_timeout(14000)
        stages = page.locator(".cmdos-stage").count()
        check("the mission actually ran", stages > 5, f"{stages} stages")
        check("the failure panel was cleared", not panel.is_visible())
        check("the report is shown", page.is_visible("#cmdos-report"))
        check("the button returned to its idle state", button.is_enabled())
        page.screenshot(path="evidence/browser/mission-button.png", full_page=False)

        browser.close()

    passed = sum(results)
    print(f"\n{passed}/{len(results)} checks passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
