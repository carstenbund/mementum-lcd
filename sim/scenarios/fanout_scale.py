"""Fan-out at 10 / 100 / 300 nodes -- and where DISPLAY_LEAD_MS comes from.

300 simulated participants on a laptop exercise the registry and the fan-out
timing long before 300 boards exist, and probably instead of (§3.3). The design
bound is ~300 participants served by a Pi with **concurrent** fan-out (§20), and
the one number that matters is the time to the *last* node -- because
``DISPLAY_LEAD_MS`` follows from that measurement rather than from a constant
someone chose.

Two comparisons are made deliberately:

* concurrent versus sequential fan-out, which turns §20's argument into a
  measurement;
* the cost of a single unreachable node, which holds a worker for its whole
  timeout -- the specific failure §20 names.

These are design properties. The same curve measured on a real AP is the
physical one, and the divergence between them is a deliverable in its own right
(risk R9).
"""

from __future__ import annotations

from mementum_node.core.sequencer import derive_display_lead

from ..harness import Harness
from ..transport import DeliveryModel
from . import ScenarioResult

POPULATIONS = (10, 100, 300)


def _population(count: int, concurrency: int = 32, unreachable: int = 0) -> tuple[Harness, float]:
    model = DeliveryModel(fanout_concurrency=concurrency)
    harness = Harness(model=model, step_ms=10.0, seed=3)
    # Compositing off: 300 buffers would measure Python, not the system. The
    # core still registers, syncs, adopts, loads and evaluates on every node.
    harness.add_nodes(count, compositing=False)
    for node in harness.nodes[:unreachable]:
        harness.bus.set_unreachable(node.node_id)
    return harness, 0.0


def run(populations=POPULATIONS) -> ScenarioResult:
    result = ScenarioResult("fanout_scale", None)
    curve: dict[int, float] = {}

    for count in populations:
        harness, _ = _population(count)
        if result.harness is None:
            result.harness = harness
        play = harness.play(42)
        curve[count] = round(play.fanout_ms, 2)

        result.check(f"{count} nodes registered", len(harness.sequencer.nodes) == count,
                     f"{len(harness.sequencer.nodes)}/{count}")
        result.check(f"PLAY reached all {count} nodes", play.delivered == count,
                     f"{play.delivered}/{count}")

        harness.advance(harness.sequencer.lead_ms + 800)
        adopted = sum(1 for n in harness.nodes if n.core.schedule.seq == play.schedule.seq)
        playing = sum(1 for n in harness.nodes if n.state == "playing")
        presenting = sum(1 for n in harness.nodes if n.core.frames_presented > 0)
        result.check(f"all {count} nodes adopted the schedule", adopted == count,
                     f"{adopted}/{count}")
        result.check(f"all {count} nodes are playing", playing == count, f"{playing}/{count}")
        result.check(f"all {count} nodes are presenting frames", presenting == count,
                     f"{presenting}/{count}")
        # Every node started with an empty cache and pulled the package itself:
        # the asset plane is pull-based precisely so this does not join the
        # fan-out cost (§18).
        pulls = sum(n.core.pulls for n in harness.nodes)
        result.check(f"{count} nodes pulled the scene independently", pulls == count,
                     f"{pulls} pulls")

    # Concurrency is the hard requirement the bound places on the server.
    sequential, _ = _population(populations[-1], concurrency=1)
    sequential_play = sequential.play(42)
    concurrent_ms = curve[populations[-1]]
    result.check("concurrent fan-out beats sequential at the design bound",
                 sequential_play.fanout_ms > concurrent_ms * 4,
                 f"sequential {sequential_play.fanout_ms:.0f} ms vs concurrent {concurrent_ms:.0f} ms")
    result.check("sequential fan-out would blow DISPLAY_LEAD_MS at the bound",
                 sequential_play.fanout_ms > harness.sequencer.lead_ms / 2,
                 f"{sequential_play.fanout_ms:.0f} ms against a {harness.sequencer.lead_ms:.0f} ms lead")

    # One dead node must not cost everyone else its timeout.
    with_dead, _ = _population(populations[1], unreachable=1)
    dead_play = with_dead.play(42)
    healthy = [p.elapsed_ms for p in dead_play.pushes if p.delivered]
    result.check("a single unreachable node does not delay the healthy ones",
                 max(healthy) < with_dead.bus.model.timeout_ms,
                 f"slowest healthy delivery {max(healthy):.1f} ms")
    result.check("the unreachable node is reported, not silently dropped",
                 any(not p.delivered and p.error == "timeout" for p in dead_play.pushes),
                 str([p.error for p in dead_play.pushes if not p.delivered]))

    lead = derive_display_lead(curve[populations[-1]])
    result.metrics["fanout_ms_by_population"] = curve
    result.metrics["sequential_fanout_ms_at_bound"] = round(sequential_play.fanout_ms, 1)
    result.metrics["derived_display_lead_ms"] = round(lead, 1)
    result.metrics["inherited_display_lead_ms"] = harness.sequencer.lead_ms
    return result


if __name__ == "__main__":  # pragma: no cover - CLI
    print(run().report())
