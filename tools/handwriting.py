#!/usr/bin/env python3
"""Handwriting converter — a phrase in, a scene package out.

The point of the project is a line that writes itself, so the natural test is a
sentence in handwriting rather than a signature squiggle. This turns text into
the stroke paths a pen would make, using Hershey's cursive font: stroke-based
by design, because it was drawn for plotters rather than for printing.

It is a **composer-side tool**. Nothing on the device ever loads a font file —
the player receives ordinary paths with their lengths already measured, which
is where that work belongs (decision 0004). Run it once, commit the scene.

    tools/fetch-hershey.sh
    .venv/bin/python tools/handwriting.py "this is mementum" \\
        --out poc/scenes/handwriting.json

Letters are separate strokes, as they are for a real pen: the player draws one
before starting the next, which is the sequential-subpath rule the reveal
already follows.

The Hershey Fonts were originally created by Dr. A. V. Hershey while working at
the U. S. National Bureau of Standards. The format of the font data in this
distribution was originally created by James Hurt, Cognition Inc.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mementum_node.core.geometry import flatten_path, polyline_length  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_FONT = os.path.join(
    os.path.dirname(HERE), "third_party", "hershey-fonts", "hershey-fonts", "cursive.jhf"
)

#: Hershey glyphs are indexed from the space character.
FIRST_CHAR = 32


def load_font(path: str = DEFAULT_FONT) -> list[tuple[int, int, list[list[tuple[int, int]]]]]:
    """Parse a .jhf file into (left, right, strokes) per glyph.

    Coordinates are single characters offset from ``R``; a pen lift is the pair
    ``" R"``. That is the whole format.
    """
    glyphs = []
    with open(path, "r", encoding="latin-1") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if len(line) < 10:
                continue
            body = line[8:]
            left = ord(body[0]) - ord("R")
            right = ord(body[1]) - ord("R")

            strokes: list[list[tuple[int, int]]] = []
            current: list[tuple[int, int]] = []
            for i in range(2, len(body) - 1, 2):
                pair = body[i : i + 2]
                if pair == " R":
                    if len(current) > 1:
                        strokes.append(current)
                    current = []
                    continue
                current.append((ord(pair[0]) - ord("R"), ord(pair[1]) - ord("R")))
            if len(current) > 1:
                strokes.append(current)
            glyphs.append((left, right, strokes))
    return glyphs


def layout(
    text: str,
    glyphs: list,
    scale: float = 1.0,
    origin: tuple[float, float] = (0.0, 0.0),
    letter_spacing: float = 0.0,
) -> list[list[tuple[float, float]]]:
    """Place a string as pen strokes, in design units."""
    x, y = origin
    out: list[list[tuple[float, float]]] = []
    for character in text:
        index = ord(character) - FIRST_CHAR
        if index < 0 or index >= len(glyphs):
            continue
        left, right, strokes = glyphs[index]
        for stroke in strokes:
            out.append(
                [((px - left) * scale + x, py * scale + y) for px, py in stroke]
            )
        x += (right - left) * scale + letter_spacing
    return out


def to_path_data(strokes: list[list[tuple[float, float]]]) -> str:
    """Strokes to an SVG ``d``: one subpath per pen stroke."""
    parts = []
    for stroke in strokes:
        parts.append("M %.2f %.2f" % stroke[0])
        parts.extend("L %.2f %.2f" % point for point in stroke[1:])
    return " ".join(parts)


def bounds(strokes) -> tuple[float, float, float, float]:
    xs = [p[0] for stroke in strokes for p in stroke]
    ys = [p[1] for stroke in strokes for p in stroke]
    return min(xs), min(ys), max(xs), max(ys)


def build_scene(
    text: str,
    width: int = 480,
    height: int = 320,
    duration: int = 5200,
    scene_id: int = 48,
    font_path: str = DEFAULT_FONT,
    stroke: str = "#e8e8f0",
    stroke_width: float = 2.5,
    margin: float = 0.10,
    travel: bool = False,
) -> dict:
    """A scene that writes ``text`` out, then holds it.

    With ``travel``, it does not write itself at all: it arrives already
    written from beyond the right edge, crosses, and leaves past the left one.
    That is what a word running through a wall needs -- each unit plays the
    same scene, started later than its neighbour by the time the word takes to
    cross one panel, and the word appears to walk from unit to unit.
    """
    glyphs = load_font(font_path)

    # Lay out once at unit scale to measure, then scale to fit the canvas.
    trial = layout(text, glyphs, 1.0)
    if not trial:
        raise ValueError(f"nothing to draw for {text!r}")
    min_x, min_y, max_x, max_y = bounds(trial)
    usable = width * (1.0 - 2 * margin)
    scale = usable / (max_x - min_x)

    strokes = layout(text, glyphs, scale)
    min_x, min_y, max_x, max_y = bounds(strokes)
    offset_x = (width - (max_x - min_x)) / 2.0 - min_x
    offset_y = height / 2.0 - (min_y + max_y) / 2.0
    strokes = [[(x + offset_x, y + offset_y) for x, y in stroke] for stroke in strokes]

    path_data = to_path_data(strokes)

    # The composer measures; the player never has to (decision 0004).
    subpaths = [polyline_length(subpath) for subpath in flatten_path(path_data)]

    if travel:
        # Already drawn, and moving: tx runs a full panel width either side, so
        # the word is entirely off one edge at each end of the animation.
        animations = [
            {"target": "hand", "property": "transform.tx", "start": 0,
             "duration": duration, "from": width, "to": -width, "easing": "linear"},
        ]
        progress = 1
    else:
        animations = [
            {"target": "hand", "property": "progress", "start": 0,
             "duration": int(duration * 0.78), "from": 0, "to": 1, "easing": "ease-in-out"},
        ]
        progress = 0

    return {
        "version": 1,
        "id": scene_id,
        "name": "travelling" if travel else "handwriting",
        "width": width,
        "height": height,
        "fit": "contain",
        "duration": duration,
        "text": text,
        "credit": (
            "Hershey Fonts by Dr. A. V. Hershey, U.S. National Bureau of Standards; "
            "data format by James Hurt, Cognition Inc."
        ),
        "layers": [
            {"id": "background", "z": 0, "objects": [
                {"type": "rect", "id": "bg", "x": 0, "y": 0, "w": width, "h": height,
                 "fill": "#0c0c11"}]},
            {"id": "writing", "z": 10, "objects": [
                {"type": "path", "id": "hand", "d": path_data,
                 "length": round(sum(subpaths), 3),
                 "subpaths": [round(value, 3) for value in subpaths],
                 "stroke": stroke, "stroke_width": stroke_width, "progress": progress}]}],
        "animations": animations,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="write a phrase as pen strokes")
    parser.add_argument("text")
    parser.add_argument("--out", default=None)
    parser.add_argument("--travel", action="store_true",
                        help="arrive written and cross the panel, for a word "
                             "running through a wall")
    parser.add_argument("--width", type=int, default=480)
    parser.add_argument("--height", type=int, default=320)
    parser.add_argument("--duration", type=int, default=5200)
    parser.add_argument("--font", default=DEFAULT_FONT)
    args = parser.parse_args(argv)

    scene = build_scene(args.text, args.width, args.height, args.duration,
                        font_path=args.font, travel=args.travel)
    payload = json.dumps(scene, indent=2) + "\n"
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(payload)
        print(f"{args.out}: {len(scene['layers'][1]['objects'][0]['subpaths'])} pen strokes, "
              f"{scene['layers'][1]['objects'][0]['length']:.0f} units of ink")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
