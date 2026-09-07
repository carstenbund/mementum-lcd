"""Clock behaviour and the schedule-as-state property.

Two things that are easy to get wrong and expensive to debug on hardware:
``millis()`` rollover, and a Cristian sync whose residual error nobody measured.
"""

import pytest

from mementum_node.core.clock import MILLIS_MASK, CristianClock, elapsed
from mementum_node.core.protocol import Capabilities, Register, Schedule
from sim.clock import NodeTimeSource, SimulationClock
from sim.harness import Harness
from sim.transport import DeliveryModel


def test_elapsed_survives_millis_rollover():
    assert elapsed(MILLIS_MASK - 5, 10) == 16
    assert elapsed(100, 350) == 250
    assert elapsed(0, 0) == 0


def test_cristian_picks_the_lowest_rtt_sample():
    master = SimulationClock(1000.0)
    source = NodeTimeSource(master, offset_ms=500.0)
    rtts = iter([80.0, 10.0, 40.0])

    def query():
        rtt = next(rtts)
        source.stall_ms += rtt
        return master.now + rtt / 2.0, 1

    clock = CristianClock(source, query, samples=3)
    sample = clock.sync()
    assert sample.rtt == pytest.approx(10.0, abs=1e-6)
    assert clock.epoch == 1


def test_sync_error_equals_the_modelled_asymmetry():
    """Cristian corrects for half the round trip; asymmetry is exactly what it
    cannot see, so the residual error should be the asymmetry and nothing
    else. If this test drifts, the transport model has changed meaning."""
    for asymmetry in (0.0, 2.0, 7.5):
        harness = Harness(
            model=DeliveryModel(latency_ms=15.0, latency_jitter_ms=0.0, asymmetry_ms=asymmetry)
        )
        node = harness.add_node("node-a", offset_ms=4321.0)
        error = node.clock.shared_now() - harness.master.now
        assert error == pytest.approx(asymmetry, abs=1e-6)


def test_capability_gate():
    esp32 = Capabilities(scene_ir=1, vector=True, text=True, lottie=False)
    assert esp32.satisfies({"scene_ir": 1, "vector": True, "text": True})[0]
    assert not esp32.satisfies({"lottie": True})[0]
    assert not esp32.satisfies({"scene_ir": 2})[0]


def test_the_schedule_is_returned_as_state_not_only_pushed():
    """Registration and heartbeat both carry the current schedule; that is the
    single property late join and missed-command recovery both rest on."""
    harness = Harness()
    harness.add_node("node-a")
    play = harness.play(42)
    harness.advance(200)

    ack = harness.sequencer.handle(Register(harness.node("node-a").core.descriptor))
    assert ack.schedule.seq == play.schedule.seq
    assert ack.schedule.playing

    late = harness.add_node("node-b")
    assert late.core.schedule.seq == play.schedule.seq


def test_a_node_that_cannot_render_fails_visibly():
    """Never silently drift out of the shared timeline (§18)."""
    harness = Harness()
    incapable = harness.add_node(
        "node-lottie-only", capabilities=Capabilities(scene_ir=1, vector=False, text=False)
    )
    assert harness.sequencer.playability(42) == {"node-lottie-only": "missing capability: vector"}

    harness.play(42)
    harness.advance(300)
    assert incapable.state == "incapable"
    assert incapable.frame is None
    assert "cannot render" in incapable.core.fail_reason


def test_refuse_policy_declines_to_schedule_at_all():
    harness = Harness(incapable_policy="refuse")
    harness.add_node("node-a", capabilities=Capabilities(vector=False))
    result = harness.play(42)
    assert not result.scheduled
    assert "cannot render" in result.refused
    assert harness.sequencer.schedule == Schedule()
