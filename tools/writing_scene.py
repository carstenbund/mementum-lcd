"""Traced handwriting -> one scene package per word.

The second half of the artist pipeline. `split_svg.py` cuts a page of filled
outlines into entries; this takes a *centreline* trace and emits a scene the
player can actually animate — one word at a time, each written by `progress`.

    tools/writing_scene.py assets/svg-source/path1.svg \\
        --words du,kannst,werden,was,du,willst --out poc/scenes/writing

Three things it does that matter downstream:

* **Reading order by vertical overlap**, not by rounding a coordinate. A word
  with a tall ascender must not be pushed onto its own line — that bug put
  `kannst` before `du` and was invisible until someone watched the sequence.
* **One scale for the whole set**, so every word keeps the size it had on the
  page and the brush stays the same width throughout.
* **Lengths declared**, total and per stroke, so no player has to measure
  (decision 0004) and `progress` sequences the strokes as one pen trajectory.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import re  # noqa: E402

from mementum_node.core.geometry import flatten_path, polyline_length  # noqa: E402

#: Pieces shorter than this are junction stubs, not strokes.
MIN_STROKE = 30.0
#: A gap wider than this share of the line height starts a new word.
WORD_GAP = 0.15


def read_centrelines(svg: str, min_stroke: float = MIN_STROKE) -> list[list[tuple[float, float]]]:
    """Every stroke in the file, flattened, with the transform applied."""
    d = re.findall(r'\sd="([^"]*)"', svg, re.S)
    if not d:
        raise ValueError("no path data in this SVG")
    tf = re.search(r"translate\(([-\d.]+)[, ]+([-\d.]+)\)", svg)
    tx, ty = (float(tf.group(1)), float(tf.group(2))) if tf else (0.0, 0.0)

    strokes = []
    for data in d:
        for sub in flatten_path(data):
            if polyline_length(sub) >= min_stroke:
                strokes.append([(x + tx, y + ty) for x, y in sub])
    return strokes


def bbox(points):
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return (min(xs), min(ys), max(xs), max(ys))


def group_words(strokes, gap_factor: float = WORD_GAP):
    """Strokes into words, in reading order."""
    boxes = [bbox(s) for s in strokes]
    lines: list[list[int]] = []
    for i in sorted(range(len(strokes)), key=lambda i: boxes[i][1]):
        for line in lines:
            lo = min(boxes[j][1] for j in line)
            hi = max(boxes[j][3] for j in line)
            if not (hi < boxes[i][1] or boxes[i][3] < lo):
                line.append(i)
                break
        else:
            lines.append([i])

    words = []
    for line in lines:
        order = sorted(line, key=lambda i: boxes[i][0])
        group = [order[0]]
        reach = boxes[order[0]][2]
        height = max(boxes[j][3] for j in line) - min(boxes[j][1] for j in line)
        for i in order[1:]:
            if boxes[i][0] - reach > height * gap_factor:
                words.append(group)
                group = [i]
            else:
                group.append(i)
            reach = max(reach, boxes[i][2])
        words.append(group)
    return [[strokes[i] for i in w] for w in words]


def simplify(points, tolerance: float = 0.6):
    """Douglas-Peucker.

    A traced curve arrives as hundreds of flattened samples; the player holds a
    bounded number of segments per stroke, and at sub-pixel tolerance the shape
    is unchanged. Smaller scene packages as well."""
    if len(points) < 3:
        return list(points)
    a, b = points[0], points[-1]
    dx, dy = b[0] - a[0], b[1] - a[1]
    span = (dx * dx + dy * dy) ** 0.5
    worst, index = -1.0, 0
    for i in range(1, len(points) - 1):
        p = points[i]
        if span > 1e-9:
            d = abs(dy * p[0] - dx * p[1] + b[0] * a[1] - b[1] * a[0]) / span
        else:
            d = ((p[0] - a[0]) ** 2 + (p[1] - a[1]) ** 2) ** 0.5
        if d > worst:
            worst, index = d, i
    if worst > tolerance:
        return simplify(points[: index + 1], tolerance)[:-1] + simplify(points[index:], tolerance)
    return [a, b]


def compact_path(strokes, quantum: float = 0.5) -> str:
    """Relative, implicit-command path data on a fixed grid.

    Measured at four times smaller than absolute two-decimal output, with the
    ink landing within 0.2 px of the original — invisible, and it keeps scene
    packages small enough to matter on a device."""
    def n(value: float) -> str:
        return "%g" % (round(value / quantum) * quantum)

    parts = []
    cx = cy = 0.0
    for stroke in strokes:
        px, py = round(stroke[0][0] / quantum) * quantum, round(stroke[0][1] / quantum) * quantum
        parts.append("m%s %s" % (n(px - cx), n(py - cy)))
        cx, cy = px, py
        segment = []
        for x, y in stroke[1:]:
            qx, qy = round(x / quantum) * quantum, round(y / quantum) * quantum
            segment.append("%s %s" % (n(qx - cx), n(qy - cy)))
            cx, cy = qx, qy
        if segment:
            parts.append("l" + " ".join(segment))
    return "".join(parts).replace(" -", "-")


def build_scenes(svg: str, names: list[str], width: int, height: int,
                 stroke: str, background: str, stroke_width: float,
                 write_ms: int, hold_ms: int, fade_ms: int) -> list[dict]:
    words = group_words(read_centrelines(svg))
    if len(words) != len(names):
        raise ValueError(f"found {len(words)} words but {len(names)} names were given")

    boxes = [bbox([p for s in w for p in s]) for w in words]
    # One scale for the set: every word keeps the size it had on the page.
    scale = min(min(width * 0.86 / (b[2] - b[0]), height * 0.72 / (b[3] - b[1])) for b in boxes)

    scenes = []
    for index, (name, word, b) in enumerate(zip(names, words, boxes)):
        ox = (width - (b[2] - b[0]) * scale) / 2
        oy = (height - (b[3] - b[1]) * scale) / 2
        placed = []
        for s in sorted(word, key=lambda s: min(p[0] for p in s)):
            s = s if s[-1][0] >= s[0][0] else s[::-1]      # the pen travels rightwards
            placed.append(simplify(
                [((x - b[0]) * scale + ox, (y - b[1]) * scale + oy) for x, y in s]))

        data = compact_path(placed)
        lengths = [polyline_length(sub) for sub in flatten_path(data)]
        scenes.append({
            "version": 1, "id": 60 + index, "name": name,
            "width": width, "height": height, "fit": "contain",
            "duration": write_ms + hold_ms + fade_ms,
            "layers": [
                {"id": "background", "z": 0, "objects": [
                    {"type": "rect", "id": "bg", "x": 0, "y": 0,
                     "w": width, "h": height, "fill": background}]},
                {"id": "writing", "z": 10, "objects": [
                    {"type": "path", "id": "hand", "d": data,
                     "length": round(sum(lengths), 3),
                     "subpaths": [round(v, 3) for v in lengths],
                     "stroke": stroke, "stroke_width": stroke_width, "progress": 0}]}],
            "animations": [
                {"target": "hand", "property": "progress", "start": 0,
                 "duration": write_ms, "from": 0, "to": 1, "easing": "ease-in-out"},
                {"target": "hand", "property": "opacity",
                 "start": write_ms + hold_ms, "duration": fade_ms,
                 "from": 1, "to": 0, "easing": "linear"}],
        })
    return scenes


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="centreline SVG -> one scene per word")
    parser.add_argument("source")
    parser.add_argument("--words", required=True, help="comma separated, in reading order")
    parser.add_argument("--out", default="poc/scenes/writing")
    parser.add_argument("--width", type=int, default=450)
    parser.add_argument("--height", type=int, default=250)
    parser.add_argument("--stroke", default="#e8e8f0")
    parser.add_argument("--background", default="#0c0c11")
    parser.add_argument("--stroke-width", type=float, default=8.0)
    parser.add_argument("--write-ms", type=int, default=1400)
    parser.add_argument("--hold-ms", type=int, default=2000)
    parser.add_argument("--fade-ms", type=int, default=600)
    args = parser.parse_args(argv)

    with open(args.source, encoding="utf-8") as fh:
        scenes = build_scenes(fh.read(), args.words.split(","), args.width, args.height,
                              args.stroke, args.background, args.stroke_width,
                              args.write_ms, args.hold_ms, args.fade_ms)
    os.makedirs(args.out, exist_ok=True)
    for index, scene in enumerate(scenes):
        path = os.path.join(args.out, f"{index:02d}-{scene['name']}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(scene, fh, indent=1)
        obj = scene["layers"][1]["objects"][0]
        print(f"  {path:44s} {len(obj['subpaths']):3d} strokes  "
              f"{obj['length']:7.1f} units  {len(obj['d']):6d} chars")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
