"""Leader change: cancel, then a fresh start (option C).

A scene running against one leader's clock cannot interpret another leader's
``millis()`` as continuity. Of the three options in §11 the first system takes
**C** explicitly: leader change cancels the active scene, and the new leader
schedules a fresh start. An intentional restart rather than an unexplained
jump.

So this scenario asserts two things that are easy to confuse: that the running
scene *stops*, and that what follows is a genuinely new schedule in a new clock
epoch -- not the old one resumed.
"""

from __future__ import annotations

from ..assert_sync import assert_identical_at
from ..harness import Harness
from . import ScenarioResult


def run(nodes: int = 3) -> ScenarioResult:
    harness = Harness()
    participants = harness.add_nodes(nodes)
    result = ScenarioResult("leader_change", harness)

    first = harness.play(42)
    harness.advance(harness.sequencer.lead_ms + 1500)
    epoch_before = harness.sequencer.leader_epoch
    result.check("the scene is running before the leader dies",
                 all(n.state == "playing" for n in participants),
                 str([n.state for n in participants]))

    # The leader goes; a client is promoted and publishes a new clock domain.
    new_epoch = harness.promote_leader()
    harness.advance(120)

    result.check("the clock epoch advanced", new_epoch > epoch_before,
                 f"{epoch_before} -> {new_epoch}")
    result.check("every node cancelled the active scene",
                 all(n.state == "idle" for n in participants),
                 str([n.state for n in participants]))
    result.check("no node is still reporting a scene position",
                 all(n.scene_time is None for n in participants),
                 str([n.scene_time for n in participants]))
    result.check("nodes adopted the new epoch",
                 all(n.core.leader_epoch == new_epoch for n in participants),
                 str([n.core.leader_epoch for n in participants]))

    # The new leader schedules afresh. Same scene, new sequence, new T0.
    second = harness.play(42)
    harness.advance(harness.sequencer.lead_ms + 1200)

    result.check("the restart is a new schedule, not the old one resumed",
                 second.schedule.seq > first.schedule.seq
                 and second.schedule.display_at > first.schedule.display_at,
                 f"seq {first.schedule.seq} -> {second.schedule.seq}")
    result.check("every node is playing again",
                 all(n.state == "playing" for n in participants),
                 str([n.state for n in participants]))
    result.check("the restart began at the beginning",
                 all((n.scene_time or 0) < 1600 for n in participants),
                 str([round(n.scene_time or -1, 1) for n in participants]))

    try:
        digest = assert_identical_at(participants, 900.0)
        result.check("identical buffers after the restart", True, digest[:12])
    except AssertionError as exc:
        result.check("identical buffers after the restart", False, str(exc))

    result.metrics["epoch"] = f"{epoch_before} -> {new_epoch}"
    result.metrics["clock_resyncs"] = [n.clock.sync_count for n in participants]
    return result


if __name__ == "__main__":  # pragma: no cover - CLI
    print(run().report())
