"""A small deterministic software rasteriser.

This is the reference renderer's rasteriser, not a general graphics library. It
exists to make one assertion possible: *two nodes rendering the same scene at
the same sceneTime produce identical buffers* (plan §3.3). Everything about it
is therefore chosen for reproducibility over speed or beauty --

* fixed 4x vertical supersampling with exact horizontal span coverage, so
  antialiasing is a pure function of the geometry;
* no floating-point accumulation across shapes: coverage is combined per
  subsample row with ``max``, which also removes seams where a stroke's
  segment quads and round joins overlap;
* polygons only. Curves are flattened in :mod:`.geometry` first.

Cross-renderer comparison (this against LVGL/ThorVG) needs a perceptual
tolerance and is a Phase 1 conformance question; comparison between two
instances of *this* renderer is exact.
"""

from __future__ import annotations

import math

from .framebuffer import Frame, blend_pixel

__all__ = ["SAMPLES", "circle", "fill_polygons", "stroke_polyline"]

#: Vertical subsamples per pixel row. Changing this changes every golden frame.
SAMPLES = 4

Point = tuple[float, float]
Polygon = list[Point]

#: Vertices used to approximate a round join or cap. Fixed for determinism.
_JOIN_VERTICES = 12


def circle(centre: Point, radius: float, vertices: int = _JOIN_VERTICES) -> Polygon:
    cx, cy = centre
    return [
        (
            cx + radius * math.cos(2.0 * math.pi * i / vertices),
            cy + radius * math.sin(2.0 * math.pi * i / vertices),
        )
        for i in range(vertices)
    ]


def stroke_polyline(points: list[Point], width: float) -> list[Polygon]:
    """Convert a polyline into filled polygons: one quad per segment plus round
    joins and caps. Overlap is harmless -- coverage is combined with ``max``."""
    if len(points) < 2 or width <= 0.0:
        if len(points) == 1 and width > 0.0:
            return [circle(points[0], width / 2.0)]
        return []
    half = width / 2.0
    polys: list[Polygon] = []
    for i in range(len(points) - 1):
        (x0, y0), (x1, y1) = points[i], points[i + 1]
        dx, dy = x1 - x0, y1 - y0
        length = math.hypot(dx, dy)
        if length <= 1e-9:
            continue
        nx, ny = -dy / length * half, dx / length * half
        polys.append(
            [(x0 + nx, y0 + ny), (x1 + nx, y1 + ny), (x1 - nx, y1 - ny), (x0 - nx, y0 - ny)]
        )
    for pt in points:
        polys.append(circle(pt, half))
    return polys


def _bounds(polys: list[Polygon]) -> tuple[float, float, float, float]:
    xs_min = ys_min = float("inf")
    xs_max = ys_max = float("-inf")
    for poly in polys:
        for x, y in poly:
            if x < xs_min:
                xs_min = x
            if x > xs_max:
                xs_max = x
            if y < ys_min:
                ys_min = y
            if y > ys_max:
                ys_max = y
    return xs_min, ys_min, xs_max, ys_max


def _edges(poly: Polygon) -> list[tuple[float, float, float, float]]:
    out = []
    n = len(poly)
    for i in range(n):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % n]
        if y0 != y1:
            out.append((x0, y0, x1, y1))
    return out


def fill_polygons(
    frame: Frame,
    polys: list[Polygon],
    rgb: tuple[int, int, int],
    alpha: float = 1.0,
    samples: int = SAMPLES,
) -> None:
    """Fill the union of ``polys`` into ``frame`` with source-over blending."""
    if not polys or alpha <= 0.0:
        return
    min_x, min_y, max_x, max_y = _bounds(polys)
    x0 = max(0, int(math.floor(min_x)))
    x1 = min(frame.width, int(math.ceil(max_x)) + 1)
    y0 = max(0, int(math.floor(min_y)))
    y1 = min(frame.height, int(math.ceil(max_y)) + 1)
    if x1 <= x0 or y1 <= y0:
        return

    prepared = []
    for poly in polys:
        edges = _edges(poly)
        if not edges:
            continue
        ys = [p[1] for p in poly]
        prepared.append((min(ys), max(ys), edges))
    if not prepared:
        return

    inv_samples = 1.0 / samples
    stride = frame.width * 4
    for py in range(y0, y1):
        acc: dict[int, float] = {}
        for s in range(samples):
            sy = py + (s + 0.5) * inv_samples
            row: dict[int, float] = {}
            for poly_min_y, poly_max_y, edges in prepared:
                if sy < poly_min_y or sy >= poly_max_y:
                    continue
                crossings = []
                for ex0, ey0, ex1, ey1 in edges:
                    if (ey0 <= sy < ey1) or (ey1 <= sy < ey0):
                        crossings.append(ex0 + (sy - ey0) * (ex1 - ex0) / (ey1 - ey0))
                if len(crossings) < 2:
                    continue
                crossings.sort()
                for i in range(0, len(crossings) - 1, 2):
                    xa = max(float(x0), crossings[i])
                    xb = min(float(x1), crossings[i + 1])
                    if xb <= xa:
                        continue
                    ia, ib = int(math.floor(xa)), int(math.floor(xb))
                    if ia == ib:
                        cov = xb - xa
                        if cov > row.get(ia, 0.0):
                            row[ia] = cov
                    else:
                        cov = ia + 1.0 - xa
                        if cov > row.get(ia, 0.0):
                            row[ia] = cov
                        for px in range(ia + 1, ib):
                            row[px] = 1.0
                        if ib < x1:
                            cov = xb - ib
                            if cov > row.get(ib, 0.0):
                                row[ib] = cov
            for px, cov in row.items():
                acc[px] = acc.get(px, 0.0) + cov * inv_samples

        base = py * stride
        for px, cov in acc.items():
            if cov <= 0.0:
                continue
            blend_pixel(frame.data, base + px * 4, rgb, min(1.0, cov) * alpha)
