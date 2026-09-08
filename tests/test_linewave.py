"""The line-wave: deformation semantics, in both players.

Covers the parts a handwriting scene never touched — a multi-phase timeline, a
deformation animated over time, periodic motion without a loop construct, and
three instances of one geometry differing only in offset and phase
(docs/playbooks/linewave.md).
"""

import json
import math
import os

import pytest

from mementum_node.core.evaluator import evaluate
from mementum_node.core.geometry import (
    DEFORM_SAMPLE_STEP,
    deform_sine,
    flatten_path,
    polyline_length,
    resample_polyline,
)
from mementum_node.core.render_backend import ReferenceRenderer
from mementum_node.core.scene import load_scene, parse_scene
from mementum_node.players.lvgl import LvglPlayer, LvglPlayerError, is_available
from sim.assert_sync import ink, looks_the_same

from .conftest_helpers import SCENE_PATH, objects_of

SCENE = os.path.join(os.path.dirname(SCENE_PATH), "linewave.json")

#: One cycle of `deform.phase`: the scene advances it 11 cycles over 5000 ms.
CYCLE_MS = 5000.0 / 11.0


@pytest.fixture(scope="module")
def scene():
    return load_scene(SCENE)


@pytest.fixture(scope="module")
def reference(scene):
    renderer = ReferenceRenderer()
    renderer.bind(b"", scene, 1000, 300)
    return renderer


# -- geometry --------------------------------------------------------------


def test_sampling_is_uniform_and_reaches_the_end():
    """The sampling rule is part of the contract: both players must sample a
    deformed path identically or the wave differs in shape."""
    points = flatten_path("M 60 150 L 940 150")[0]
    samples = resample_polyline(points)
    total = polyline_length(points)

    assert samples[0][1] == 0.0
    assert samples[-1][1] == pytest.approx(total)
    assert len(samples) == math.ceil(total / DEFORM_SAMPLE_STEP) + 1
    steps = [b[1] - a[1] for a, b in zip(samples, samples[1:])]
    assert max(steps) - min(steps) < 1e-6, "samples are not uniform"


def test_a_sine_deformation_has_the_requested_amplitude():
    samples = resample_polyline(flatten_path("M 60 150 L 940 150")[0])
    waved = deform_sine(samples, amplitude=46.0, wavelength=260.0, phase=0.0)
    ys = [point[1] for point in waved]
    assert max(ys) == pytest.approx(196.0, abs=1.0)
    assert min(ys) == pytest.approx(104.0, abs=1.0)


@pytest.mark.parametrize("phase", [0.0, 0.25, 0.5, 0.75])
def test_phase_is_periodic_by_one_cycle(phase):
    """Periodic motion with no loop construct: `phase` advances linearly and the
    sine takes it modulo a cycle, so the picture repeats while playback stays a
    pure function of sceneTime."""
    samples = resample_polyline(flatten_path("M 60 150 L 940 150")[0])
    a = deform_sine(samples, 46.0, 260.0, phase)
    b = deform_sine(samples, 46.0, 260.0, phase + 1.0)
    assert all(abs(p[1] - q[1]) < 1e-6 for p, q in zip(a, b))


def test_zero_amplitude_leaves_the_path_alone():
    samples = resample_polyline(flatten_path("M 60 150 L 940 150")[0])
    flat = deform_sine(samples, 0.0, 260.0, 0.3)
    assert all(abs(point[1] - 150.0) < 1e-6 for point in flat)


# -- the scene -------------------------------------------------------------


def test_the_scene_loads_with_three_instances(scene):
    objects = objects_of(scene)
    assert {"wave_main", "wave_upper", "wave_lower"} <= set(objects)
    for object_id, expected in (("wave_main", 0.0), ("wave_upper", 0.25), ("wave_lower", 0.5)):
        assert objects[object_id].deform is not None
        assert objects[object_id].deform.phase == pytest.approx(expected)


def test_the_instances_hold_their_phase_offsets(scene):
    """The three waves are one geometry differing only in offset and phase; if
    the offsets drift the chorus becomes a blur."""
    for scene_time in (3200.0, 4200.0, 5200.0, 6000.0):
        objects = objects_of(evaluate(scene, scene_time))
        main = objects["wave_main"].deform.phase
        assert objects["wave_upper"].deform.phase - main == pytest.approx(0.25, abs=1e-4)
        assert objects["wave_lower"].deform.phase - main == pytest.approx(0.50, abs=1e-4)


def test_the_timeline_has_phases(scene):
    """Build up, then decay, on one property — the case that did not work
    before decision 0006."""
    amplitude = lambda t: objects_of(evaluate(scene, t))["wave_main"].deform.amplitude
    assert amplitude(0) == 0.0
    assert amplitude(1900) > 0.0
    assert amplitude(4000) == pytest.approx(46.0)
    assert amplitude(6900) < 46.0
    assert amplitude(9000) == pytest.approx(0.0, abs=1e-6)
    assert amplitude(10000) == pytest.approx(0.0, abs=1e-6)


def test_progress_is_measured_on_the_undeformed_path(scene):
    """A reveal and a deformation are independent: waving the line must not
    change how much of it has been drawn."""
    raw = json.loads(open(SCENE, encoding="utf-8").read())
    for obj in raw["layers"][1]["objects"]:
        obj["progress"] = 0.5
    raw["animations"] = []

    extents = []
    for amplitude in (0.0, 40.0):
        for obj in raw["layers"][1]["objects"]:
            obj["deform"]["amplitude"] = amplitude
        renderer = ReferenceRenderer()
        renderer.bind(b"", parse_scene(raw), 1000, 300)
        frame = renderer.render(0.0)
        lit = [x for x in range(frame.width) if any(frame.get(x, y)[0] > 60 for y in range(300))]
        extents.append(max(lit))
    assert abs(extents[0] - extents[1]) <= 2, f"the reveal moved with amplitude: {extents}"


def test_the_animation_arc(reference):
    """Nothing, entering, waving, resolving — the shape of the whole scene."""
    mass = {t: ink(reference.render(t)).mass for t in (0, 600, 1200, 4200, 9500, 10000)}
    assert mass[0] == 0.0
    assert mass[600] < mass[1200] < mass[4200]
    assert mass[9500] < mass[4200]
    assert mass[10000] == pytest.approx(mass[9500], rel=0.05)


# -- both players ----------------------------------------------------------

pytestmark_c = pytest.mark.skipif(
    not is_available(), reason="C player not built; run: make -C poc/host-player -j4 lib"
)


@pytest.fixture(scope="module")
def c_player():
    player = LvglPlayer()
    with open(SCENE, "rb") as fh:
        player.bind(fh.read(), None, 1000, 300)
    return player


@pytestmark_c
@pytest.mark.parametrize(
    "scene_time", [600.0, 1200.0, 2200.0, 3200.0, 4200.0, 5200.0, 6800.0, 8400.0, 9500.0]
)
def test_both_players_draw_the_same_wave(reference, c_player, scene_time):
    same, detail = looks_the_same(reference.render(scene_time), c_player.render(scene_time))
    assert same, f"at {scene_time} ms: {detail}"


@pytestmark_c
def test_both_players_evaluate_the_deformation_alike(scene, c_player):
    for scene_time in (0, 1900, 2600, 4200, 6900, 9000):
        expected = objects_of(evaluate(scene, scene_time))["wave_main"].deform
        assert c_player.property_at("wave_main", "deform.amplitude", scene_time) == pytest.approx(
            expected.amplitude, abs=1e-3
        )
        assert c_player.property_at("wave_main", "deform.phase", scene_time) == pytest.approx(
            expected.phase, abs=1e-3
        )


@pytestmark_c
def test_the_c_player_is_periodic_too(c_player):
    same, detail = looks_the_same(c_player.render(4000.0), c_player.render(4000.0 + CYCLE_MS))
    assert same, detail


@pytestmark_c
def test_an_unknown_deformation_is_refused():
    raw = json.loads(open(SCENE, encoding="utf-8").read())
    raw["layers"][1]["objects"][0]["deform"]["type"] = "swirl"
    with pytest.raises(ValueError):
        parse_scene(raw)
    player = LvglPlayer()
    with pytest.raises(LvglPlayerError):
        player.bind(json.dumps(raw).encode("utf-8"), None, 1000, 300)
