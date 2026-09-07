"""Capture and the virtual video wall (plan §3.6).

Part of the gate: *any node's buffer can be captured to PNG and the mosaic
renders*. Capture happens at the sink boundary, so a captured PNG must be the
node's actual composited frame -- not a re-render that might differ.
"""

import os

import pytest

from mementum_node.core.png import read_png
from sim.assert_sync import diff_frames, diff_image, skew_report
from sim.capture import annotate, capture_at, capture_live, capture_sequence
from sim.harness import Harness
from sim.wall import mosaic, wall_at, wall_live


@pytest.fixture(scope="module")
def playing():
    harness = Harness()
    harness.add_nodes(3)
    harness.play(42)
    harness.advance(harness.sequencer.lead_ms + 2200)
    return harness


def test_capture_writes_the_nodes_own_frame(playing, tmp_path):
    node = playing.nodes[0]
    path = capture_live(node, str(tmp_path / "live.png"))
    assert read_png(path) == node.frame


def test_capture_at_matches_composition(playing, tmp_path):
    node = playing.nodes[1]
    path = capture_at(node, 1500.0, str(tmp_path / "t1500.png"))
    assert read_png(path).hash() == node.compose(1500.0).hash()


def test_capture_does_not_disturb_playback(playing, tmp_path):
    node = playing.nodes[0]
    before = (node.core.frames_presented, node.core.last_scene_time, node.frame.hash())
    capture_at(node, 42.0, str(tmp_path / "probe.png"))
    assert (node.core.frames_presented, node.core.last_scene_time, node.frame.hash()) == before


def test_capture_sequence_names_files_by_time(playing, tmp_path):
    paths = capture_sequence(playing.nodes[0], [0, 1050, 4200], str(tmp_path / "seq"))
    assert [os.path.basename(p) for p in paths] == [
        "node-000_t000000.png",
        "node-000_t001050.png",
        "node-000_t004200.png",
    ]
    assert all(os.path.getsize(p) > 0 for p in paths)


def test_annotate_leaves_the_original_untouched(playing):
    frame = playing.nodes[0].frame
    before = frame.hash()
    labelled = annotate(frame, "node-000 t=1500ms")
    assert frame.hash() == before
    assert labelled.hash() != before


def test_the_wall_renders_every_node(playing):
    frame = wall_live(playing.nodes, columns=3, tile_width=160)
    assert frame.width > 3 * 160
    assert frame.height > 100


def test_the_wall_handles_heterogeneous_displays():
    from mementum_node.core.protocol import Display

    harness = Harness()
    harness.add_node("esp32", display=Display(480, 320, "rgb565"))
    harness.add_node("pi", display=Display(1920, 1080, "argb8888"))
    harness.play(42)
    harness.advance(harness.sequencer.lead_ms + 1000)
    frame = wall_at(harness.nodes, 900.0, tile_width=120)
    assert frame.width > 0 and frame.height > 0


def test_the_wall_needs_at_least_one_tile():
    with pytest.raises(ValueError):
        mosaic([])


def test_diff_of_identical_and_differing_frames(playing):
    a, b = playing.nodes[0], playing.nodes[1]
    same = diff_frames(a.compose(1000.0), b.compose(1000.0))
    assert same.identical and "identical" in str(same)

    different = diff_frames(a.compose(1000.0), b.compose(2000.0))
    assert not different.identical
    assert 0.0 < different.fraction < 1.0
    assert diff_image(a.compose(1000.0), b.compose(2000.0)).width == a.compose(1000.0).width


def test_skew_report_reads_as_a_verdict(playing):
    report = skew_report(playing.nodes)
    assert report.max_skew_ms < 35.0
    assert "max skew" in str(report)
    assert set(report.deltas) == {n.node_id for n in playing.nodes}
