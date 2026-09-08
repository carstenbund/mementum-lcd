"""The scene model and the evaluator.

The property under test is purity: seeking to a time must equal arriving there
by stepping (plan 0.3 task 7). Everything about recovery depends on it.
"""

import json

import pytest

from mementum_node.core.evaluator import evaluate
from mementum_node.core.scene import load_scene, parse_scene, scene_hash

from .conftest_helpers import SCENE_PATH, objects_of


@pytest.fixture(scope="module")
def scene():
    return load_scene(SCENE_PATH)


def test_scene_loads(scene):
    assert (scene.version, scene.width, scene.height, scene.fit) == (1, 480, 320, "contain")
    assert scene.duration == 4200
    assert scene.object_ids() == ("bg", "signature", "caption")


def test_scene_hash_is_key_order_independent():
    with open(SCENE_PATH, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    shuffled = dict(reversed(list(raw.items())))
    assert scene_hash(raw) == scene_hash(shuffled)


def test_seek_equals_stepping(scene):
    """The forbidden alternative is an accumulator; this is what forbids it."""
    stepped = None
    for t in range(0, 4201, 33):
        stepped = evaluate(scene, t)
    seeked = evaluate(scene, 4191)  # the last step landed at 4191, not 4200
    assert objects_of(stepped)["signature"].progress == objects_of(seeked)["signature"].progress
    for t in (0, 500, 1234.5, 3000, 4200, 99999):
        assert objects_of(evaluate(scene, t)) == objects_of(evaluate(scene, t))


def test_hold_before_and_after(scene):
    at_start = objects_of(evaluate(scene, 0))
    before_caption = objects_of(evaluate(scene, 2999))
    after_end = objects_of(evaluate(scene, 10_000))
    assert at_start["signature"].progress == 0.0
    assert before_caption["caption"].opacity == 0.0
    assert after_end["signature"].progress == 1.0
    assert after_end["caption"].opacity == 1.0


def test_evaluation_does_not_mutate_the_scene(scene):
    before = objects_of(scene)["signature"].progress
    evaluate(scene, 2100)
    assert objects_of(scene)["signature"].progress == before


def test_easing_is_applied_not_linear(scene):
    """ease-in-out at the midpoint is 0.5, but at a quarter it is 0.125."""
    quarter = objects_of(evaluate(scene, 1050))["signature"].progress
    assert quarter == pytest.approx(0.125, abs=1e-9)


@pytest.mark.parametrize(
    "mutation, message",
    [
        ({"animations": [{"target": "nope", "property": "opacity", "start": 0,
                          "duration": 1, "from": 0, "to": 1}]}, "unknown object"),
        ({"animations": [{"target": "bg", "property": "colour", "start": 0,
                          "duration": 1, "from": 0, "to": 1}]}, "not animatable"),
        ({"animations": [{"target": "bg", "property": "opacity", "start": 0,
                          "duration": 1, "from": 0, "to": 1, "easing": "bounce"}]}, "easing"),
        ({"version": 2}, "version"),
    ],
)
def test_invalid_scenes_are_refused(mutation, message):
    with open(SCENE_PATH, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    raw.update(mutation)
    with pytest.raises(ValueError) as exc:
        parse_scene(raw)
    assert message in str(exc.value)


#: A phase list: build up, hold, decay. The governing animation is the last one
#: to have started, so an animation that has not begun cannot impose its
#: ``from`` value on an earlier phase (decision 0006). Shared with
#: ``tests/test_c_player.py`` so both evaluators are pinned to the same vector.
PHASE_SCENE = {
    "version": 1,
    "width": 100,
    "height": 100,
    "layers": [{"id": "l", "z": 0, "objects": [
        {"type": "rect", "id": "r", "x": 0, "y": 0, "w": 10, "h": 10,
         "fill": "#ffffff", "opacity": 0}]}],
    "animations": [
        {"target": "r", "property": "opacity", "start": 0, "duration": 1000,
         "from": 0, "to": 1, "easing": "linear"},
        {"target": "r", "property": "opacity", "start": 5000, "duration": 1000,
         "from": 1, "to": 0, "easing": "linear"},
    ],
}

PHASE_VECTOR = [(0, 0.0), (500, 0.5), (1000, 1.0), (3000, 1.0),
                (5000, 1.0), (5500, 0.5), (6000, 0.0), (9000, 0.0)]


@pytest.mark.parametrize("scene_time, expected", PHASE_VECTOR)
def test_a_phase_list_composes(scene_time, expected):
    """Two animations on one property, at different times, must both happen."""
    scene = parse_scene(PHASE_SCENE)
    assert objects_of(evaluate(scene, scene_time))["r"].opacity == pytest.approx(
        expected, abs=1e-6
    )


def test_an_unstarted_animation_does_not_reach_backwards(scene):
    """The regression this rule exists for: before decision 0006 the decay's
    ``from`` value overwrote the entire build-up."""
    parsed = parse_scene(PHASE_SCENE)
    assert objects_of(evaluate(parsed, 0))["r"].opacity == 0.0
    assert objects_of(evaluate(parsed, 250))["r"].opacity == pytest.approx(0.25)
