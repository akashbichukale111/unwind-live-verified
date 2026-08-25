"""The committed demo render: present, playable, and never claiming to be a model call.

WHY THIS FILE EXISTS
--------------------
`web/static/media/` holds a video, an audio track and a narration that ship
WITH the repository, unlike `.media/`, which is gitignored model output. The
distinction is the whole point, and it is easy to erode: someone regenerates
the bundle from a live Veo call, or drops the "NOT a model call" labelling,
and the page starts presenting a model artefact it did not produce -- or, just
as bad, presenting a local render as one.

So these tests assert three separate things:

1. The bytes are actually there and are actually decodable media. A manifest
   that outlives its files puts a dead `<video>` element on a live page.
2. The bundle is reproducible from committed input by
   `scripts/build_demo_media.py` alone -- no credential, no network. That is
   the property that makes committing it legitimate at all.
3. Nothing in the serving path or the page describes it as model output.
"""

from __future__ import annotations

import json
import re
import struct
import wave
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
MEDIA = REPO / "web" / "static" / "media"
MANIFEST = MEDIA / "manifest.json"


@pytest.fixture(scope="module")
def manifest() -> dict:
    assert MANIFEST.is_file(), (
        "web/static/media/manifest.json is missing. Run "
        "`python scripts/build_demo_media.py` to render the committed bundle."
    )
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 1. The bytes exist and are real media
# ---------------------------------------------------------------------------


def test_every_manifest_entry_has_bytes_on_disk(manifest: dict) -> None:
    """A manifest entry with no file behind it is a broken player on a live page."""
    for slot in ("video", "audio", "narration"):
        entry = manifest[slot]
        path = MEDIA / entry["file"]
        assert path.is_file(), f"{slot}: {entry['file']} is named in the manifest but absent"
        assert path.stat().st_size == entry["bytes"], (
            f"{slot}: {entry['file']} is {path.stat().st_size} bytes, manifest says {entry['bytes']}"
            " -- the manifest was not regenerated with the file"
        )


def test_video_ships_both_containers(manifest: dict) -> None:
    """One render, two wrappers, because no single codec covers every target.

    Safari and iOS decode H.264/AAC in MP4. A Chromium built without
    proprietary codecs -- including the headless one `evidence/browser/` runs
    in -- decodes VP9/Opus in WebM and refuses the MP4 with
    MEDIA_ERR_SRC_NOT_SUPPORTED. Shipping one of the two leaves a real
    audience unable to play the video.
    """
    mimes = [s["mime"] for s in manifest["video"]["sources"]]
    assert "video/webm" in mimes and "video/mp4" in mimes, mimes
    for source in manifest["video"]["sources"]:
        path = MEDIA / source["file"]
        assert path.is_file(), source["file"]
        assert path.stat().st_size > 100_000, f"{source['file']} is implausibly small"


def test_video_files_carry_their_container_signature() -> None:
    """Decodable, not just present -- checked at the container header."""
    mp4 = (MEDIA / "mission-replay.mp4").read_bytes()[:32]
    assert mp4[4:8] == b"ftyp", "mission-replay.mp4 has no ISO-BMFF ftyp box"
    webm = (MEDIA / "mission-replay.webm").read_bytes()[:4]
    assert webm == b"\x1a\x45\xdf\xa3", "mission-replay.webm has no EBML header"


def test_audio_is_audible_for_its_whole_duration() -> None:
    """A silent WAV would pass a size check and fail the only test that matters.

    The bar is deliberately RMS over each two-second window, not peak over the
    file: a single loud click at the start would clear a peak check while
    leaving 34 seconds of silence behind it.
    """
    with wave.open(str(MEDIA / "mission-signal.wav")) as w:
        frames = w.getnframes()
        rate = w.getframerate()
        assert w.getsampwidth() == 2 and w.getnchannels() == 1
        samples = struct.unpack(f"<{frames}h", w.readframes(frames))

    assert frames / rate > 20, "the signal is too short to be a mission replay"
    block = rate * 2
    windows = [samples[i : i + block] for i in range(0, frames - block, block)]
    for n, window in enumerate(windows):
        rms = (sum(v * v for v in window) / len(window)) ** 0.5
        # -30 dBFS. Quiet, but unambiguously not silence.
        assert rms > 32768 * 0.03, f"window {n} ({n * 2}s) is effectively silent: rms={rms:.0f}"


# ---------------------------------------------------------------------------
# 2. It is reproducible from committed input, which is why it may be committed
# ---------------------------------------------------------------------------


def test_the_source_brief_is_committed(manifest: dict) -> None:
    """The render's only input must be in the repository, not on someone's disk."""
    brief = REPO / manifest["source_brief"]
    assert brief.is_file(), f"{manifest['source_brief']} is not committed"
    record = json.loads(brief.read_text(encoding="utf-8"))["brief"]
    assert record["mission_id"] == manifest["mission_id"]
    assert record["checkpoint_count"] == manifest["checkpoint_count"]


def test_the_generator_reaches_no_network_and_no_model() -> None:
    """The claim "reproducible with no credential" has to be structural.

    `scripts/build_demo_media.py` may import ffmpeg and Pillow and read a
    committed JSON file. If it ever imports a Google client, a credential
    resolver or an HTTP library, the bundle stops being reproducible and this
    whole file's premise is void.
    """
    source = (REPO / "scripts" / "build_demo_media.py").read_text(encoding="utf-8")
    forbidden = (
        "google",
        "vertexai",
        "genai",
        "requests",
        "httpx",
        "urllib",
        "media.adapters",
        "aiohttp",
        "socket",
    )
    for name in forbidden:
        assert not re.search(rf"^\s*(import|from)\s+{re.escape(name)}\b", source, re.M), (
            f"scripts/build_demo_media.py imports {name!r} -- the demo bundle must be "
            "renderable with no credential and no network"
        )


# ---------------------------------------------------------------------------
# 3. It is never presented as model output
# ---------------------------------------------------------------------------


def test_manifest_states_it_is_not_a_model_call(manifest: dict) -> None:
    assert manifest["kind"] == "DETERMINISTIC_LOCAL_RENDER"
    assert manifest["not_a_model_call"] is True


def test_the_page_labels_every_player_as_a_local_render() -> None:
    """The label travels with the player, in the same string that builds it.

    Checked in the source rather than in a browser because a label that lives
    in a separate paragraph can be moved, collapsed or scrolled past; one that
    is concatenated into the player's own markup cannot be rendered without it.
    """
    app = (REPO / "web" / "static" / "app.js").read_text(encoding="utf-8")
    start = app.index("function demoStrip(")
    body = app[start : app.index("\n  }", start)]
    assert "PLAYS NOW" in body
    assert "deterministic local render" in body
    assert "NOT a " in body, "demoStrip must say which model did NOT generate this"
    # And the strip is used by every card, not just the video one.
    assert "demoStrip(m.modality)" in app


def test_the_committed_render_is_kept_out_of_the_verified_evidence_panel() -> None:
    """Two panels, two provenances, and they must not blend.

    `/api/media/verified-evidence` reports the one real 2026-08-21 Veo/Lyria
    generation. If the committed local render were ever served through that
    endpoint, a local render would be displayed under a heading that says
    "real Vertex generation".
    """
    from services.api.main import _VERIFIED_EVIDENCE_FILES

    committed = {p.name for p in MEDIA.iterdir() if p.is_file()}
    for _, (filename, _) in _VERIFIED_EVIDENCE_FILES.items():
        assert filename not in committed, (
            f"{filename} is both a committed demo file and a verified-evidence file"
        )
