"""A node that misses PLAY recovers on the next heartbeat.

The one property the protocol has to provide is that **the schedule is state,
not an event** (§19). This scenario removes the event -- the PLAY push to one
node simply never arrives -- and checks that the node recovers anyway, from the
schedule returned on its next heartbeat.

That is what makes the heartbeat interval the worst-case recovery latency, and
why it must be short relative to scene duration. The scenario asserts the bound
rather than assuming it.
"""

from __future__ import annotations

from ..assert_sync import assert_identical_at
from ..harness import Harness
from . import ScenarioResult


def run(heartbeat_ms: int = 1000) -> ScenarioResult:
    harness = Harness(heartbeat_ms=heartbeat_ms)
    good, missed = harness.add_nodes(2)
    result = ScenarioResult("missed_command", harness)

    harness.bus.drop_next_push(missed.node_id, 1)
    play = harness.play(42)

    delivered = {p.node_id: p.delivered for p in play.pushes}
    result.check("PLAY was delivered to one node and lost for the other",
                 delivered.get(good.node_id) and not delivered.get(missed.node_id),
                 str(delivered))

    # Straight after the push, only the node that received it knows anything.
    harness.advance(50)
    result.check("the node that missed PLAY knows nothing yet",
                 missed.core.schedule.seq == 0 and good.core.schedule.seq == play.schedule.seq,
                 f"missed seq={missed.core.schedule.seq}, good seq={good.core.schedule.seq}")

    # Recovery must arrive within one heartbeat interval, with margin for the
    # round trip -- no retry, no replay, no catch-up animation.
    harness.advance(heartbeat_ms + 200)
    recovered_at = harness.master.now
    result.check("the missed schedule arrived on the heartbeat",
                 missed.core.schedule.seq == play.schedule.seq,
                 f"seq={missed.core.schedule.seq}")
    result.check("recovery was by heartbeat, not by a retried push",
                 missed.core.recovered_by_heartbeat >= 1,
                 f"{missed.core.recovered_by_heartbeat} heartbeat recovery/recoveries")

    harness.advance(harness.sequencer.lead_ms + 1500)
    result.check("both nodes are playing", good.state == "playing" and missed.state == "playing",
                 f"{good.state} / {missed.state}")

    for scene_time in (1200.0, 3400.0):
        try:
            digest = assert_identical_at([good, missed], scene_time)
            result.check(f"identical buffers at sceneTime={scene_time:.0f}ms", True, digest[:12])
        except AssertionError as exc:
            result.check(f"identical buffers at sceneTime={scene_time:.0f}ms", False, str(exc))

    result.metrics["heartbeat_interval_ms"] = heartbeat_ms
    result.metrics["recovery_by_ms"] = round(recovered_at, 1)
    result.metrics["pushes_dropped"] = harness.bus.pushes_dropped
    return result


if __name__ == "__main__":  # pragma: no cover - CLI
    print(run().report())
