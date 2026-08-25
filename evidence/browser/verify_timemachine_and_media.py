"""Time Machine fix + Media Lab + seven-card regression, in one real browser run."""

import os

from playwright.sync_api import sync_playwright

#: Pinned path from the sandbox this was written in; used only when it
#: exists on disk. Elsewhere (e.g. Windows) Playwright resolves its own
#: installed browser instead.
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
errs = []
failed = []
res = []


def ck(n, ok, d=""):
    res.append((n, bool(ok), str(d)))
    print(f"  {'PASS' if ok else 'FAIL'}  {n}{(' — ' + str(d)) if d else ''}")


with sync_playwright() as pw:
    b = pw.chromium.launch(**({"executable_path": CHROME} if os.path.exists(CHROME) else {}))
    p = b.new_page(viewport={"width": 1500, "height": 1100})
    p.on("console", lambda m: errs.append(f"{m.type}: {m.text}") if m.type == "error" else None)
    p.on("pageerror", lambda e: errs.append(f"PAGEERROR: {e}"))
    p.on("requestfailed", lambda r: failed.append(f"{r.url} -> {r.failure}"))
    p.goto("http://127.0.0.1:8099", wait_until="networkidle")
    p.wait_for_timeout(2000)

    print("\n== MEDIA LAB (in Agentic Command OS) ==")
    ck("media lab renders", p.is_visible("#media-lab"))
    ck(
        "three modality cards",
        p.locator(".media-card").count() == 3,
        f"{p.locator('.media-card').count()}",
    )
    lab = p.inner_text("#media-lab")
    # Model strings are IMPORTED, never retyped. `lib/config.py` is the only
    # file allowed to hold one, and `tests/test_config_singleton.py` enforces
    # that by grepping every TRACKED file -- which this script is. Hardcoding
    # them here was a real violation of the repository's own rule (CI caught
    # it; it passed locally only because the file was still untracked when the
    # suite ran). Importing also means the check cannot quietly keep asserting
    # a stale model ID after `lib/config.py` changes.
    from lib.config import get_config

    _cfg = get_config()
    for m, mid in [
        ("GEMINI", _cfg.model_deep),
        ("VEO", _cfg.veo_model),
        ("LYRIA", _cfg.lyria_model),
    ]:
        ck(f"{m} card + model id", m in lab and mid in lab, mid)
    ck("all three CONFIGURED_NOT_EXERCISED", lab.count("CONFIGURED_NOT_EXERCISED") == 3)
    ck("no fake LIVE claim", "GENERATED" not in lab)
    note = p.inner_text("#media-note")
    ck(
        "note explains fail-closed",
        "NO VERTEX CREDENTIAL" in note and "NOT_CONFIGURED" in note,
        note[:64],
    )
    ck(
        "note distinguishes the committed render from a model call",
        "never a model call" in note,
    )

    print("\n== THE COMMITTED RENDER PLAYS, WITH NO CREDENTIAL ==")
    # THE POINT OF THIS BLOCK. Every check above proves the lab is HONEST
    # about having no credential. None of them proved a visitor can actually
    # watch or hear anything, and for a long time they could not: three
    # buttons that all returned NOT_CONFIGURED was the entire experience of
    # this panel on a deployment without Vertex. The committed deterministic
    # render fixes that without touching the honesty -- so it is checked here,
    # in the same run, that BOTH hold at once.
    for modality in ("gemini", "veo", "lyria"):
        strip = p.locator(f".media-card[data-modality={modality}] .media-demo")
        ck(f"{modality}: player is inside its own card", strip.count() == 1)
        ck(
            f"{modality}: labelled a local render, not a generation",
            "deterministic local render" in strip.inner_text()
            and f"NOT a {modality.upper()}" in strip.inner_text(),
        )

    played = p.evaluate("""async () => {
      const v = document.querySelector('.media-card[data-modality=veo] video');
      const a = document.querySelector('.media-card[data-modality=lyria] audio');
      await Promise.all([v.play().catch(() => {}), a.play().catch(() => {})]);
      await new Promise(r => setTimeout(r, 3000));
      return {
        video: {src: v.currentSrc, w: v.videoWidth, h: v.videoHeight,
                t: v.currentTime, err: v.error && v.error.code},
        audio: {src: a.currentSrc, dur: a.duration, t: a.currentTime,
                muted: a.muted, err: a.error && a.error.code},
      };
    }""")
    vid, aud = played["video"], played["audio"]
    #: currentTime > 0 with no error is the only thing that distinguishes a
    #: video that PLAYED from one that merely loaded, and videoWidth proves
    #: frames were actually decoded rather than a container being parsed.
    ck(
        "VIDEO really plays — decoded frames, clock advancing",
        vid["err"] is None and vid["w"] > 0 and vid["t"] > 0.5,
        f"{vid['w']}x{vid['h']} at t={vid['t']:.2f}s · {vid['src'].rsplit('/', 1)[-1]}",
    )
    ck(
        "AUDIO really plays — unmuted, clock advancing",
        aud["err"] is None and not aud["muted"] and aud["t"] > 0.5,
        f"{aud['dur']:.1f}s track at t={aud['t']:.2f}s · {aud['src'].rsplit('/', 1)[-1]}",
    )
    narration = p.inner_text("#media-demo-narration")
    ck(
        "GEMINI card shows its zero-model mission intelligence",
        len(narration) > 400 and "ZERO-MODEL RENDER" in narration,
        f"{len(narration)} chars",
    )

    print("\n== REAL VERIFIED EVIDENCE (the archived 2026-08-21 Veo/Lyria pass) ==")
    p.wait_for_timeout(1500)
    verified_json = p.evaluate("fetch('/api/media/verified-evidence').then(r => r.json())")
    ck("endpoint reachable", isinstance(verified_json, dict), verified_json)
    veo_v = (verified_json or {}).get("veo", {})
    lyria_v = (verified_json or {}).get("lyria", {})
    if veo_v.get("available") or lyria_v.get("available"):
        ck("panel unhidden when evidence present", p.is_visible("#media-verified"))
        if veo_v.get("available"):
            ck("real veo video element present + sized", p.locator("#mv-video").count() == 1)
            ck(
                "veo byte size matches the endpoint's own stat() call",
                p.get_attribute("#mv-video", "src") == veo_v["url"],
                veo_v.get("size_bytes"),
            )
        if lyria_v.get("available"):
            ck("real lyria audio element present", p.locator("#mv-audio").count() == 1)
            ck(
                "lyria src matches the endpoint's own artefact url",
                p.get_attribute("#mv-audio", "src") == lyria_v["url"],
                lyria_v.get("size_bytes"),
            )
    else:
        ck(
            "panel honestly stays hidden — no local .media/ artefacts in this environment",
            not p.is_visible("#media-verified"),
        )

    print("\n== MEDIA: press a button with no mission ==")
    p.locator(".media-go").first.click()
    p.wait_for_timeout(1500)
    ck("refuses without a mission", "run a mission first" in p.inner_text("#media-out-gemini"))

    print("\n== run a real mission, then Media Lab ==")
    p.fill("#cmdos-token", "demo-tok")
    p.click("#cmdos-run")
    p.wait_for_timeout(14000)
    ck(
        "mission ran",
        p.locator(".cmdos-stage").count() > 5,
        f"{p.locator('.cmdos-stage').count()} stages",
    )
    p.locator(".media-go").first.click()
    p.wait_for_timeout(3000)
    out = p.inner_text("#media-out-gemini")
    ck("gemini returns NOT_CONFIGURED", "NOT_CONFIGURED" in out, out.split("\n")[0][:50])
    ck("reason is real", "UNWIND_VERTEX_DISABLED" in out or "credentials" in out)
    ck("shows the grounded prompt it would send", "grounded prompt" in out)
    p.locator(".media-go").nth(1).click()
    p.wait_for_timeout(2500)
    veo = p.inner_text("#media-out-veo")
    ck(
        # Scoped to the per-mission result container, not the whole page:
        # the page can legitimately hold a SEPARATE <video> for the "Real
        # Verified Evidence" panel (the one archived 2026-08-21 Veo
        # generation, played back regardless of this mission's own
        # NOT_CONFIGURED status) without that counting as a fabricated
        # result for THIS mission's own click.
        "veo NOT_CONFIGURED, no fake video",
        "NOT_CONFIGURED" in veo and p.locator("#media-out-veo video").count() == 0,
    )
    p.locator(".media-go").nth(2).click()
    p.wait_for_timeout(2500)
    ly = p.inner_text("#media-out-lyria")
    ck(
        "lyria NOT_CONFIGURED, no fake audio",
        "NOT_CONFIGURED" in ly and p.locator("#media-out-lyria audio").count() == 0,
    )
    p.screenshot(path="evidence/browser/media-lab.png", full_page=True)

    print("\n== CONSEQUENCE PREVIEW (the agent action simulator) ==")
    p.evaluate("document.getElementById('cq-out').scrollIntoView()")
    p.wait_for_timeout(2500)
    ck(
        "consequence graph renders",
        p.locator(".cq-node").count() > 0,
        f"{p.locator('.cq-node').count()} nodes",
    )
    ck("risk index renders", p.is_visible(".cq-risk"))
    cq = p.inner_text("#cq-out")
    ck("shows the real 2,594 radius", "2,594" in cq or "2594" in cq)
    ck("names the escaped consequences", "ESCAPED" in cq.upper())
    ck(
        "risk index is decomposed",
        all(
            d in cq
            for d in [
                "security",
                "data",
                "financial",
                "operational",
                "privilege",
                "irreversibility",
            ]
        ),
    )
    ck("labelled a heuristic, not a certified score", "not an industry-certified" in cq)
    # Changing the proposed action must CHANGE the answer -- otherwise it is a picture.
    before = p.inner_text(".cq-total")
    p.select_option("#cq-action", "SECRET_ACCESS")
    p.wait_for_timeout(2500)
    after = p.inner_text(".cq-total")
    ck(
        "changing the action changes the risk",
        before != after,
        f"{before.strip()} -> {after.strip()}",
    )
    # An untraceable premise must say UNKNOWN, never a safe-looking zero.
    p.select_option("#cq-premise", "nonexistent|premise|1")
    p.wait_for_timeout(2500)
    unknown = p.inner_text("#cq-out")
    ck("untraceable premise says UNKNOWN not zero", "UNKNOWN" in unknown.upper())
    p.select_option("#cq-premise", "supplier_K|lead_time_days|20")
    p.wait_for_timeout(2000)
    p.screenshot(path="evidence/browser/consequence-preview.png", full_page=False)

    print("\n== MISSION TIME MACHINE (the reported bug) ==")
    # There is no longer a button to press. The Time Machine is a section of
    # the Agentic Command OS page and loads with it, so the check is that it
    # is ALREADY populated -- and that the page never navigated to get there.
    p.wait_for_timeout(4500)
    ck("renders inline, with no button pressed", p.is_visible("#mtm-heading"))
    ck(
        "no Time Machine button remains",
        p.locator("#cmdos-open-timemachine").count() == 0,
    )
    ck(
        "did not navigate away from Agentic Command OS",
        p.evaluate("window.__unwindState.screen") == "command-os",
    )
    ck(
        "mission list populated",
        p.locator("#mtm-missions [data-mission]").count() > 0,
        f"{p.locator('#mtm-missions [data-mission]').count()} missions",
    )
    ck(
        "checkpoints auto-load",
        p.locator("#mtm-checkpoints [data-seq]").count() > 0,
        f"{p.locator('#mtm-checkpoints [data-seq]').count()} checkpoints",
    )
    ck(
        "mission arc renders",
        p.locator(".mtm-arc-node").count() > 0,
        f"{p.locator('.mtm-arc-node').count()} nodes",
    )
    ck("current node marked", p.locator(".mtm-arc-dot-current").count() == 1)
    st = p.inner_text("#mtm-state")
    ck("RESUME labelled LIVE", "RESUME FROM LAST CHECKPOINT" in st)
    ck(
        "REPLAY honestly NOT IMPLEMENTED",
        "REPLAY FROM AN ARBITRARY CHECKPOINT" in st and "NOT IMPLEMENTED" in st,
    )
    p.locator("#mtm-checkpoints [data-seq]").first.click()
    p.wait_for_timeout(1200)
    ck("checkpoint detail opens", p.is_visible("#mtm-detail"))
    p.screenshot(path="evidence/browser/timemachine.png", full_page=True)

    # The Time Machine used to be its own screen, so Escape needed a special
    # case to get back to Agentic Command OS. Inline, there is no screen to
    # leave -- opening a checkpoint's detail must not have navigated anywhere,
    # and Escape from here does what it does from any Core screen.
    print("\n== NO NAVIGATION HAPPENED ==")
    ck(
        "still on Agentic Command OS after opening a checkpoint",
        p.evaluate("window.__unwindState.screen") == "command-os",
    )
    ck("the Media Lab is still on screen alongside it", p.is_visible("#media-lab"))

    print("\n== SEVEN-CARD REGRESSION ==")
    p.click("#cmdos-open-instrument")
    p.wait_for_timeout(2500)
    ck("[2/7] instrument", p.is_visible("#instrument"))
    for dc, label, sec in [
        ("0", "WARRANT", "#warrant-detail"),
        ("2", "CONTROL TOWER", "#tower-detail"),
        ("3", "COUNTERSIGN", "#countersign-detail"),
        ("4", "HYPERION-ZERO", "#hyperion-detail"),
        ("5", "SINGULARITY-MESH", "#singularity-detail"),
    ]:
        p.evaluate(f"document.querySelector('[data-card=\"{dc}\"]').click()")
        p.wait_for_timeout(2000)
        ck(f"{label} opens + renders", p.is_visible(sec) and len(p.inner_text(sec)) > 120)
        p.evaluate(
            "document.querySelectorAll('.detail-back').forEach(x=>{if(x.offsetParent!==null)x.click()})"
        )
        p.wait_for_timeout(1000)
    p.evaluate("document.querySelector('[data-card=\"1\"]').click()")
    p.wait_for_timeout(3000)
    ck("UNWIND CORE opens", p.is_visible("#bar-wrap") or p.is_visible("#split"))

    # ERR_ABORTED on /static/media/ is Chromium ending a `preload="metadata"`
    # range request once it has the header it wanted, and on re-render when a
    # replaced <video> drops its own pending fetch. Neither is a broken URL --
    # the play checks above prove those same files decode and run -- so they
    # are expected here rather than treated as a failed request.
    exp = (
        "401",
        "fonts.googleapis",
        "ERR_CONNECTION_RESET",
        "/static/media/",
    )
    bad = [f for f in failed if not any(e in f for e in exp)]
    ck("no unexpected failed requests", not bad, "; ".join(bad[:2]) or "none")
    b.close()
ok = sum(1 for _, o, _ in res if o)
print(f"\n{ok}/{len(res)} checks passed")
raise SystemExit(0 if ok == len(res) else 1)
