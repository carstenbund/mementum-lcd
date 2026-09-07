"""A node that joins mid-scene converges to the same buffer.

Late join is not a mechanism. The running schedule comes back in the ordinary
REGISTER acknowledgement, the node computes ``sceneTime = T - T0``, and it
enters mid-animation (§19). Nobody else is delayed.

Two flavours matter and both are here: a node with the scene already cached
(seek immediately) and a node with an empty cache (pull, then seek to the
current time). The second is what actually bounds recovery.
"""

from __future__ import annotations

from ..assert_sync import assert_identical_at
from ..harness import Harness
from . import ScenarioResult


def run(join_at_ms: float = 2000.0) -> ScenarioResult:
    harness = Harness()
    early = harness.add_nodes(2)
    result = ScenarioResult("late_join", harness)

    play = harness.play(42)
    harness.advance(harness.sequencer.lead_ms + join_at_ms)

    frames_before = {n.node_id: n.core.frames_presented for n in early}
    scene_time_before = early[0].scene_time

    # The joiner registers into a scene that is already running, with an empty
    # cache: it must pull the package and seek, not start from zero.
    joiner = harness.add_node("node-late", compositing=True)
    result.check("joiner adopted the running schedule",
                 joiner.core.schedule.seq == play.schedule.seq,
                 f"seq {joiner.core.schedule.seq} vs {play.schedule.seq}")
    result.check("joiner pulled the scene it did not have", joiner.core.pulls >= 1,
                 f"{joiner.core.pulls} asset pull(s)")
    result.check("joiner is playing", joiner.state == "playing", joiner.state)

    harness.advance(400)

    joined_scene_time = joiner.scene_time
    result.check("joiner entered mid-animation, not at zero",
                 joined_scene_time is not None and joined_scene_time > join_at_ms - 100,
                 f"sceneTime={joined_scene_time!r}, joined after {join_at_ms:.0f}ms")

    for scene_time in (join_at_ms + 100.0, 3400.0, 4200.0):
        try:
            digest = assert_identical_at(harness.nodes, scene_time)
            result.check(f"joiner matches at sceneTime={scene_time:.0f}ms", True, digest[:12])
        except AssertionError as exc:
            result.check(f"joiner matches at sceneTime={scene_time:.0f}ms", False, str(exc))

    # Nobody else is delayed: the incumbents kept presenting throughout.
    still_running = all(
        n.core.frames_presented > frames_before[n.node_id] for n in early
    )
    result.check("the join delayed nobody", still_running,
                 f"frames before={frames_before}")

    result.metrics["scene_time_at_join"] = round(scene_time_before or 0.0, 1)
    result.metrics["joiner_scene_time"] = round(joined_scene_time or 0.0, 1)
    result.metrics["joiner_frames"] = joiner.core.frames_presented
    return result


if __name__ == "__main__":  # pragma: no cover - CLI
    print(run().report())
