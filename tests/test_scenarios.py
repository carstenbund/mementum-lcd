"""The Phase 0c gate, in CI, with no hardware (plan §3.5).

    Two simulated nodes produce identical buffers at the same sceneTime; a node
    joining mid-scene converges to the same buffer; a node that misses PLAY
    recovers on the next heartbeat; any node's buffer can be captured to PNG
    and the mosaic renders; the whole suite runs in CI without hardware.

Every scenario carries its own checks, so these tests run them and demand that
all of those checks passed -- the failure message names the specific claim that
broke rather than "assert False".
"""

import pytest

from sim import scenarios


@pytest.mark.parametrize("name", scenarios.NAMES)
def test_scenario(name):
    scenarios.run(name).assert_passed()


def test_scenarios_are_deterministic():
    """Same scenario, same seed, same buffers -- identical results on every run
    and on every machine, which is what makes them worth having in CI."""
    first = scenarios.run("basic_play")
    second = scenarios.run("basic_play")
    for node_a, node_b in zip(first.harness.nodes, second.harness.nodes):
        assert node_a.compose(2100.0).hash() == node_b.compose(2100.0).hash()
    assert first.harness.summary() == second.harness.summary()


def test_the_gate_two_nodes_identical_buffers():
    result = scenarios.run("basic_play")
    a, b = result.harness.nodes[:2]
    for scene_time in (0.0, 1234.0, 4200.0):
        assert a.compose(scene_time).data == b.compose(scene_time).data


def test_the_gate_late_join_converges():
    result = scenarios.run("late_join")
    joiner = result.harness.node("node-late")
    incumbent = result.harness.node("node-000")
    assert joiner.core.schedule.seq == incumbent.core.schedule.seq
    assert joiner.compose(3000.0).hash() == incumbent.compose(3000.0).hash()


def test_the_gate_missed_play_recovers_on_heartbeat():
    result = scenarios.run("missed_command")
    recovered = result.harness.node("node-001")
    assert recovered.core.recovered_by_heartbeat >= 1
    assert recovered.state == "playing"


def test_frame_hashes_agree_across_nodes():
    """The device-side check (§3.6), modelled: two nodes at one sceneTime must
    report the same frame hash."""
    result = scenarios.run("clock_jitter")
    digests = {n.node_id: n.compose(2000.0).hash() for n in result.harness.nodes}
    assert len(set(digests.values())) == 1, digests


def test_fanout_curve_is_monotonic_and_bounded():
    result = scenarios.run("fanout_scale")
    curve = result.metrics["fanout_ms_by_population"]
    sizes = sorted(curve)
    assert [curve[s] for s in sizes] == sorted(curve[s] for s in sizes)
    # Concurrent fan-out to the design bound must leave DISPLAY_LEAD_MS room.
    assert curve[max(sizes)] < result.metrics["inherited_display_lead_ms"] / 4
