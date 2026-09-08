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

__all__ = [
    "DEFORM_SAMPLE_STEP",
    "HELIX_BANDS",
    "HELIX_FOCAL",
    "Subpath",
    "band_of",
    "band_depth",
    "deform_helix",
    "deform_sine",
    "perspective_scale",
    "flatten_path",
    "parse_path",
    "polyline_length",
    "normal_offsets",
    "resample_polyline",
    "nearest_arc_position",
    "ripple_offsets",
    "trim_polyline",
]

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


# -- deformation ----------------------------------------------------------
#
# A deformation is Mementum's contribution to an authored symbol: SVG gives the
# geometry, and the timeline moves it. The vocabulary is deliberately small and
# named -- `sine` first -- because a general expression language here would be a
# graphics language, which is on the refusal list.
#
# Both players must sample the path identically or the wave differs in shape,
# so the sampling rule is part of the contract rather than an implementation
# detail: **uniform steps of 2.0 design units along the undeformed arc length,
# always including the final point.**

#: Design units between deformation samples. Changing this changes every wave.
DEFORM_SAMPLE_STEP = 2.0


def resample_polyline(points: Subpath, step: float = DEFORM_SAMPLE_STEP) -> list[tuple[Point, float]]:
    """Uniform samples along a polyline as (point, distance-from-start).

    The last sample is always the polyline's end, so a deformation reaches the
    end of the stroke rather than stopping a fraction short of it.
    """
    total = polyline_length(points)
    if total <= 0.0 or len(points) < 2:
        return [(points[0], 0.0)] if points else []

    count = max(2, int(math.ceil(total / step)) + 1)
    out: list[tuple[Point, float]] = []
    index = 0
    walked = 0.0
    seg_length = _dist(points[0], points[1])

    for i in range(count):
        target = total * i / (count - 1)
        while index < len(points) - 2 and walked + seg_length < target:
            walked += seg_length
            index += 1
            seg_length = _dist(points[index], points[index + 1])
        a, b = points[index], points[index + 1]
        t = 0.0 if seg_length <= 0.0 else (target - walked) / seg_length
        out.append(((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t), target))
    return out


def deform_sine(
    samples: list[tuple[Point, float]],
    amplitude: float,
    wavelength: float,
    phase: float,
) -> Subpath:
    """Offset each sample perpendicular to the path by a travelling sine.

        offset = amplitude * sin(2*pi * (distance / wavelength + phase))

    ``phase`` is in cycles, and it is animated linearly rather than looped: a
    loop construct would need an iteration counter, and a counter in the render
    path breaks late join. Taking the phase modulo a cycle happens here, in the
    sine, so periodic motion stays a pure function of ``sceneTime``.
    """
    if not samples:
        return []
    if wavelength <= 0.0:
        return [point for point, _ in samples]

    out: Subpath = []
    for i, (point, distance) in enumerate(samples):
        previous = samples[max(0, i - 1)][0]
        following = samples[min(len(samples) - 1, i + 1)][0]
        dx, dy = following[0] - previous[0], following[1] - previous[1]
        length = math.hypot(dx, dy)
        if length <= 1e-9:
            out.append(point)
            continue
        nx, ny = -dy / length, dx / length
        offset = amplitude * math.sin(2.0 * math.pi * (distance / wavelength + phase))
        out.append((point[0] + nx * offset, point[1] + ny * offset))
    return out


# -- helix ----------------------------------------------------------------
#
# The same travelling wave, but a quarter cycle apart in two directions: the
# in-plane offset the sine already applies, and an equal offset in *depth*. The
# stroke then reads as a ribbon turning in space rather than a line wobbling on
# glass.
#
# There is no 3D pipeline behind this and there should not be. Each sample gets
# a `z`, one perspective divide projects it back onto the design canvas, and the
# output is the same strokes as everything else. What sells the depth is not the
# projection but what rides on it: nearer parts of the stroke are drawn thicker
# and brighter.
#
# Both players must band the stroke identically or the two look different, so
# the depth factor is analytic -- derived from the amplitude and focal length
# rather than measured per frame.

#: Distance from the eye to the design canvas, in design units.
HELIX_FOCAL = 520.0

#: Depth bands. A stroke is drawn once per band, far to near, because a stroke
#: width is a property of a path and not of a point -- on the device as here.
HELIX_BANDS = 8

#: How much darker the farthest band is than the nearest.
HELIX_SHADE_FAR = 0.45


def perspective_scale(z: float, focal: float = HELIX_FOCAL) -> float:
    """Projection factor for a sample at depth ``z``. Positive z is nearer."""
    denominator = focal - z
    if denominator <= 1e-6:
        return 1.0
    return focal / denominator


def band_depth(band: int, bands: int = HELIX_BANDS) -> float:
    """The representative depth factor of a band, 0 (far) to 1 (near)."""
    return (band + 0.5) / bands


def band_of(t: float, bands: int = HELIX_BANDS) -> int:
    index = int(t * bands)
    return 0 if index < 0 else (bands - 1 if index >= bands else index)


def normal_offsets(samples: list[tuple[Point, float]], offsets: list[float]) -> Subpath:
    """Displace each sample perpendicular to the path by its own offset.

    The shared step behind every in-plane deformation: a sine, a ripple, or
    both added together before anything is drawn."""
    out: Subpath = []
    for i, ((point, _), offset) in enumerate(zip(samples, offsets)):
        previous = samples[max(0, i - 1)][0]
        following = samples[min(len(samples) - 1, i + 1)][0]
        dx, dy = following[0] - previous[0], following[1] - previous[1]
        length = math.hypot(dx, dy)
        if length <= 1e-9 or offset == 0.0:
            out.append(point)
            continue
        out.append((point[0] - dy / length * offset, point[1] + dx / length * offset))
    return out


def ripple_offsets(
    samples: list[tuple[Point, float]], ripples, scene_time: float, offset: float = 0.0
) -> list[float]:
    """Total in-plane offset from every live ripple, per sample.

    ``offset`` is how far along the whole path this subpath starts, so a ripple
    is positioned on the pen's trajectory rather than within one stroke."""
    return [
        sum(ripple.offset(offset + distance, scene_time) for ripple in ripples)
        for _, distance in samples
    ]


def deform_helix(
    samples: list[tuple[Point, float]],
    amplitude: float,
    wavelength: float,
    phase: float,
    centre: Point,
    focal: float = HELIX_FOCAL,
    sway: float | None = None,
    extra: list[float] | None = None,
) -> list[tuple[Point, float]]:
    """Project a helical deformation. Returns [(point, depth factor 0..1)].

    ``amplitude`` moves the stroke *into* the picture and ``sway`` moves it
    *across*. Only the second can fold — an inward offset larger than the local
    radius of curvature makes the curve cross itself — so they are separate
    numbers rather than one.

    ``centre`` is the design canvas centre: the vanishing point, so an object's
    position decides how much perspective it gets, as it should.
    """
    if sway is None:
        sway = amplitude * 0.4
    if not samples:
        return []
    if wavelength <= 0.0 or amplitude == 0.0:
        return [(point, 1.0) for point, _ in samples]

    near = perspective_scale(abs(amplitude), focal)
    far = perspective_scale(-abs(amplitude), focal)
    span = near - far

    out: list[tuple[Point, float]] = []
    for i, (point, distance) in enumerate(samples):
        previous = samples[max(0, i - 1)][0]
        following = samples[min(len(samples) - 1, i + 1)][0]
        dx, dy = following[0] - previous[0], following[1] - previous[1]
        length = math.hypot(dx, dy)
        theta = 2.0 * math.pi * (distance / wavelength + phase)

        x, y = point
        offset = sway * math.sin(theta) + (extra[i] if extra is not None else 0.0)
        if length > 1e-9 and offset != 0.0:
            nx, ny = -dy / length, dx / length
            x += nx * offset
            y += ny * offset
        z = amplitude * math.cos(theta)

        k = perspective_scale(z, focal)
        out.append((
            (centre[0] + (x - centre[0]) * k, centre[1] + (y - centre[1]) * k),
            1.0 if span <= 1e-9 else (k - far) / span,
        ))
    return out


def nearest_arc_position(scene, x: float, y: float, max_distance: float = 60.0):
    """The arc position of the stroke nearest a point on the design canvas.

    A touch lands on a canvas but a ripple travels along a line, so the finger
    has to be mapped onto the stroke first. Returns ``None`` when nothing is
    near enough to have been touched, which is what a tap on empty background
    is.
    """
    best = None
    best_distance = max_distance * max_distance
    for layer in scene.layers:
        for obj in layer.objects:
            if obj.type != "path" or not obj.visible:
                continue
            # Cumulative along the whole path, not restarted per stroke: a
            # ripple travels one pen trajectory, exactly as `progress` reveals
            # one. Measuring per subpath would fire the disturbance at the same
            # local distance into every stroke at once.
            walked = 0.0
            for subpath in flatten_path(obj.props["d"]):
                for point, distance in resample_polyline(subpath, 6.0):
                    delta = (point[0] - x) ** 2 + (point[1] - y) ** 2
                    if delta < best_distance:
                        best_distance = delta
                        best = walked + distance
                walked += polyline_length(subpath)
    return best
