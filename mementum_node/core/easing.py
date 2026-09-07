"""Normative easing curves (proposal §14, plan 0b.1 task 2).

These are written to be *reimplementable*: exact formulae, no library calls, and
fixed test vectors in ``VECTORS`` that any second implementation (C on the
ESP32, the reference evaluator, a future Rust one) must reproduce. A wrong
easing curve looks exactly like a sync bug while being nothing of the kind, so
this module is the contract, not a convenience.

    linear       f(p) = p
    ease-in      f(p) = p^2
    ease-out     f(p) = 1 - (1 - p)^2
    ease-in-out  f(p) = 2p^2                 for p < 0.5
                        1 - 2(1 - p)^2       for p >= 0.5

``p`` is clamped to [0, 1] before evaluation. All curves satisfy f(0) = 0,
f(1) = 1 and are monotonically non-decreasing.
"""

from __future__ import annotations

__all__ = ["EASINGS", "VECTORS", "ease", "is_known"]


def _linear(p: float) -> float:
    return p


def _ease_in(p: float) -> float:
    return p * p


def _ease_out(p: float) -> float:
    q = 1.0 - p
    return 1.0 - q * q


def _ease_in_out(p: float) -> float:
    if p < 0.5:
        return 2.0 * p * p
    q = 1.0 - p
    return 1.0 - 2.0 * q * q


EASINGS = {
    "linear": _linear,
    "ease-in": _ease_in,
    "ease-out": _ease_out,
    "ease-in-out": _ease_in_out,
}


def is_known(name: str) -> bool:
    return name in EASINGS


def ease(name: str, p: float) -> float:
    """Apply easing ``name`` to normalised progress ``p`` (clamped to [0, 1])."""
    try:
        fn = EASINGS[name]
    except KeyError:
        raise ValueError(f"unknown easing curve: {name!r}") from None
    if p <= 0.0:
        return 0.0
    if p >= 1.0:
        return 1.0
    return fn(p)


#: Fixed vectors. The contract for any reimplementation; compared to 1e-9.
VECTORS = {
    "linear": [(0.0, 0.0), (0.25, 0.25), (0.5, 0.5), (0.75, 0.75), (1.0, 1.0)],
    "ease-in": [(0.0, 0.0), (0.25, 0.0625), (0.5, 0.25), (0.75, 0.5625), (1.0, 1.0)],
    "ease-out": [(0.0, 0.0), (0.25, 0.4375), (0.5, 0.75), (0.75, 0.9375), (1.0, 1.0)],
    "ease-in-out": [
        (0.0, 0.0),
        (0.25, 0.125),
        (0.5, 0.5),
        (0.75, 0.875),
        (1.0, 1.0),
    ],
}
