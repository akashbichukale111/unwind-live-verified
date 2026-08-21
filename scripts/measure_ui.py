"""Drive the real UI in a real browser: measure frame rate, capture the screens.

⚠ THE FRAME RATE REPORTED IN THE README COMES FROM THIS SCRIPT. It is measured
by counting `requestAnimationFrame` callbacks in the page over a fixed window,
at the full node count, with the field actually animating -- not estimated, not
asserted, and not measured on an empty canvas.

It also captures a PNG of each screen so the demo can be checked without a
human watching, and asserts the cull's on-screen number equals the material
count the cascade computed. A counter that disagrees with the cascade would be
the single most damaging bug this interface could ship.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SHOTS = REPO / "docs" / "shots"
PORT = int(os.environ.get("UNWIND_UI_PORT", "8077"))
BASE = f"http://127.0.0.1:{PORT}"


def main() -> int:
    from playwright.sync_api import sync_playwright

    SHOTS.mkdir(parents=True, exist_ok=True)
    env = {
        **os.environ,
        "UNWIND_VERTEX_DISABLED": "1",
        "UNWIND_OTEL_CONSOLE": "0",
        "PYTHONPATH": str(REPO),
    }
    server = subprocess.Popen(
        [
            str(REPO / ".venv" / "bin" / "python"),
            "-m",
            "uvicorn",
            "services.api.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(PORT),
            "--log-level",
            "warning",
        ],
        cwd=REPO,
        env=env,
    )
    results: dict = {}
    try:
        _wait_for_server()
        with sync_playwright() as p:
            browser = p.chromium.launch(
                executable_path=os.environ.get(
                    "UNWIND_CHROME", "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
                ),
                args=["--no-sandbox", "--use-gl=swiftshader", "--enable-unsafe-swiftshader"],
            )
            page = browser.new_page(viewport={"width": 1600, "height": 900})
            errors: list[str] = []
            failed_requests: list[str] = []
            page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
            page.on("requestfailed", lambda r: failed_requests.append(r.url))
            # Console messages do not carry the URL of a failed subresource, so
            # a blocked CDN and a broken app script look identical there. The
            # request URL is the only way to tell them apart, so that is what
            # this run is judged on.

            page.goto(BASE, wait_until="networkidle")
            page.wait_for_function(
                "window.__unwindState && window.__unwindState.n > 0", timeout=30000
            )
            node_count = page.evaluate("window.__unwindState.n")
            results["nodes_rendered"] = node_count

            # ---- frame rate, measured ------------------------------------
            results["fps"] = _measure_fps(page)

            page.screenshot(path=str(SHOTS / "01-field.png"))

            # ---- the parse echo ------------------------------------------
            page.fill("#bar", "supplier_K lead time is now 20 days")
            page.press("#bar", "Enter")
            page.wait_for_selector("#echo:not([hidden])", timeout=15000)
            page.screenshot(path=str(SHOTS / "03-echo.png"))
            results["echo_text"] = page.inner_text("#echo")

            # ---- the wave and the cull -----------------------------------
            page.click("#e-confirm")
            page.wait_for_selector("#split:not([hidden])", timeout=90000)
            cull = page.evaluate("window.__unwindCull")
            results["cull"] = cull
            counter_to = page.inner_text("#counter-to").replace(",", "")
            results["counter_on_screen"] = int(counter_to)
            page.screenshot(path=str(SHOTS / "05-split.png"))
            results["split_gap"] = page.inner_text("#split-gap")

            # ---- the obligation ------------------------------------------
            page.click("#split .btn-advance")
            page.wait_for_selector("#obligation:not([hidden])", timeout=20000)
            page.wait_for_timeout(900)
            page.screenshot(path=str(SHOTS / "06-obligation.png"), full_page=True)
            results["obligation"] = {
                "exposure": page.inner_text("#o-exposure"),
                "irreversible": page.inner_text("#o-irr"),
                "approver": page.inner_text("#o-approver"),
                "nomodel_visible": not page.is_hidden("#o-nomodel"),
                # One commitment told through two channels must render ONE
                # counterparty heading, not two.
                "counterparty_headings": page.eval_on_selector_all(
                    "#o-told .who", "els => els.map(e => e.textContent)"
                ),
            }

            # ---- the court -----------------------------------------------
            page.click("#obligation .btn-advance")
            page.wait_for_selector("#court:not([hidden])", timeout=20000)
            page.screenshot(path=str(SHOTS / "07-court.png"))
            results["court_dissent"] = page.inner_text("#court-dissent")[:200]

            # ---- load rating ---------------------------------------------
            page.click("#court .btn-advance")
            page.wait_for_selector("#loadrating:not([hidden])", timeout=20000)
            page.wait_for_timeout(1700)
            page.screenshot(path=str(SHOTS / "08-loadrating.png"))
            results["loadrating"] = page.inner_text(".lr-nums")

            # ---- honesty panel -------------------------------------------
            page.click("#loadrating .btn-advance")
            page.wait_for_selector("#honesty:not([hidden])", timeout=20000)
            page.screenshot(path=str(SHOTS / "09-honesty.png"), full_page=True)
            results["worst_class"] = page.inner_text("#h-worst")

            # ---- the refusal ---------------------------------------------
            page.click("#honesty .btn-advance")
            page.wait_for_timeout(400)
            page.fill("#bar", "broker says supplier_K lead time is 34")
            page.press("#bar", "Enter")
            page.wait_for_selector("#e-refusal:not([hidden])", timeout=15000)
            page.screenshot(path=str(SHOTS / "04-refusal.png"))
            results["refusal_text"] = page.inner_text("#e-refusal")

            # ---- 380px responsive ----------------------------------------
            page.set_viewport_size({"width": 380, "height": 780})
            page.wait_for_timeout(500)
            page.screenshot(path=str(SHOTS / "10-narrow-380.png"))
            results["h_scroll_at_380"] = page.evaluate(
                "document.documentElement.scrollWidth > document.documentElement.clientWidth"
            )

            # A blocked font CDN is an environment fact -- this container has no
            # egress to fonts.googleapis.com -- and the page is built to render
            # without it. Anything failing from OUR OWN ORIGIN still fails the run.
            own = [u for u in failed_requests if u.startswith(BASE)]
            external = [u for u in failed_requests if not u.startswith(BASE)]
            results["page_errors"] = errors + own
            results["ignored_external_requests"] = external
            browser.close()
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()

    print(json.dumps(results, indent=2, sort_keys=True))

    # ---- the assertions that matter --------------------------------------
    failures: list[str] = []
    if results.get("nodes_rendered", 0) < 4000:
        failures.append(f"only {results.get('nodes_rendered')} nodes rendered; need 4000+")
    fps = results["fps"]["median"]
    if fps < 55:
        failures.append(f"median frame rate {fps} is below 55")
    cull = results.get("cull") or {}
    if results.get("counter_on_screen") != cull.get("material"):
        failures.append(
            f"the counter says {results.get('counter_on_screen')} but the cascade "
            f"computed {cull.get('material')} material nodes"
        )
    headings = results.get("obligation", {}).get("counterparty_headings", [])
    if len(headings) != len(set(headings)):
        failures.append(f"a counterparty is listed more than once: {headings}")
    if results.get("h_scroll_at_380"):
        failures.append("the page scrolls horizontally at 380px")
    if results.get("page_errors"):
        failures.append(f"page errors: {results['page_errors'][:3]}")

    if failures:
        print("\nFAILURES:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    print("\nAll UI assertions passed.")
    return 0


def _measure_fps(page) -> dict:
    """Count rAF callbacks over a fixed window. Three runs, report the median."""
    samples = []
    for _ in range(3):
        samples.append(
            page.evaluate(
                """() => new Promise((resolve) => {
                     let frames = 0;
                     const t0 = performance.now();
                     function step() {
                       frames++;
                       if (performance.now() - t0 < 2000) requestAnimationFrame(step);
                       else resolve(Math.round(frames * 1000 / (performance.now() - t0)));
                     }
                     requestAnimationFrame(step);
                   })"""
            )
        )
    samples.sort()
    return {"samples": samples, "median": samples[len(samples) // 2]}


def _wait_for_server() -> None:
    import urllib.error
    import urllib.request

    for _ in range(60):
        try:
            with urllib.request.urlopen(f"{BASE}/api/healthz", timeout=2) as r:
                if r.status == 200:
                    return
        except (urllib.error.URLError, OSError):
            time.sleep(0.5)
    raise RuntimeError("the API did not start")


if __name__ == "__main__":
    raise SystemExit(main())
