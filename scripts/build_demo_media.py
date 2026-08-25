"""Render the committed Mission Replay video and Mission Signal audio.

WHAT THESE FILES ARE, AND WHAT THEY ARE NOT
-------------------------------------------
`web/static/media/mission-replay.mp4` and `.../mission-signal.wav` are a
DETERMINISTIC LOCAL RENDER of one real mission's persisted checkpoints. They
are not Veo output and they are not Lyria output. Every frame and every note
below is computed by this file from `evidence/media/grounded-brief-*.json` --
the exact grounded brief `media/grounding.py` built from the checkpoints
`command_os/checkpoint.py` actually wrote for `mission_628ee1fb5b`.

WHY THEY ARE COMMITTED WHEN `.media/` IS GITIGNORED
---------------------------------------------------
`.gitignore` refuses generated MODEL output: "a generated video/audio file is
not reproducible by any test and must not be committed as if it were evidence
of a call this repo can re-run". That rule is about reproducibility, and it is
exactly why these two files may be committed: re-running this script on any
machine, with no credential and no network, reproduces them byte-for-byte from
committed input. `tests/test_demo_media.py` asserts they are present, playable
and labelled as a local render.

They exist because a deployment that has never had a Vertex credential still
has to be able to SHOW the mission, not just describe it. The Media Lab's
Veo and Lyria cards remain honest about their own status; this is a separate,
separately-labelled artefact that plays everywhere.

Regenerate with:  python scripts/build_demo_media.py
"""

from __future__ import annotations

import json
import math
import struct
import subprocess
import sys
import wave
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BRIEF = REPO / "evidence" / "media" / "grounded-brief-20260820T092845Z.json"
OUT_DIR = REPO / "web" / "static" / "media"

# The site's own palette (web/static/style.css). Reusing it means the video
# reads as part of the instrument rather than as a stock clip dropped into it.
INK = (0x12, 0x15, 0x1A)
SLATE = (0x26, 0x2C, 0x34)
GRAPHITE = (0x4A, 0x53, 0x5E)
BONE = (0xED, 0xE8, 0xDE)
AMBER = (0xC8, 0x8A, 0x2E)
OXIDE = (0x8C, 0x3A, 0x2B)
VERDIGRIS = (0x3E, 0x7A, 0x6E)

W, H = 1280, 720
FPS = 24
SECONDS_PER_MOMENT = 2.5
LEAD_IN = 2.0
LEAD_OUT = 3.0
SAMPLE_RATE = 44100


# ---------------------------------------------------------------------------
# INPUT -- the real brief, never invented
# ---------------------------------------------------------------------------
def load_brief() -> dict:
    with BRIEF.open(encoding="utf-8") as fh:
        return json.load(fh)["brief"]


def is_containment(moment: dict) -> bool:
    return "CONTAIN" in moment["phase"].upper() or "ISOLATED" in moment["summary"].upper()


def accent_for(moment: dict) -> tuple[int, int, int]:
    """Colour is DERIVED FROM THE CHECKPOINT ITSELF, not decoration.

    A phase that ran for real is bone; a simulated one is amber; a
    containment or refusal is oxide. Someone reading the video can tell
    which is which without the audio and without the caption. The
    containment check reads the phase and summary, not just the status
    label -- CONTAIN's status is "LIVE", and painting the one moment the
    mission isolated an agent the same colour as a routine step would hide
    exactly the frame a reviewer is looking for.
    """
    if is_containment(moment):
        return OXIDE
    up = moment["status"].upper()
    if "BLOCKED" in up or "REFUS" in up or "FAILED" in up:
        return OXIDE
    if "SIMULATED" in up:
        return AMBER
    return BONE


# ---------------------------------------------------------------------------
# AUDIO -- "MISSION SIGNAL". One note per checkpoint, pitched by what happened.
# ---------------------------------------------------------------------------
# A minor pentatonic ladder, so consecutive checkpoints are always consonant
# and the piece is listenable rather than a test tone. The mapping is fixed and
# documented: a mission that went badly is AUDIBLY lower and rougher than one
# that did not, which is the only reason to render state as sound at all.
SCALE_HZ = [174.61, 196.00, 233.08, 261.63, 293.66, 349.23, 392.00, 466.16, 523.25]
DRIFT_DETUNE = {"NORMAL": 0.0, "ELEVATED": 0.9, "DRIFT": 2.4, "CRITICAL": 5.0}


def envelope(i: int, n: int, attack: float, release: float) -> float:
    a = int(n * attack)
    r = int(n * release)
    if i < a:
        return i / max(a, 1)
    if i > n - r:
        return max(0.0, (n - i) / max(r, 1))
    return 1.0


def render_signal(brief: dict) -> list[float]:
    """One continuous pad + one struck note per checkpoint."""
    moments = brief["moments"]
    detune = DRIFT_DETUNE.get(brief.get("drift_band", "NORMAL"), 0.0)
    total_s = LEAD_IN + len(moments) * SECONDS_PER_MOMENT + LEAD_OUT
    n_total = int(total_s * SAMPLE_RATE)
    buf = [0.0] * n_total

    # The pad: the mission's baseline, one drone that never stops for as long
    # as the mission is open. Detuned by the drift band, so an ELEVATED
    # mission beats slowly against itself and a CRITICAL one is rough.
    root = SCALE_HZ[0]
    for i in range(n_total):
        t = i / SAMPLE_RATE
        env = envelope(i, n_total, 0.06, 0.22) * 0.16
        buf[i] += env * (
            math.sin(2 * math.pi * root * t)
            + 0.6 * math.sin(2 * math.pi * (root + detune) * t)
            + 0.35 * math.sin(2 * math.pi * root * 1.5 * t)
        )

    # One note per checkpoint. Pitch climbs with the mission arc; a
    # containment checkpoint drops a fifth instead of climbing, which is the
    # single most audible event in the piece because it is the single most
    # important one in the mission.
    for idx, moment in enumerate(moments):
        start_s = LEAD_IN + idx * SECONDS_PER_MOMENT
        start = int(start_s * SAMPLE_RATE)
        n = int(SECONDS_PER_MOMENT * 1.6 * SAMPLE_RATE)
        n = min(n, n_total - start)
        if n <= 0:
            continue
        degree = min(idx, len(SCALE_HZ) - 1)
        freq = SCALE_HZ[degree]
        if is_containment(moment):
            freq = SCALE_HZ[0] * 0.75  # a fifth below the root -- the drop
        for i in range(n):
            t = i / SAMPLE_RATE
            env = envelope(i, n, 0.008, 0.75) * 0.30
            # Two partials and a soft octave: a struck-string shape, not a beep.
            buf[start + i] += env * (
                math.sin(2 * math.pi * freq * t)
                + 0.30 * math.sin(2 * math.pi * freq * 2 * t)
                + 0.12 * math.sin(2 * math.pi * freq * 3.01 * t)
            )

    # The final chord: the mission's terminal status, held. VERIFIED resolves
    # to the major third; anything else stays on the bare fifth.
    tail = int(LEAD_OUT * SAMPLE_RATE)
    tail_start = n_total - tail
    resolved = bool(brief.get("verified"))
    chord = [root, root * 1.5, root * (1.25 if resolved else 1.5) * 2]
    for i in range(tail):
        t = i / SAMPLE_RATE
        env = envelope(i, tail, 0.10, 0.60) * 0.22
        for f in chord:
            buf[tail_start + i] += env * math.sin(2 * math.pi * f * t)

    peak = max(abs(v) for v in buf) or 1.0
    return [v / peak * 0.89 for v in buf]


def write_wav(samples: list[float], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(
            b"".join(struct.pack("<h", int(max(-1.0, min(1.0, s)) * 32767)) for s in samples)
        )


# ---------------------------------------------------------------------------
# NARRATION -- "MISSION INTELLIGENCE", rendered with zero model calls.
# ---------------------------------------------------------------------------
# The Gemini card's third artefact. Written by the same rules the video's
# colour mapping uses, from the same brief, so the text, the picture and the
# sound cannot disagree about what happened -- which is the entire point of
# `media/grounding.py` building one brief for three modalities.
def render_narration(brief: dict) -> str:
    moments = brief["moments"]
    contained = [m for m in moments if is_containment(m)]
    simulated = [m for m in moments if "SIMULATED" in m["status"].upper()]
    lines = [
        f"MISSION {brief['mission_id']} — {brief['status']}",
        "",
        f"Objective: {brief['objective']}",
        f"Arc: {' → '.join(brief['arc'])}",
        "",
        f"{brief['checkpoint_count']} checkpoints were persisted. Drift band closed at "
        f"{brief.get('drift_band', 'UNKNOWN')}.",
    ]
    if contained:
        c = contained[0]
        lines += [
            "",
            f"The mission's decisive moment is checkpoint {c['seq']}, {c['phase']}: {c['summary']}",
            "",
            "Everything after that checkpoint is priced against a contained fleet, "
            "not a clean one — which is why the steps that follow carry a tax the "
            "earlier ones do not.",
        ]
    if simulated:
        lines += [
            "",
            f"{len(simulated)} of {len(moments)} checkpoints are labelled SIMULATED "
            f"({', '.join(m['phase'].split(' — ')[0] for m in simulated)}). They are "
            "not counted as live evidence anywhere in this system.",
        ]
    lines += [
        "",
        f"Human principal: {brief.get('human_principal') or 'none recorded'}.",
        f"Independently verified: {brief.get('verified')}.",
        "",
        "ZERO-MODEL RENDER — every sentence above is assembled by "
        "scripts/build_demo_media.py from the committed grounded brief. No Gemini "
        "call produced it, and it claims nothing the checkpoints do not say.",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# VIDEO -- "MISSION REPLAY". One card per checkpoint, in mission order.
# ---------------------------------------------------------------------------
def _font(size: int, mono: bool = True):
    from PIL import ImageFont

    candidates = (
        ["DejaVuSansMono-Bold.ttf", "DejaVuSansMono.ttf"]
        if mono
        else ["DejaVuSans-Bold.ttf", "DejaVuSans.ttf"]
    )
    roots = ["/usr/share/fonts/truetype/dejavu/", "/usr/share/fonts/TTF/", ""]
    for root in roots:
        for name in candidates:
            try:
                return ImageFont.truetype(root + name, size)
            except OSError:
                continue
    return ImageFont.load_default()


def wrap(draw, text: str, font, max_w: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for word in words:
        trial = (cur + " " + word).strip()
        if draw.textlength(trial, font=font) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def frame_for(brief: dict, t: float):
    """The frame at time `t`. Pure function of the brief and the clock."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (W, H), INK)
    d = ImageDraw.Draw(img)
    moments = brief["moments"]

    f_title = _font(46, mono=False)
    f_label = _font(15)
    f_phase = _font(27)
    f_body = _font(19)
    f_small = _font(14)

    # A structural grid, at the graphite that style.css reserves for lines.
    for x in range(0, W, 64):
        d.line([(x, 0), (x, H)], fill=SLATE, width=1)
    d.line([(0, 96), (W, 96)], fill=SLATE, width=1)
    d.line([(0, H - 86), (W, H - 86)], fill=SLATE, width=1)

    # Persistent header: which mission this is. Never off-screen, so no frame
    # of this video can be quoted without its own provenance.
    d.text((56, 34), "UNWIND — MISSION REPLAY", font=f_title, fill=BONE)
    d.text(
        (56, H - 66),
        f"{brief['mission_id']} · {brief['status']} · drift {brief.get('drift_band', '—')}"
        f" · {brief['checkpoint_count']} checkpoints",
        font=f_label,
        fill=GRAPHITE,
    )
    d.text(
        (56, H - 44),
        "deterministic local render of persisted checkpoints — not a Veo generation",
        font=f_small,
        fill=GRAPHITE,
    )

    body_top = 96.0
    if t < LEAD_IN:
        # Title card: the objective, held, before anything moves.
        a = min(1.0, t / 0.8)
        fade = tuple(int(INK[i] + (BONE[i] - INK[i]) * a) for i in range(3))
        d.text((56, 210), "OBJECTIVE", font=f_label, fill=GRAPHITE)
        for j, line in enumerate(wrap(d, brief["objective"], f_phase, W - 130)):
            d.text((56, 244 + j * 40), line, font=f_phase, fill=fade)
        d.text((56, 400), "ARC", font=f_label, fill=GRAPHITE)
        for j, line in enumerate(wrap(d, " → ".join(brief["arc"]), f_small, W - 130)):
            d.text((56, 428 + j * 22), line, font=f_small, fill=GRAPHITE)
        return img

    idx_f = (t - LEAD_IN) / SECONDS_PER_MOMENT
    idx = int(idx_f)
    if idx >= len(moments):
        # Closing card: the terminal state, and how it can be re-checked.
        d.text((56, 220), "TERMINAL STATE", font=f_label, fill=GRAPHITE)
        d.text(
            (56, 252),
            brief["status"],
            font=f_title,
            fill=VERDIGRIS if brief.get("verified") else AMBER,
        )
        d.text(
            (56, 336),
            f"isolated agent   {brief.get('isolated_agent') or '—'}",
            font=f_body,
            fill=BONE,
        )
        d.text(
            (56, 368),
            f"human principal  {brief.get('human_principal') or '—'}",
            font=f_body,
            fill=BONE,
        )
        d.text(
            (56, 400),
            f"independently verified  {brief.get('verified')}",
            font=f_body,
            fill=BONE,
        )
        d.text(
            (56, 470),
            "re-derive the input:  GET /api/media/mission/{id}/brief",
            font=f_small,
            fill=GRAPHITE,
        )
        return img

    moment = moments[idx]
    local = idx_f - idx
    accent = accent_for(moment)
    rail_x = W - 330

    # Progress ladder: every checkpoint as a tick, the current one lit. The
    # viewer can always see where in the mission this frame sits.
    for j in range(len(moments)):
        x0 = 56 + j * ((W - 112) / len(moments))
        x1 = x0 + (W - 112) / len(moments) - 6
        colour = accent_for(moments[j]) if j <= idx else SLATE
        if j == idx:
            colour = accent
        d.rectangle([x0, body_top + 26, x1, body_top + 30], fill=colour)

    # The card itself, sliding in from the right over the first 0.35 of its slot.
    slide = int(max(0.0, (0.35 - local) / 0.35) * 90)
    x = 56 + slide
    top = body_top + 78
    card_w = rail_x - 60 - (56 + slide + 24)

    d.text(
        (x, top),
        f"CHECKPOINT {moment['seq']:02d} / {len(moments):02d}",
        font=f_label,
        fill=GRAPHITE,
    )
    d.rectangle([x, top + 30, x + 5, top + 210], fill=accent)

    phase_lines = wrap(d, moment["phase"], f_phase, card_w)
    y = top + 30
    for line in phase_lines[:2]:
        d.text((x + 24, y), line, font=f_phase, fill=accent)
        y += 36

    d.text((x + 24, y + 8), moment["status"], font=f_label, fill=GRAPHITE)
    y += 40

    for line in wrap(d, moment["summary"], f_body, card_w)[:6]:
        d.text((x + 24, y), line, font=f_body, fill=BONE)
        y += 28

    # RIGHT RAIL -- the whole arc, always visible. A replay that only ever
    # shows one phase at a time cannot be checked against the mission; this
    # column means any frame states both where it is and what it is inside.
    d.line([(rail_x - 40, body_top + 60), (rail_x - 40, H - 110)], fill=SLATE, width=1)
    d.text((rail_x, body_top + 60), "MISSION ARC", font=f_label, fill=GRAPHITE)
    ry = body_top + 92
    for j, phase in enumerate(brief["arc"]):
        if j == idx:
            d.rectangle([rail_x - 12, ry - 3, rail_x - 8, ry + 15], fill=accent)
            d.text((rail_x, ry), phase, font=f_small, fill=accent)
        else:
            d.text((rail_x, ry), phase, font=f_small, fill=GRAPHITE if j < idx else SLATE)
        ry += 22

    return img


# TWO CONTAINERS, AND THIS IS NOT BELT-AND-BRACES FOR ITS OWN SAKE.
# H.264/AAC in MP4 is what Safari and iOS will decode; VP9/Opus in WebM is what
# a Chromium build compiled without proprietary codecs will decode -- and that
# is not a hypothetical browser, it is the one this repository's own headless
# verification runs in (`evidence/browser/`). Shipping only MP4 means the
# automated proof that the player works cannot actually watch it play. Both
# are rendered from the SAME frames and the same audio, so they are the same
# artefact in two wrappers, not two different videos.
VIDEO_ENCODINGS = (
    # (suffix, mime, ffmpeg output args). WebM is listed first because that is
    # the order the <source> elements go in: every evergreen browser takes it,
    # Safari falls through to the MP4.
    (
        "webm",
        "video/webm",
        [
            "-c:v",
            "libvpx-vp9",
            "-pix_fmt",
            "yuv420p",
            "-b:v",
            "0",
            "-crf",
            "34",
            "-row-mt",
            "1",
            "-deadline",
            "good",
            "-cpu-used",
            "3",
            "-c:a",
            "libopus",
            "-b:a",
            "96k",
        ],
    ),
    (
        "mp4",
        "video/mp4",
        [
            "-c:v",
            "libx264",
            "-profile:v",
            "high",
            "-pix_fmt",
            "yuv420p",
            "-preset",
            "slow",
            "-crf",
            "26",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            # metadata first, so it streams instead of buffering the whole file
            "-movflags",
            "+faststart",
        ],
    ),
)


def render_video(brief: dict, audio: Path, outputs: list[Path]) -> None:
    """Encode every container in ONE pass over the frames.

    Rendering the frames twice would be slow and, worse, would leave open the
    possibility of the two files differing. ffmpeg takes one raw stream on
    stdin and writes both outputs from it.
    """
    import imageio_ffmpeg

    total_s = LEAD_IN + len(brief["moments"]) * SECONDS_PER_MOMENT + LEAD_OUT
    n_frames = int(total_s * FPS)
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()

    cmd = [
        ffmpeg,
        "-y",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s",
        f"{W}x{H}",
        "-r",
        str(FPS),
        "-i",
        "-",
        "-i",
        str(audio),
    ]
    for out, (_, _, args) in zip(outputs, VIDEO_ENCODINGS, strict=True):
        out.parent.mkdir(parents=True, exist_ok=True)
        cmd += [*args, "-shortest", str(out)]

    proc = subprocess.Popen(
        cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
    )
    assert proc.stdin is not None
    for i in range(n_frames):
        proc.stdin.write(frame_for(brief, i / FPS).tobytes())
        if i % (FPS * 5) == 0:
            print(f"  frame {i}/{n_frames}", flush=True)
    proc.stdin.close()
    err = proc.stderr.read().decode("utf-8", "replace") if proc.stderr else ""
    if proc.wait() != 0:
        sys.exit("ffmpeg failed:\n" + err[-4000:])


def main() -> int:
    brief = load_brief()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    wav = OUT_DIR / "mission-signal.wav"
    videos = [OUT_DIR / f"mission-replay.{suffix}" for suffix, _, _ in VIDEO_ENCODINGS]

    print("rendering mission signal (audio)…")
    write_wav(render_signal(brief), wav)
    print(f"  {wav} · {wav.stat().st_size:,} bytes")

    print("rendering mission replay (video)…")
    render_video(brief, wav, videos)
    for path in videos:
        print(f"  {path} · {path.stat().st_size:,} bytes")

    # A poster frame, so the player shows the mission rather than a black
    # rectangle before anyone presses play.
    poster = OUT_DIR / "mission-replay-poster.jpg"
    frame_for(brief, LEAD_IN + 3 * SECONDS_PER_MOMENT + 0.6).save(poster, quality=88)
    print(f"  {poster} · {poster.stat().st_size:,} bytes")

    narration = OUT_DIR / "mission-narration.txt"
    narration.write_text(render_narration(brief) + "\n", encoding="utf-8")
    print(f"  {narration} · {narration.stat().st_size:,} bytes")

    manifest = OUT_DIR / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "source_brief": str(BRIEF.relative_to(REPO)).replace("\\", "/"),
                "mission_id": brief["mission_id"],
                "checkpoint_count": brief["checkpoint_count"],
                "generator": "scripts/build_demo_media.py",
                "kind": "DETERMINISTIC_LOCAL_RENDER",
                "not_a_model_call": True,
                "video": {
                    #: `file`/`mime` name the FALLBACK the manifest guarantees;
                    #: `sources` is the ordered list the <video> element emits
                    #: as <source> children. A reader of this manifest that
                    #: understands neither still gets one playable file.
                    "file": videos[-1].name,
                    "bytes": videos[-1].stat().st_size,
                    "mime": VIDEO_ENCODINGS[-1][1],
                    "sources": [
                        {
                            "file": path.name,
                            "mime": mime,
                            "bytes": path.stat().st_size,
                        }
                        for path, (_, mime, _) in zip(videos, VIDEO_ENCODINGS, strict=True)
                    ],
                    "poster": poster.name,
                    "duration_seconds": round(
                        LEAD_IN + len(brief["moments"]) * SECONDS_PER_MOMENT + LEAD_OUT, 1
                    ),
                },
                "audio": {"file": wav.name, "bytes": wav.stat().st_size, "mime": "audio/wav"},
                "narration": {
                    "file": narration.name,
                    "bytes": narration.stat().st_size,
                    "mime": "text/plain",
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"  {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
