"""Recompute every token pair and fail if any text colour is below 4.5:1.

The design brief fixes seven colours and a 4.5:1 floor. Those two constraints
are in tension: against `--ink`, only `--bone` and `--amber` actually clear the
floor, and the obvious reading of the palette -- rust for irreversible, patina
for settled -- puts unreadable text on the field.

So the rule this script enforces is:

    ON THE DARK FIELD  text may only be --bone or --amber.
    ON THE PAPER       text may only be --ink, --graphite or --oxide.
    EVERYWHERE ELSE    --slate, --graphite, --oxide and --verdigris are for
                       lines, fills and borders, where no contrast floor applies.

It parses style.css rather than trusting a comment, because a comment saying
"contrast checked" is exactly the kind of claim this project does not accept.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CSS = REPO / "web" / "static" / "style.css"

TOKENS = {
    "ink": "#12151A",
    "slate": "#262C34",
    "graphite": "#4A535E",
    "bone": "#EDE8DE",
    "amber": "#C88A2E",
    "oxide": "#8C3A2B",
    "verdigris": "#3E7A6E",
}

FLOOR = 4.5

#: Selectors whose surface is the PAPER (bone ground), where the legal set is
#: different. Anything not matching these is treated as sitting on --ink.
PAPER_PREFIXES = (".paper", ".o-", ".told", "#o-", ".btn-dark", ".instr-freeze")

LEGAL_ON_INK = {"bone", "amber"}
LEGAL_ON_BONE = {"ink", "graphite", "oxide"}


def luminance(hex_colour: str) -> float:
    h = hex_colour.lstrip("#")
    channels = [int(h[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4) for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def ratio(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def main() -> int:
    css = CSS.read_text(encoding="utf-8")
    failures: list[str] = []

    # ---- 1. the matrix, recomputed -------------------------------------
    print("contrast against --ink (the field):")
    for name, value in TOKENS.items():
        if name == "ink":
            continue
        r = ratio(value, TOKENS["ink"])
        legal = name in LEGAL_ON_INK
        print(f"  {name:10s} {r:5.2f}:1  {'text-legal' if legal else 'NON-TEXT ONLY'}")
        if legal and r < FLOOR:
            failures.append(f"--{name} is declared text-legal on ink but measures {r:.2f}:1")

    print("contrast against --bone (the paper):")
    for name, value in TOKENS.items():
        if name == "bone":
            continue
        r = ratio(value, TOKENS["bone"])
        legal = name in LEGAL_ON_BONE
        print(f"  {name:10s} {r:5.2f}:1  {'text-legal' if legal else 'NON-TEXT ONLY'}")
        if legal and r < FLOOR:
            failures.append(f"--{name} is declared text-legal on bone but measures {r:.2f}:1")

    # ---- 2. the stylesheet actually obeys it ---------------------------
    # Match `selector { ... color: var(--token) ... }`. `border-color`,
    # `background` and `stroke` are deliberately NOT matched: a 1px rule in
    # slate is not text and no floor applies to it.
    for match in re.finditer(r"([^{}]+)\{([^}]*)\}", css):
        selector = match.group(1).strip().splitlines()[-1].strip()
        body = match.group(2)
        if selector.startswith("@") or not selector:
            continue
        for colour_match in re.finditer(r"(?<![-\w])color:\s*var\(--([a-z]+)\)", body):
            token = colour_match.group(1)
            on_paper = any(p in selector for p in PAPER_PREFIXES)
            allowed = LEGAL_ON_BONE if on_paper else LEGAL_ON_INK
            if token not in allowed:
                surface = "bone/paper" if on_paper else "ink/field"
                r = ratio(TOKENS[token], TOKENS["bone" if on_paper else "ink"])
                failures.append(
                    f"{selector!r} sets color:var(--{token}) on {surface} "
                    f"({r:.2f}:1, below {FLOOR})"
                )

    # ---- 3. no eighth colour -------------------------------------------
    hexes = {h.upper() for h in re.findall(r"#[0-9A-Fa-f]{6}", css)}
    extra = hexes - {v.upper() for v in TOKENS.values()}
    if extra:
        failures.append(f"colours outside the seven tokens: {sorted(extra)}")

    # ---- 4. no gradient, no radius above 4px ---------------------------
    if re.search(r"linear-gradient|radial-gradient|conic-gradient", css):
        failures.append("a gradient is present; the brief forbids gradients on surfaces")
    for radius in re.findall(r"border-radius:\s*([0-9.]+)px", css):
        if float(radius) > 4:
            failures.append(f"border-radius {radius}px exceeds the 4px structural limit")

    print("")
    if failures:
        print("FAILURES:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    print("Contrast, palette, gradient and radius checks all pass.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
