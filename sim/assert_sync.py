"""Buffer comparison across nodes -- the assertion the architecture rests on.

    Two nodes rendering the same scene at the same sceneTime must produce
    identical buffers.

That is the property the whole design rests on, and it is far easier to assert
on a buffer than to measure on a panel (§3.3). Between two instances of the
same renderer the comparison is exact; between *different* renderers (this
against LVGL/ThorVG on the device) it needs a perceptual tolerance, because
antialiasing and text metrics legitimately differ -- which is itself the
measurement that answers proposal open question 7, and a Phase 1 concern.

Skew is the other half. Capturing every node at one wall-clock instant and
diffing turns "who is behind, and by how much" into a picture rather than a
number -- the in-simulation counterpart of the GPIO frame markers (§0.4).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from mementum_node.core.framebuffer import Frame

__all__ = [
    "FrameDiff",
    "InkReport",
    "SkewReport",
    "assert_identical_at",
    "assert_looks_the_same",
    "diff_frames",
    "diff_image",
    "hashes_at",
    "ink",
    "looks_the_same",
    "skew_report",
]

#: Proposal §10 / plan 0.7. Simulated skew is a design property; the same
#: numbers measured on hardware are the physical ones that satisfy the gate.
SKEW_TARGET_MS = 20.0
SKEW_HARD_MS = 35.0


@dataclass(frozen=True)
class FrameDiff:
    width: int
    height: int
    differing_pixels: int
    max_channel_delta: int

    @property
    def total_pixels(self) -> int:
        return self.width * self.height

    @property
    def identical(self) -> bool:
        return self.differing_pixels == 0

    @property
    def fraction(self) -> float:
        return self.differing_pixels / self.total_pixels if self.total_pixels else 0.0

    def __str__(self) -> str:
        if self.identical:
            return f"identical ({self.width}x{self.height})"
        return (
            f"{self.differing_pixels}/{self.total_pixels} pixels differ "
            f"({self.fraction * 100:.3f}%), max channel delta {self.max_channel_delta}"
        )


def diff_frames(a: Frame, b: Frame) -> FrameDiff:
    if (a.width, a.height) != (b.width, b.height):
        raise ValueError(
            f"frame sizes differ: {a.width}x{a.height} vs {b.width}x{b.height}"
        )
    if a.data == b.data:
        return FrameDiff(a.width, a.height, 0, 0)
    differing = 0
    worst = 0
    da, db = a.data, b.data
    for i in range(0, len(da), 4):
        if da[i : i + 4] == db[i : i + 4]:
            continue
        differing += 1
        for c in range(4):
            delta = abs(da[i + c] - db[i + c])
            if delta > worst:
                worst = delta
    return FrameDiff(a.width, a.height, differing, worst)


def diff_image(a: Frame, b: Frame, highlight: tuple[int, int, int] = (255, 40, 40)) -> Frame:
    """A picture of the difference: matching pixels dimmed, differences marked."""
    out = Frame(a.width, a.height)
    da, db, do = a.data, b.data, out.data
    for i in range(0, len(da), 4):
        if da[i : i + 4] == db[i : i + 4]:
            do[i] = da[i] // 4
            do[i + 1] = da[i + 1] // 4
            do[i + 2] = da[i + 2] // 4
            do[i + 3] = 255
        else:
            do[i], do[i + 1], do[i + 2], do[i + 3] = (*highlight, 255)
    return out


def hashes_at(nodes: Sequence, scene_time: float) -> dict[str, str]:
    """Composite every node at one scene time and hash the results.

    This is the simulator's form of the device-side frame hash (§3.6): the same
    check, on the same kind of buffer, at almost no cost."""
    return {node.node_id: node.compose(scene_time).hash() for node in nodes}


def assert_identical_at(nodes: Sequence, scene_time: float) -> str:
    """Assert every node composites the same buffer at ``scene_time``.

    Returns the shared frame hash. Raises ``AssertionError`` naming the first
    node that disagrees and by how much, because "they differ" is not a useful
    thing to read in CI."""
    if len(nodes) < 2:
        raise ValueError("comparing buffers needs at least two nodes")
    reference_node = nodes[0]
    reference = reference_node.compose(scene_time)
    for node in nodes[1:]:
        other = node.compose(scene_time)
        if other.data == reference.data:
            continue
        report = diff_frames(reference, other)
        raise AssertionError(
            f"buffers differ at sceneTime={scene_time:.1f}ms: "
            f"{reference_node.node_id} vs {node.node_id}: {report}"
        )
    return reference.hash()


@dataclass(frozen=True)
class SkewReport:
    """Scene-time skew between nodes, sampled at one instant of virtual time."""

    scene_times: dict[str, float]
    reference: str

    @property
    def deltas(self) -> dict[str, float]:
        if not self.scene_times:
            return {}
        base = self.scene_times[self.reference]
        return {node_id: t - base for node_id, t in self.scene_times.items()}

    @property
    def max_skew_ms(self) -> float:
        if not self.scene_times:
            return 0.0
        values = list(self.scene_times.values())
        return max(values) - min(values)

    @property
    def within_target(self) -> bool:
        return self.max_skew_ms <= SKEW_TARGET_MS

    @property
    def within_hard_bound(self) -> bool:
        return self.max_skew_ms <= SKEW_HARD_MS

    def __str__(self) -> str:
        if not self.scene_times:
            return "no node is playing; no skew to report"
        verdict = (
            "within target"
            if self.within_target
            else ("within hard bound" if self.within_hard_bound else "OVER BUDGET")
        )
        return (
            f"max skew {self.max_skew_ms:.2f} ms across {len(self.scene_times)} nodes "
            f"({verdict}; target {SKEW_TARGET_MS:.0f} ms, hard {SKEW_HARD_MS:.0f} ms)"
        )


def skew_report(nodes: Iterable) -> SkewReport:
    """Sample every node's scene time at this instant. A node that is not
    playing is excluded -- it has no position to be skewed from."""
    times = {}
    for node in nodes:
        scene_time = node.scene_time
        if scene_time is not None:
            times[node.node_id] = scene_time
    reference = next(iter(times), "")
    return SkewReport(times, reference)


# -- comparing *different* renderers ---------------------------------------
#
# Exact equality is available only between two instances of the same renderer.
# Across renderers -- the Python reference against C/LVGL/ThorVG -- antialiasing
# and glyph shapes legitimately differ, and per-pixel comparison says nothing
# useful. What matters is whether it is still the same picture, which is a
# question about where the ink is, not about which pixels carry it.
#
# The thresholds below are deliberately loose. This is handwriting that appears
# and is gone in a few seconds; the standard is whether someone watching would
# notice, not whether a difference is detectable.

#: How much total ink may differ, as a fraction.
INK_TOLERANCE = 0.05
#: How far the centre of the ink may move, in pixels.
CENTROID_TOLERANCE = 1.0


@dataclass(frozen=True)
class InkReport:
    """Where the drawn stuff is: how much, and centred where."""

    mass: float
    centroid_x: float
    centroid_y: float

    def __str__(self) -> str:
        return (
            f"ink {self.mass / 1000:.1f}k at ({self.centroid_x:.2f}, {self.centroid_y:.2f})"
        )


def ink(frame: Frame, background: tuple[int, int, int, int] | None = None) -> InkReport:
    """Total luminance above the background, and its centre of mass.

    ``background`` defaults to the frame's top-left pixel, which is the
    background in every scene we draw. Cheap, and good enough for a comparison
    whose thresholds are measured in whole pixels.
    """
    if background is None:
        background = frame.get(0, 0)
    base = (background[0] * 299 + background[1] * 587 + background[2] * 114) // 1000

    total = cx = cy = 0.0
    data = frame.data
    for y in range(frame.height):
        row = y * frame.width
        for x in range(frame.width):
            i = (row + x) * 4
            value = (data[i] * 299 + data[i + 1] * 587 + data[i + 2] * 114) // 1000 - base
            if value > 8:
                total += value
                cx += x * value
                cy += y * value
    if total <= 0:
        return InkReport(0.0, 0.0, 0.0)
    return InkReport(total, cx / total, cy / total)


def looks_the_same(
    a: Frame,
    b: Frame,
    ink_tolerance: float = INK_TOLERANCE,
    centroid_tolerance: float = CENTROID_TOLERANCE,
) -> tuple[bool, str]:
    """Are these two frames the same picture, drawn by different renderers?"""
    ink_a, ink_b = ink(a), ink(b)
    if ink_a.mass <= 0.0 and ink_b.mass <= 0.0:
        return True, "both frames are empty"
    if ink_a.mass <= 0.0 or ink_b.mass <= 0.0:
        return False, f"one frame is empty: {ink_a} vs {ink_b}"

    mass_delta = abs(ink_a.mass - ink_b.mass) / max(ink_a.mass, ink_b.mass)
    centroid_delta = max(
        abs(ink_a.centroid_x - ink_b.centroid_x), abs(ink_a.centroid_y - ink_b.centroid_y)
    )
    detail = (
        f"ink {mass_delta * 100:.2f}% apart, centroid {centroid_delta:.2f} px apart "
        f"({ink_a} vs {ink_b})"
    )
    return (mass_delta <= ink_tolerance and centroid_delta <= centroid_tolerance), detail


def assert_looks_the_same(a: Frame, b: Frame, context: str = "") -> str:
    same, detail = looks_the_same(a, b)
    if not same:
        raise AssertionError(f"frames are not the same picture{f' ({context})' if context else ''}: {detail}")
    return detail
