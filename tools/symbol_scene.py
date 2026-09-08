"""A symbol outline -> a scene package that transforms it.

The companion to `writing_scene.py`. Where that one turns handwriting into
words that write themselves, this takes a symbol — an outline traced from the
artist's mark — and emits a scene in which the mark draws itself, turns,
breathes and settles.

    tools/symbol_scene.py assets/svg-source/signart02.svg --name eagle \\
        --out poc/scenes/eagle.json

Two things it has to do for the device's player:

* **Simplify.** A traced outline arrives with a couple of thousand points; at
  sub-pixel tolerance a couple of hundred carry the same shape.
* **Chunk.** The player holds a bounded number of segments per stroke, so a
  long outline travels as consecutive runs that share endpoints. `progress`
  draws them in order, because subpaths are already sequenced as one
  trajectory — so a chunked outline still reads as one continuous line.

The mark is *stroked*, not filled: a solid silhouette cannot draw itself.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mementum_node.core.geometry import flatten_path, polyline_length  # noqa: E402

#: Contours smaller than this are tracing dust.
MIN_AREA = 100.0
#: Simplification tolerance, in source units. Sub-pixel once scaled down.
TOLERANCE = 0.8
#: Segments per chunk, inside the player's per-stroke bound.
CHUNK = 44


def _area(contour) -> float:
    total = 0.0
    for i in range(len(contour)):
        x0, y0 = contour[i]
        x1, y1 = contour[(i + 1) % len(contour)]
        total += x0 * y1 - x1 * y0
    return abs(total) / 2


def simplify(points, tolerance: float = TOLERANCE):
    if len(points) < 3:
        return list(points)
    a, b = points[0], points[-1]
    dx, dy = b[0] - a[0], b[1] - a[1]
    span = math.hypot(dx, dy)
    worst, index = -1.0, 0
    for i in range(1, len(points) - 1):
        p = points[i]
        d = (abs(dy * p[0] - dx * p[1] + b[0] * a[1] - b[1] * a[0]) / span
             if span > 1e-9 else math.dist(p, a))
        if d > worst:
            worst, index = d, i
    if worst > tolerance:
        return simplify(points[: index + 1], tolerance)[:-1] + simplify(points[index:], tolerance)
    return [a, b]


def read_contours(svg: str, min_area: float = MIN_AREA):
    """Every contour worth drawing, largest first."""
    contours = []
    for _, d in re.findall(r"<path([^>]*?)\sd=\"([^\"]*)\"", svg, re.S):
        for sub in flatten_path(d):
            if len(sub) > 4 and _area(sub) >= min_area:
                contours.append(sub)
    return sorted(contours, key=_area, reverse=True)


def compact_path(chunks, quantum: float = 0.5) -> str:
    def n(v):
        return "%g" % (round(v / quantum) * quantum)

    parts, cx, cy = [], 0.0, 0.0
    for chunk in chunks:
        px, py = round(chunk[0][0] / quantum) * quantum, round(chunk[0][1] / quantum) * quantum
        parts.append("m%s %s" % (n(px - cx), n(py - cy)))
        cx, cy = px, py
        segment = []
        for x, y in chunk[1:]:
            qx, qy = round(x / quantum) * quantum, round(y / quantum) * quantum
            segment.append("%s %s" % (n(qx - cx), n(qy - cy)))
            cx, cy = qx, qy
        if segment:
            parts.append("l" + " ".join(segment))
    return "".join(parts).replace(" -", "-")


def build_scene(svg: str, name: str, width: int, height: int, scene_id: int,
                stroke: str, background: str, stroke_width: float,
                draw_ms: int, hold_ms: int) -> dict:
    contours = read_contours(svg)
    if not contours:
        raise ValueError("no contours large enough to draw")

    closed = [simplify(c) + [c[0]] for c in contours]
    xs = [p[0] for c in closed for p in c]
    ys = [p[1] for c in closed for p in c]
    scale = min(width * 0.78 / (max(xs) - min(xs)), height * 0.82 / (max(ys) - min(ys)))
    ox = (width - (max(xs) - min(xs)) * scale) / 2
    oy = (height - (max(ys) - min(ys)) * scale) / 2

    chunks = []
    for contour in closed:                       # largest first: shape, then detail
        placed = [((x - min(xs)) * scale + ox, (y - min(ys)) * scale + oy) for x, y in contour]
        chunks += [placed[i:i + CHUNK + 1] for i in range(0, len(placed) - 1, CHUNK)]

    data = compact_path(chunks)
    lengths = [polyline_length(s) for s in flatten_path(data)]
    settle = draw_ms + 200

    return {
        "version": 1, "id": scene_id, "name": name,
        "width": width, "height": height, "fit": "contain",
        "duration": draw_ms + hold_ms + 2800,
        "layers": [
            {"id": "background", "z": 0, "objects": [
                {"type": "rect", "id": "bg", "x": 0, "y": 0, "w": width, "h": height,
                 "fill": background}]},
            {"id": "symbol", "z": 10, "objects": [
                {"type": "path", "id": "mark", "d": data,
                 "length": round(sum(lengths), 3),
                 "subpaths": [round(v, 3) for v in lengths],
                 "stroke": stroke, "stroke_width": stroke_width, "progress": 0,
                 "deform": {"type": "helix", "amplitude": 0, "sway": 0,
                            "wavelength": 150, "phase": 0, "focal": 420}}]}],
        "animations": [
            {"target": "mark", "property": "progress", "start": 0,
             "duration": draw_ms, "from": 0, "to": 1, "easing": "ease-in-out"},
            {"target": "mark", "property": "deform.amplitude", "start": settle,
             "duration": 1600, "from": 0, "to": 22, "easing": "ease-in-out"},
            {"target": "mark", "property": "deform.sway", "start": settle,
             "duration": 1600, "from": 0, "to": 5, "easing": "ease-in-out"},
            {"target": "mark", "property": "deform.phase", "start": settle,
             "duration": hold_ms + 1600, "from": 0, "to": 5, "easing": "linear"},
            {"target": "mark", "property": "transform.scale", "start": settle + 2000,
             "duration": 2400, "from": 1.0, "to": 1.12, "easing": "ease-in-out"},
            {"target": "mark", "property": "deform.amplitude", "start": draw_ms + hold_ms,
             "duration": 1800, "from": 22, "to": 0, "easing": "ease-in-out"},
            {"target": "mark", "property": "deform.sway", "start": draw_ms + hold_ms,
             "duration": 1800, "from": 5, "to": 0, "easing": "ease-in-out"},
            {"target": "mark", "property": "transform.scale", "start": draw_ms + hold_ms,
             "duration": 1800, "from": 1.12, "to": 1.0, "easing": "ease-in-out"},
            {"target": "mark", "property": "opacity", "start": draw_ms + hold_ms + 2000,
             "duration": 800, "from": 1, "to": 0, "easing": "linear"}],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="symbol outline -> a scene that transforms it")
    parser.add_argument("source")
    parser.add_argument("--name", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--id", type=int, default=70)
    parser.add_argument("--width", type=int, default=450)
    parser.add_argument("--height", type=int, default=250)
    parser.add_argument("--stroke", default="#7fe3c0")
    parser.add_argument("--background", default="#0b1016")
    parser.add_argument("--stroke-width", type=float, default=2.2)
    parser.add_argument("--draw-ms", type=int, default=3000)
    parser.add_argument("--hold-ms", type=int, default=5000)
    args = parser.parse_args(argv)

    with open(args.source, encoding="utf-8") as fh:
        scene = build_scene(fh.read(), args.name, args.width, args.height, args.id,
                            args.stroke, args.background, args.stroke_width,
                            args.draw_ms, args.hold_ms)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(scene, fh, indent=1)
    obj = scene["layers"][1]["objects"][0]
    print(f"  {args.out:34s} {len(obj['subpaths']):3d} chunks  "
          f"{obj['length']:7.0f} units  {len(obj['d']):6d} chars")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
