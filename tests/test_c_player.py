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


def test_c_evaluator_handles_a_phase_list():
    """The same vector the Python evaluator is pinned to (decision 0006)."""
    import json

    from .test_scene_and_evaluator import PHASE_SCENE, PHASE_VECTOR

    player = LvglPlayer()
    player.bind(json.dumps(PHASE_SCENE).encode("utf-8"), None, 100, 100)
    for scene_time, expected in PHASE_VECTOR:
        assert player.property_at("r", "opacity", scene_time) == pytest.approx(
            expected, abs=1e-6
        ), f"at {scene_time} ms"


def test_rendering_backwards_gives_the_same_frame(payload):
    """The C evaluator writes state in place, so it must reset to the authored
    values every time. Without that, a property whose animation has not started
    yet keeps whatever the last frame left -- accumulation through the back
    door, and exactly what §10 forbids."""
    player = LvglPlayer()
    player.bind(payload, None, 480, 320)
    early = player.render(700.0).hash()
    player.render(4200.0)  # the caption is visible here
    assert player.render(700.0).hash() == early, "a backwards seek showed a stale frame"


# -- the second layer, on the code path that ships -------------------------


def test_the_c_player_ripples(payload):
    """The ESP32 units run this player, so a touch that only the Python
    reference can show is a touch that does not exist on the hardware."""
    from mementum_node.core.ripple import Ripple

    player = LvglPlayer()
    player.bind(payload, None, 480, 320)
    assert player.ripple_count() == 0

    still = player.render(2000.0).hash()
    player.add_ripple(Ripple(origin=611.0, start=2000.0, amplitude=16.0))
    assert player.ripple_count() == 1
    assert player.render(2000.0).hash() != still, "the ripple changed nothing"

    # It is transient: once its life is over the picture is the original again.
    assert player.render(4000.0).hash() == player.render(4000.0).hash()


def test_both_players_ripple_alike():
    """Same disturbance, same instant, same picture — the conformance the
    second layer needs before it can be called real."""
    from mementum_node.core.render_backend import ReferenceRenderer
    from mementum_node.core.ripple import Ripple

    scene_path = os.path.join(os.path.dirname(SCENE_PATH), "loop-helix.json")
    with open(scene_path, "rb") as fh:
        payload = fh.read()

    reference = ReferenceRenderer()
    reference.bind(payload, load_scene(scene_path), 480, 320)
    player = LvglPlayer()
    player.bind(payload, None, 480, 320)

    ripple = Ripple(origin=611.0, start=3000.0, amplitude=16.0)
    reference.add_ripple(ripple)
    player.add_ripple(ripple)

    for scene_time in (3000, 3200, 3600, 4000, 4400, 4600):
        same, detail = looks_the_same(reference.render(scene_time), player.render(scene_time))
        assert same, f"at {scene_time} ms: {detail}"


def test_a_node_with_a_ripple_capable_renderer_never_reports_it_unsupported():
    """The silent skip this replaces was the real defect: a unit that cannot
    show the second layer must be visible as such, not quietly inert (§18)."""
    from mementum_node.players.lvgl import LvglPlayer as Player
    from sim.harness import Harness

    harness = Harness(scene_path="poc/scenes/loop-helix.json", lead_ms=250)
    node = harness.add_node("c-unit", renderer=Player())
    harness.play(47)
    harness.advance(harness.sequencer.lead_ms + 600)

    assert node.state == "playing"
    node.core.touch(266.0, 190.0)
    assert node.core.ripples_unsupported == 0
    assert node.renderer.ripple_count() == 1


def test_both_players_write_by_letter(payload):
    """Handwriting is the case that found this: `progress` applied to each
    subpath independently grows every letter at once. Only the C player
    sequenced them, because the multi-stroke fixture had only ever been run
    through the C player — so this asserts both."""
    from mementum_node.core.render_backend import ReferenceRenderer

    scene_path = os.path.join(os.path.dirname(SCENE_PATH), "handwriting.json")
    with open(scene_path, "rb") as fh:
        hand = fh.read()

    reference = ReferenceRenderer()
    reference.bind(hand, load_scene(scene_path), 480, 320)
    player = LvglPlayer()
    player.bind(hand, None, 480, 320)

    def written_extent(frame):
        """How far to the right the writing has reached."""
        lit = [
            x
            for x in range(frame.width)
            for y in range(0, frame.height, 3)
            if frame.get(x, y)[0] > 60
        ]
        return max(lit) if lit else 0

    early, late = 900.0, 2900.0
    for renderer in (reference, player):
        assert written_extent(renderer.render(early)) < written_extent(
            renderer.render(late)
        ), "the writing must advance left to right, not fill in everywhere at once"
        # A quarter of the way in, the phrase must not already reach the end.
        assert written_extent(renderer.render(early)) < 0.5 * written_extent(
            renderer.render(5200.0)
        )

    for scene_time in (600.0, 900.0, 1800.0, 2900.0, 4100.0, 5200.0):
        same, detail = looks_the_same(reference.render(scene_time), player.render(scene_time))
        assert same, f"at {scene_time} ms: {detail}"


def test_the_player_reports_a_path_beyond_its_bounds(payload):
    """Real handwriting is 31 pen strokes against an old limit of 16. Whatever
    the bound is, exceeding it must be an error the loader states, not a scene
    that half loads."""
    import json

    scene = json.loads(payload.decode("utf-8"))
    scene["layers"][1]["objects"][0]["d"] = " ".join(
        f"M {i} 0 L {i + 1} 1" for i in range(MM_MAX_SUBPATHS_GUESS + 40)
    )
    player = LvglPlayer()
    with pytest.raises(LvglPlayerError) as exc:
        player.bind(json.dumps(scene).encode("utf-8"), None, 480, 320)
    assert "bounds" in str(exc.value) or "unsupported" in str(exc.value)


#: The C player's subpath limit; the test above only needs to exceed it.
MM_MAX_SUBPATHS_GUESS = 64
