"""The C player: does the device's code agree with the reference?

`poc/player/` holds the sources the ESP-IDF build will compile -- scene model,
JSON loader, easing, evaluator, LVGL renderer -- and this suite runs them
through ctypes against the Python reference. One evaluator, not two (plan
§3.7), checked rather than trusted (risk R6).

Skipped wholesale when the library has not been built, because the Phase 0c
suite must keep running on a machine with no C toolchain.
"""

import json
import os

import pytest

from mementum_node.core.easing import VECTORS, ease
from mementum_node.core.evaluator import evaluate
from mementum_node.core.scene import load_scene
from mementum_node.players.lvgl import LvglPlayer, LvglPlayerError, PlayerLibrary, is_available
from sim.assert_sync import ink, looks_the_same

from .conftest_helpers import SCENE_PATH, objects_of

pytestmark = pytest.mark.skipif(
    not is_available(),
    reason="C player not built; run: make -C poc/host-player -j4 lib",
)

THREE_STROKES = os.path.join(os.path.dirname(SCENE_PATH), "three-strokes.json")


@pytest.fixture(scope="module")
def library():
    return PlayerLibrary.instance()


@pytest.fixture(scope="module")
def payload():
    with open(SCENE_PATH, "rb") as fh:
        return fh.read()


@pytest.fixture(scope="module")
def player(payload):
    player = LvglPlayer()
    player.bind(payload, None, 480, 320)
    return player


# -- the contract ---------------------------------------------------------


@pytest.mark.parametrize("name", sorted(VECTORS))
def test_c_easing_matches_the_fixed_vectors(library, name):
    """The vectors in core/easing.py are normative; this is the second
    implementation they exist to bind."""
    for p, expected in VECTORS[name]:
        assert library.ease(name, p) == pytest.approx(expected, abs=1e-6)


@pytest.mark.parametrize("name", sorted(VECTORS))
def test_c_and_python_easing_agree_everywhere(library, name):
    for i in range(0, 101):
        p = i / 100.0
        assert library.ease(name, p) == pytest.approx(ease(name, p), abs=1e-6)


@pytest.mark.parametrize("scene_time", [0, 500, 1050, 2100, 3400, 4200, 9000])
def test_c_and_python_evaluators_agree(player, scene_time):
    """Same scene, same time, same animated values -- in two languages."""
    reference = objects_of(evaluate(load_scene(SCENE_PATH), scene_time))
    assert player.property_at("signature", "progress", scene_time) == pytest.approx(
        reference["signature"].progress, abs=1e-6
    )
    assert player.property_at("caption", "opacity", scene_time) == pytest.approx(
        reference["caption"].opacity, abs=1e-6
    )


def test_c_and_python_measure_the_same_path(player):
    from mementum_node.core.geometry import flatten_path, polyline_length

    with open(SCENE_PATH, "r", encoding="utf-8") as fh:
        d = json.load(fh)["layers"][1]["objects"][0]["d"]
    python_length = polyline_length(flatten_path(d)[0])
    assert player.path_length("signature") == pytest.approx(python_length, rel=1e-3)
    assert player.subpath_count("signature") == 1


def test_declared_length_wins_over_measurement(payload):
    """The composer's number is authoritative when it provides one, so a player
    never has to reproduce anyone else's flattening."""
    scene = json.loads(payload.decode("utf-8"))
    scene["layers"][1]["objects"][0]["length"] = 1234.5
    player = LvglPlayer()
    player.bind(json.dumps(scene).encode("utf-8"), None, 480, 320)
    assert player.path_length("signature") == pytest.approx(1234.5, abs=1e-3)


# -- the two rules that are actually visible ------------------------------


@pytest.fixture(scope="module")
def strokes_player():
    with open(THREE_STROKES, "rb") as fh:
        player = LvglPlayer()
        player.bind(fh.read(), None, 240, 120)
    return player


def _stroke_extents(frame):
    """Drawn width of each of the three horizontal strokes, in pixels."""
    out = []
    for y in (30, 55, 80):
        lit = [x for x in range(frame.width) if frame.get(x, y)[0] > 60]
        out.append(max(lit) - min(lit) if lit else 0)
    return out


def test_strokes_appear_in_sequence_not_together(strokes_player):
    """Three separated strokes, revealed as one pen trajectory.

    A single dash pattern cannot express this -- the dash restarts at every
    moveTo -- so the player sequences the subpaths itself. Getting this wrong
    is immediately visible: all three strokes growing at once instead of one
    after another.
    """
    halfway = _stroke_extents(strokes_player.render(1500.0))
    assert halfway[0] > 90, f"the first stroke should be complete: {halfway}"
    assert 30 < halfway[1] < 75, f"the second stroke should be part-drawn: {halfway}"
    assert halfway[2] == 0, f"the third stroke should not have started: {halfway}"


@pytest.mark.parametrize(
    "scene_time, expected",
    [(0.0, (0, 0, 0)), (500.0, (1, 0, 0)), (1500.0, (1, 1, 0)), (2500.0, (1, 1, 1))],
)
def test_strokes_arrive_one_at_a_time(strokes_player, scene_time, expected):
    drawn = tuple(1 if extent > 0 else 0 for extent in
                  _stroke_extents(strokes_player.render(scene_time)))
    assert drawn == expected


def test_the_signature_actually_finishes(player):
    """At progress 1 the dash is dropped entirely. Otherwise a declared length
    slightly short of the renderer's own leaves the last fraction undrawn --
    the animation never completing, at the moment someone is watching it
    complete."""
    nearly = ink(player.render(4100.0)).mass
    complete = ink(player.render(4200.0)).mass
    later = ink(player.render(6000.0)).mass
    assert complete > nearly
    assert later == pytest.approx(complete, rel=1e-6), "a finished scene must stay finished"


# -- against the reference -------------------------------------------------


@pytest.mark.parametrize("scene_time", [700.0, 1400.0, 2100.0, 2900.0])
def test_c_and_python_draw_the_same_picture(player, scene_time):
    """Before the caption fades in, the two renderers can be compared directly.
    Antialiasing differs; where the ink is does not."""
    from mementum_node.core.render_backend import ReferenceRenderer

    reference = ReferenceRenderer()
    reference.bind(b"", load_scene(SCENE_PATH), 480, 320)
    same, detail = looks_the_same(reference.render(scene_time), player.render(scene_time))
    assert same, detail


def test_text_is_the_known_divergence(player):
    """Recorded, not hidden: `font_id` resolves to a different asset in each
    player, so the caption genuinely differs until fonts are carried on the
    asset plane and addressed by content hash."""
    from mementum_node.core.render_backend import ReferenceRenderer

    reference = ReferenceRenderer()
    reference.bind(b"", load_scene(SCENE_PATH), 480, 320)
    same, detail = looks_the_same(reference.render(4200.0), player.render(4200.0))
    assert not same, f"fonts unexpectedly agree, which would be worth investigating: {detail}"


def test_the_c_player_is_deterministic(player):
    assert player.render(2100.0).hash() == player.render(2100.0).hash()
    assert player.render(2100.0).hash() != player.render(2200.0).hash()


def test_seek_equals_stepping_in_c(player):
    stepped = None
    for t in range(0, 2101, 33):
        stepped = player.render(t)
    assert stepped.hash() == player.render(2079.0).hash()


def test_a_bad_scene_is_refused(payload):
    player = LvglPlayer()
    with pytest.raises(LvglPlayerError):
        player.bind(b'{"version": 2}', None, 480, 320)
    with pytest.raises(LvglPlayerError):
        player.bind(b"not json at all", None, 480, 320)
