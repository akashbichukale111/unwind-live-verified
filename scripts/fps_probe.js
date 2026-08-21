/**
 * Headless frame-time probe over a SCRIPTED PAN, at the full 4,206-node
 * field. This is the honest complement to `scripts/measure_ui.py`'s FPS
 * number: that script samples `requestAnimationFrame` callback COUNTS over
 * a fixed window; this one collects every INDIVIDUAL frame's duration
 * while the page is under continuous input (a scripted mouse sweep across
 * the canvas, back and forth, for a few seconds), and reports the full
 * distribution -- median and p95 -- not just an average that a handful of
 * slow frames could hide.
 *
 * "Canvas/WebGL for the graph": the field (`web/static/app.js`) renders
 * 4,206 nodes on a 2D `<canvas>`, batched by state so `fillStyle` is set
 * seven times per frame rather than once per node -- see that file's own
 * comment. This probe measures whether that batching actually holds up
 * under interaction, not just at idle.
 *
 * Usage:
 *   cd scripts && npm install    # once, installs playwright-core only
 *   node fps_probe.js
 *
 * Requires a Chromium binary. Reuses the one the Python test suite already
 * has (`UNWIND_CHROME`, same default `scripts/measure_ui.py` uses) rather
 * than downloading a second copy.
 */

const { chromium } = require("playwright-core");
const { spawn } = require("child_process");
const fs = require("fs");
const path = require("path");
const http = require("http");

const REPO = path.resolve(__dirname, "..");
const OUT_DIR = path.join(REPO, "evidence", "fps");
const PORT = process.env.UNWIND_UI_PORT || "8079";
const BASE = `http://127.0.0.1:${PORT}`;
const CHROME = process.env.UNWIND_CHROME || "/opt/pw-browsers/chromium-1234/chrome-linux64/chrome";

function waitForServer(url, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  return new Promise((resolve, reject) => {
    function attempt() {
      const req = http.get(`${url}/api/healthz`, (res) => {
        res.resume();
        if (res.statusCode === 200) return resolve();
        retry();
      });
      req.on("error", retry);
      function retry() {
        if (Date.now() > deadline) return reject(new Error("server did not start"));
        setTimeout(attempt, 500);
      }
    }
    attempt();
  });
}

async function main() {
  fs.mkdirSync(OUT_DIR, { recursive: true });

  const server = spawn(
    path.join(REPO, ".venv", "bin", "python"),
    ["-m", "uvicorn", "services.api.main:app", "--host", "127.0.0.1", "--port", PORT, "--log-level", "warning"],
    {
      cwd: REPO,
      env: { ...process.env, UNWIND_VERTEX_DISABLED: "1", UNWIND_OTEL_CONSOLE: "0", PYTHONPATH: REPO },
    }
  );

  let browser;
  const result = { probe: "scripted-pan frame times", node_count: null, samples: [] };
  try {
    await waitForServer(BASE, 30000);

    browser = await chromium.launch({
      executablePath: CHROME,
      args: ["--no-sandbox", "--use-gl=swiftshader", "--enable-unsafe-swiftshader"],
    });
    const page = await browser.newPage({ viewport: { width: 1600, height: 900 } });
    await page.goto(BASE, { waitUntil: "networkidle" });
    await page.waitForFunction("window.__unwindState && window.__unwindState.n > 0", { timeout: 30000 });
    result.node_count = await page.evaluate("window.__unwindState.n");

    // Start collecting every frame's duration, in-page, via rAF deltas --
    // the same primitive `web/static/app.js:tick` already uses for its own
    // on-screen fps counter, just recording the raw series instead of a
    // rolling average.
    await page.evaluate(() => {
      window.__fpsProbe = { frames: [], last: null };
      function step(now) {
        if (window.__fpsProbe.last !== null) {
          window.__fpsProbe.frames.push(now - window.__fpsProbe.last);
        }
        window.__fpsProbe.last = now;
        requestAnimationFrame(step);
      }
      requestAnimationFrame(step);
    });

    // The scripted pan: a sine sweep across the canvas, continuous input
    // for ~4 seconds, moving the mouse ~60 times/sec.
    const w = 1600;
    const h = 900;
    const durationMs = 4000;
    const stepMs = 16;
    const t0 = Date.now();
    while (Date.now() - t0 < durationMs) {
      const t = (Date.now() - t0) / 1000;
      const x = w / 2 + (w / 2 - 40) * Math.sin(t * 1.3);
      const y = h / 2 + (h / 3) * Math.sin(t * 0.7);
      await page.mouse.move(x, y);
      await page.waitForTimeout(stepMs);
    }

    const frames = await page.evaluate("window.__fpsProbe.frames");
    result.samples = frames;

    await browser.close();
  } finally {
    server.kill();
  }

  const sorted = [...result.samples].sort((a, b) => a - b);
  const n = sorted.length;
  const pct = (p) => (n ? sorted[Math.min(n - 1, Math.floor((p / 100) * n))] : null);
  const fpsFromFrameTime = (ms) => (ms ? Math.round(1000 / ms) : null);

  const summary = {
    node_count: result.node_count,
    frame_count: n,
    frame_time_ms: {
      median: pct(50),
      p95: pct(95),
      max: sorted[n - 1] || null,
    },
    fps: {
      median: fpsFromFrameTime(pct(50)),
      p5_worst_case: fpsFromFrameTime(pct(95)),
    },
  };

  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  const outFile = path.join(OUT_DIR, `fps-probe-${stamp}.json`);
  fs.writeFileSync(outFile, JSON.stringify({ ...summary, raw_samples: result.samples }, null, 2));
  fs.writeFileSync(path.join(OUT_DIR, "latest.json"), JSON.stringify(summary, null, 2));

  console.log(JSON.stringify(summary, null, 2));
  console.log(`written: ${outFile}`);

  if (!summary.node_count || summary.node_count < 4000) {
    console.error(`FAIL: only ${summary.node_count} nodes rendered; need 4000+`);
    process.exit(1);
  }
  if (!summary.fps.median || summary.fps.median < 55) {
    console.error(`FAIL: median fps ${summary.fps.median} under scripted pan is below 55`);
    process.exit(1);
  }
  console.log("PASS");
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
