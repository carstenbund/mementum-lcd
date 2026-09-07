"""Path flattening, measurement and arc-length trimming.

``progress`` is the risk-R1 question in geometric form: whatever the device ends
up using (a dash pattern through ThorVG, or compile-time path splitting), these
are the semantics it has to reproduce.
"""

import pytest

from mementum_node.core.geometry import (
    flatten_path,
    parse_path,
    polyline_length,
    trim_polyline,
)


def test_lines_flatten_exactly():
    assert flatten_path("M 0 0 L 10 0 L 10 10") == [[(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)]]


def test_relative_and_shorthand_commands():
    absolute = flatten_path("M 10 10 L 20 10 L 20 20 Z")
    relative = flatten_path("m 10 10 l 10 0 l 0 10 z")
    assert absolute == relative
    assert flatten_path("M 0 0 H 5 V 5")[0][-1] == (5.0, 5.0)


def test_flattening_is_deterministic():
    d = "M 0 0 C 20 0 40 40 60 40 Q 80 40 100 0"
    assert flatten_path(d) == flatten_path(d)


def test_length_of_a_known_polyline():
    assert polyline_length([(0, 0), (3, 4), (3, 14)]) == pytest.approx(15.0)


@pytest.mark.parametrize("progress", [0.1, 0.25, 0.5, 0.75, 0.9])
def test_trim_takes_the_right_arc_length(progress):
    points = flatten_path("M 0 0 C 30 0 70 40 100 40")[0]
    total = polyline_length(points)
    assert polyline_length(trim_polyline(points, progress)) == pytest.approx(
        total * progress, rel=1e-9
    )


def test_trim_endpoints():
    points = flatten_path("M 0 0 L 100 0")[0]
    assert trim_polyline(points, 0.0) == []
    assert trim_polyline(points, 1.0) == points
    assert trim_polyline(points, 0.5)[-1] == (50.0, 0.0)


def test_malformed_paths_are_refused():
    with pytest.raises(ValueError):
        parse_path("40 200 L 10 10")
    with pytest.raises(ValueError):
        flatten_path("M 0 0 C 1 1 2 2")
    with pytest.raises(ValueError):
        flatten_path("M 0 0 A 5 5 0 0 1 10 10")
