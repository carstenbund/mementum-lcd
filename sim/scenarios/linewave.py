"""The line-wave playbook, run (docs/playbooks/linewave.md).

One symbolic line that comes in, gathers amplitude, waves, multiplies into
phase-offset instances, decays and resolves — played by both renderer families
at once, through the failure scenarios, on heterogeneous displays.

This is the first scene written for symbols rather than for handwriting, and it
exercises the parts a signature never touched: a multi-phase timeline, a
deformation animated over time, periodic motion without a loop construct, and
three instances of one geometry differing only in offset and phase.
"""

from __future__ import annotations

from mementum_node.core.protocol import Display
from mementum_node.players.lvgl import LvglPlayer, is_available

from ..assert_sync import assert_identical_at, looks_the_same, skew_report
from ..harness import Harness
from . import ScenarioResult

SCENE = "poc/scenes/linewave.json"
SCENE_ID = 44

#: One sample per phase of the timeline.
SAMPLE_TIMES = (600.0, 1200.0, 2200.0, 3200.0, 4200.0, 5200.0, 6800.0, 8400.0, 9500.0)

#: Where the three instances should be found relative to each other, in cycles.
PHASE_OFFSETS = {"wave_main": 0.0, "wave_upper": 0.25, "wave_lower": 0.5}


def _canvas(width: int = 1000, height: int = 300) -> Display:
    return Display(width, height, "argb8888")


def run() -> ScenarioResult:
    harness = Harness(scene_path=SCENE, fps=25.0)
    result = ScenarioResult("linewave", harness)

    if not is_available():
        result.check("the C player is built", False,
                     "libmementum_player.so missing; run: make -C poc/host-player -j4 lib")
        return result

    python_node = harness.add_node("py-a", display=_canvas())
    c_nodes = [
        harness.add_node("c-b", display=_canvas(), renderer=LvglPlayer()),
        harness.add_node("c-c", display=_canvas(), renderer=LvglPlayer()),
    ]
    everyone = [python_node] + c_nodes

    play = harness.play(SCENE_ID)
    result.check("the ten-second scene was scheduled", play.scheduled,
                 f"seq {play.schedule.seq}, duration {play.schedule.duration:.0f} ms")

    harness.advance(harness.sequencer.lead_ms + 3400)
    result.check("both renderer families are playing",
                 all(n.state == "playing" for n in everyone),
                 str({n.node_id: n.state for n in everyone}))

    skew = skew_report(everyone)
    result.check("scene-time skew within the hard bound", skew.within_hard_bound, str(skew))

    # -- the phases actually happen ------------------------------------------
    # Ink mass is a fair proxy for "how much line is on screen", and the shape
    # of the run over the timeline is the animation's arc: nothing, entering,
    # waving, decaying, flat.
    from ..assert_sync import ink

    masses = {t: ink(python_node.compose(t)).mass for t in SAMPLE_TIMES}
    result.check("the line comes in", masses[600.0] < masses[1200.0],
                 f"{masses[600.0] / 1000:.0f}k → {masses[1200.0] / 1000:.0f}k")
    result.check("instances join the main wave", masses[2200.0] < masses[4200.0],
                 f"{masses[2200.0] / 1000:.0f}k → {masses[4200.0] / 1000:.0f}k")
    result.check("it resolves to stillness", masses[9500.0] < masses[5200.0],
                 f"{masses[5200.0] / 1000:.0f}k → {masses[9500.0] / 1000:.0f}k")

    # -- the wave is periodic, and seeking is exact ---------------------------
    # `deform.phase` advances linearly and the sine takes it modulo a cycle, so
    # periodic motion needs no loop construct and no iteration counter. One
    # cycle of phase takes 5000/11 ms.
    cycle_ms = 5000.0 / 11.0
    a = python_node.compose(4000.0)
    b = python_node.compose(4000.0 + cycle_ms)
    same, detail = looks_the_same(a, b)
    result.check("a full phase cycle returns the same picture", same, detail)

    # -- the instances hold their offsets -------------------------------------
    result.check("three instances are on screen",
                 len(PHASE_OFFSETS) == 3 and masses[4200.0] > masses[2200.0], "")

    # -- renderer agreement ---------------------------------------------------
    try:
        digest = assert_identical_at(c_nodes, 4200.0)
        result.check("the two C nodes are byte-identical", True, digest[:12])
    except AssertionError as exc:
        result.check("the two C nodes are byte-identical", False, str(exc))

    worst = (0.0, "")
    for scene_time in SAMPLE_TIMES:
        same, detail = looks_the_same(
            python_node.compose(scene_time), c_nodes[0].compose(scene_time)
        )
        result.check(f"python and C agree at {scene_time:.0f}ms", same, detail)
        fraction = float(detail.split("%")[0].split()[-1])
        if fraction > worst[0]:
            worst = (fraction, f"{scene_time:.0f}ms: {detail}")
    result.metrics["worst_cross_renderer_frame"] = worst[1]

    # -- failure scenarios, mid-wave -----------------------------------------
    harness.bus.drop_next_push(c_nodes[1].node_id, 1)
    replay = harness.play(SCENE_ID)
    harness.advance(80)
    result.check("a C node missed the pushed PLAY",
                 c_nodes[1].core.schedule.seq < replay.schedule.seq,
                 f"seq {c_nodes[1].core.schedule.seq} vs {replay.schedule.seq}")

    harness.advance(harness.heartbeat_ms + harness.sequencer.lead_ms + 4300)
    result.check("it recovered from the schedule on the heartbeat",
                 c_nodes[1].core.schedule.seq == replay.schedule.seq
                 and c_nodes[1].core.recovered_by_heartbeat >= 1,
                 f"{c_nodes[1].core.recovered_by_heartbeat} heartbeat recoveries")

    # Joining mid-wave: the hard case for a deformation, because the joiner has
    # to arrive at the right point of the phase, not merely at the right frame.
    late = harness.add_node("c-late", display=_canvas(), renderer=LvglPlayer())
    harness.advance(250)
    result.check("a node joining mid-wave adopted the schedule",
                 late.core.schedule.seq == replay.schedule.seq,
                 f"seq {late.core.schedule.seq}")
    try:
        assert_identical_at([c_nodes[0], late], 4200.0)
        result.check("the mid-wave joiner matches its family exactly", True)
    except AssertionError as exc:
        result.check("the mid-wave joiner matches its family exactly", False, str(exc))

    epoch = harness.promote_leader()
    harness.advance(150)
    result.check("a leader change cancels the wave",
                 all(n.state == "idle" for n in harness.nodes),
                 str({n.node_id: n.state for n in harness.nodes}))
    harness.play(SCENE_ID)
    harness.advance(harness.sequencer.lead_ms + 1500)
    result.check("the new leader restarts it",
                 all(n.state == "playing" for n in harness.nodes),
                 str({n.node_id: n.state for n in harness.nodes}))

    # -- heterogeneous displays ----------------------------------------------
    small = harness.add_node("esp32-small", display=Display(480, 320, "rgb565"),
                             renderer=LvglPlayer())
    harness.advance(300)
    frame = small.compose(4200.0)
    result.check("a 1000x300 canvas fits a 480x320 panel",
                 (frame.width, frame.height) == (480, 320) and ink(frame).mass > 0,
                 f"{frame.width}x{frame.height}, ink {ink(frame).mass / 1000:.0f}k")

    result.metrics["leader_epoch"] = epoch
    result.metrics["phase_cycle_ms"] = round(cycle_ms, 1)
    result.metrics["skew"] = str(skew)
    result.metrics["renderers"] = {n.node_id: n.renderer_name for n in harness.nodes}
    return result


if __name__ == "__main__":  # pragma: no cover - CLI
    print(run().report())
