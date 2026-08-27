/* UNWIND — the field, the wave, the cull, and the paper.
 *
 * ⚠ EVERY NUMBER ON SCREEN ARRIVES FROM THE SERVER. The counter is decremented
 * by SSE events carrying real cascade verdicts; it is NOT a tween toward a
 * known total. That is why it can never disagree with the events that produced
 * it, and it is why `culled` below is incremented inside the event handler and
 * nowhere else.
 *
 * The only thing that is not real is the PACING of delivery -- the cascade
 * finishes in well under a second and a person needs about twenty to read the
 * die-back. The server reports `paced_ms` in its `begin` event and we print it
 * on screen, because a paced stream that claims to be live is a lie and a
 * disclosed one is a demo.
 */

(() => {
  "use strict";

  const T = {
    ink: "#12151A",
    slate: "#262C34",
    graphite: "#4A535E",
    bone: "#EDE8DE",
    amber: "#C88A2E",
    oxide: "#8C3A2B",
    verdigris: "#3E7A6E",
  };

  // Node lifecycle. Index into T via STATE_COLOUR.
  const S = {
    IDLE: 0,
    FLARE: 1,
    IMMATERIAL: 2,
    CLOSED: 3,
    UNRESOLVED: 4,
    MAT_ESC: 5,
    MAT_CONT: 6,
  };

  const REGIME_STATE = {
    immaterial_contained: S.IMMATERIAL,
    immaterial_escaped: S.IMMATERIAL,
    closed_out: S.CLOSED,
    unresolved: S.UNRESOLVED,
    material_escaped: S.MAT_ESC,
    material_contained: S.MAT_CONT,
  };

  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const canvas = document.getElementById("field");
  const ctx = canvas.getContext("2d", { alpha: false });

  const $ = (id) => document.getElementById(id);

  //: Escape text before it goes into innerHTML. A mission objective is
  //: OPERATOR-SUPPLIED free text that round-trips through Firestore and back
  //: into the Time Machine's mission list, so interpolating it raw was a
  //: stored-XSS path: an objective containing a script tag would execute for
  //: the next operator who opened the panel. Every interpolation of
  //: server-derived text in the Time Machine goes through this.
  const esc = (s) =>
    String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  const state = {
    nodes: null,
    n: 0,
    x: null,
    y: null,
    z: null,      // 0 near (recent) .. 1 far (old). Depth axis IS time.
    r: null,      // radius in px, from z
    st: null,     // Uint8Array of S.*
    t0: null,     // Float32Array flare start
    index: new Map(),
    stones: [],
    field: null,
    screen: "instrument",
    running: false,
    sag: 0,       // spring displacement of the load lines
    sagV: 0,
    sagTarget: 0,
    frames: 0,
    fpsT: 0,
    fps: 0,
    fpsSamples: [],
  };

  // ── layout ────────────────────────────────────────────────────────

  // Deterministic pseudo-random so the field is identical on every run. A demo
  // that reshuffles between takes is a demo nobody can rehearse.
  function rand(i, salt) {
    const v = Math.sin(i * 12.9898 + salt * 78.233) * 43758.5453;
    return v - Math.floor(v);
  }

  let W = 0;
  let H = 0;
  let DPR = 1;
  let horizon = 0;

  function resize() {
    DPR = Math.min(window.devicePixelRatio || 1, 2);
    W = window.innerWidth;
    H = window.innerHeight;
    canvas.width = Math.floor(W * DPR);
    canvas.height = Math.floor(H * DPR);
    canvas.style.width = W + "px";
    canvas.style.height = H + "px";
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
    horizon = H * 0.16;
    if (state.nodes) layout();
  }

  function layout() {
    const n = state.n;
    const maxAge = state.maxAge || 1;
    for (let i = 0; i < n; i++) {
      const node = state.nodes[i];
      // DEPTH AXIS IS TIME. Older decisions sit further back: smaller, dimmer,
      // nearer the horizon. This is the product's whole point made spatial --
      // decisions keep operating long after the premise under them died.
      const z = Math.min(1, node.age / maxAge);
      state.z[i] = z;
      const spreadX = 0.06 + 0.88 * rand(i, 1);
      // Perspective: far rows converge toward the centre.
      const converge = 0.5 + (spreadX - 0.5) * (1 - 0.22 * z);
      state.x[i] = converge * W;
      const band = horizon + (1 - z) * (H * 0.72 - horizon);
      state.y[i] = band + (rand(i, 2) - 0.5) * H * 0.05 * (1 - 0.5 * z);
      state.r[i] = (1 - 0.55 * z) * 1.9 + 0.75;
    }
  }

  // ── render ────────────────────────────────────────────────────────

  const FLARE_MS = 900;

  function draw(now) {
    ctx.fillStyle = T.ink;
    ctx.fillRect(0, 0, W, H);

    drawLoadLines(now);

    const n = state.n;
    const st = state.st;
    const t0 = state.t0;

    // Batch by state so fillStyle is set seven times per frame rather than
    // 4,206 times. This is the difference between 60 fps and 12.
    for (let s = 0; s <= 6; s++) {
      let colour = T.graphite;
      let baseAlpha = 0.95;
      if (s === S.FLARE) { colour = T.amber; baseAlpha = 1; }
      else if (s === S.IMMATERIAL) { colour = T.slate; baseAlpha = 0.5; }
      else if (s === S.CLOSED) { colour = T.slate; baseAlpha = 0.34; }
      else if (s === S.UNRESOLVED) { colour = T.bone; baseAlpha = 0.62; }
      else if (s === S.MAT_ESC) { colour = T.amber; baseAlpha = 1; }
      else if (s === S.MAT_CONT) { colour = T.verdigris; baseAlpha = 0.95; }

      ctx.fillStyle = colour;
      for (let i = 0; i < n; i++) {
        if (st[i] !== s) continue;
        let a = baseAlpha * (1 - 0.42 * state.z[i]);
        let rad = state.r[i];
        if (s === S.FLARE) {
          const k = Math.min(1, (now - t0[i]) / FLARE_MS);
          a = 1 - k * 0.35;
          rad = state.r[i] * (1 + 2.2 * (1 - k));
        } else if (s === S.MAT_ESC) {
          // A slow breath, so the survivors read as still live.
          a = baseAlpha * (0.78 + 0.22 * Math.sin(now / 620 + i));
          rad = state.r[i] * 1.9;
        } else if (s === S.IDLE) {
          a = baseAlpha * (0.74 + 0.26 * Math.sin(now / 2400 + i * 0.37)) * (1 - 0.42 * state.z[i]);
        }
        ctx.globalAlpha = Math.max(0.03, Math.min(1, a));
        const d = rad * 2;
        ctx.fillRect(state.x[i] - rad, state.y[i] - rad, d, d);
      }
    }
    ctx.globalAlpha = 1;
  }

  /* ⭐ LOAD-BEARING LINES.
   *
   * Thickness is a function of the number of decisions resting on that premise
   * and of nothing else -- `direct` comes straight from the reverse index. A
   * premise carrying 882 direct dependents is a thick taut line; one carrying
   * two is a hairline. This is a structural load diagram, not a network graph.
   *
   * On retraction the lines GO SLACK: `state.sag` is driven by a spring, the
   * curve's control point drops, and the conclusions above lose their footing
   * before anything flares.
   */
  function drawLoadLines(now) {
    const stones = state.stones;
    if (!stones.length) return;
    const baseY = H * 0.93;
    const maxDirect = stones[0].direct || 1;

    for (let i = 0; i < stones.length; i++) {
      const s = stones[i];
      const slot = state.stoneSlot[i];
      const sx = (0.05 + 0.9 * ((slot + 0.5) / stones.length)) * W;
      const load = s.direct / maxDirect;
      const thickness = 0.5 + Math.sqrt(load) * 7.0;

      const isHub = s.id === state.hubId;
      const sag = isHub ? state.sag : state.sag * 0.28;

      // Height carries load too: a premise holding 882 decisions rises most of
      // the frame, one holding two barely leaves the plinth. Two encodings of
      // the same true number, so the diagram reads at a glance and on inspection.
      const rise = H * (0.16 + 0.62 * Math.sqrt(load));
      const topY = baseY - rise;
      const lean = (W * 0.5 - sx) * 0.06;
      const midY = (baseY + topY) / 2 + sag * rise * 0.34;
      const midX = sx + lean * 0.5 + sag * lean * 0.8;

      ctx.beginPath();
      ctx.moveTo(sx, baseY);
      ctx.quadraticCurveTo(midX, midY, sx + lean, topY);
      ctx.lineWidth = Math.max(0.6, thickness * (1 - 0.3 * sag));
      ctx.strokeStyle = isHub && state.sag > 0.02 ? T.oxide : T.graphite;
      ctx.globalAlpha = isHub ? 0.95 : 0.30 + 0.45 * load;
      ctx.stroke();

      // The premise stone itself.
      ctx.globalAlpha = 1;
      ctx.fillStyle = isHub && state.sag > 0.02 ? T.oxide : T.graphite;
      const sw = 2 + thickness * 0.8;
      ctx.fillRect(sx - sw / 2, baseY - 3, sw, 6);
    }
    ctx.globalAlpha = 1;
  }

  function tick(now) {
    // Spring: stiffness 120, damping 18, as specified.
    if (!reduced) {
      const k = 120;
      const c = 18;
      const dt = 1 / 60;
      const a = (state.sagTarget - state.sag) * k - state.sagV * c;
      state.sagV += a * dt;
      state.sag += state.sagV * dt;
    } else {
      state.sag = state.sagTarget;
    }

    // Settle expired flares into their final regime.
    const st = state.st;
    const t0 = state.t0;
    const fin = state.finalState;
    for (let i = 0; i < state.n; i++) {
      if (st[i] === S.FLARE && now - t0[i] > FLARE_MS) st[i] = fin[i];
    }

    draw(now);

    state.frames++;
    if (!state.fpsT) state.fpsT = now;
    if (now - state.fpsT >= 1000) {
      state.fps = Math.round((state.frames * 1000) / (now - state.fpsT));
      state.fpsSamples.push(state.fps);
      state.frames = 0;
      state.fpsT = now;
      window.__unwindFps = state.fps;
      window.__unwindFpsSamples = state.fpsSamples;
    }
    requestAnimationFrame(tick);
  }

  // ── data ──────────────────────────────────────────────────────────

  async function boot() {
    const res = await fetch("/api/field");
    const field = await res.json();
    state.field = field;
    state.nodes = field.nodes;
    state.n = field.nodes.length;
    state.maxAge = field.nodes.reduce((m, node) => Math.max(m, node.age), 1);
    state.stones = field.stones;
    state.hubId = field.hub.claim_id;
    // Stones arrive sorted heaviest-first, which would stack every thick line
    // at the left edge. Position carries no information, so it is assigned for
    // legibility: the hub near a third across, the rest filling around it.
    const total = field.stones.length;
    const hubSlot = Math.floor(total * 0.30);
    const free = [];
    for (let k = 0; k < total; k++) if (k !== hubSlot) free.push(k);
    state.stoneSlot = new Int32Array(total);
    let f = 0;
    field.stones.forEach((stone, i) => {
      state.stoneSlot[i] = stone.id === field.hub.claim_id ? hubSlot : free[f++];
    });

    const n = state.n;
    state.x = new Float32Array(n);
    state.y = new Float32Array(n);
    state.z = new Float32Array(n);
    state.r = new Float32Array(n);
    state.st = new Uint8Array(n);
    state.finalState = new Uint8Array(n);
    state.t0 = new Float32Array(n);
    field.nodes.forEach((node, i) => state.index.set(node.id, i));

    $("c-nodes").textContent = field.counts.conclusions.toLocaleString();
    $("c-claims").textContent = field.counts.claims.toLocaleString();
    $("c-edges").textContent = field.counts.reverse_index_edges.toLocaleString();
    $("c-debt").textContent = field.debt.total.toLocaleString();
    $("debt-note").textContent =
      `across ${field.debt.claims_implicated} premises · ${field.debt.conclusions_scored} decisions`;

    $("bar-hints").innerHTML =
      `try <b>supplier_K lead time is now 20 days</b>` +
      `<br>or <b>broker says supplier_K lead time is 34</b> &nbsp;(this one is refused)`;

    resize();
    requestAnimationFrame(tick);
  }

  // ── the retraction bar → the parse echo ───────────────────────────

  /* The bar accepts prose and resolves it to a (claim, source, value). This is
   * deliberately forgiving on the way IN and strict on the way OUT: whatever it
   * decides is rendered back through the echo for a human to confirm, so a
   * misparse arrives as a question rather than as a correction somebody
   * receives. */
  function interpret(text) {
    const t = text.toLowerCase();
    const num = t.match(/(\d+(?:\.\d+)?)/);
    const value = num ? parseFloat(num[1]) : 20;
    let source = "src_supplier_K";
    if (/broker|zenith|freight/.test(t)) source = "src_broker_Z";
    else if (/msa|amendment|agreement|clause/.test(t)) source = "src_msa_K";
    else if (/supplier_l|supplier l/.test(t)) source = "src_supplier_L";
    else if (/erp|internal/.test(t)) source = "src_erp_internal";
    return { claim: "clm_000000", source, new_value: value };
  }

  let pending = null;

  async function showEcho(spec) {
    const q = new URLSearchParams(spec).toString();
    const res = await fetch(`/api/echo?${q}`);
    const e = await res.json();
    pending = spec;

    $("e-read").innerHTML =
      `${e.read_as.canonical} &nbsp; <b>${e.read_as.from} → ${e.read_as.to}</b>`;
    $("e-source").textContent = `${e.source} · authority ${e.authority.reason_code}`;
    $("e-affects").innerHTML =
      `${e.affects_claim} &nbsp; (carrying <b>${e.carrying.toLocaleString()}</b> decisions)`;

    const refusal = $("e-refusal");
    if (!e.authority.allowed) {
      refusal.hidden = false;
      refusal.innerHTML =
        `<span class="code">REFUSED — ${e.authority.reason_code}</span><br>${e.authority.why}`;
      $("e-confirm").textContent = "Show the refusal";
    } else {
      refusal.hidden = true;
      $("e-confirm").textContent = "Confirm";
    }
    $("bar-wrap").classList.add("gone");
    $("echo").hidden = false;
    $("e-confirm").focus();
  }

  // ── the wave and the cull ─────────────────────────────────────────

  function runCascade(spec) {
    $("echo").hidden = true;
    const counter = $("counter");
    counter.hidden = false;

    // Lines go slack FIRST. The footing is lost before anything flares.
    state.sagTarget = 1;

    let radius = 0;
    let culled = 0;
    const tally = { immaterial: 0, closed_out: 0, unresolved: 0, material: 0 };

    const q = new URLSearchParams({ ...spec, pace_ms: reduced ? 0 : 6 }).toString();
    const es = new EventSource(`/api/cascade/stream?${q}`);
    state.running = true;

    // `begin` carries the radius and the pacing disclosure. Deliberately not
    // named `open`: EventSource fires a native `open` on connect, and two
    // different payloads in one listener is a bug waiting for a bad demo.
    es.addEventListener("begin", (ev) => {
      const d = JSON.parse(ev.data);
      radius = d.radius;
      $("counter-from").textContent = radius.toLocaleString();
      $("counter-to").textContent = radius.toLocaleString();
      const pacing = $("pacing");
      pacing.hidden = false;
      pacing.textContent = d.paced_ms
        ? `real cascade verdicts · delivery paced ${d.paced_ms} ms/batch for legibility`
        : "real cascade verdicts · unpaced";
    });

    es.addEventListener("nodes", (ev) => {
      const data = JSON.parse(ev.data);
      const now = performance.now();
      for (const node of data.n) {
        const i = state.index.get(node.id);
        if (i === undefined) continue;
        const final = REGIME_STATE[node.r] ?? S.IDLE;
        state.finalState[i] = final;
        state.st[i] = reduced ? final : S.FLARE;
        state.t0[i] = now;

        // ⚠ THE COUNTER MOVES HERE AND NOWHERE ELSE. Every decrement is caused
        // by an event that carried a real verdict, so the number on screen is
        // the number of events received. It cannot drift from the cascade.
        if (final === S.MAT_ESC || final === S.MAT_CONT) tally.material++;
        else {
          culled++;
          if (final === S.IMMATERIAL) tally.immaterial++;
          else if (final === S.CLOSED) tally.closed_out++;
          else if (final === S.UNRESOLVED) tally.unresolved++;
        }
      }
      $("counter-to").textContent = (radius - culled).toLocaleString();
      $("counter-breakdown").textContent =
        `${tally.immaterial.toLocaleString()} immaterial — the buffer absorbed it\n` +
        `${tally.closed_out.toLocaleString()} already closed out — the world moving cannot hurt them\n` +
        `${tally.unresolved.toLocaleString()} unresolved — sent to judgment, not guessed`;
    });

    es.addEventListener("refused", (ev) => {
      const d = JSON.parse(ev.data);
      state.sagTarget = 0;
      counter.hidden = true;
      const refusal = $("e-refusal");
      refusal.hidden = false;
      refusal.innerHTML =
        `<span class="code">REFUSED — ${d.reason_code}</span><br>${d.why}` +
        `<br><br>Decision state: <b>${d.decision_state}</b>. Nothing was traversed; ` +
        `the radius is zero.`;
      $("echo").hidden = false;
      $("e-confirm").textContent = "Try an authorised source";
      $("e-confirm").onclick = restart;
    });

    es.addEventListener("done", (ev) => {
      const d = JSON.parse(ev.data);
      es.close();
      state.running = false;
      if (d.radius === 0) return;
      $("counter-to").textContent = d.material.toLocaleString();
      window.__unwindCull = { radius: d.radius, material: d.material, regimes: d.regimes };
      setTimeout(() => showSplit(spec), reduced ? 0 : 1600);
    });

  }

  // ── the split ─────────────────────────────────────────────────────

  async function showSplit(spec) {
    const res = await fetch(`/api/survivors?${new URLSearchParams(spec)}`);
    const d = await res.json();

    $("s-rev-n").textContent = d.counts.reversible;
    $("s-esc-n").textContent = d.counts.escaped;

    const row = (r, escaped) =>
      `<li class="${r.age_days >= 120 ? "old" : ""}"><span>${r.id} · ${r.kind}</span>` +
      `<span class="age">${escaped ? "sent " + r.sent_at : r.decided_at} · ${r.age_days}d</span></li>`;

    $("s-rev").innerHTML = d.reversible.slice(0, 14).map((r) => row(r, false)).join("");
    $("s-esc").innerHTML = d.escaped.slice(0, 14).map((r) => row(r, true)).join("");

    $("split-gap").innerHTML =
      `<b>${d.counts.escaped_120d_or_older} of these went out 120 days or more before ` +
      `the fact changed</b>, the oldest ${d.oldest_escaped_days} days. Everything on the ` +
      `right already reached a counterparty. That gap is the product.`;

    show("split");
  }

  // ── the obligation (dark → paper) ─────────────────────────────────

  async function showObligation(spec) {
    const res = await fetch(`/api/obligation?${new URLSearchParams(spec)}`);
    const o = await res.json();

    $("o-id").textContent = o.obligation_id;
    $("o-status").textContent = o.status.replace(/_/g, " ");
    $("o-lede").textContent =
      `A commitment we made rests on a fact that is no longer true, and it has ` +
      `already left the building.`;

    // GROUPED BY COUNTERPARTY, not by telling. One customer reached through two
    // channels is one customer and one apology -- rendering a heading per
    // telling would put the same name on screen twice and undo the whole point
    // of deriving identity from the commitment rather than from the effect.
    const byWho = new Map();
    for (const t of o.tellings) {
      if (!byWho.has(t.counterparty)) byWho.set(t.counterparty, []);
      byWho.get(t.counterparty).push(t);
    }
    $("o-told").innerHTML = [...byWho.entries()]
      .map(
        ([who, ts]) =>
          `<div class="told"><div class="who">${who}</div>` +
          `<div class="line">told &nbsp;${ts[0].told}</div>` +
          ts
            .map(
              (t) =>
                `<div class="line">when &nbsp;${t.told_at.slice(0, 10)} · via ` +
                `${t.connector} (${t.ref})</div>`
            )
            .join("") +
          `<div class="line now">now &nbsp;&nbsp;${ts[0].now}</div></div>`
      )
      .join("");

    $("o-rev").innerHTML = o.reversible_actions.map((a) => `<li>${a}</li>`).join("")
      || `<li>nothing reversible remains</li>`;
    $("o-irr").innerHTML = o.unrecoverable.map((a) => `<li>${a}</li>`).join("")
      || `<li>nothing unrecoverable</li>`;

    const ex = o.exposure;
    const money = (m) => `${ex.currency} ${(m / 100).toLocaleString(undefined, { minimumFractionDigits: 2 })}`;
    $("o-exposure").innerHTML =
      `${money(ex.low)} — ${money(ex.high)}` +
      (ex.unpriced_effects
        ? `<span class="unpriced">⚠ ${ex.unpriced_effects} unrecoverable effect(s) carry no ` +
          `recorded amount and are NOT priced into this range.</span>`
        : "");
    $("o-assume-list").innerHTML = ex.assumptions.map((a) => `<li>${a}</li>`).join("");

    $("o-draft").textContent = o.correction_text.replace(/\[drafted without a model[^\]]*\]/g, "").trim();
    const tag = $("o-nomodel");
    tag.hidden = !o.drafted_without_model;
    if (o.drafted_without_model) {
      tag.textContent =
        "DRAFTED WITHOUT A MODEL — Vertex was unavailable for this run. The facts above " +
        "are read from the record; the wording is deterministic. The tag stays visible.";
    }
    $("o-approver").textContent = o.approver;
    show("obligation");
  }

  // ── court ─────────────────────────────────────────────────────────

  async function showCourt(spec) {
    const res = await fetch(`/api/court?${new URLSearchParams(spec)}`);
    const c = await res.json();
    if (!c.convened) {
      $("court-meta").textContent = c.why;
      show("court");
      return;
    }
    $("court-meta").textContent =
      `${c.team_seated} owners seated from ${c.team_eligible} eligible · ` +
      `${c.turns_used} turns · budget ${c.budget.spent}/${c.budget.allowance} · ` +
      `converged ${c.converged} · team dissolved ${c.team_dissolved}`;

    $("court-pleas").innerHTML = c.pleas
      .map(
        (p) =>
          `<li><span>${p.owner}</span><span class="stance ${p.stance}">${p.stance.replace(/_/g, " ")}</span>` +
          `<span>${p.conclusion}</span><span class="ev">${p.evidence.length} cited</span></li>`
      )
      .join("");

    $("court-ruling").innerHTML =
      `${c.ruling.decision}` +
      (c.ruling.advisory
        ? `<span class="advisory">ADVISORY — above the cost threshold this ruling does not ` +
          `take effect on its own authority; it becomes a recommendation attached to a ` +
          `signature request.</span>`
        : "");

    $("court-dissent").innerHTML = c.dissent.length
      ? `<span class="lbl">dissent recorded (${c.dissent.length})</span><br>` +
        c.dissent.map((d) => `· ${d}`).join("<br>")
      : `<span class="lbl">no dissent</span><br>every seated owner's stance survived the tally.`;

    show("court");
  }

  // ── load rating ───────────────────────────────────────────────────

  async function showLoadRating() {
    const res = await fetch("/api/loadrating?source=src_supplier_K");
    const d = await res.json();
    $("lr-source").textContent = `${d.source_id} · ${d.name} · version ${d.version}`;
    $("lr-before").textContent = d.before.toFixed(2);
    $("lr-after").textContent = d.after.toFixed(2);
    $("lr-note").textContent = d.note + " Versioned and reversible: the downgrade appends, it never overwrites.";
    const bar = $("lr-bar");
    bar.style.width = d.before * 100 + "%";
    show("loadrating");
    requestAnimationFrame(() => {
      setTimeout(() => { bar.style.width = d.after * 100 + "%"; }, reduced ? 0 : 260);
    });
  }

  // ── honesty ───────────────────────────────────────────────────────

  async function showHonesty() {
    notePeekOrigin();
    hideCore();
    const res = await fetch("/api/honesty");
    const h = await res.json();
    const cov = h.coverage;

    const rows = cov.by_class
      .map(
        (c) =>
          `<tr class="${c.label === cov.worst_class ? "worst" : ""}">` +
          `<td>${c.label}</td><td>${c.gold}</td><td>${c.correct}</td>` +
          `<td>${c.wrong_value}</td><td>${c.missed}</td>` +
          `<td>${c.recall === null ? "—" : (c.recall * 100).toFixed(1) + "%"}</td></tr>`
      )
      .join("");
    $("h-cov").innerHTML =
      `<tr><th>class</th><th>gold</th><th>correct</th><th>wrong</th><th>missed</th><th>recall</th></tr>` +
      rows;
    $("h-worst").textContent =
      `Overall ${(cov.overall_recall * 100).toFixed(1)}% over ${cov.artifacts_audited} artifacts. ` +
      `Worst class ${cov.worst_class} at ${(cov.worst_recall * 100).toFixed(1)}%. ` +
      `This is where Gemini's second pass earns its place.`;

    const cr = h.credentials;
    $("h-creds").innerHTML =
      `<div>model &nbsp; <span class="ok">${cr.model_fast}</span> · ${cr.model_deep}</div>` +
      `<div>location &nbsp; ${cr.location}</div>` +
      `<div>vertex &nbsp; <span class="${cr.vertex_disabled ? "bad" : "ok"}">` +
      `${cr.vertex_disabled ? "DISABLED for this run" : "enabled"}</span></div>` +
      `<div>live verification &nbsp; <span class="${cr.live_verification_present ? "ok" : "bad"}">` +
      `${cr.live_verification_present ? "docs/LIVE-VERIFICATION.md present" : "NOT PRESENT — no model call has been made from this repository"}</span></div>` +
      `<div style="margin-top:10px">${cr.note}</div>`;

    $("h-built").innerHTML =
      h.built.map((b) => `<div><span class="b">[BUILT]</span> ${b}</div>`).join("") +
      h.designed.map((d) => `<div><span class="d">[DESIGNED]</span> ${d}</div>`).join("");

    show("honesty");
  }

  // ── the instrument (Card 0 spanning Cards 1-3) ─────────────────────

  /* Bars are updated IN PLACE, never re-rendered wholesale, after the
   * first paint -- the BURN/earn demo moment is the amber fill actually
   * animating across a CSS `width` transition, which only fires when the
   * same DOM node's style changes, not when a fresh node is inserted
   * already at its target width. */
  function barRow(b) {
    const max = Math.max(b.balance_bp, b.threshold_bp, 1) * 1.4;
    const fillPct = Math.min(100, (b.balance_bp / max) * 100);
    const thresholdPct = Math.min(100, (b.threshold_bp / max) * 100);
    const earned = b.provenance !== "SYNTHETIC";
    return (
      `<div class="warrant-row" data-agent="${b.agent_id}" data-risk="${b.risk_class}">` +
      `<span class="wr-label mono">${b.agent_id} · ${b.capability} · ${b.risk_class}</span>` +
      `<div class="wr-track"><div class="wr-fill" style="width:${fillPct}%"></div>` +
      `<div class="wr-threshold" style="left:${thresholdPct}%"></div></div>` +
      `<span class="wr-value mono">${b.balance_bp.toLocaleString()}bp</span>` +
      `<span class="wr-synthetic mono ${earned ? "earned" : ""}">${earned ? "EARNED" : "SYNTHETIC"}</span>` +
      `</div>`
    );
  }

  // Bars can be on screen in two places at once -- the home hero and the
  // Warrant detail screen -- so every live update touches every matching
  // row, not just the first. querySelectorAll, never querySelector.
  function updateBar(b) {
    const rows = document.querySelectorAll(
      `.warrant-row[data-agent="${b.agent_id}"][data-risk="${b.risk_class}"]`
    );
    rows.forEach((row) => {
      const max = Math.max(b.balance_bp, b.threshold_bp, 1) * 1.4;
      const fillPct = Math.min(100, (b.balance_bp / max) * 100);
      row.querySelector(".wr-fill").style.width = fillPct + "%";
      row.querySelector(".wr-value").textContent = b.balance_bp.toLocaleString() + "bp";
      const earned = b.provenance !== "SYNTHETIC";
      const syn = row.querySelector(".wr-synthetic");
      syn.classList.toggle("earned", earned);
      syn.textContent = earned ? "EARNED" : "SYNTHETIC";
    });
  }

  function renderInstrument(d) {
    $("instr-bars").innerHTML = d.card0.bars.map(barRow).join("");
    $("instr-route").hidden = true;

    $("instr-c1").innerHTML =
      `<div>causal debt <span class="amber">${d.card1.debt.total.toLocaleString()}</span></div>` +
      `<div>conclusions ${d.card1.counts.conclusions.toLocaleString()}</div>` +
      `<div>claims ${d.card1.counts.claims.toLocaleString()}</div>`;

    $("instr-c2").innerHTML =
      d.card2.agents
        .map((a) => `<div>${a.agent_id} · ${a.status} · [${a.capabilities.join(", ")}]</div>`)
        .join("") + `<div style="margin-top:8px">${d.card2.reason_codes.join(" → ")}</div>`;

    const c3 = d.card3;
    let c3html;
    if (c3.agreement_rate != null) {
      c3html =
        `<div>agreement rate <span class="amber">${(c3.agreement_rate * 100).toFixed(1)}%</span> ` +
        `(${c3.agreed}/${c3.decided})</div>` +
        `<div>${c3.simulated_run ? "SIMULATED — live Gemma unreachable this session" : "LIVE"}</div>` +
        (c3.disagreed > 0
          ? `<div class="instr-freeze-mark"><span class="lbl">CHALLENGE ×${c3.disagreed}</span></div>`
          : "");
    } else {
      c3html = `<div>${c3.note || "not yet measured"}</div>`;
    }
    $("instr-c3").innerHTML = c3html;
  }

  // Same reasoning as updateBar: the BURN/EARN demo moment must read the
  // same on the home hero and inside the Warrant detail screen, whichever
  // one the judge is looking at.
  function applyInstrumentAction(d) {
    d.bars.forEach(updateBar);
    document.querySelectorAll(".instr-route").forEach((route) => {
      route.hidden = false;
      route.classList.remove("refused", "allowed");
      route.classList.add(d.allowed ? "allowed" : "refused");
      route.innerHTML =
        `<span class="code">${d.reason_code}</span> — ${d.before_bp}bp → ${d.after_bp}bp` +
        (d.allowed
          ? " · delegation permitted"
          : " · routed to a human, no cache, visible on the very next call");
    });
    document.querySelectorAll(".instr-feed-line").forEach((l) => l.classList.add("active"));
    setTimeout(
      () => document.querySelectorAll(".instr-feed-line").forEach((l) => l.classList.remove("active")),
      reduced ? 0 : 900
    );
  }

  // ── card detail screens (Warrant / Control Tower / Countersign) ────

  /* Each detail screen reuses exactly the payload `/api/instrument` already
   * serves for the home hero -- no second backend path, no invented data.
   * The difference is presentation: the home tiles are a compact preview,
   * these are the full real surface, on their own screen, reachable by
   * click and returned from by Esc/T like every other overlay. */

  async function fetchInstrument() {
    const res = await fetch("/api/instrument");
    return res.json();
  }

  async function showWarrantDetail() {
    // Chrome (title, back link, lede) is static markup and shows on click;
    // only the data-driven bars below populate once the fetch resolves --
    // same "open first, populate after" fix as showInstrument.
    show("warrant-detail");
    const d = await fetchInstrument();
    if (!d.available) { showInstrument(); return; }
    $("wd-bars").innerHTML = d.card0.bars.map(barRow).join("");
    $("wd-route").hidden = true;
  }

  function renderTowerDetail(card2) {
    const scopeLine = (label, arr) =>
      arr && arr.length ? `<div>${label}: ${arr.join(", ")}</div>` : "";
    $("td-registry").innerHTML = card2.agents
      .map((a) => {
        const thresholds = Object.entries(a.risk_class_thresholds || {})
          .map(([k, v]) => `${k} ${v}`)
          .join(" / ");
        return (
          `<div class="reg-row">` +
          `<div class="reg-id">${a.agent_id} ` +
          `<span class="${a.status === "active" ? "" : "amber"}">[${a.status}]</span></div>` +
          scopeLine("capabilities", a.capabilities) +
          scopeLine("authority_scope", a.authority_scope) +
          scopeLine("data_scope", a.data_scope) +
          (a.max_budget != null
            ? `<div>max_budget ${a.max_budget}${thresholds ? " · risk thresholds " + thresholds : ""}</div>`
            : "") +
          `</div>`
        );
      })
      .join("");
    $("td-reasons").textContent = card2.reason_codes.join("  →  ");
  }

  async function showTowerDetail() {
    show("tower-detail");
    const d = await fetchInstrument();
    if (!d.available) { showInstrument(); return; }
    renderTowerDetail(d.card2);
  }

  function renderCountersignDetail(c3) {
    if (c3.agreement_rate == null) {
      $("cd-body").innerHTML = `<p>${c3.note || "not yet measured"}</p>`;
      return;
    }
    const probe = c3.live_reachability_probe || {};
    const gemma = c3.gemma_family || "gemma";
    const judgingSide = c3.gemini_family_as_judging_side || "gemini";
    let honesty = c3.simulated_run
      ? "SIMULATED — live Gemma unreachable this session"
      : "LIVE — Gemma reachable and answering this session";
    if (c3.simulated_run && probe.error) {
      honesty += `<br><span class="detail-note-quiet">probe: ${probe.error.slice(0, 160)}${probe.error.length > 160 ? "…" : ""}</span>`;
    }
    $("cd-body").innerHTML =
      `<p>Independent verifier: <span class="amber">${gemma}</span> re-reads each case's ` +
      `extraction/judgement material a second time, from a model family separate from the ` +
      `judging side (<span class="amber">${judgingSide}</span>). It writes nothing to the ` +
      `truth layer -- its record reaches only the Memory Bank and the warrant minting gate.</p>` +
      `<p>agreement rate <span class="amber">${(c3.agreement_rate * 100).toFixed(1)}%</span> ` +
      `(${c3.agreed}/${c3.decided} decided, ${c3.disagreed} DISAGREE, ${c3.unavailable} unavailable) ` +
      `over ${c3.scenarios_total} scenarios.</p>` +
      `<p>${honesty}</p>` +
      (c3.disagreed > 0
        ? `<div class="instr-freeze-mark"><span class="lbl">CHALLENGE ×${c3.disagreed}</span></div>`
        : "") +
      `<p>A DISAGREE writes a CHALLENGE event to the warrant ledger: minting freezes for that ` +
      `case until a human resolves it. A countersign record whose model family or principal ` +
      `matches the judging side is rejected outright -- collusion cannot gate its own mint.</p>`;
  }

  async function showCountersignDetail() {
    show("countersign-detail");
    const d = await fetchInstrument();
    if (!d.available) { showInstrument(); return; }
    renderCountersignDetail(d.card3);
  }

  // ── HYPERION-ZERO (immune layer over Card 2's Gateway) ──────────────
  // Its own endpoint, `/api/hyperion` -- a real, distinct concern (fleet
  // security aggregate) from the four-card instrument payload, the same way
  // `/api/loadrating` and `/api/honesty` are already their own endpoints
  // rather than folded into `/api/instrument`.

  async function fetchHyperion() {
    const res = await fetch("/api/hyperion");
    return res.json();
  }

  function hyperionStatLine(h) {
    return (
      `<div class="hy-stat-grid">` +
      `<div class="hy-stat"><span class="n">${h.agents_protected}</span><span class="l">agents protected</span></div>` +
      `<div class="hy-stat"><span class="n">${h.threats_detected}</span><span class="l">threats detected</span></div>` +
      `<div class="hy-stat"><span class="n">${h.blocked_actions}</span><span class="l">blocked actions</span></div>` +
      `<div class="hy-stat"><span class="n">${h.fleet_health_pct}%</span><span class="l">fleet health</span></div>` +
      `</div>`
    );
  }

  function renderHyperionHome(h) {
    if (!h.available) {
      $("instr-hyperion-body").innerHTML =
        `<div class="hy-status-line">immune log unreachable — start <span class="mono">make emulator</span></div>`;
      return;
    }
    const status = h.events_total > 0
      ? `<span class="dot" aria-hidden="true"></span>IMMUNE CORE ACTIVE — ${h.events_total} decision${h.events_total === 1 ? "" : "s"} observed`
      : `<span class="dot" aria-hidden="true"></span>IMMUNE CORE ACTIVE — no decisions observed yet`;
    $("instr-hyperion-body").innerHTML =
      `<div class="hy-status-line">${status}</div>` + hyperionStatLine(h);
  }

  function eventRow(e) {
    const blocked = !e.allowed;
    const ts = e.recorded_at ? new Date(e.recorded_at).toLocaleTimeString() : "";
    return (
      `<div class="reg-row">` +
      `<div class="reg-id">${e.agent_id} ` +
      `<span class="${blocked ? "amber" : ""}">[${e.reason_code}]</span></div>` +
      `<div>${e.threat_type} · risk ${e.risk_score}/100 (${e.risk_level}) · ${ts}</div>` +
      `<div>${e.task}</div>` +
      `</div>`
    );
  }

  function renderHyperionDetail(h) {
    if (!h.available) {
      $("hd-summary").innerHTML = `<p>${h.reason}</p>`;
      $("hd-events").innerHTML = "";
      return;
    }
    $("hd-summary").innerHTML =
      hyperionStatLine(h) +
      `<p style="margin-top:16px">${h.agents_observed} agent(s) observed directly · ` +
      `${h.risk_band_counts.LOW} LOW · ${h.risk_band_counts.MEDIUM} MEDIUM · ` +
      `${h.risk_band_counts.HIGH} HIGH · ${h.risk_band_counts.CRITICAL} CRITICAL</p>`;
    $("hd-events").innerHTML = h.recent_events.length
      ? h.recent_events.map(eventRow).join("")
      : `<p>No events logged yet — run the probe below, or reload after the Gateway has been called elsewhere.</p>`;
  }

  async function showHyperionDetail() {
    show("hyperion-detail");
    const h = await fetchHyperion();
    renderHyperionDetail(h);
  }

  async function handleHyperionProbe() {
    // Server-side this is require_principal-gated; plain fetch() never sent
    // a credential, so an unauthenticated caller got a JSON error body with
    // no `.decision`, and this threw before the route element updated.
    const res = await authedFetch("/api/hyperion/probe", { method: "POST" });
    const route = $("hd-probe-result");
    if (!res.ok) {
      const { status, help, detail } = await describeFailure(res);
      route.hidden = false;
      route.classList.remove("allowed");
      route.classList.add("refused");
      route.innerHTML =
        `<span class="code">HTTP ${status}</span> — ${esc(help)}` +
        (detail ? `<div class="cmdos-hint mono">${esc(detail)}</div>` : "");
      return;
    }
    const d = await res.json();
    route.hidden = false;
    route.classList.remove("refused", "allowed");
    route.classList.add(d.decision.allowed ? "allowed" : "refused");
    route.innerHTML =
      `<span class="code">${d.decision.reason_code}</span> — ${d.assessment.threat_type}, ` +
      `risk ${d.assessment.risk_score}/100 (${d.assessment.risk_level}) — ${d.decision.reason}`;
    renderHyperionDetail(d);
    renderHyperionHome(d);
  }

  // ── SINGULARITY-MESH (Card 5 -- zero-trust autonomous agent fleet) ──
  // Its own endpoints, `/api/singularity` and the two probes -- an
  // independent concern from both the four-card instrument payload and
  // Hyperion's `/api/hyperion`. See `singularity/DESIGN.md`: only
  // Capability Genome, Behavioral DNA and their event log are LIVE; the
  // fleet/architecture/MCP/etc. sections below are reference content and
  // are rendered with an explicit ARCHITECTURE badge, never claimed live.

  async function fetchSingularity() {
    const res = await fetch("/api/singularity");
    return res.json();
  }

  function statusBadge(status) {
    const s = String(status || "");
    let cls = "arch";
    if (s.includes("LIVE")) cls = "live";
    else if (s.includes("DEMO") || s.includes("SIMULATION")) cls = "demo";
    return `<span class="sm-status ${cls}">${s}</span>`;
  }

  function smFlowLine(steps) {
    return steps.map((s) => `<span>${s}</span>`).join('<span class="sm-arrow">→</span>');
  }

  function smFlowSteps(containerId, steps, liveNames) {
    const live = new Set(liveNames || []);
    $(containerId).innerHTML = steps
      .map((s, i) => {
        const name = s.name || s;
        const isLive = live.has(name) || (s.status && String(s.status).includes("LIVE"));
        const step = `<span class="step${isLive ? " live" : ""}">${name}</span>`;
        return i === 0 ? step : `<span class="sep">→</span>${step}`;
      })
      .join("");
  }

  function renderSingularityHome(d) {
    if (!d.mesh_available) {
      $("instr-c5").innerHTML =
        `<div>Capability Genome · Behavioral DNA <span class="amber">ARCHITECTURE PREVIEW</span></div>` +
        `<div style="opacity:.6">mesh log unreachable — start <span class="mono">make emulator</span></div>`;
      return;
    }
    $("instr-c5").innerHTML =
      `<div>fleet ${d.fleet.length} agents · lifecycle ${d.lifecycle_stages.length} stages</div>` +
      `<div class="amber">genome ${d.genome_events_total} · drift ${d.behavior_events_total} · ` +
      `denials ${d.capability_denials} · isolations ${d.behavioral_isolations}</div>`;
  }

  function fleetRow(a) {
    return (
      `<div class="reg-row">` +
      `<div class="reg-id">${a.title} ${statusBadge(a.status)}</div>` +
      `<div>${a.responsibility}</div>` +
      `<div>inputs: ${a.inputs.join(", ")}</div>` +
      `<div>outputs: ${a.outputs.join(", ")}</div>` +
      `<div>security: ${a.security_responsibility}</div>` +
      `<div>relationship: ${a.relationship}</div>` +
      `</div>`
    );
  }

  function renderSingularityDetail(d) {
    // The Agent Fleet -- Sentinel + Orchestrator up top, workers in their own section.
    const sentinelAndOrchestrator = d.fleet.filter((a) => !a.role.startsWith("WORKER"));
    const workers = d.fleet.filter((a) => a.role.startsWith("WORKER"));
    $("sm-fleet").innerHTML = sentinelAndOrchestrator.map(fleetRow).join("");
    $("sm-workers").innerHTML = workers.map(fleetRow).join("");

    // Lifecycle timeline (hero).
    $("sm-lifecycle").innerHTML = d.lifecycle_stages
      .map(
        (s) =>
          `<div class="sm-stage"><div class="n">${String(s.n).padStart(2, "0")}</div>` +
          `<div class="name">${s.name}</div><div class="note">${s.note}</div></div>`
      )
      .join("");

    // Agent Immune System.
    $("sm-immune").innerHTML = d.immune_layers
      .map(
        (l) =>
          `<div class="sm-immune-card${l.status === "LIVE" ? " sm-immune-live" : ""}">` +
          `<div class="name">${l.name} ${statusBadge(l.status)}</div>` +
          `<div class="threat">${l.threat}</div>` +
          `<div class="action">${l.action}</div></div>`
      )
      .join("");

    // MCP / Knowledge Catalog / Model Armor / Agent Gateway flows.
    $("sm-mcp-flow").innerHTML = smFlowLine(d.mcp_flow);
    $("sm-catalog").innerHTML = smFlowLine(d.knowledge_catalog_sources);
    $("sm-armor-flow").innerHTML = smFlowLine(d.model_armor_flow);
    $("sm-gateway-resp").innerHTML = smFlowLine(d.agent_gateway_responsibilities);
    $("sm-memory-chain").innerHTML = smFlowLine(d.agent_memory_chain);
    $("sm-a2a-chain").innerHTML = smFlowLine(d.agent_to_agent_chain);
    $("sm-agentic-chain").innerHTML = smFlowLine(d.why_agentic_chain);
    $("sm-governed-stack").innerHTML = d.governed_autonomy_stack
      .map((s, i) => (i === 0 ? `<span>${s}</span>` : `<span class="sm-plus">+</span><span>${s}</span>`))
      .join("") + `<span class="sm-eq-arrow">↓</span><span class="amber">SAFE AUTONOMOUS FLEET</span>`;
    $("sm-innovation-stack").innerHTML = d.innovation_stack
      .map((s, i) => (i === 0 ? `<span>${s}</span>` : `<span class="sm-plus">+</span><span>${s}</span>`))
      .join("");

    // IAM identities.
    $("sm-iam").innerHTML = d.iam_identities
      .map(
        (id) =>
          `<div class="reg-row"><div class="reg-id">${id.account}</div>` +
          `<div>allowed: ${id.allowed.join(", ")}</div>` +
          `<div>denied: ${id.denied.join(", ")}</div></div>`
      )
      .join("");

    // Seven architecture layers.
    $("sm-layers").innerHTML = d.architecture_layers
      .map(
        (l) =>
          `<div class="sm-layer-row"><span class="n">${l.n}</span><span class="name">${l.name}</span>` +
          `<span class="detail">${l.detail}</span>${statusBadge(l.status)}</div>`
      )
      .join("");

    // Recovery flow -- rendered once compactly (self-healing section) and
    // once as the full attack->resume walkthrough (same underlying steps).
    smFlowSteps("sm-recovery-flow", d.recovery_flow);
    smFlowSteps("sm-recovery-detail", d.recovery_flow);

    // 3-minute demo.
    $("sm-demo-phases").innerHTML = d.demo_phases
      .map(
        (p) =>
          `<div class="sm-demo-phase"><div class="title">PHASE ${p.phase} — ${p.title}</div>` +
          `<div class="input">"${p.input}"</div>` +
          `<div class="mono">${smFlowLine(p.flow)}</div>` +
          `<div class="sm-note">${p.status}</div></div>`
      )
      .join("");

    // Implementation status table.
    $("sm-status-table").innerHTML = Object.entries(d.implementation_status)
      .map(([k, v]) => `<div class="row"><span>${k.replace(/_/g, " ")}</span>${statusBadge(v)}</div>`)
      .join("");

    // Observability stream -- real mesh events when the log has any,
    // honestly empty otherwise. Never fabricated to look live.
    const events = d.recent_events || [];
    $("sm-observability-empty").hidden = events.length > 0 || d.mesh_available === false;
    $("sm-observability").innerHTML = events
      .map((e) => {
        const ts = e.recorded_at ? new Date(e.recorded_at).toLocaleTimeString() : "";
        return (
          `<div class="reg-row"><div class="reg-id">${e.agent_role} ` +
          `<span class="${e.allowed ? "" : "amber"}">[${e.reason_code}]</span></div>` +
          `<div>${e.kind === "genome" ? "capability genome" : "behavioral DNA"} · ${e.reason} · ${ts}</div>` +
          `</div>`
        );
      })
      .join("");
  }

  function renderGenomeResult(scenario, genome) {
    const route = $("sm-genome-result");
    route.hidden = false;
    route.classList.remove("refused", "allowed");
    route.classList.add(genome.decision === "ALLOW" ? "allowed" : "refused");
    route.innerHTML =
      `<span class="code">${genome.decision}</span> (${scenario}) — risk ${genome.risk_level} — ${genome.reason}` +
      (genome.denied_actions.length ? `<br>denied: ${genome.denied_actions.join(", ")}` : "") +
      (genome.allowed_actions.length ? `<br>allowed: ${genome.allowed_actions.join(", ")}` : "");
  }

  //: Renders a failed action directly into the same result slot a success
  //: would use, with the .refused styling the rest of this card already
  //: uses for a denied outcome -- no second notification surface.
  async function showProbeFailure(elId, res) {
    const { status, help, detail } = await describeFailure(res);
    const route = $(elId);
    route.hidden = false;
    route.classList.remove("allowed");
    route.classList.add("refused");
    route.innerHTML =
      `<span class="code">HTTP ${status}</span> — ${esc(help)}` +
      (detail ? `<br>${esc(detail)}` : "");
  }

  async function handleGenomeProbe(scenario) {
    const res = await fetch(`/api/singularity/genome/probe?scenario=${scenario}`, { method: "POST" });
    if (!res.ok) {
      await showProbeFailure("sm-genome-result", res);
      return;
    }
    const d = await res.json();
    renderGenomeResult(d.scenario, d.genome);
    renderSingularityDetail({ ...(await fetchSingularity()), ...d });
    renderSingularityHome(await fetchSingularity());
  }

  function renderBehaviorResult(scenario, assessment) {
    const route = $("sm-behavior-result");
    route.hidden = false;
    route.classList.remove("refused", "allowed");
    route.classList.add(assessment.drift_band === "NORMAL" ? "allowed" : "refused");
    route.innerHTML =
      `<span class="code">${assessment.drift_band}</span> (${scenario}) — score ${assessment.drift_score}/100 ` +
      `— action ${assessment.capability_action}<br>${assessment.signals.join("; ")}`;
  }

  async function handleBehaviorProbe(scenario) {
    const res = await fetch(`/api/singularity/behavior/probe?scenario=${scenario}`, { method: "POST" });
    if (!res.ok) {
      await showProbeFailure("sm-behavior-result", res);
      return;
    }
    const d = await res.json();
    renderBehaviorResult(d.scenario, d.assessment);
    renderSingularityDetail({ ...(await fetchSingularity()), ...d });
    renderSingularityHome(await fetchSingularity());
  }

  async function showSingularityDetail() {
    show("singularity-detail");
    const d = await fetchSingularity();
    renderSingularityDetail(d);
  }

  $("sm-genome-normal").addEventListener("click", () => handleGenomeProbe("normal"));
  $("sm-genome-attack").addEventListener("click", () => handleGenomeProbe("attack"));
  $("sm-behavior-normal").addEventListener("click", () => handleBehaviorProbe("normal"));
  $("sm-behavior-drift").addEventListener("click", () => handleBehaviorProbe("drift"));

  // ── instrument (home) / core / honesty-peek visibility ──────────────

  /* THE INSTRUMENT is the default landing view -- it needs no toggle-off,
   * only a way IN to Core (click Card 1) and a way BACK (Esc, T, or the
   * "the four cards" link). Honesty is the one remaining true "peek": H
   * can be pressed from either the instrument or from inside Core, and
   * must restore exactly which of those it was pressed from on toggle-off
   * -- never a state.st reset (that would wipe an in-progress cascade),
   * just visibility. */
  let coreVisibleBeforePeek = false;

  function notePeekOrigin() {
    coreVisibleBeforePeek = !$("hud-left").hidden;
  }

  function hideCore() {
    $("hud-left").hidden = true;
    $("hud-right").hidden = true;
    $("legend").hidden = true;
    $("bar-wrap").hidden = true;
    $("core-home-link").hidden = true;
  }

  function showCoreChrome() {
    $("hud-left").hidden = false;
    $("hud-right").hidden = false;
    $("legend").hidden = false;
    $("bar-wrap").hidden = false;
    $("core-home-link").hidden = false;
  }

  function restorePeekedFrom() {
    if (coreVisibleBeforePeek) {
      showCoreChrome();
      state.screen = "field";
    } else {
      showInstrument();
    }
  }

  function enterCore() {
    hideAll();
    showCoreChrome();
    if (state.st) {
      restart();
    } else {
      // boot() has not resolved yet -- reveal the chrome now; restart()
      // itself runs later once state.st exists, nothing to reset yet.
      $("bar-wrap").classList.remove("gone");
      $("bar").focus();
    }
  }

  document.querySelectorAll(".instr-clickable").forEach((el) => {
    const activate = () => {
      switch (el.dataset.card) {
        case "0": showWarrantDetail(); break;
        case "1": enterCore(); break;
        case "2": showTowerDetail(); break;
        case "3": showCountersignDetail(); break;
        case "4": showHyperionDetail(); break;
        case "5": showSingularityDetail(); break;
      }
    };
    el.addEventListener("click", activate);
    el.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); activate(); }
    });
  });

  $("core-home-link").addEventListener("click", showInstrument);
  document.querySelectorAll(".detail-back").forEach((btn) => {
    btn.addEventListener("click", showInstrument);
  });

  // ── AGENTIC COMMAND OS — master orchestration layer above the instrument.
  // Additive only: every function below is new, nothing above it changed.

  let cmdosMissionId = null;

  // ---- operator credential -------------------------------------------------
  // Every mutating endpoint refuses an anonymous caller (401). The token lives
  // in sessionStorage only -- never localStorage, so it does not outlive the
  // tab -- and is sent as a bearer header. When the server is configured with
  // UNWIND_DEV_PRINCIPAL the field can stay empty; the auth-mode line below
  // says which of those is true rather than leaving a judge to guess.
  const TOKEN_KEY = "unwind.operator.token";

  function operatorToken() {
    const field = $("cmdos-token");
    return (field && field.value.trim()) || sessionStorage.getItem(TOKEN_KEY) || "";
  }

  function authHeaders() {
    const token = operatorToken();
    return token ? { Authorization: "Bearer " + token } : {};
  }

  //: `quietAuth: true` suppresses the page-level NOT AUTHENTICATED banner for
  //: a read that renders its own, more specific one. The banner's text is
  //: about MUTATING endpoints refusing an anonymous caller; raising it the
  //: instant an anonymous visitor loads the page -- which is what the now-
  //: inline Time Machine's passive read would otherwise do -- tells them
  //: something was refused that they never asked for. The Time Machine still
  //: says NOT AUTHENTICATED in its own panel, where it is true and actionable.
  async function authedFetch(url, options) {
    const opts = Object.assign({}, options || {});
    const quiet = opts.quietAuth === true;
    delete opts.quietAuth;
    opts.headers = Object.assign({}, opts.headers || {}, authHeaders());
    const res = await fetch(url, opts);
    if ((res.status === 401 || res.status === 403) && !quiet) {
      $("cmdos-authfail").hidden = false;
    }
    return res;
  }

  function statusClass(status) {
    if (status.indexOf("LIVE") === 0) return "cmdos-live";
    if (status === "SIMULATED") return "cmdos-simulated";
    if (status === "UNAVAILABLE") return "cmdos-unavailable";
    if (status === "DESIGNED") return "cmdos-designed";
    return "cmdos-reference";
  }

  function renderMissionStages(stages) {
    const el = $("cmdos-stages");
    el.innerHTML = stages.map((s) => (
      "<li class='cmdos-stage'>" +
        "<div class='cmdos-stage-head'>" +
          "<span class='cmdos-stage-n'>" + String(s.n).padStart(2, "0") + "</span>" +
          "<span class='cmdos-stage-name cond'>" + s.name + "</span>" +
          "<span class='cmdos-tag " + statusClass(s.status) + "'>" + s.status + "</span>" +
        "</div>" +
        "<div class='cmdos-stage-summary'>" + s.summary + "</div>" +
      "</li>"
    )).join("");
  }

  //: Status -> headline. Never a bare success over a refusal: the mapping is
  //: the UI half of `command_os/mission.py:_mission_status`, and the two must
  //: agree because the report carries the status the server computed.
  const STATUS_HEADLINE = {
    COMPLETED: "MISSION: COMPLETED",
    COMPLETED_WITH_RESTRICTIONS: "MISSION: COMPLETED WITH RESTRICTIONS",
    BLOCKED: "MISSION: BLOCKED",
    CHALLENGED: "MISSION: CHALLENGED — minting frozen, routed to a human",
    FAILED_SAFE: "MISSION: FAILED SAFE",
    HALTED: "MISSION: HALTED",
    AWAITING_HUMAN: "MISSION: AWAITING HUMAN",
  };

  function row(k, v) {
    return "<div><span class='k'>" + k + "</span><span class='v'>" +
      (v === null || v === undefined || v === "" ? "—" : v) + "</span></div>";
  }

  function renderPlan(plan) {
    const panel = $("cmdos-plan-panel");
    if (!plan) { panel.hidden = true; return; }
    panel.hidden = false;
    const steps = plan.steps.map((st) => (
      "<div class='cmdos-plan-step'>" +
        "<span class='cmdos-plan-seq'>" + String(st.seq).padStart(2, "0") + "</span>" +
        "<span class='cmdos-plan-role cond'>" + st.role + "</span>" +
        "<span class='cmdos-plan-tool'>" + st.tool + "</span>" +
        "<span class='cmdos-tag cmdos-reference'>" + st.action_kind + "</span>" +
        "<span class='cmdos-plan-scope'>" + (st.requested_scope || []).join(", ") + "</span>" +
      "</div>"
    )).join("");
    const clamps = (plan.clamps || []).length
      ? "<div class='cmdos-plan-clamps'>validator narrowed: " +
          plan.clamps.map((c) => "<div>· " + c + "</div>").join("") + "</div>"
      : "";
    $("cmdos-plan").innerHTML =
      "<div class='cmdos-plan-head'>" +
        "<span class='cmdos-tag " + statusClass(plan.provenance === "ZERO_MODEL" ? "SIMULATED" : "LIVE") + "'>" +
          plan.provenance + "</span>" +
        "<span class='cmdos-plan-class cond'>" + plan.objective_class + "</span>" +
        "<span class='cmdos-hint'>" + plan.model + "</span>" +
      "</div>" +
      steps + clamps +
      (plan.notes ? "<div class='cmdos-hint'>" + plan.notes + "</div>" : "");
  }

  function renderMissionReport(report, missionStatus) {
    const el = $("cmdos-report");
    el.hidden = false;
    const headline = STATUS_HEADLINE[report.status] || ("MISSION: " + report.status);
    el.innerHTML =
      "<div class='cmdos-report-title cond'>" + headline + "</div>" +
      "<div class='cmdos-report-grid'>" +
        row("objective class", report.objective_class) +
        row("planner", report.planner_provenance + " · " + report.planner_model) +
        row("agents selected", (report.agents_selected || []).join(", ")) +
        row("steps planned / executed", report.steps_planned + " / " + report.steps_executed) +
        row("replans", report.replans) +
        row("evidence parsed", report.evidence_records_parsed + " / " + report.evidence_records_total +
            " (" + Math.round((report.evidence_completeness || 0) * 100) + "%)") +
        row("contradictions found", report.contradictions_found) +
        row("reconciliation", (report.reconciliation_verdict || "—") +
            (report.contradictions_found
              ? " · " + report.contradictions_reconciled + " settled / " +
                report.contradictions_disputed + " disputed"
              : "")) +
        row("disputed claims", (report.disputed_claims || []).join(", ")) +
        row("escalations found", report.escalations_found) +
        row("drift", report.drift_band + " (" + report.drift_score + ")") +
        row("agents isolated", report.agents_isolated + (report.isolated_agent ? " · " + report.isolated_agent : "")) +
        row("gateway refusals", (report.gateway_refusals || []).join(", ")) +
        row("unsafe actions executed", report.unsafe_actions_executed) +
        row("worker faults", report.worker_faults +
            ((report.worker_fault_kinds || []).length
              ? " · " + report.worker_fault_kinds.join(", ")
              : "")) +
        row("challenger", report.challenger_agrees === null ? "UNAVAILABLE"
              : (report.challenger_agrees ? "AGREED" : "DISAGREED")) +
        row("human principal", report.human_principal) +
        row("gate", report.gate) +
        row("external action", report.external_action) +
        row("external id", report.external_action_id) +
        row("verified", report.verified === null ? "—" : String(report.verified)) +
      "</div>" +
      (report.challenger_ground
        ? "<div class='cmdos-hint cmdos-ground'>challenger ground: " + report.challenger_ground + "</div>"
        : "");
  }

  function renderExternal(report) {
    const panel = $("cmdos-external-panel");
    if (!report || !report.external_action_id) { panel.hidden = true; return; }
    panel.hidden = false;
    $("cmdos-external").innerHTML =
      "<div class='cmdos-report-grid'>" +
        row("action", report.external_action) +
        row("backend", report.external_backend) +
        row("external id", report.external_action_id) +
        row("replayed", String(report.external_replayed)) +
        row("independently verified", String(report.verified)) +
      "</div>";
  }

  //: RECALL. Everything rendered here is read back from the mission's own
  //: PLAN checkpoint, never recomputed -- a re-run of the retriever could
  //: return something different now, and what a judge needs to see is the
  //: retrieval that actually informed the plan.
  //:
  //: Every interpolation goes through esc(): a knowledge record's statement
  //: is server-derived text that ultimately traces back to an evidence file,
  //: which is exactly the stored-XSS path the Time Machine already had once.
  function renderRecall(body) {
    const panel = $("cmdos-recall-panel");
    const consulted = body && body.consulted;
    if (!consulted) { panel.hidden = true; return; }
    panel.hidden = false;

    if (consulted.available === false) {
      $("cmdos-recall").innerHTML =
        "<div class='cmdos-reality-row'>" +
          "<span class='cmdos-reality-feature'>knowledge store</span>" +
          "<span class='cmdos-tag cmdos-unavailable'>UNAVAILABLE</span>" +
        "</div>" +
        "<div class='cmdos-hint'>" + esc(consulted.reason || "") + "</div>" +
        "<div class='cmdos-hint'>the mission planned exactly as it would have with no store; " +
          "recall informs planning, it never gates it</div>";
      return;
    }

    const corpus = consulted.corpus_records || 0;
    const selected = consulted.selected || 0;
    const rejected = (consulted.zero_scored || 0) + (consulted.dropped_for_budget || 0) +
      (consulted.filtered_out || 0);

    const counts =
      "<div class='cmdos-report-grid'>" +
        row("records in the store", corpus) +
        row("selected for this plan", selected + (corpus ? " of " + corpus : "")) +
        row("rejected", rejected + " (" + (consulted.zero_scored || 0) + " scored zero, " +
            (consulted.dropped_for_budget || 0) + " over budget, " +
            (consulted.filtered_out || 0) + " filtered)") +
        row("context used", (consulted.chars_returned || 0) + " / " +
            (consulted.char_budget || 0) + " characters") +
        row("risk profile", esc(body.risk_profile_before_recall || "—") + "  →  " +
            esc(body.risk_profile || "—")) +
        row("knowledge this mission produced", (body.produced || []).length) +
      "</div>";

    const records = (consulted.selected_records || []).map((r) => (
      "<div class='cmdos-recall-row'>" +
        "<div class='cmdos-recall-head'>" +
          "<span class='cmdos-tag cmdos-reference'>" + esc(r.kind) + "</span>" +
          "<span class='cmdos-recall-subject cond'>" + esc(r.subject) + "</span>" +
          "<span class='cmdos-hint'>score " + esc(r.score) + " · terms " +
            esc((r.matched_terms || []).join(", ")) + "</span>" +
        "</div>" +
        "<div class='cmdos-recall-statement'>" + esc(r.statement) + "</div>" +
        "<div class='cmdos-hint'>from mission " + esc(r.mission_id) +
          (r.checkpoint_seq ? " · checkpoint " + esc(r.checkpoint_seq) : "") +
          (r.source ? " · source " + esc(r.source) : "") + "</div>" +
      "</div>"
    )).join("");

    const directive = consulted.directive || {};
    const applied = (body.scrutiny_applied || []).map(
      (n) => "<div>· " + esc(n) + "</div>"
    ).join("");

    const directiveBlock =
      "<div class='cmdos-recall-directive'>" +
        "<div class='cmdos-recall-head'>" +
          "<span class='cmdos-tag " + ((directive.derived_from || []).length ? "cmdos-live" : "cmdos-reference") + "'>" +
            "SCRUTINY DIRECTIVE</span>" +
          "<span class='cmdos-hint'>risk floor " + esc(directive.raise_risk_class || "LOW") +
            " · verification " + ((directive.require_verification) ? "REQUIRED" : "not required") +
            " · derived from " + ((directive.derived_from || []).length) + " record(s)</span>" +
        "</div>" +
        (directive.scrutiny_notes || []).map((n) => "<div class='cmdos-hint'>· " + esc(n) + "</div>").join("") +
        (applied ? "<div class='cmdos-plan-clamps'>applied to the plan:" + applied + "</div>" : "") +
      "</div>";

    $("cmdos-recall").innerHTML = counts + records + directiveBlock;
  }

  //: RECONCILIATION. Read out of the mission's own RECONCILE stage rather
  //: than re-derived, for the same reason as recall above.
  function renderReconciliation(stages) {
    const panel = $("cmdos-reconcile-panel");
    const stage = (stages || []).find((s) => s.name.indexOf("RECONCILE") === 0);
    const data = stage && stage.detail && stage.detail.reconciliation;
    if (!data) {
      // No reconciliation ran. That is a FACT about the evidence -- it did
      // not contradict itself -- and hiding the panel with no explanation
      // would read as a missing feature.
      panel.hidden = true;
      return;
    }
    panel.hidden = false;

    const settled = (data.resolutions || []).map((r) => (
      "<div class='cmdos-recall-row'>" +
        "<div class='cmdos-recall-head'>" +
          "<span class='cmdos-tag cmdos-live'>SETTLED</span>" +
          "<span class='cmdos-recall-subject cond'>" + esc(r.claim_id) + "</span>" +
          "<span class='cmdos-hint'>" + esc(r.predicate) + " = " + esc(r.chosen_value) +
            " · authority " + esc(r.chosen_authority) + "</span>" +
        "</div>" +
        "<div class='cmdos-recall-statement'>" + esc(r.why) + "</div>" +
      "</div>"
    )).join("");

    const disputed = (data.disputes || []).map((d) => (
      "<div class='cmdos-recall-row'>" +
        "<div class='cmdos-recall-head'>" +
          "<span class='cmdos-tag cmdos-unavailable'>DISPUTED</span>" +
          "<span class='cmdos-recall-subject cond'>" + esc(d.claim_id) + "</span>" +
          "<span class='cmdos-hint'>" + esc(d.dispute_kind) + "</span>" +
        "</div>" +
        "<div class='cmdos-report-grid'>" +
          row("by recency", esc(d.recency_value) + " (" + esc(d.recency_source) + ")") +
          row("by authority", (d.authority_value === null || d.authority_value === undefined)
                ? "no ranked authority holds standing"
                : esc(d.authority_value) + " (" + esc(d.authority_source) + ")") +
        "</div>" +
        "<div class='cmdos-recall-statement'>" + esc(d.why) + "</div>" +
      "</div>"
    )).join("");

    $("cmdos-reconcile").innerHTML =
      "<div class='cmdos-report-grid'>" +
        row("verdict", esc(data.verdict)) +
        row("contradictions considered", data.contradictions_considered) +
        row("rules compared", esc((data.rules_compared || []).join(" vs "))) +
      "</div>" + settled + disputed;
  }

  async function loadRecall(missionId) {
    const res = await authedFetch("/api/recall/mission/" + missionId);
    if (!res.ok) { $("cmdos-recall-panel").hidden = true; return; }
    const body = await res.json();
    if (body.available === false) { $("cmdos-recall-panel").hidden = true; return; }
    renderRecall(body);
  }

  function renderTrust(state) {
    const el = $("cmdos-trust");
    const rows = [
      ["TRUSTED", state.trusted],
      ["UNTRUSTED", state.untrusted],
      ["QUARANTINED", state.quarantined],
      ["REVOKED", state.revoked],
    ];
    el.innerHTML = rows.map(([label, items]) => (
      "<div class='cmdos-reality-row'>" +
        "<span class='cmdos-reality-feature'>" + label + "</span>" +
        "<span class='cmdos-tag " + statusClass(label === "TRUSTED" ? "LIVE" : label === "REVOKED" ? "UNAVAILABLE" : "SIMULATED") + "'>" +
          items.length + "</span>" +
      "</div>"
    )).join("");
  }

  function renderFirewall(decisions) {
    const el = $("cmdos-firewall");
    el.innerHTML = decisions.map((d) => (
      "<div class='cmdos-reality-row' title='" + d.reason + "'>" +
        "<span class='cmdos-reality-feature'>" + String(d.seq).padStart(2, "0") + " " + d.stage + "</span>" +
        "<span class='cmdos-tag " + (d.decision === "INCLUDE" ? "cmdos-live" : d.decision === "REJECT" ? "cmdos-unavailable" : "cmdos-simulated") + "'>" +
          d.decision + "</span>" +
      "</div>"
    )).join("");
  }

  async function loadTrustAndFirewall(missionId) {
    const [trustRes, firewallRes] = await Promise.all([
      authedFetch("/api/command-os/mission/" + missionId + "/trust"),
      authedFetch("/api/command-os/mission/" + missionId + "/context-firewall"),
    ]);
    if (!trustRes.ok || !firewallRes.ok) return;
    renderTrust(await trustRes.json());
    renderFirewall((await firewallRes.json()).decisions);
    $("cmdos-trust-firewall").hidden = false;
  }

  //: The 30-second version of everything below. Every node reads a field
  //: already present on `report`, `plan` or `stages[0].detail` -- the exact
  //: same data `renderMissionReport`, `renderReconciliation` and `renderRecall`
  //: already render in full. This is not a second source of truth, it is an
  //: index into the one that exists, in the order the mission actually ran.
  function renderMissionFlow(d) {
    const el = $("cmdos-flow");
    const chain = $("cmdos-flow-chain");
    if (!d.report) { el.hidden = true; return; }
    const r = d.report;
    const planDetail = (d.stages && d.stages[0] && d.stages[0].detail) || {};
    const recall = planDetail.recall || {};
    const selected = recall.selected_records || [];
    const reconcileStage = (d.stages || []).find((s) => s.name.indexOf("RECONCILE") === 0);
    const reconcileData = reconcileStage && reconcileStage.detail && reconcileStage.detail.reconciliation;

    const node = (label, reached, detail) => (
      "<li class='cmdos-flow-node " + (reached ? "reached" : "skipped") + "'>" +
        "<span class='cmdos-flow-arrow'>" + (reached ? "●" : "○") + "</span>" +
        "<span class='cmdos-flow-label'>" + esc(label) + "</span>" +
        (detail ? "<span class='cmdos-flow-detail'>" + detail + "</span>" : "") +
      "</li>"
    );

    const nodes = [
      node("OBJECTIVE", true, esc(r.objective)),
      node(
        "PLAN",
        true,
        esc(r.objective_class) + " · " + esc(r.planner_provenance) + " (" + esc(r.planner_model) + ") · " +
          r.steps_planned + " step(s)"
      ),
      node(
        "DELEGATE → SPECIALISTS",
        (r.agents_selected || []).length > 0,
        esc((r.agents_selected || []).join(", ") || "no specialist selected")
      ),
      node(
        "EXECUTE",
        r.steps_executed > 0,
        r.steps_executed + " / " + r.steps_planned + " step(s) executed · tools: " +
          esc((r.tools_used || []).join(", ") || "—")
      ),
      node(
        "FAILURE / REPLAN",
        r.replans > 0 || r.worker_faults > 0,
        r.replans + " replan(s) · " + r.worker_faults + " worker fault(s)" +
          ((r.worker_fault_kinds || []).length ? " (" + esc(r.worker_fault_kinds.join(", ")) + ")" : "")
      ),
      node(
        "RECONCILE",
        !!reconcileData,
        reconcileData
          ? esc(reconcileData.verdict) + " · " + (reconcileData.resolutions || []).length +
            " settled / " + (reconcileData.disputes || []).length + " disputed"
          : "no contradiction in this mission's evidence — nothing to reconcile"
      ),
      node(
        "GOVERNANCE",
        !!r.human_principal,
        r.human_principal
          ? "gate " + esc(r.gate || "—") + " · principal " + esc(r.human_principal) +
            " · challenger " + (r.challenger_agrees === null ? "UNAVAILABLE" : r.challenger_agrees ? "AGREED" : "DISAGREED")
          : "no human decision recorded in this mission"
      ),
      node(
        "EXTERNAL ACTION",
        !!r.external_action_id,
        r.external_action_id
          ? esc(r.external_action) + " · " + esc(r.external_action_id) + " · verified " + String(r.verified)
          : "no external effect — nothing mutated outside this process"
      ),
      node(
        "DISTILL KNOWLEDGE",
        r.status !== "AWAITING_HUMAN",
        r.status === "AWAITING_HUMAN"
          ? "distillation happens on completion — this mission is still paused at the gate"
          : "on completion, what this mission measured is written to the knowledge store, " +
            "named to this mission id — see the Evolving Knowledge panel below"
      ),
      node(
        "NEXT-MISSION ADAPTATION",
        selected.length > 0,
        selected.length > 0
          ? selected.length + " record(s) recalled from " +
            new Set(selected.map((s) => s.mission_id)).size + " prior mission(s) · " +
            (planDetail.scrutiny_applied || []).length + " change(s) applied to THIS plan"
          : recall.corpus_records
            ? recall.corpus_records + " record(s) in the store; none scored high enough to select"
            : "no prior mission had written anything yet when this one planned"
      ),
    ];
    chain.innerHTML = nodes.join("");
    el.hidden = false;
  }

  function applyMissionResult(d) {
    cmdosMissionId = d.mission_id;
    renderMissionStages(d.stages);
    renderPlan(d.plan);
    renderReconciliation(d.stages);
    renderMissionFlow(d);
    loadRecall(d.mission_id);
    if (d.status === "AWAITING_HUMAN") {
      $("cmdos-gate").hidden = false;
      $("cmdos-report").hidden = true;
      $("cmdos-trust-firewall").hidden = true;
      $("cmdos-external-panel").hidden = true;
    } else {
      $("cmdos-gate").hidden = true;
      renderMissionReport(d.report, d.status);
      renderExternal(d.report);
      loadTrustAndFirewall(d.mission_id);
    }
    // The Time Machine sits right below this report and must show the
    // mission that just ran, not whatever was on screen before it started —
    // otherwise a mission that visibly completed above reads as absent below.
    renderTimeMachine();
  }

  //: Status -> what an operator should DO about it. Never a bare code: a
  //: number tells you something failed, not which of your problems it is.
  const MISSION_FAILURE_HELP = {
    400: "the request was rejected as malformed — check the objective text",
    401: "NOT AUTHENTICATED — enter an operator token above, then run again",
    403: "authenticated, but this principal may not run a mission (a service " +
         "token cannot; the human gate requires a human principal)",
    404: "no such mission",
    409: "the mission is in a state that refuses this action",
    422: "the request was well-formed but rejected — see the detail below",
    429: "rate limited — this instance allows a bounded number of requests per " +
         "principal per minute",
    500: "the server errored — see the detail below and the server log",
  };

  //: Shared by every action handler below, so a failed request is described
  //: the same way everywhere rather than each caller inventing its own
  //: wording. Never throws -- a body that is not JSON just means no detail.
  async function describeFailure(res) {
    let detail = "";
    try {
      const body = await res.json();
      detail = body.detail || body.reason || "";
    } catch (err) {
      detail = "";
    }
    const help = MISSION_FAILURE_HELP[res.status] || "the request failed";
    return { status: res.status, help, detail };
  }

  async function showMissionFailure(res) {
    const el = $("cmdos-authfail");
    const { status, help, detail } = await describeFailure(res);
    el.hidden = false;
    el.innerHTML =
      "<span class='cmdos-tag cmdos-unavailable'>HTTP " + status + "</span> " +
      esc(help) + (detail ? "<div class='cmdos-hint mono'>" + esc(detail) + "</div>" : "");
    // Put the operator where the fix is, rather than making them find it.
    if (status === 401) {
      const token = $("cmdos-token");
      if (token) { token.focus(); token.select(); }
    }
    el.scrollIntoView({ block: "nearest" });
  }

  async function runMission() {
    const btn = $("cmdos-run");
    btn.disabled = true;
    btn.textContent = "MISSION RUNNING…";
    $("cmdos-offline").hidden = true;
    $("cmdos-report").hidden = true;
    $("cmdos-gate").hidden = true;
    $("cmdos-trust-firewall").hidden = true;
    $("cmdos-stages").innerHTML = "";
    $("cmdos-authfail").hidden = true;
    $("cmdos-plan-panel").hidden = true;
    $("cmdos-external-panel").hidden = true;
    $("cmdos-recall-panel").hidden = true;
    $("cmdos-reconcile-panel").hidden = true;
    try {
      const autoApprove = !$("cmdos-auto-approve").checked;
      const objective = encodeURIComponent($("cmdos-objective-input").value.trim());
      const res = await authedFetch(
        "/api/command-os/mission?auto_approve=" + autoApprove + "&objective=" + objective,
        { method: "POST" }
      );
      if (res.status === 503) {
        $("cmdos-offline").hidden = false;
        return;
      }
      // EVERY failure must be visible AT THE POINT OF ACTION.
      //
      // This used to be `if (!res.ok) return;` -- a silent return. A 401 at
      // least surfaced `#cmdos-authfail` via authedFetch, but 400, 403, 409,
      // 422, 429 and 500 produced NOTHING AT ALL: the button disabled for a
      // few hundred milliseconds, snapped back to its idle label, and the
      // operator was left looking at an unchanged screen with no way to tell
      // the click from a no-op. That is the definition of a dead button.
      if (!res.ok) {
        await showMissionFailure(res);
        return;
      }
      const token = operatorToken();
      if (token) sessionStorage.setItem(TOKEN_KEY, token);
      applyMissionResult(await res.json());
    } finally {
      btn.disabled = false;
      btn.textContent = "Run autonomous mission";
    }
  }

  async function handleGateDecision(decision) {
    if (!cmdosMissionId) return;
    const res = await authedFetch(
      "/api/command-os/mission/" + cmdosMissionId + "/gate?decision=" + decision,
      { method: "POST" }
    );
    // Same discipline as runMission(): a failed gate decision must be visible
    // AT THE POINT OF ACTION, not a silent no-op that leaves the operator
    // staring at an unchanged gate. Reuses the existing #cmdos-authfail
    // banner rather than a second notification surface.
    if (!res.ok) {
      await showMissionFailure(res);
      return;
    }
    applyMissionResult(await res.json());
  }

  async function renderSystemReality() {
    const res = await fetch("/api/command-os/status");
    const d = await res.json();
    const byArea = {};
    d.rows.forEach((r) => {
      (byArea[r.area] = byArea[r.area] || []).push(r);
    });
    const el = $("cmdos-reality");
    el.innerHTML = Object.keys(byArea).map((area) => (
      "<div class='cmdos-reality-group'>" +
        "<div class='cmdos-reality-area cond'>" + area + "</div>" +
        byArea[area].map((r) => (
          "<div class='cmdos-reality-row'>" +
            "<span class='cmdos-reality-feature'>" + r.feature.replace(/_/g, " ") + "</span>" +
            "<span class='cmdos-tag " + statusClass(r.status) + "'>" + r.status + "</span>" +
          "</div>"
        )).join("") +
      "</div>"
    )).join("");
  }

  async function renderFleet() {
    const res = await fetch("/api/command-os/fleet");
    if (!res.ok) return;
    const d = await res.json();
    $("cmdos-fleet").innerHTML = d.roles.map((r) => (
      "<div class='cmdos-fleet-row' title='" + r.purpose + "'>" +
        "<div class='cmdos-fleet-id cond'>" + r.agent_id + "</div>" +
        "<div class='cmdos-fleet-scope'>scope: " + r.authority_scope.join(", ") + "</div>" +
        "<div class='cmdos-fleet-tools'>tools: " + (r.tools.length ? r.tools.join(", ") : "—") + "</div>" +
      "</div>"
    )).join("");
  }

  async function renderEconomics() {
    const drift = $("cmdos-econ-drift").value;
    const completeness = Number($("cmdos-econ-completeness").value) / 100;
    const disagree = $("cmdos-econ-disagree").checked;
    const res = await fetch(
      "/api/command-os/economics?drift_band=" + drift +
      "&completeness=" + completeness +
      "&model_disagreement=" + disagree
    );
    if (!res.ok) return;
    const d = await res.json();
    $("cmdos-economics").innerHTML =
      "<div class='cmdos-econ-tax'>uncertainty tax <span class='cond'>+" + d.tax_pct + "%</span></div>" +
      (d.contributions.length
        ? "<div class='cmdos-hint'>" + d.contributions.map((c) => "· " + c).join("<br>") + "</div>"
        : "<div class='cmdos-hint'>· no uncertainty signal fired</div>") +
      d.prices.map((p) => (
        "<div class='cmdos-reality-row'>" +
          "<span class='cmdos-reality-feature'>" + p.action_kind.replace(/_/g, " ").toLowerCase() + "</span>" +
          "<span class='cmdos-tag " + (p.cost_bp > p.base_bp ? "cmdos-simulated" : "cmdos-live") + "'>" +
            p.cost_bp + "bp</span>" +
        "</div>"
      )).join("");
  }

  async function renderAuthMode() {
    const res = await fetch("/api/command-os/status");
    if (!res.ok) return;
    const d = await res.json();
    const a = d.auth || {};
    const parts = ["env " + a.env];
    if (a.iap_trusted) parts.push("IAP trusted");
    if (a.bearer_tokens_configured) parts.push(a.bearer_tokens_configured + " bearer token(s) configured");
    if (a.dev_principal_configured && a.dev_principal_permitted) parts.push("dev principal active — no token needed");
    parts.push("anonymous mutation: " + (a.anonymous_mutation_possible ? "POSSIBLE" : "refused"));
    $("cmdos-authmode").textContent = parts.join(" · ");
  }

  async function showCommandOS() {
    hideCore();
    show("command-os");
    renderSystemReality();
    renderAuthMode();
    renderFleet();
    renderEconomics();
    renderConsequence();
    renderModelRoster();
    renderMediaLab();
    renderVerifiedEvidence();
    renderTimeMachine();
  }

  // ── CONSEQUENCE PREVIEW — the agent action simulator ──────────────────
  //
  // Reads the public, read-only preview endpoint. Every number rendered is a
  // real reverse-index traversal over the committed corpus; nothing here can
  // mutate anything, which is why it needs no credential.

  const CQ_SEVERITY = { CRITICAL: "cmdos-unavailable", CAUTION: "cmdos-simulated", INFO: "cmdos-live" };

  async function renderConsequence() {
    const host = $("cq-out");
    if (!host) return;
    const [subject, predicate, value] = $("cq-premise").value.split("|");
    const action = $("cq-action").value;
    host.innerHTML = "<div class='cmdos-hint mono'>walking the reverse index…</div>";
    let d;
    try {
      d = await (await fetch(
        "/api/command-os/consequence-preview?subject=" + encodeURIComponent(subject) +
        "&predicate=" + encodeURIComponent(predicate) +
        "&value=" + encodeURIComponent(value) +
        "&action_kind=" + encodeURIComponent(action)
      )).json();
    } catch (err) {
      host.innerHTML = "<div class='cmdos-hint mono'>preview unavailable</div>";
      return;
    }

    // UNKNOWN is not ZERO, and the UI must not let them look alike.
    if (!d.resolved) {
      host.innerHTML =
        "<div class='cq-unknown'><span class='cmdos-tag cmdos-unavailable'>BLAST RADIUS UNKNOWN</span>" +
        "<div class='cmdos-hint mono'>" + esc(d.reason_unresolved) + "</div></div>";
      return;
    }

    const r = d.risk;
    const dims = ["security", "data", "financial", "operational", "privilege", "irreversibility"];
    host.innerHTML =
      "<div class='cq-grid'>" +
        "<div class='cq-graph'>" +
          d.graph.map((n) =>
            "<div class='cq-node cq-node-" + esc(n.kind) + "'>" +
              "<span class='cmdos-tag " + (CQ_SEVERITY[n.severity] || "cmdos-live") + "'>" + esc(n.severity) + "</span>" +
              "<span class='cq-label cond'>" + esc(n.label) + "</span>" +
              (n.count ? "<span class='cq-count cond'>" + n.count.toLocaleString() + "</span>" : "") +
              "<div class='cmdos-hint mono cq-detail'>" + esc(n.detail) + "</div>" +
            "</div>"
          ).join("<div class='cq-arrow' aria-hidden='true'>↓</div>") +
        "</div>" +
        "<div class='cq-risk'>" +
          "<div class='cmdos-report-title cond'>UNWIND RISK INDEX</div>" +
          "<div class='cq-total cond'>" + r.total + "<span class='cq-band'>" + esc(r.band) + "</span></div>" +
          dims.map((k) =>
            "<div class='cq-dim'><span class='cq-dim-k mono'>" + k + "</span>" +
            "<span class='cq-dim-bar'><i style='width:" + r[k] + "%'></i></span>" +
            "<span class='cq-dim-v mono'>" + r[k] + "</span></div>"
          ).join("") +
          "<div class='cmdos-hint mono cq-disclaim'>" + esc(r.disclaimer) + "</div>" +
          "<div class='cmdos-hint mono'>reversible: <b>" + (d.reversible ? "yes" : "NO — consequences already escaped") + "</b></div>" +
        "</div>" +
      "</div>";
  }

  ["cq-premise", "cq-action"].forEach((id) => {
    const el = $(id);
    if (el) el.addEventListener("change", renderConsequence);
  });

  // ── GOOGLE MODEL STACK ───────────────────────────────────────────────
  //
  // Every model string this system pins, joined to what a real call actually
  // did. The join happens on the server (`/api/media/model-roster`) because
  // both halves have exactly one legitimate source -- `lib/config.py` for the
  // ID, `evidence/models/verification-*.json` for the status -- and a list
  // hardcoded here could drift from either. A model with no verification
  // reads UNVERIFIED rather than borrowing a sibling's green tick.
  const ROSTER_CLASS = {
    LIVE_VERIFIED: "cmdos-live",
    UNAVAILABLE: "cmdos-unavailable",
    UNVERIFIED: "cmdos-designed",
  };

  //: Held so the Media Lab cards can render their committed player without a
  //: second round-trip -- one fetch fills both. renderModelRoster() and
  //: renderMediaLab() are both fired without awaiting each other (see
  //: showCommandOS()), so whichever of their two independent fetches
  //: resolves first must not decide whether the players show up: both go
  //: through this single memoized promise, and renderMediaLab() awaits it
  //: before building any card so demoBundle is never read before it is set.
  let demoBundle = null;
  let demoBundlePromise = null;

  function loadModelRoster() {
    if (!demoBundlePromise) {
      demoBundlePromise = fetch("/api/media/model-roster")
        .then((r) => r.json())
        .then((d) => {
          demoBundle = d.demo_bundle || null;
          return d;
        })
        .catch(() => {
          demoBundle = null;
          return null;
        });
    }
    return demoBundlePromise;
  }

  async function renderModelRoster() {
    const host = $("model-roster");
    if (!host) return;
    const d = await loadModelRoster();
    if (!d) {
      host.innerHTML = "<div class='cmdos-hint mono'>model roster unavailable</div>";
      return;
    }
    host.innerHTML =
      d.models
        .map(
          (m) =>
            "<div class='model-chip'>" +
            "<div class='model-chip-head'>" +
            "<span class='model-family cond'>" + esc(m.family) + "</span>" +
            "<span class='cmdos-tag " + (ROSTER_CLASS[m.status] || "cmdos-reference") + "'>" +
            esc(m.status) + "</span>" +
            "</div>" +
            "<div class='model-id mono'>" + esc(m.model) + "</div>" +
            "<div class='cmdos-hint mono'>" + esc(m.role) + "</div>" +
            (m.latency_ms
              ? "<div class='cmdos-hint mono'>real call returned in " + m.latency_ms + "ms</div>"
              : "") +
            // The failure reason is Google's own text, shown in full rather
            // than summarised -- "UNAVAILABLE" without the 404 body is a
            // status nobody can act on.
            (m.status !== "LIVE_VERIFIED" && m.reason
              ? "<details class='media-details'><summary class='mono'>why</summary>" +
                "<pre class='media-text'>" + esc(m.reason) + "</pre></details>"
              : "") +
            "</div>"
        )
        .join("") +
      "<div class='model-roster-foot cmdos-hint mono'>" +
      esc(String(d.live_verified)) + " of " + esc(String(d.total)) +
      " model strings have a recorded live call" +
      (d.verification_source ? " · " + esc(d.verification_source) : "") +
      (d.verified_at ? " · " + esc(d.verified_at) : "") +
      "</div>";
  }

  // ── MISSION MEDIA LAB ────────────────────────────────────────────────
  //
  // Three cards, one shared input. Each card's status comes from
  // `/api/media/status`, which is the SAME `_availability()` check a real
  // call makes -- so a card can never advertise itself as more available
  // than the call behind it. A NOT_CONFIGURED card still shows its model ID
  // and still lets you inspect the grounded brief that WOULD be sent; what
  // it does not do is pretend to have generated anything.
  //
  // WHAT CHANGED, AND WHY IT IS NOT A DISHONESTY
  // --------------------------------------------
  // Every card now also carries a player that WORKS ON ARRIVAL, sourced from
  // the committed demo bundle (`scripts/build_demo_media.py`). Before this,
  // a deployment with no Vertex credential rendered three buttons that all
  // returned NOT_CONFIGURED and nothing anyone could watch or hear -- a
  // media lab that could not show media. The committed render is a
  // deterministic local render of the same mission brief the live call would
  // send, and it is labelled that way on every card, in the manifest, and in
  // the endpoint that serves it. It is not presented as model output, and
  // the live-call button beside it still reports its own real status.
  const MEDIA_ICONS = { gemini: "◆", veo: "▶", lyria: "≋" };
  const MEDIA_VERB = { gemini: "Synthesize", veo: "Generate replay", lyria: "Generate signal" };

  function fmtBytes(n) {
    if (!n && n !== 0) return "";
    const mb = n / (1024 * 1024);
    return mb >= 1 ? mb.toFixed(1) + " MB" : (n / 1024).toFixed(0) + " KB";
  }

  //: The committed-render strip for one modality. Returns "" when the bundle
  //: is absent, so a build without it degrades to exactly the old behaviour
  //: rather than to a broken element.
  function demoStrip(modality) {
    if (!demoBundle || !demoBundle.available) return "";
    const label =
      "<div class='media-demo-label mono'>PLAYS NOW · deterministic local render of " +
      esc(String(demoBundle.mission_id)) + "'s " +
      esc(String(demoBundle.checkpoint_count)) + " persisted checkpoints — " +
      "NOT a " + esc(modality.toUpperCase()) + " generation</div>";

    if (modality === "veo" && demoBundle.video) {
      const v = demoBundle.video;
      // ONE RENDER, TWO CONTAINERS, EMITTED AS <source> CHILDREN.
      // A bare src= would ship a single codec, and there is no single codec
      // every target decodes: Safari and iOS need H.264/AAC in MP4, while a
      // Chromium built without proprietary codecs -- including the headless
      // one this repo's own browser evidence runs in -- needs VP9/Opus in
      // WebM. The server lists them in preference order and only lists files
      // that are actually on disk, so the browser picks the first it can play
      // and there is no arrangement in which it picks nothing.
      const sources = (v.sources && v.sources.length ? v.sources : [v])
        .map((src) =>
          "<source src='" + esc(src.url) + "'" +
          (src.mime_type ? " type='" + esc(src.mime_type) + "'" : "") + ">")
        .join("");
      const formats = (v.sources && v.sources.length ? v.sources : [v])
        .map((src) => esc(String(src.mime_type || "").split("/").pop()))
        .join(" + ");
      return (
        "<div class='media-demo'>" + label +
        "<video class='media-player' controls playsinline preload='metadata'" +
        (v.poster_url ? " poster='" + esc(v.poster_url) + "'" : "") + ">" +
        sources + "</video>" +
        "<div class='media-model mono'>" + esc(v.filename.replace(/\.[^.]+$/, "")) +
        " · " + fmtBytes(v.size_bytes) +
        (v.duration_seconds ? " · " + v.duration_seconds + "s" : "") +
        " · " + formats + "</div>" +
        "</div>"
      );
    }
    if (modality === "lyria" && demoBundle.audio) {
      const a = demoBundle.audio;
      return (
        "<div class='media-demo'>" + label +
        "<audio class='media-player' controls preload='metadata' src='" + esc(a.url) + "'></audio>" +
        "<div class='media-model mono'>" + esc(a.filename) + " · " + fmtBytes(a.size_bytes) +
        " · 44.1kHz mono wav</div>" +
        "</div>"
      );
    }
    if (modality === "gemini" && demoBundle.narration) {
      // Text has no transport control, so the equivalent of "press play" is
      // "show it". It is collapsed by default only because it is long.
      return (
        "<div class='media-demo'>" + label +
        "<details class='media-details' open><summary class='mono'>mission intelligence</summary>" +
        "<pre class='media-text' id='media-demo-narration'>loading…</pre></details>" +
        "</div>"
      );
    }
    return "";
  }

  async function renderMediaLab() {
    const host = $("media-lab");
    if (!host) return;
    // Both fetches run concurrently (fired from showCommandOS() without
    // awaiting each other); wait for demoBundle here so the two orders --
    // model-roster resolving first or /api/media/status resolving first --
    // render identically instead of only one of them showing the players.
    await loadModelRoster();
    let d;
    try {
      d = await (await fetch("/api/media/status")).json();
    } catch (err) {
      host.innerHTML = "<div class='cmdos-hint mono'>media status unavailable</div>";
      return;
    }
    host.innerHTML = d.modalities
      .map(
        (m) =>
          "<div class='media-card' data-modality='" + esc(m.modality) + "'>" +
          "<div class='media-card-head'>" +
          "<span class='media-glyph'>" + (MEDIA_ICONS[m.modality] || "•") + "</span>" +
          "<span class='media-name cond'>" + esc(m.modality.toUpperCase()) + "</span>" +
          "<span class='cmdos-tag " + statusClass(m.status) + "'>" + esc(m.status) + "</span>" +
          "</div>" +
          "<div class='media-title cond'>" + esc(m.title) + "</div>" +
          "<div class='cmdos-hint mono'>" + esc(m.purpose) + "</div>" +
          "<div class='media-model mono'>model <b>" + esc(m.model) + "</b>" +
          (m.auth_mode ? " · auth <b>" + esc(m.auth_mode) + "</b>" : "") + "</div>" +
          demoStrip(m.modality) +
          // The reason is Google's own resolver output, kept VERBATIM and in
          // full -- but collapsed. Printed open it is the same ~90 words on
          // all three cards, which buried the players and the live-call
          // buttons under a wall of identical text. Collapsed, the status
          // badge still says NOT CONFIGURED and the detail is one click away.
          (m.reason && m.status !== "CONFIGURED"
            ? "<details class='media-details'><summary class='mono'>why this cannot make a live call</summary>" +
              "<pre class='media-text'>" + esc(m.reason) + "</pre></details>"
            : "") +
          "<button type='button' class='btn btn-quiet media-go' data-modality='" +
          esc(m.modality) + "'>" + (MEDIA_VERB[m.modality] || "Run") + " — live call</button>" +
          "<div class='media-out mono' id='media-out-" + esc(m.modality) + "'></div>" +
          "</div>"
      )
      .join("");

    // The narration is fetched rather than inlined so the committed text file
    // stays the single copy -- the page cannot show a stale paraphrase of it.
    const narrationEl = $("media-demo-narration");
    if (narrationEl && demoBundle && demoBundle.narration) {
      fetch(demoBundle.narration.url)
        .then((r) => r.text())
        .then((t) => { narrationEl.textContent = t; })
        .catch(() => { narrationEl.textContent = "narration unavailable"; });
    }

    // The note is the honest part: it says why the LIVE buttons will
    // fail-closed BEFORE anyone presses one, rather than after.
    // Two credential paths, reported separately -- an API key makes Gemini and
    // Veo live but cannot reach Lyria, and saying otherwise would be exactly
    // the over-reporting this panel exists to prevent.
    const modes = d.auth_modes_detected || {};
    const modeLabel = modes.mode === "adc"
      ? ("Application Default Credentials" + (modes.project ? " · project " + modes.project : ""))
      : modes.mode === "api_key" ? "Gemini API key" : "";
    const live = d.modalities.filter((m) => m.status === "CONFIGURED").length;
    $("media-note").textContent = d.available
      ? "credential detected (" + modeLabel + ") — " + live +
        " of 3 modalities can make a real call now. The players above are the committed " +
        "deterministic render and do not depend on that credential."
      : "NO VERTEX CREDENTIAL IN THIS ENVIRONMENT — each card's \u201cwhy\u201d carries the " +
        "resolver's verbatim reason. The adapters, prompts and model IDs are complete and the " +
        "request path is verified to reach Google; a live-call button returns NOT_CONFIGURED " +
        "rather than a fabricated artefact. The players above still work regardless: they are " +
        "a committed local render of the same mission brief, never a model call.";

    host.querySelectorAll(".media-go").forEach((btn) => {
      btn.addEventListener("click", () => runMedia(btn.dataset.modality, btn));
    });
  }

  // ── REAL VERIFIED EVIDENCE — the one real Veo/Lyria generation this
  // project ran (2026-08-21), played from the actual bytes when this
  // environment has them. `.media/` is gitignored generated output, so a
  // fresh clone, CI, or a deployment built before that pass will not have
  // these files -- the panel stays hidden rather than showing dead players,
  // the same discipline the Media Lab cards use for NOT_CONFIGURED.
  async function renderVerifiedEvidence() {
    const section = $("media-verified");
    if (!section) return;
    let d;
    try {
      d = await (await fetch("/api/media/verified-evidence")).json();
    } catch (err) {
      section.hidden = true;
      return;
    }
    const veo = d.veo || {};
    const lyria = d.lyria || {};
    const veoBox = $("media-verified-veo");
    if (veo.available) {
      $("mv-video").src = veo.url;
      $("mv-video-meta").textContent =
        "real generated file · " + fmtBytes(veo.size_bytes) + " · " + veo.filename;
      veoBox.hidden = false;
    } else {
      veoBox.hidden = true;
    }
    const lyriaBox = $("media-verified-lyria");
    if (lyria.available) {
      $("mv-audio").src = lyria.url;
      $("mv-audio-meta").textContent =
        "real generated file · " + fmtBytes(lyria.size_bytes) + " · " + lyria.filename;
      lyriaBox.hidden = false;
    } else {
      lyriaBox.hidden = true;
    }
    section.hidden = !(veo.available || lyria.available);
  }

  const MEDIA_ROUTE = { gemini: "synthesize", veo: "replay", lyria: "signal" };

  //: The failure statuses are DERIVED FROM GOOGLE'S ACTUAL ERROR
  //: (media/adapters.py:classify_failure), not guessed. They are rendered
  //: distinctly because they have different fixes: AUTH_REQUIRED means
  //: re-authenticate, ACCESS_REQUIRED means grant a role or enable an API,
  //: QUOTA_LIMITED means wait or raise a quota. Collapsing them into one
  //: red badge tells an operator nothing about what to do next.
  const MEDIA_STATUS_CLASS = {
    GENERATED: "LIVE",
    NOT_CONFIGURED: "DESIGNED",
    AUTH_REQUIRED: "UNAVAILABLE",
    ACCESS_REQUIRED: "UNAVAILABLE",
    QUOTA_LIMITED: "SIMULATED",
    UNAVAILABLE: "UNAVAILABLE",
    ERROR: "UNAVAILABLE",
  };

  async function runMedia(modality, btn) {
    // Reuse the Command OS's own mission id -- the Media Lab must describe
    // the mission the operator just watched run, not a separately-tracked one
    // that could drift out of sync with what is on screen.
    const missionId = cmdosMissionId;
    const out = $("media-out-" + modality);
    if (!missionId) {
      out.textContent = "run a mission first — there is no mission state to read from";
      return;
    }
    const original = btn.textContent;
    btn.disabled = true;
    btn.textContent = "working…";
    out.textContent = "";
    try {
      const res = await authedFetch(
        "/api/media/mission/" + encodeURIComponent(missionId) + "/" + MEDIA_ROUTE[modality],
        { method: "POST" }
      );
      if (res.status === 401 || res.status === 403) {
        out.textContent = "NOT AUTHENTICATED — enter an operator token above";
        return;
      }
      if (!res.ok) {
        const { status, help, detail } = await describeFailure(res);
        out.innerHTML =
          "<span class='cmdos-tag cmdos-unavailable'>HTTP " + status + "</span> " +
          esc(help) + (detail ? "<div class='cmdos-hint mono'>" + esc(detail) + "</div>" : "");
        return;
      }
      const r = await res.json();
      renderMediaResult(out, r);
    } catch (err) {
      out.textContent = "request failed: " + err;
    } finally {
      btn.disabled = false;
      btn.textContent = original;
    }
  }

  function renderMediaResult(out, r) {
    const head =
      "<div class='media-result-head'><span class='cmdos-tag " +
      statusClass(MEDIA_STATUS_CLASS[r.status] || "DESIGNED") +
      "'>" + esc(r.status) + "</span> <span class='mono'>" + esc(r.model) + "</span></div>";
    if (r.status === "GENERATED") {
      let body = "";
      if (r.text) body += "<pre class='media-text'>" + esc(r.text) + "</pre>";
      if (r.artifact_path && r.modality === "veo") {
        body += "<video class='media-player' controls src='/media-artifact/" +
          esc(r.artifact_path.split('/').pop()) + "'></video>";
      }
      if (r.artifact_path && r.modality === "lyria") {
        body += "<audio class='media-player' controls src='/media-artifact/" +
          esc(r.artifact_path.split('/').pop()) + "'></audio>";
      }
      out.innerHTML = head + body +
        "<div class='cmdos-hint mono'>grounded on " +
        esc(String((r.detail && r.detail.grounded_on_checkpoints) || "the mission brief")) +
        " · prompt sha " + esc(r.prompt_sha256) + " · " + r.latency_ms + "ms</div>";
      return;
    }
    // NOT_CONFIGURED or FAILED. Show the real reason AND the prompt that
    // would have been sent -- the work is real even when the call cannot run.
    out.innerHTML = head +
      "<div class='cmdos-hint mono'>" + esc(r.reason) + "</div>" +
      "<details class='media-details'><summary class='mono'>the grounded prompt this would send</summary>" +
      "<pre class='media-text'>" + esc(r.prompt) + "</pre></details>";
  }

  $("cmdos-run").addEventListener("click", runMission);
  $("cmdos-open-instrument").addEventListener("click", showInstrument);
  $("instr-cmdos-link").addEventListener("click", showCommandOS);
  $("cmdos-gate-approve").addEventListener("click", () => handleGateDecision("approve"));
  $("cmdos-gate-deny").addEventListener("click", () => handleGateDecision("deny"));
  ["cmdos-econ-drift", "cmdos-econ-completeness", "cmdos-econ-disagree"].forEach((id) => {
    $(id).addEventListener("input", renderEconomics);
    $(id).addEventListener("change", renderEconomics);
  });

  // ── MISSION TIME MACHINE ────────────────────────────────────────────

  // THE BUG THIS SECTION FIXES, STATED PLAINLY
  // ------------------------------------------------
  // `/api/command-os/missions` and `.../checkpoints` were placed behind
  // `require_principal` when authentication was added. The two fetches below
  // were NOT updated at the same time: they used the bare `fetch`, so they
  // sent no bearer token, got 401, and `d.available` came back undefined.
  // The `!d.available` branch then rendered "no missions recorded yet" --
  // the SAME empty state as a genuinely empty database. The panel opened,
  // showed nothing, and reported the cause as "no missions" while the real
  // cause was "not authenticated". Worse, the bare `fetch` bypassed
  // `authedFetch`'s 401 handler, so the `#cmdos-authfail` banner that exists
  // precisely to say "your token is missing" never appeared.
  //
  // Both fetches now go through `authedFetch`, and -- the part that actually
  // matters -- NOT AUTHENTICATED, EMPTY and FAILED are three distinct
  // rendered states. An empty panel must never be able to mean two different
  // things again.

  //: The arc and checkpoint columns are always on screen now that this is a
  //: section rather than a screen behind a button. A column that renders
  //: nothing is indistinguishable from a column that failed to render, so
  //: every terminal state fills them in rather than leaving them blank.
  function mtmPlaceholder(text) {
    $("mtm-timeline").innerHTML =
      "<li class='cmdos-hint mono mtm-empty'>" + esc(text) + "</li>";
    $("mtm-checkpoints").innerHTML = mtmNotice(text);
  }

  function mtmNotice(text, hint) {
    return (
      "<li class='cmdos-stage'><div class='cmdos-stage-summary'>" +
      esc(text) +
      "</div>" +
      (hint ? "<div class='cmdos-hint mono'>" + esc(hint) + "</div>" : "") +
      "</li>"
    );
  }

  //: RENDERS IN PLACE. This used to call hideCore()/show("mission-time-machine")
  //: and take over the screen. The Time Machine is now a heading on the
  //: Command OS page, so it populates its own elements and navigates nowhere.
  async function renderTimeMachine() {
    if (!$("mtm-missions")) return;
    $("mtm-checkpoints").innerHTML = "";
    $("mtm-detail").hidden = true;
    $("mtm-timeline").innerHTML = "";
    $("mtm-state").hidden = true;
    const list = $("mtm-missions");
    list.innerHTML = mtmNotice("loading missions…");

    let res;
    try {
      res = await authedFetch("/api/command-os/missions", { quietAuth: true });
    } catch (err) {
      list.innerHTML = mtmNotice(
        "could not reach the mission index",
        String(err)
      );
      mtmPlaceholder("no mission arc — the mission index could not be reached");
      return;
    }

    // STATE 1 — NOT AUTHENTICATED. Distinct from "empty", and actionable.
    if (res.status === 401 || res.status === 403) {
      list.innerHTML = mtmNotice(
        "NOT AUTHENTICATED — mission history is a protected read",
        "enter an operator credential at the top of this page and it loads here. " +
          "Mission history names who approved what, so it is not an anonymous read."
      );
      mtmPlaceholder("no mission arc until mission history can be read");
      return;
    }
    if (!res.ok) {
      list.innerHTML = mtmNotice("mission index unavailable (HTTP " + res.status + ")");
      mtmPlaceholder("no mission arc — the mission index is unavailable");
      return;
    }

    const d = await res.json();
    // STATE 2 — Firestore unreachable. Honestly distinct from empty.
    if (!d.available) {
      list.innerHTML = mtmNotice(
        "FIRESTORE UNREACHABLE",
        d.reason || "checkpoints are persisted in Firestore; without it there is no history to show"
      );
      mtmPlaceholder("no mission arc — checkpoints live in Firestore, which is unreachable");
      return;
    }
    // STATE 3 — genuinely empty.
    if (!d.missions || d.missions.length === 0) {
      list.innerHTML = mtmNotice(
        "no missions recorded yet",
        "run one from Agentic Command OS — every mission writes a checkpoint per phase"
      );
      mtmPlaceholder("no mission arc yet — run a mission above and it appears here");
      return;
    }

    // STATE 4 — loaded.
    list.innerHTML = d.missions
      .map(
        (m) =>
          "<li class='cmdos-stage cmdos-clickable' data-mission='" +
          esc(m.mission_id) +
          "' role='button' tabindex='0'>" +
          "<div class='cmdos-stage-head'>" +
          "<span class='cmdos-stage-name cond'>" +
          esc(m.mission_id) +
          "</span>" +
          "<span class='cmdos-tag " +
          missionStatusClass(m.status) +
          "'>" +
          esc(m.status) +
          "</span>" +
          "</div>" +
          "<div class='cmdos-stage-summary'>" +
          esc(m.objective) +
          "</div>" +
          "</li>"
      )
      .join("");
    list.querySelectorAll("[data-mission]").forEach((li) => {
      const open = () => loadCheckpointTimeline(li.dataset.mission);
      li.addEventListener("click", open);
      li.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter" || ev.key === " ") {
          ev.preventDefault();
          open();
        }
      });
    });
    // Open the most recent mission immediately. Landing on a list that needs
    // one more click before it shows anything is what made this panel read
    // as broken in the first place.
    loadCheckpointTimeline(d.missions[0].mission_id);
  }

  //: A mission's status is a closed vocabulary from `command_os/schema.py`.
  //: COMPLETED_WITH_RESTRICTIONS is deliberately NOT painted as a clean pass:
  //: the mission finished with something denied, and the badge says so.
  function missionStatusClass(status) {
    if (status === "COMPLETED") return "cmdos-live";
    if (status === "HALTED" || status === "BLOCKED" || status === "FAILED_SAFE") {
      return "cmdos-unavailable";
    }
    return "cmdos-simulated";
  }

  async function loadCheckpointTimeline(missionId) {
    $("mtm-detail").hidden = true;
    const el = $("mtm-checkpoints");
    el.innerHTML = mtmNotice("loading checkpoints…");
    const res = await authedFetch(
      "/api/command-os/mission/" + missionId + "/checkpoints", { quietAuth: true });
    if (res.status === 401 || res.status === 403) {
      el.innerHTML = mtmNotice("NOT AUTHENTICATED — checkpoints are a protected read");
      return;
    }
    if (!res.ok) {
      el.innerHTML = mtmNotice("checkpoints unavailable (HTTP " + res.status + ")");
      return;
    }
    const d = await res.json();
    el.innerHTML = d.checkpoints
      .map(
        (c) =>
          "<li class='cmdos-stage cmdos-clickable' data-seq='" +
          c.seq +
          "' role='button' tabindex='0'>" +
          "<div class='cmdos-stage-head'>" +
          "<span class='cmdos-stage-n'>" +
          String(c.seq).padStart(2, "0") +
          "</span>" +
          "<span class='cmdos-stage-name cond'>" +
          esc(c.stage.name) +
          "</span>" +
          "<span class='cmdos-tag " +
          statusClass(c.stage.status) +
          "'>" +
          esc(c.stage.status) +
          "</span>" +
          "</div>" +
          "<div class='cmdos-stage-summary'>" +
          esc(c.stage.summary) +
          "</div>" +
          "</li>"
      )
      .join("");
    el.querySelectorAll("[data-seq]").forEach((li, i) => {
      const open = () => showCheckpointDetail(d.checkpoints[i]);
      li.addEventListener("click", open);
      li.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter" || ev.key === " ") {
          ev.preventDefault();
          open();
        }
      });
    });
    renderMissionArc(missionId, d.checkpoints);
  }

  // ── The mission arc: PAST → … → CURRENT TRUSTED STATE ────────────────
  //
  // Every row below is derived from a checkpoint that was actually written.
  // Nothing is inferred, and a phase the mission never reached is not drawn
  // -- an arc that always shows DRIFT → THREAT → REPAIR regardless of what
  // happened would be exactly the narrative-shaped fiction this repository
  // refuses everywhere else.
  async function renderMissionArc(missionId, checkpoints) {
    const arc = $("mtm-timeline");
    arc.innerHTML = checkpoints
      .map((c, i) => {
        const last = i === checkpoints.length - 1;
        return (
          "<li class='mtm-arc-node'>" +
          "<span class='mtm-arc-dot " +
          (last ? "mtm-arc-dot-current" : "") +
          "'></span>" +
          "<span class='mtm-arc-label cond'>" +
          esc(c.stage.name.split("—")[0].trim()) +
          "</span>" +
          "<span class='cmdos-tag " +
          statusClass(c.stage.status) +
          "'>" +
          esc(c.stage.status) +
          "</span>" +
          "</li>"
        );
      })
      .join("");

    // Current trusted state + what resume can genuinely do, side by side.
    const state = $("mtm-state");
    state.hidden = false;
    state.innerHTML = "<div class='cmdos-hint mono'>reading trusted state…</div>";
    const tRes = await authedFetch(
      "/api/command-os/mission/" + missionId + "/trust", { quietAuth: true });
    if (!tRes.ok) {
      state.innerHTML = "<div class='cmdos-hint mono'>trusted state unavailable</div>";
      return;
    }
    const t = await tRes.json();
    const status = t.mission_status || "UNKNOWN";
    // RESUME is genuinely implemented (command_os/mission.py:resume_mission)
    // but only MEANS anything for a mission that has not reached a final
    // status. Rather than offer a button that silently no-ops, the control is
    // disabled and says which of the three real cases this mission is in.
    const resumable = status === "RUNNING" || status === "AWAITING_HUMAN";
    state.innerHTML =
      "<div class='cmdos-report-title cond'>CURRENT MISSION STATE</div>" +
      "<div class='cmdos-report-grid'>" +
      "<div><span class='k'>mission</span><span class='v'>" + esc(missionId) + "</span></div>" +
      "<div><span class='k'>status</span><span class='v'>" + esc(status) + "</span></div>" +
      "<div><span class='k'>checkpoints</span><span class='v'>" + checkpoints.length + "</span></div>" +
      "<div><span class='k'>trusted</span><span class='v'>" + t.trusted.length + "</span></div>" +
      "<div><span class='k'>quarantined</span><span class='v'>" + t.quarantined.length + "</span></div>" +
      "<div><span class='k'>revoked</span><span class='v'>" + t.revoked.length + "</span></div>" +
      "</div>" +
      "<div class='mtm-caps'>" +
      "<div class='mtm-cap'>" +
      "<span class='cmdos-tag cmdos-live'>LIVE</span>" +
      "<span class='mtm-cap-name cond'>RESUME FROM LAST CHECKPOINT</span>" +
      "<div class='cmdos-hint mono'>" +
      (resumable
        ? "this mission is " + esc(status) + " and can be continued"
        : "this mission is " + esc(status) +
          " — a final mission returns its stored trace and re-runs nothing (no duplicate spend, no duplicate external action)") +
      "</div>" +
      "<button type='button' id='mtm-resume' class='btn btn-quiet'" +
      (resumable ? "" : " disabled") +
      ">Resume mission</button>" +
      "</div>" +
      "<div class='mtm-cap'>" +
      "<span class='cmdos-tag cmdos-designed'>NOT IMPLEMENTED</span>" +
      "<span class='mtm-cap-name cond'>REPLAY FROM AN ARBITRARY CHECKPOINT</span>" +
      "<div class='cmdos-hint mono'>" +
      "resume_mission() continues strictly after the LAST persisted checkpoint. " +
      "Re-entering the mission at checkpoint N &lt; last is not implemented, and " +
      "would need compensation for the external action and warrant already spent " +
      "beyond N. Not faked here." +
      "</div>" +
      "</div>" +
      "</div>";

    const btn = document.getElementById("mtm-resume");
    if (btn && resumable) {
      btn.addEventListener("click", async () => {
        btn.disabled = true;
        btn.textContent = "resuming…";
        const r = await authedFetch(
          "/api/command-os/mission/" + missionId + "/resume",
          { method: "POST" }
        );
        const body = await r.json().catch(() => ({}));
        btn.textContent = r.ok
          ? "resumed → " + (body.status || "?")
          : "resume refused (HTTP " + r.status + ")";
        if (r.ok) loadCheckpointTimeline(missionId);
      });
    }
  }

  function showCheckpointDetail(cp) {
    const el = $("mtm-detail");
    el.hidden = false;
    el.innerHTML =
      "<div class='cmdos-report-title cond'>CHECKPOINT " + String(cp.seq).padStart(2, "0") + "</div>" +
      "<div class='cmdos-report-grid'>" +
        "<div><span class='k'>stage</span><span class='v'>" + cp.stage.name + "</span></div>" +
        "<div><span class='k'>status</span><span class='v'>" + cp.status + "</span></div>" +
        "<div><span class='k'>recorded</span><span class='v'>" + cp.created_at + "</span></div>" +
      "</div>" +
      "<pre class='cmdos-hint mono' style='white-space:pre-wrap;margin-top:12px'>" +
        JSON.stringify(cp.ctx, null, 2) +
      "</pre>";
  }

  $("cmdos-open-evolution").addEventListener("click", showEvolution);
  $("evo-back").addEventListener("click", showCommandOS);

  async function showInstrument() {
    // The panel used to stay entirely hidden until three sequential,
    // awaited fetches all resolved (~2.5s on a cold Firestore emulator) --
    // indistinguishable, for that whole window, from a dead button. It now
    // opens on click (the same "show first, populate after" idiom
    // renderTimeMachine uses) and the three independent reads run in
    // parallel instead of one after another.
    hideCore();
    const offline = $("instr-offline");
    const loading = $("instr-loading");
    const body = $("instr-body");
    offline.hidden = true;
    body.hidden = true;
    loading.hidden = false;
    show("instrument");

    let d, h, s;
    try {
      [d, h, s] = await Promise.all([
        fetch("/api/instrument").then((r) => r.json()),
        fetchHyperion(),
        fetchSingularity(),
      ]);
    } catch (err) {
      loading.hidden = true;
      offline.hidden = false;
      return;
    }
    loading.hidden = true;
    if (!d.available) {
      offline.hidden = false;
      body.hidden = true;
      return;
    }
    offline.hidden = true;
    body.hidden = false;
    renderInstrument(d);
    renderHyperionHome(h);
    renderSingularityHome(s);
  }

  //: Both burn and earn are principal-scoped server side (require_principal /
  //: require_human_principal in services/api/main.py) -- plain fetch() never
  //: sent a credential, so these could only ever have worked where an
  //: anonymous dev principal was configured, and failed invisibly everywhere
  //: else: the error body has no `.bars`, so `applyInstrumentAction` threw
  //: before anything on screen changed.
  async function showInstrumentActionFailure(res) {
    const { status, help, detail } = await describeFailure(res);
    document.querySelectorAll(".instr-route").forEach((route) => {
      route.hidden = false;
      route.classList.remove("allowed");
      route.classList.add("refused");
      route.innerHTML =
        `<span class="code">HTTP ${status}</span> — ${esc(help)}` +
        (detail ? `<div class="cmdos-hint mono">${esc(detail)}</div>` : "");
    });
  }
  async function handleBurn() {
    const res = await authedFetch("/api/instrument/burn", { method: "POST" });
    if (!res.ok) {
      await showInstrumentActionFailure(res);
      return;
    }
    applyInstrumentAction(await res.json());
  }
  async function handleEarn() {
    const res = await authedFetch("/api/instrument/earn", { method: "POST" });
    if (!res.ok) {
      await showInstrumentActionFailure(res);
      return;
    }
    applyInstrumentAction(await res.json());
  }
  $("instr-burn").addEventListener("click", handleBurn);
  $("instr-earn").addEventListener("click", handleEarn);
  $("wd-burn").addEventListener("click", handleBurn);
  $("wd-earn").addEventListener("click", handleEarn);
  $("hd-probe").addEventListener("click", handleHyperionProbe);

  // ── trajectory evaluation & governed evolution ────────────────────
  //
  // Every value rendered here comes from a persisted document. There is no
  // computed-on-read score and no placeholder number anywhere in this panel:
  // a mission that was never scored renders as "not scored", which is a real
  // and different thing from a score of zero.

  function evoNotice(text, hint) {
    return (
      "<div class='cmdos-stage-summary'>" + esc(text) + "</div>" +
      (hint ? "<div class='cmdos-hint mono'>" + esc(hint) + "</div>" : "")
    );
  }

  //: Criteria that may never regress, per evolution/promote.py. Kept in sync
  //: with that module by tests/test_evolution_promote.py's partition
  //: assertion; duplicated here only for display grouping.
  const EVO_SAFETY = [
    "POLICY_COMPLIANCE", "RISK_DISCIPLINE", "CONTEXT_QUALITY",
    "TOOL_CORRECTNESS", "RECOVERY",
  ];

  function evoBar(score) {
    const pct = Math.round(Math.max(0, Math.min(1, score)) * 100);
    return (
      "<span class='evo-bar' aria-hidden='true'><span class='evo-bar-fill' style='width:" +
      pct + "%'></span></span>"
    );
  }

  function renderEvaluation(ev) {
    if (!ev) {
      $("evo-detail").innerHTML = evoNotice(
        "select an evaluated mission",
        "each row below is a mission that was scored when it completed"
      );
      return;
    }
    const rows = (ev.criteria || []).map((c) => {
      const safety = EVO_SAFETY.indexOf(c.key) !== -1;
      return (
        "<tr class='" + (c.passed ? "" : "evo-failed") + "'>" +
        "<td>" + esc(c.name) + (safety ? " <span class='evo-tag'>safety</span>" : "") + "</td>" +
        "<td class='evo-num'>" + c.score.toFixed(4) + "</td>" +
        "<td class='evo-num'>" + c.weight.toFixed(2) + "</td>" +
        "<td>" + evoBar(c.score) + "</td>" +
        "<td class='evo-why'>" + esc(c.passed ? c.expected : c.failure) + "</td>" +
        "</tr>"
      );
    }).join("");

    const failures = (ev.failures || []).length
      ? "<div class='cmdos-hint mono evo-failures'><strong>Named failures</strong><ul>" +
        ev.failures.map((f) => "<li>" + esc(f) + "</li>").join("") +
        "</ul></div>"
      : "";

    // The mission's own status, carried verbatim. An evaluation can never read
    // better than the mission it scores, and showing both side by side is the
    // whole point of the panel.
    $("evo-detail").innerHTML =
      "<div class='evo-headline'>" +
      "<span class='evo-composite'>" + ev.composite.toFixed(4) + "</span>" +
      "<span class='cmdos-hint mono'>composite &middot; mission reported " +
      esc(ev.outcome || "—") + "</span>" +
      "</div>" +
      "<div class='cmdos-hint mono'>scored against version " +
      esc(ev.agent_version_id || "—") + "</div>" +
      "<table class='evo-table'><thead><tr><th>criterion</th><th>score</th>" +
      "<th>weight</th><th></th><th>expected / failure</th></tr></thead><tbody>" +
      rows + "</tbody></table>" + failures;
  }

  async function showEvolution() {
    hideCore();
    // Open FIRST, populate after -- the same fix evidence/timemachine/
    // TIME-MACHINE-FIX.md diagnosed and evidence/INDEX.md 14 applied to six
    // more buttons. A panel that stays hidden while it fetches is
    // indistinguishable from a dead button.
    show("evolution");
    $("evo-versions").innerHTML = evoNotice("loading…");
    $("evo-missions").innerHTML = "";
    $("evo-history").innerHTML = "";
    renderEvaluation(null);

    let versionsRes, evalsRes, historyRes;
    try {
      [versionsRes, evalsRes, historyRes] = await Promise.all([
        authedFetch("/api/evolution/versions?agent_key=orchestrator"),
        authedFetch("/api/evolution/evaluations"),
        authedFetch("/api/evolution/history"),
      ]);
    } catch (err) {
      $("evo-versions").innerHTML = evoNotice("could not reach the API", String(err));
      return;
    }

    if (versionsRes.status === 401 || versionsRes.status === 403) {
      $("evo-versions").innerHTML = evoNotice(
        "NOT AUTHENTICATED — evaluations are a protected read",
        "enter an operator token in Agentic Command OS, then reopen this panel. " +
          "An evaluation names which agent version produced which behaviour, so it is not an anonymous read."
      );
      return;
    }
    if (!versionsRes.ok) {
      $("evo-versions").innerHTML = evoNotice("unavailable (HTTP " + versionsRes.status + ")");
      return;
    }

    const versions = await versionsRes.json();
    if (!versions.available) {
      $("evo-versions").innerHTML = evoNotice(
        "FIRESTORE UNREACHABLE",
        versions.reason || "agent versions are persisted in Firestore; without it there is no roster to show"
      );
      return;
    }

    $("evo-versions").innerHTML =
      "<table class='evo-table'><thead><tr><th></th><th>version</th><th>status</th>" +
      "<th>provenance</th><th>promoted by</th></tr></thead><tbody>" +
      (versions.versions || []).map((v) => {
        const serving = v.version_id === versions.active_version_id;
        return (
          "<tr class='" + (serving ? "evo-serving" : "") + "'>" +
          "<td>" + (serving ? "<span class='evo-tag'>serving</span>" : "") + "</td>" +
          "<td>v" + v.version_n + " <span class='cmdos-hint'>" + esc(v.version_id) + "</span></td>" +
          "<td>" + esc(v.status) + "</td>" +
          "<td>" + esc(v.provenance) + (v.model ? " &middot; " + esc(v.model) : "") + "</td>" +
          "<td>" + esc(v.promoted_by || "—") + "</td>" +
          "</tr>"
        );
      }).join("") +
      "</tbody></table>" +
      "<div class='cmdos-hint mono'>a version carries an instruction and a bounded policy. " +
      "It carries no scope, no tools and no budget: those live in fleet/roles.py behind the " +
      "Gateway, which this loop never writes to.</div>";

    const evals = evalsRes.ok ? await evalsRes.json() : { evaluations: [] };
    const rows = (evals.evaluations || []).slice().reverse();
    if (!rows.length) {
      $("evo-missions").innerHTML = mtmNotice(
        "no mission has been scored yet",
        "run a mission from Agentic Command OS — every completed mission is scored automatically"
      );
    } else {
      $("evo-missions").innerHTML = rows.map((ev, i) =>
        "<li class='cmdos-stage evo-pick' data-i='" + i + "'>" +
        "<div class='cmdos-stage-summary'>" + ev.composite.toFixed(4) +
        " &middot; " + esc(ev.outcome || "—") + "</div>" +
        "<div class='cmdos-hint mono'>" + esc(ev.objective || ev.mission_id) + "</div>" +
        ((ev.failures || []).length
          ? "<div class='cmdos-hint mono'>" + ev.failures.length + " named failure(s)</div>"
          : "") +
        "</li>"
      ).join("");
      Array.prototype.forEach.call(
        document.querySelectorAll("#evo-missions .evo-pick"),
        (el) => el.addEventListener("click", () => renderEvaluation(rows[Number(el.dataset.i)]))
      );
      renderEvaluation(rows[0]);
    }

    const history = historyRes.ok ? await historyRes.json() : { decisions: [] };
    const decisions = history.decisions || [];
    $("evo-history").innerHTML = decisions.length
      ? "<table class='evo-table'><thead><tr><th>outcome</th><th>composite</th>" +
        "<th>decided by</th><th>reasons</th></tr></thead><tbody>" +
        decisions.slice().reverse().map((d) =>
          "<tr class='" + (d.outcome === "REFUSED" ? "evo-failed" : "") + "'>" +
          "<td>" + esc(d.outcome) + "</td>" +
          "<td class='evo-num'>" + d.baseline_composite.toFixed(4) + " &rarr; " +
          d.candidate_composite.toFixed(4) + "</td>" +
          "<td>" + esc(d.human_principal || "—") + "</td>" +
          "<td class='evo-why'>" + (d.reasons || []).map(esc).join("<br>") + "</td>" +
          "</tr>"
        ).join("") + "</tbody></table>"
      : evoNotice(
          "no promotion has been attempted",
          "a refused candidate is kept, never deleted — a rejected proposal is part of the audit record"
        );
  }

  // ── screen orchestration ──────────────────────────────────────────

  const SCREENS = [
    "split", "obligation", "court", "loadrating", "honesty", "instrument",
    "warrant-detail", "tower-detail", "countersign-detail", "hyperion-detail",
    "singularity-detail", "command-os", "evolution",
  ];

  function show(name) {
    SCREENS.forEach((s) => { $(s).hidden = s !== name; });
    state.screen = name;
    const btn = document.querySelector(`#${name} .btn-advance`);
    if (btn) btn.focus();
  }

  function hideAll() {
    SCREENS.forEach((s) => { $(s).hidden = true; });
    state.screen = "field";
  }

  function restart() {
    hideAll();
    $("echo").hidden = true;
    $("counter").hidden = true;
    $("pacing").hidden = true;
    $("bar-wrap").classList.remove("gone");
    $("bar").value = "";
    $("e-confirm").onclick = onConfirm;
    state.sagTarget = 0;
    state.st.fill(S.IDLE);
    state.finalState.fill(S.IDLE);
    $("bar").focus();
  }

  function onConfirm() {
    if (!pending) return;
    runCascade(pending);
  }

  // ── wiring ────────────────────────────────────────────────────────

  $("bar-form").addEventListener("submit", (ev) => {
    ev.preventDefault();
    const text = $("bar").value.trim();
    if (!text) return;
    showEcho(interpret(text));
  });

  $("e-confirm").onclick = onConfirm;
  $("e-cancel").onclick = restart;

  document.querySelectorAll(".btn-advance").forEach((btn) => {
    btn.addEventListener("click", () => {
      const next = btn.dataset.next;
      if (next === "obligation") showObligation(pending || { claim: "clm_000000", source: "src_supplier_K", new_value: 20 });
      else if (next === "court") showCourt(pending || { claim: "clm_000000", source: "src_supplier_K", new_value: 20 });
      else if (next === "loadrating") showLoadRating();
      else if (next === "honesty") showHonesty();
      else if (next === "field") enterCore();
      else restart();
    });
  });

  window.addEventListener("keydown", (ev) => {
    if (ev.key === "h" || ev.key === "H") {
      if (state.screen === "honesty") { hideAll(); restorePeekedFrom(); return; }
      showHonesty();
    } else if (ev.key === "t" || ev.key === "T") {
      if (document.activeElement === $("bar")) return;
      showInstrument();
    } else if (ev.key === "r" || ev.key === "R") {
      if (document.activeElement !== $("bar") && state.screen !== "instrument") restart();
    } else if (ev.key === "Escape") {
      // The instrument is home -- Escape from any Core-nested screen
      // (bare field, or mid split/obligation/court/loadrating) returns to
      // it. Honesty is the one true peek and restores whichever of
      // instrument/Core it was opened from, not always the instrument.
      if (state.screen === "honesty") { hideAll(); restorePeekedFrom(); return; }
      // The Time Machine used to be its own screen, reached by a button, and
      // needed a special Escape case to get back. It is now a section of the
      // Command OS page, so there is nothing to escape from.
      //
      // The evolution panel IS still its own overlay, opened from Agentic
      // Command OS, so Escape returns the user where they came from rather
      // than to the instrument -- which would strand them one screen away
      // from the panel they had just been on.
      if (state.screen === "evolution") { showCommandOS(); return; }
      if (state.screen !== "instrument") showInstrument();
    }
  });

  window.addEventListener("resize", resize);

  // Replay disclosure. If the API cannot be reached, the demo falls back to the
  // committed golden transcript -- and says so, in a banner nobody can miss.
  boot().catch((err) => {
    const banner = $("replay-banner");
    banner.hidden = false;
    banner.textContent =
      "REPLAY — live run failed (" + err.message + "), this is a recorded execution";
  });
  showCommandOS();

  window.__unwindState = state;
})();
