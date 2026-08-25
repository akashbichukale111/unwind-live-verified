"""`make deploy-verify URL=...` — prove the deployed service COMPUTES.

⚠ A DEPLOYMENT THAT RENDERS BUT COMPUTES NOTHING IS WORSE THAN NO DEPLOYMENT,
because it looks finished. So this does not check that the page loads. It:

  1. hits /api/healthz and reports the stage the service thinks it is
  2. runs ONE REAL CASCADE against the deployed API over SSE
  3. counts the node events it actually received
  4. asserts the deployed service's own totals agree with those events
  5. asserts the refusal path still refuses, by reason code
  6. drives the deployed UI in a real browser, if Playwright is available, and
     asserts the on-screen cull counter equals the cascade's material count --
     the same assertion `make ui-check` makes locally

Step 4 is the one that matters. The counter on screen is decremented by arriving
events and by nothing else; if the deployed service reported a total that
disagreed with what it sent, the number a judge reads would be a lie.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TIMEOUT = 120


def die(headline: str, *lines: str) -> None:
    print("", file=sys.stderr)
    print("=" * 70, file=sys.stderr)
    print(f"DEPLOY-VERIFY FAILED: {headline}", file=sys.stderr)
    print("=" * 70, file=sys.stderr)
    for line in lines:
        print(line, file=sys.stderr)
    raise SystemExit(1)


def get(url: str) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={"User-Agent": "unwind-deploy-verify"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError) as exc:
        die(f"could not reach {url}", str(exc))
        raise  # unreachable


def parse_sse(raw: str) -> list[tuple[str, dict]]:
    out: list[tuple[str, dict]] = []
    for block in raw.split("\n\n"):
        name = payload = None
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line[7:]
            elif line.startswith("data: "):
                try:
                    payload = json.loads(line[6:])
                except json.JSONDecodeError:
                    payload = None
        if name and payload is not None:
            out.append((name, payload))
    return out


def main(argv: list[str]) -> int:
    if len(argv) < 2 or not argv[1].startswith("http"):
        die(
            "no URL given",
            "usage: make deploy-verify URL=https://unwind-xxxx.a.run.app",
        )
    base = argv[1].rstrip("/")

    print("=" * 70)
    print(f"UNWIND — verifying deployment at {base}")
    print("=" * 70)

    # ---- 1. health -------------------------------------------------------
    status, body = get(f"{base}/api/healthz")
    if status != 200:
        die(f"/api/healthz returned {status}", body[:400])
    health = json.loads(body)
    print(f"[1/5] healthz OK  stage={health.get('stage')}")
    print(f"      model={health.get('model')}  location={health.get('vertex_location')}")
    print(f"      vertex_disabled={health.get('vertex_disabled')}")

    # ---- 2. the UI is served from this same origin -----------------------
    status, page = get(f"{base}/")
    if status != 200:
        die(f"/ returned {status}", "the UI is not served from this origin")
    for marker in ("<canvas", "/static/app.js", "/static/style.css"):
        if marker not in page:
            die("the page served is not the UNWIND field", f"missing {marker!r}")
    print("[2/5] UI served from the same origin (canvas + 2 static assets)")

    # ---- 3. a real cascade, over SSE -------------------------------------
    print("[3/5] running one real cascade against the deployed API ...")
    status, raw = get(f"{base}/api/cascade/stream?pace_ms=0&batch=200")
    if status != 200:
        die(f"/api/cascade/stream returned {status}", raw[:400])
    events = parse_sse(raw)
    if not events:
        die("the stream produced no events", raw[:400])

    names = [n for n, _ in events]
    if names[0] != "begin" or names[-1] != "done":
        die("unexpected stream shape", f"first={names[0]!r} last={names[-1]!r}")

    begin = events[0][1]
    done = events[-1][1]
    delivered = sum(len(p["n"]) for n, p in events if n == "nodes")

    print(f"      radius announced : {begin['radius']}")
    print(f"      node events sent : {delivered}")
    print(f"      done.sent        : {done['sent']}")
    print(f"      material         : {done['material']}")
    print(f"      model calls      : {done['model_calls']}")

    # ⚠ THE ASSERTION THAT MATTERS.
    if not (delivered == done["sent"] == done["radius"] == begin["radius"]):
        die(
            "the deployed service's totals disagree with what it actually sent",
            f"announced={begin['radius']} delivered={delivered} reported={done['sent']}",
            "The on-screen counter is driven by arriving events. If these differ,",
            "the number a judge reads is not the number the cascade computed.",
        )
    if sum(done["regimes"].values()) != done["radius"]:
        die("the regime tallies do not partition the radius", json.dumps(done["regimes"]))
    if done["model_calls"] != 0:
        die(
            "the deployed cascade made a model call",
            f"model_calls={done['model_calls']} — T0/T1 must be model-free",
        )
    print("[3/5] counter integrity OK — announced = delivered = reported")

    # ---- 4. the refusal path still refuses -------------------------------
    status, raw = get(f"{base}/api/cascade/stream?source=src_broker_Z&new_value=34&pace_ms=0")
    refusal = dict(parse_sse(raw))
    if "refused" not in refusal:
        die("the deployed service did not refuse an out-of-scope source")
    code = refusal["refused"].get("reason_code")
    if code != "source_outside_claim_scope":
        die("refused for the wrong reason", f"reason_code={code!r}")
    if refusal["done"]["radius"] != 0:
        die("a refused retraction still walked the graph", str(refusal["done"]["radius"]))
    print(f"[4/5] adversarial refusal OK — {code}, radius 0")

    # ---- 5. the deployed UI, in a real browser ---------------------------
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[5/5] SKIPPED — playwright not installed; API verified, UI not driven")
        print("")
        print("Deployment verified at the API level.")
        return 0

    chrome = os.environ.get("UNWIND_CHROME", "/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
    if not Path(chrome).exists():
        print(f"[5/5] SKIPPED — no chromium at {chrome}; API verified, UI not driven")
        return 0

    print("[5/5] driving the deployed UI in a real browser ...")
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chrome, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1600, "height": 900})
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(base, wait_until="networkidle", timeout=60000)
        page.wait_for_function("window.__unwindState && window.__unwindState.n > 0", timeout=60000)
        nodes = page.evaluate("window.__unwindState.n")

        # The bare `#bar` field screen was retired as the landing view (see
        # evidence/deploy/ui-premium-fix-2026-08-17.md and evidence/INDEX.md
        # §9): Agentic Command OS is default now, `#bar` lives inside UNWIND
        # CORE, one navigation step deeper (Command OS -> the instrument ->
        # card 1). `window.__unwindState` still populates on load regardless
        # (`boot()` runs unconditionally), so the wait above is unaffected --
        # only the field itself needs a real click-through to become visible.
        page.click("#cmdos-open-instrument")
        # The overlay itself opens immediately (2026-08-25 fix: showInstrument()
        # no longer waits for its three fetches before showing); #instr-body,
        # which holds the actual card grid, unhides a beat later once that
        # data arrives -- wait for the thing actually being clicked next.
        page.wait_for_selector("#instr-body:not([hidden])", timeout=30000)
        page.click('[data-card="1"]')
        page.wait_for_selector("#bar-wrap:not([hidden])", timeout=30000)

        page.fill("#bar", "supplier_K lead time is now 20 days")
        page.press("#bar", "Enter")
        page.wait_for_selector("#echo:not([hidden])", timeout=30000)
        page.click("#e-confirm")
        page.wait_for_selector("#split:not([hidden])", timeout=180000)

        cull = page.evaluate("window.__unwindCull")
        on_screen = int(page.inner_text("#counter-to").replace(",", ""))
        browser.close()

    print(f"      nodes rendered   : {nodes}")
    print(f"      counter on screen: {on_screen}")
    print(f"      cascade material : {cull['material']}")

    if on_screen != cull["material"]:
        die(
            "the deployed UI's counter disagrees with the deployed cascade",
            f"screen={on_screen} cascade={cull['material']}",
        )
    if nodes < 4000:
        die("the deployed field rendered too few nodes", f"nodes={nodes}")
    if errors:
        die("the deployed page raised errors", *errors[:3])

    print("")
    print("=" * 70)
    print("DEPLOYMENT VERIFIED — it renders AND it computes.")
    print(f"  URL       : {base}")
    print(f"  radius    : {done['radius']}  ->  material {done['material']}")
    print(f"  counter   : {on_screen} (equals the cascade's own count)")
    print(f"  refusal   : {code}")
    print(f"  model calls on T0/T1: {done['model_calls']}")
    print("=" * 70)
    print("")
    print("Paste this block into docs/DEPLOY.md and the README.")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(REPO))
    raise SystemExit(main(sys.argv))
