"""Rendering is a pure function of (scene, sceneTime, display).

This is the claim the whole architecture rests on, tested at the level below the
protocol: before two *nodes* can agree, one renderer has to agree with itself.
"""

import pytest

from mementum_node.core.evaluator import evaluate
from mementum_node.core.framebuffer import Frame
from mementum_node.core.pacer import RecordPacer
from mementum_node.core.png import encode_png, read_png, write_png
from mementum_node.core.renderer import render_scene
from mementum_node.core.scene import load_scene

from .conftest_helpers import SCENE_PATH


@pytest.fixture(scope="module")
def scene():
    return load_scene(SCENE_PATH)


@pytest.mark.parametrize("scene_time", [0, 700, 2100, 3400, 4200])
def test_same_time_gives_the_same_bytes(scene, scene_time):
    a = render_scene(evaluate(scene, scene_time))
    b = render_scene(evaluate(scene, scene_time))
    assert a.data == b.data
    assert a.hash() == b.hash()


def test_different_times_give_different_pictures(scene):
    hashes = {render_scene(evaluate(scene, t)).hash() for t in (0, 1000, 2000, 3000, 4200)}
    assert len(hashes) == 5


def test_record_pacer_run_is_byte_identical(scene):
    """The record pacer walks scene time with no wall clock at all, so
    rendering the same scene twice must be byte-identical (plan 0b.3)."""
    pacer = RecordPacer(fps=8)
    def run():
        return [render_scene(evaluate(scene, t)).hash() for t in pacer.times(1000)]
    assert run() == run()


def test_render_is_independent_of_evaluation_history(scene):
    """Arriving at a time by stepping must render the same as seeking to it."""
    for t in range(0, 2000, 100):
        render_scene(evaluate(scene, t))
    stepped = render_scene(evaluate(scene, 2000))
    fresh = render_scene(evaluate(load_scene(SCENE_PATH), 2000))
    assert stepped.data == fresh.data


def test_display_size_changes_the_frame_not_the_scene(scene):
    small = render_scene(evaluate(scene, 3000), 480, 320)
    large = render_scene(evaluate(scene, 3000), 960, 640)
    assert (small.width, small.height) == (480, 320)
    assert (large.width, large.height) == (960, 640)
    assert small.hash() != large.hash()


def test_fit_contain_letterboxes_a_wider_display(scene):
    """A 16:9 display showing a 3:2 canvas must have empty columns at the
    edges: ``fit`` is a policy, not a stretch."""
    wide = render_scene(evaluate(scene, 4200), 960, 360)
    assert wide.get(1, 180) == (0, 0, 0, 255)
    assert wide.get(480, 180) != (0, 0, 0, 255)


def test_png_round_trip_is_lossless_and_stable(scene, tmp_path):
    frame = render_scene(evaluate(scene, 2100))
    path = write_png(frame, str(tmp_path / "frame.png"))
    assert read_png(path) == frame
    assert encode_png(frame) == encode_png(frame)


def test_frame_hash_detects_a_single_pixel(scene):
    frame = render_scene(evaluate(scene, 1000))
    before = frame.hash()
    changed = Frame(frame.width, frame.height, bytearray(frame.data))
    changed.set(240, 160, (255, 0, 0, 255))
    assert changed.hash() != before
