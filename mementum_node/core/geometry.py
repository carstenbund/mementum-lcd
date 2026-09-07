"""Path geometry: parse, flatten, measure, trim (proposal §7, plan 0.3 step 3).

Two things matter here beyond drawing.

*Determinism.* Flattening uses a fixed subdivision rule derived from the control
polygon length, never an adaptive tolerance that could differ between machines.
Two nodes must produce identical buffers, so the geometry has to be identical
first.

*Stroke progress (risk R1).* ``progress`` is expressed here as arc-length
trimming of the flattened polyline -- the same semantics as the dash-pattern
reveal the ESP32 player will attempt through LVGL/ThorVG
(``dasharray = [len*p, len]``). If that API turns out not to exist and the
fallback is compile-time path splitting, the *semantics* below are what the
split must reproduce, and this module is where the reference lives.

The supported ``d`` subset is M, L, H, V, C, Q, Z in both absolute and relative
forms. Arcs and smooth shorthands are deliberately absent (§25).
"""

from __future__ import annotations

import math
import re

__all__ = ["Subpath", "flatten_path", "parse_path", "polyline_length", "trim_polyline"]

Point = tuple[float, float]
Subpath = list[Point]

_TOKEN = re.compile(r"[MmLlHhVvCcQqZz]|[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?")

#: Flattening: one segment per this many units of control-polygon length,
#: clamped to [_MIN_SEG, _MAX_SEG]. Fixed, so the result is reproducible.
_UNITS_PER_SEGMENT = 3.0
_MIN_SEG = 6
_MAX_SEG = 64


def _dist(a: Point, b: Point) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def _segments_for(points: list[Point]) -> int:
    control = sum(_dist(points[i], points[i + 1]) for i in range(len(points) - 1))
    return max(_MIN_SEG, min(_MAX_SEG, int(control / _UNITS_PER_SEGMENT) + 1))


def _cubic(p0: Point, p1: Point, p2: Point, p3: Point) -> list[Point]:
    n = _segments_for([p0, p1, p2, p3])
    out = []
    for i in range(1, n + 1):
        t = i / n
        u = 1.0 - t
        a, b, c, d = u * u * u, 3 * u * u * t, 3 * u * t * t, t * t * t
        out.append(
            (
                a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0],
                a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1],
            )
        )
    return out


def _quadratic(p0: Point, p1: Point, p2: Point) -> list[Point]:
    n = _segments_for([p0, p1, p2])
    out = []
    for i in range(1, n + 1):
        t = i / n
        u = 1.0 - t
        a, b, c = u * u, 2 * u * t, t * t
        out.append(
            (a * p0[0] + b * p1[0] + c * p2[0], a * p0[1] + b * p1[1] + c * p2[1])
        )
    return out


def parse_path(d: str) -> list[tuple[str, list[float]]]:
    """Tokenise an SVG ``d`` attribute into (command, numbers) pairs."""
    tokens = _TOKEN.findall(d)
    out: list[tuple[str, list[float]]] = []
    cmd, args = None, []
    for tok in tokens:
        if tok[0].isalpha():
            if cmd is not None:
                out.append((cmd, args))
            cmd, args = tok, []
        else:
            if cmd is None:
                raise ValueError("path data must start with a command")
            args.append(float(tok))
    if cmd is not None:
        out.append((cmd, args))
    return out


def flatten_path(d: str) -> list[Subpath]:
    """Flatten ``d`` into polylines, one per subpath. Deterministic."""
    subpaths: list[Subpath] = []
    current: Subpath = []
    cursor: Point = (0.0, 0.0)
    start: Point = (0.0, 0.0)

    def flush() -> None:
        nonlocal current
        if len(current) > 1:
            subpaths.append(current)
        current = []

    for cmd, args in parse_path(d):
        rel = cmd.islower()
        op = cmd.upper()
        if op == "M":
            if len(args) < 2 or len(args) % 2:
                raise ValueError("M expects pairs of coordinates")
            flush()
            for i in range(0, len(args), 2):
                pt = (args[i], args[i + 1])
                if rel:
                    pt = (cursor[0] + pt[0], cursor[1] + pt[1])
                if i == 0:
                    current = [pt]
                    start = pt
                else:
                    current.append(pt)
                cursor = pt
        elif op in ("L", "H", "V"):
            step = {"L": 2, "H": 1, "V": 1}[op]
            if not args or len(args) % step:
                raise ValueError(f"{op} expects {step} argument(s) per point")
            for i in range(0, len(args), step):
                if op == "L":
                    pt = (args[i], args[i + 1])
                    if rel:
                        pt = (cursor[0] + pt[0], cursor[1] + pt[1])
                elif op == "H":
                    x = cursor[0] + args[i] if rel else args[i]
                    pt = (x, cursor[1])
                else:
                    y = cursor[1] + args[i] if rel else args[i]
                    pt = (cursor[0], y)
                current.append(pt)
                cursor = pt
        elif op == "C":
            if not args or len(args) % 6:
                raise ValueError("C expects 6 arguments per segment")
            for i in range(0, len(args), 6):
                pts = [(args[i + j], args[i + j + 1]) for j in (0, 2, 4)]
                if rel:
                    pts = [(cursor[0] + x, cursor[1] + y) for x, y in pts]
                current.extend(_cubic(cursor, pts[0], pts[1], pts[2]))
                cursor = pts[2]
        elif op == "Q":
            if not args or len(args) % 4:
                raise ValueError("Q expects 4 arguments per segment")
            for i in range(0, len(args), 4):
                pts = [(args[i + j], args[i + j + 1]) for j in (0, 2)]
                if rel:
                    pts = [(cursor[0] + x, cursor[1] + y) for x, y in pts]
                current.extend(_quadratic(cursor, pts[0], pts[1]))
                cursor = pts[1]
        elif op == "Z":
            if current:
                current.append(start)
                cursor = start
                flush()
        else:  # pragma: no cover - guarded by the tokeniser
            raise ValueError(f"unsupported path command: {cmd!r}")
    flush()
    return subpaths


def polyline_length(points: Subpath) -> float:
    return sum(_dist(points[i], points[i + 1]) for i in range(len(points) - 1))


def trim_polyline(points: Subpath, progress: float) -> Subpath:
    """Return the leading ``progress`` fraction (0..1) of a polyline by arc
    length, interpolating inside the segment where the cut falls."""
    if progress >= 1.0:
        return list(points)
    if progress <= 0.0 or len(points) < 2:
        return []
    total = polyline_length(points)
    if total <= 0.0:
        return []
    target = total * progress
    out = [points[0]]
    walked = 0.0
    for i in range(len(points) - 1):
        a, b = points[i], points[i + 1]
        seg = _dist(a, b)
        if seg <= 0.0:
            continue
        if walked + seg >= target:
            t = (target - walked) / seg
            out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
            return out
        walked += seg
        out.append(b)
    return out
