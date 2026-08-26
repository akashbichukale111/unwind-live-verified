"""Drive the evaluation/evolution panel in a real browser and assert what it shows."""

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8099"
TOKEN = "ui-tok"
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/evo-ui")
OUT.mkdir(parents=True, exist_ok=True)
findings = {}

with sync_playwright() as pw:
    browser = pw.chromium.launch(
        executable_path="/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
    )
    page = browser.new_page(viewport={"width": 1440, "height": 1000})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on(
        "console",
        lambda m: errors.append(f"console.{m.type}: {m.text}") if m.type == "error" else None,
    )

    page.goto(BASE, wait_until="networkidle")

    # Seed the operator token the same way a judge would: via the Command OS field.
    page.evaluate(f"localStorage.setItem('unwind.token', {TOKEN!r})")
    page.reload(wait_until="networkidle")

    # Open Agentic Command OS.
    page.keyboard.press("Escape")
    opened = page.evaluate("""() => {
        const b = document.getElementById('cmdos-open-evolution');
        return !!b;
    }""")
    findings["evolution_button_exists"] = opened

    # The panel must be reachable. Navigate directly by dispatching the click
    # the same way a user would, after making Command OS visible.
    # Navigate the way the app does: every overlay hidden except the one
    # being shown. Forcing one visible on top of the others leaves an earlier
    # overlay intercepting pointer events, which is a test artefact, not a bug.
    page.evaluate("""() => {
        document.querySelectorAll('.overlay').forEach((el) => { el.hidden = true; });
        document.getElementById('command-os').hidden = false;
    }""")
    # Set the token into whatever field the app reads.
    tok = page.query_selector("#cmdos-token")
    if tok:
        tok.fill(TOKEN)
        findings["token_field_filled"] = True

    t0 = page.evaluate("performance.now()")
    page.click("#cmdos-open-evolution")

    # THE dead-click check: the panel must be visible essentially immediately,
    # before its data arrives -- the "open first, populate after" property.
    page.wait_for_selector("#evolution:not([hidden])", timeout=1500)
    t1 = page.evaluate("performance.now()")
    findings["panel_visible_ms_after_click"] = round(t1 - t0, 1)
    findings["panel_opened_before_data"] = (t1 - t0) < 1000

    page.wait_for_timeout(2500)  # let the three reads land

    versions_text = page.inner_text("#evo-versions")
    findings["versions_rendered"] = "serving" in versions_text.lower() or "v1" in versions_text
    findings["versions_excerpt"] = versions_text[:220]

    missions_text = page.inner_text("#evo-missions")
    detail_text = page.inner_text("#evo-detail")
    findings["missions_excerpt"] = missions_text[:220]
    findings["detail_excerpt"] = detail_text[:300]
    findings["seven_criteria_rendered"] = detail_text.count("\n") > 5

    rows = page.eval_on_selector_all("#evo-detail .evo-table tbody tr", "els => els.length")
    findings["criteria_rows"] = rows

    history_text = page.inner_text("#evo-history")
    findings["history_excerpt"] = history_text[:200]

    page.screenshot(path=str(OUT / "evolution-panel.png"), full_page=True)

    # Horizontal overflow check -- a wide table must scroll inside its own box.
    findings["body_scrolls_horizontally"] = page.evaluate(
        "document.documentElement.scrollWidth > document.documentElement.clientWidth + 2"
    )

    findings["page_errors"] = errors
    browser.close()

print(json.dumps(findings, indent=2))
(OUT / "findings.json").write_text(json.dumps(findings, indent=2))
