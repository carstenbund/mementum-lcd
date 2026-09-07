"""Easing is normative (proposal §14). These vectors are the contract that any
reimplementation -- the C evaluator on the ESP32 above all -- must reproduce.
A wrong curve presents as a sync bug while being nothing of the kind (risk R6).
"""

import pytest

from mementum_node.core.easing import EASINGS, VECTORS, ease


@pytest.mark.parametrize("name", sorted(VECTORS))
def test_fixed_vectors(name):
    for p, expected in VECTORS[name]:
        assert ease(name, p) == pytest.approx(expected, abs=1e-9)


@pytest.mark.parametrize("name", sorted(EASINGS))
def test_endpoints_and_monotonicity(name):
    assert ease(name, 0.0) == 0.0
    assert ease(name, 1.0) == 1.0
    previous = -1.0
    for i in range(101):
        value = ease(name, i / 100.0)
        assert value >= previous - 1e-12, f"{name} is not monotonic at p={i / 100}"
        previous = value


@pytest.mark.parametrize("name", sorted(EASINGS))
def test_out_of_range_is_clamped(name):
    assert ease(name, -5.0) == 0.0
    assert ease(name, 5.0) == 1.0


def test_unknown_curve_is_an_error():
    with pytest.raises(ValueError):
        ease("bounce", 0.5)
