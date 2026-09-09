"""The helix deformation, in both players.

A travelling wave a quarter cycle apart in-plane and in depth, projected back
onto the design canvas. There is no 3D pipeline behind it — one `z` per sample
and one perspective divide — and what sells the depth is that nearer parts of
the stroke are drawn thicker and brighter.

The banding is what needs pinning: a stroke width belongs to a path rather than
to a point, so both players express depth by drawing the stroke once per band,
and they must band it identically or the ribbons disagree.
"""

import json
import math
import os

import pytest

from mementum_node.core.geometry import (
    HELIX_BANDS,
    HELIX_FOCAL,
    band_depth,
    band_of,
    deform_helix,
    flatten_path,
    perspective_scale,
    resample_polyline,
)
from mementum_node.core.render_backend import ReferenceRenderer
from mementum_node.core.scene import load_scene, parse_scene
from mementum_node.players.lvgl import LvglPlayer, LvglPlayerError, is_available
from sim.assert_sync import looks_the_same

from .conftest_helpers import SCENE_PATH, objects_of

SCENE = os.path.join(os.path.dirname(SCENE_PATH), "loop-helix.json")
PHASES = (0.0, 0.15, 0.37, 0.62, 0.85)


def _signature_d() -> str:
    with open(SCENE_PATH, encoding="utf-8") as fh:
        return json.load(fh)["layers"][1]["objects"][0]["d"]


def tightest_radius(d: str, window: int = 2) -> float:
    """The smallest radius of curvature along a path, in design units.

    Sway larger than this folds the curve through itself, so it is the number
    an author needs when choosing one."""
    points = [point for point, _ in resample_polyline(flatten_path(d)[0])]
    smallest = float("inf")
    for i in range(len(points)):
        a = points[max(0, i - window)]
        b = points[i]
        c = points[min(len(points) - 1, i + window)]
        area2 = abs((b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1]))
        if area2 < 1e-9:
            continue
        sides = math.dist(a, b) * math.dist(b, c) * math.dist(a, c)
        smallest = min(smallest, sides / area2)
    return smallest


def _still(kind: str, amplitude: float, phase: float, sway: float | None = None) -> dict:
    """A one-frame scene: the signature loop, deformed, nothing animated."""
    return {
        "version": 1, "width": 480, "height": 320, "fit": "contain",
        "layers": [
            {"id": "b", "z": 0, "objects": [
                {"type": "rect", "id": "bg", "x": 0, "y": 0, "w": 480, "h": 320,
                 "fill": "#101014"}]},
            {"id": "w", "z": 10, "objects": [
                {"type": "path", "id": "loop", "d": _signature_d(), "stroke": "#e8e8f0",
                 "stroke_width": 3, "progress": 1,
                 "deform": {"type": kind, "amplitude": amplitude, "wavelength": 220,
                            "phase": phase,
                            **({} if sway is None else {"sway": sway})}}]}],
        "animations": [],
    }


def _render(raw: dict):
    renderer = ReferenceRenderer()
    renderer.bind(b"", parse_scene(raw), 480, 320)
    return renderer.render(0.0)


# -- the projection --------------------------------------------------------


def test_perspective_is_symmetric_about_the_canvas():
    """Equal depth either side of the canvas gives reciprocal scaling."""
    near = perspective_scale(26.0)
    far = perspective_scale(-26.0)
    assert near > 1.0 > far > 0.0
    assert near * far == pytest.approx(
        (HELIX_FOCAL ** 2) / (HELIX_FOCAL ** 2 - 26.0 ** 2), rel=1e-9
    )


def test_bands_cover_the_depth_range():
    assert band_of(-1.0) == 0
    assert band_of(0.0) == 0
    assert band_of(1.0) == HELIX_BANDS - 1
    assert band_of(2.0) == HELIX_BANDS - 1
    assert 0.0 < band_depth(0) < band_depth(HELIX_BANDS - 1) < 1.0


def test_a_helix_uses_the_whole_depth_range():
    samples = resample_polyline(flatten_path("M 40 200 L 440 200")[0])
    projected = deform_helix(samples, 26.0, 220.0, 0.0, (240.0, 200.0))
    depths = [t for _, t in projected]
    assert min(depths) == pytest.approx(0.0, abs=1e-6)
    assert max(depths) == pytest.approx(1.0, abs=1e-6)
    assert {band_of(t) for t in depths} == set(range(HELIX_BANDS))


def test_zero_amplitude_is_flat_and_frontal():
    """No wave means no depth: the projection must collapse to identity rather
    than to some almost-identity that shifts the picture."""
    samples = resample_polyline(flatten_path("M 40 200 L 440 200")[0])
    projected = deform_helix(samples, 0.0, 220.0, 0.4, (240.0, 200.0))
    for (point, t), (original, _) in zip(projected, samples):
        assert point == original
        assert t == 1.0


@pytest.mark.parametrize("phase", [0.0, 0.3, 0.7])
def test_the_helix_is_periodic(phase):
    samples = resample_polyline(flatten_path("M 40 200 L 440 200")[0])
    a = deform_helix(samples, 26.0, 220.0, phase, (240.0, 200.0))
    b = deform_helix(samples, 26.0, 220.0, phase + 1.0, (240.0, 200.0))
    for (pa, ta), (pb, tb) in zip(a, b):
        assert pa[0] == pytest.approx(pb[0], abs=1e-6)
        assert pa[1] == pytest.approx(pb[1], abs=1e-6)
        assert ta == pytest.approx(tb, abs=1e-6)


# -- what it looks like ----------------------------------------------------


def test_perspective_moves_points_both_ways_about_the_centre():
    """Half the ribbon comes toward the eye and half goes away, so a helix must
    push some samples out from the vanishing point and pull others in. A
    projection that only ever grew would be a zoom, not a turn."""
    centre = (240.0, 200.0)
    samples = resample_polyline(flatten_path("M 40 200 L 440 200")[0])
    projected = deform_helix(samples, 26.0, 220.0, 0.0, centre)

    def radius(point):
        return math.hypot(point[0] - centre[0], point[1] - centre[1])

    changes = [radius(new) - radius(old) for (new, _), (old, _) in zip(projected, samples)]
    assert max(changes) > 0.5, "nothing came nearer"
    assert min(changes) < -0.5, "nothing went further away"


def _brightness(frame):
    """Mean brightness of lit pixels, and how much mid-grey there is relative to
    full brightness. Depth shading shows up in both."""
    lit = [frame.data[i] for i in range(0, len(frame.data), 4) if frame.data[i] > 40]
    bright = sum(1 for value in lit if value > 200)
    mid = sum(1 for value in lit if 60 <= value <= 150)
    return sum(lit) / len(lit), mid / max(1, bright)


def test_depth_shades_the_stroke():
    """A helix has near and far parts and a plain sine does not, so at the same
    amplitude the helix is dimmer on average and carries far more mid-grey.

    Measured rather than assumed: mean lit brightness 147 against 189, and a
    mid-to-bright ratio of 2.0 against 0.3."""
    helix_mean, helix_ratio = _brightness(_render(_still("helix", 26.0, 0.15)))
    sine_mean, sine_ratio = _brightness(_render(_still("sine", 26.0, 0.15)))

    assert helix_mean < sine_mean - 20, (helix_mean, sine_mean)
    assert helix_ratio > sine_ratio * 3, (helix_ratio, sine_ratio)


def test_the_scene_loads(request):
    scene = load_scene(SCENE)
    loop = objects_of(scene)["loop"]
    assert loop.deform is not None
    assert loop.deform.type == "helix"
    assert loop.deform.focal == pytest.approx(520.0)
    assert scene.duration == 8000


def test_an_unknown_deformation_is_still_refused():
    with pytest.raises(ValueError):
        parse_scene(_still("corkscrew", 26.0, 0.0))


# -- both players ----------------------------------------------------------

needs_c = pytest.mark.skipif(
    not is_available(), reason="C player not built; run: make -C poc/host-player -j4 lib"
)


@needs_c
@pytest.mark.parametrize("phase", PHASES)
def test_both_players_turn_the_same_ribbon(phase):
    raw = _still("helix", 26.0, phase)
    player = LvglPlayer()
    player.bind(json.dumps(raw).encode("utf-8"), None, 480, 320)
    same, detail = looks_the_same(_render(raw), player.render(0.0))
    assert same, f"phase {phase}: {detail}"


@needs_c
def test_both_players_agree_across_the_animated_scene():
    reference = ReferenceRenderer()
    reference.bind(b"", load_scene(SCENE), 480, 320)
    player = LvglPlayer()
    with open(SCENE, "rb") as fh:
        player.bind(fh.read(), None, 480, 320)
    for scene_time in (0, 1200, 2400, 4000, 6000, 7200, 8000):
        same, detail = looks_the_same(reference.render(scene_time), player.render(scene_time))
        assert same, f"at {scene_time} ms: {detail}"


@needs_c
def test_the_c_player_refuses_an_unknown_deformation():
    player = LvglPlayer()
    with pytest.raises(LvglPlayerError):
        player.bind(json.dumps(_still("corkscrew", 26.0, 0.0)).encode("utf-8"), None, 480, 320)


@needs_c
def test_the_helix_is_deterministic_in_c():
    player = LvglPlayer()
    with open(SCENE, "rb") as fh:
        player.bind(fh.read(), None, 480, 320)
    assert player.render(4000.0).hash() == player.render(4000.0).hash()
    player.render(0.0)
    assert player.render(4000.0).hash() == player.render(4000.0).hash()


# -- sway: the part that can fold ------------------------------------------


def test_sway_defaults_to_a_fraction_of_the_amplitude():
    loop = objects_of(parse_scene(_still("helix", 30.0, 0.0)))["loop"]
    assert loop.deform.sway == pytest.approx(12.0)


def test_sway_is_what_moves_the_stroke_across_the_picture():
    """Depth alone must leave the drawing where it is: the projection scales
    about the vanishing point, it does not displace along the path's normal."""
    centre = (240.0, 200.0)
    samples = resample_polyline(flatten_path("M 40 200 L 440 200")[0])

    depth_only = deform_helix(samples, 34.0, 220.0, 0.25, centre, sway=0.0)
    with_sway = deform_helix(samples, 34.0, 220.0, 0.25, centre, sway=12.0)

    # On a horizontal line the normal is vertical, so sway shows up in y.
    assert max(abs(p[1] - 200.0) for p, _ in depth_only) < 1e-6
    assert max(abs(p[1] - 200.0) for p, _ in with_sway) > 5.0


def test_the_shipped_scene_keeps_sway_below_the_tightest_loop():
    """The ripples that prompted `sway` were the in-plane offset exceeding the
    signature's own radius of curvature — 14 units at its tightest. A scene
    whose sway climbs back above that would fold again, and look like a bug
    nobody can explain."""
    scene = load_scene(SCENE)
    loop = objects_of(scene)["loop"]
    radius = tightest_radius(loop.props["d"])
    assert radius < 20.0, f"the fixture is meant to have tight loops: {radius:.1f}"

    peak = max(
        (animation.from_value, animation.to_value)
        for animation in scene.animations
        if animation.property == "deform.sway"
    )
    assert max(peak) < radius, f"sway {max(peak)} would fold a radius of {radius:.1f}"
