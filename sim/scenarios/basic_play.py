"""M0c: a simulated swarm plays a scene in one process.

The gate: *two simulated nodes produce identical buffers at the same
sceneTime*. Everything else in Phase 0c is an elaboration of this one check.
"""

from __future__ import annotations

from mementum_node.core.sequencer import derive_display_lead

from ..assert_sync import assert_identical_at, skew_report
from ..harness import Harness
from . import ScenarioResult

SAMPLE_TIMES = (0.0, 700.0, 2100.0, 3400.0, 4200.0)


def run(nodes: int = 2, fps: float = 30.0) -> ScenarioResult:
    harness = Harness(fps=fps)
    harness.add_nodes(nodes)
    result = ScenarioResult("basic_play", harness)

    play = harness.play(42)
    result.check("PLAY accepted and fanned out", play.scheduled and play.delivered == nodes,
                 f"delivered {play.delivered}/{nodes}")

    # Sample skew mid-scene, while every node is actually playing.
    harness.advance(harness.sequencer.lead_ms + 2000)
    skew = skew_report(harness.nodes)
    result.check("scene-time skew within the hard bound", skew.within_hard_bound, str(skew))
    harness.advance(2800)

    playing_or_done = [n for n in harness.nodes if n.core.frames_presented > 0]
    result.check("every node rendered frames", len(playing_or_done) == nodes,
                 f"{len(playing_or_done)}/{nodes} presented at least one frame")

    for scene_time in SAMPLE_TIMES:
        try:
            digest = assert_identical_at(harness.nodes, scene_time)
            result.check(f"identical buffers at sceneTime={scene_time:.0f}ms", True, digest[:12])
        except AssertionError as exc:
            result.check(f"identical buffers at sceneTime={scene_time:.0f}ms", False, str(exc))

    # A moving picture, not a still: the same node at two times must differ,
    # or "identical buffers" would be satisfied by rendering nothing at all.
    early, late = harness.nodes[0].compose(500.0), harness.nodes[0].compose(3500.0)
    result.check("the scene actually animates", early.data != late.data,
                 f"{early.hash()[:8]} vs {late.hash()[:8]}")

    result.metrics["skew_mid_scene"] = str(skew)
    result.metrics["fanout_ms"] = round(play.fanout_ms, 2)
    result.metrics["derived_display_lead_ms"] = round(derive_display_lead(play.fanout_ms), 1)
    result.metrics["frames_presented"] = harness.summary()["frames"]
    return result


if __name__ == "__main__":  # pragma: no cover - CLI
    print(run().report())
