"""A swarm where some nodes run the Python reference and some run the C player.

    node A → Python reference
    node B → C / LVGL / ThorVG
    node C → C / LVGL / ThorVG
    node D → Python reference

all playing one scene, under the same failure scenarios as everything else.
This is the test §3.7 exists for: if the same scene semantics survive being
rendered by two independent implementations while the protocol is being abused,
the semantics are the thing that is real, not one particular renderer.

Two standards apply, and conflating them would be a mistake:

* **within a renderer family** buffers must be *identical* -- an exact
  comparison is a cheap tripwire for a node showing the wrong frame;
* **across families** frames must be the *same picture* -- antialiasing differs
  legitimately, so the comparison is where the ink is, not which pixels carry
  it.

Text is the known exception. `font_id` resolves to a preprocessed asset on the
device and to a built-in Montserrat here, so the caption genuinely differs
between the two players. Until fonts are carried on the asset plane and
addressed by content hash (proposal §9, §18), cross-family comparison is done
where the caption is not yet visible, and the divergence is measured rather
than hidden.
"""

from __future__ import annotations

from mementum_node.players.lvgl import LvglPlayer, is_available

from ..assert_sync import assert_identical_at, looks_the_same
from ..harness import Harness
from . import ScenarioResult

#: The caption fades in at 3000 ms; before that a frame is background and stroke.
STROKE_ONLY_TIMES = (700.0, 1400.0, 2100.0, 2900.0)


def run() -> ScenarioResult:
    harness = Harness()
    result = ScenarioResult("mixed_renderers", harness)

    if not is_available():
        result.check("the C player is built", False,
                     "libmementum_player.so missing; run: make -C poc/host-player -j4 lib")
        return result

    python_nodes = [harness.add_node("py-a"), harness.add_node("py-d")]
    c_nodes = [
        harness.add_node("c-b", renderer=LvglPlayer()),
        harness.add_node("c-c", renderer=LvglPlayer()),
    ]
    everyone = python_nodes + c_nodes

    play = harness.play(42)
    harness.advance(harness.sequencer.lead_ms + 2400)

    result.check("both renderer families are playing",
                 all(n.state == "playing" for n in everyone),
                 str({n.node_id: n.state for n in everyone}))
    result.check("both families render the same number of frames",
                 len({n.core.frames_presented for n in everyone}) == 1,
                 str({n.node_id: n.core.frames_presented for n in everyone}))

    # -- within a family: exact ---------------------------------------------
    for label, family in (("python", python_nodes), ("C/LVGL", c_nodes)):
        try:
            digest = assert_identical_at(family, 2100.0)
            result.check(f"{label} nodes are byte-identical to each other", True, digest[:12])
        except AssertionError as exc:
            result.check(f"{label} nodes are byte-identical to each other", False, str(exc))

    # -- across families: the same picture ----------------------------------
    for scene_time in STROKE_ONLY_TIMES:
        same, detail = looks_the_same(
            python_nodes[0].compose(scene_time), c_nodes[0].compose(scene_time)
        )
        result.check(f"python and C draw the same picture at {scene_time:.0f}ms", same, detail)

    # -- the failure scenarios, with both families in the swarm -------------

    # A lost PLAY, recovered from the schedule on the next heartbeat.
    harness.bus.drop_next_push(c_nodes[1].node_id, 1)
    replay = harness.play(42)
    harness.advance(120)
    result.check("the C node missed the pushed PLAY",
                 c_nodes[1].core.schedule.seq < replay.schedule.seq,
                 f"seq {c_nodes[1].core.schedule.seq} vs {replay.schedule.seq}")
    harness.advance(harness.heartbeat_ms + harness.sequencer.lead_ms + 900)
    result.check("the C node recovered on the heartbeat",
                 c_nodes[1].core.schedule.seq == replay.schedule.seq
                 and c_nodes[1].core.recovered_by_heartbeat >= 1,
                 f"seq {c_nodes[1].core.schedule.seq}, "
                 f"{c_nodes[1].core.recovered_by_heartbeat} heartbeat recoveries")

    # A late joiner on each renderer, into a running scene, with empty caches.
    late_python = harness.add_node("py-late")
    late_c = harness.add_node("c-late", renderer=LvglPlayer())
    harness.advance(300)
    result.check("late joiners on both renderers adopted the schedule",
                 late_python.core.schedule.seq == replay.schedule.seq
                 and late_c.core.schedule.seq == replay.schedule.seq,
                 f"python seq {late_python.core.schedule.seq}, c seq {late_c.core.schedule.seq}")

    everyone = everyone + [late_python, late_c]
    try:
        assert_identical_at([python_nodes[0], late_python], 1500.0)
        result.check("the python joiner matches its family exactly", True)
    except AssertionError as exc:
        result.check("the python joiner matches its family exactly", False, str(exc))
    try:
        assert_identical_at([c_nodes[0], late_c], 1500.0)
        result.check("the C joiner matches its family exactly", True)
    except AssertionError as exc:
        result.check("the C joiner matches its family exactly", False, str(exc))

    # A leader change: everyone cancels, the new leader starts afresh.
    epoch = harness.promote_leader()
    harness.advance(150)
    result.check("both families cancelled on the leader change",
                 all(n.state == "idle" for n in everyone),
                 str({n.node_id: n.state for n in everyone}))
    harness.play(42)
    harness.advance(harness.sequencer.lead_ms + 1200)
    result.check("both families restarted together",
                 all(n.state == "playing" for n in everyone),
                 str({n.node_id: n.state for n in everyone}))

    same, detail = looks_the_same(
        python_nodes[0].compose(2100.0), c_nodes[0].compose(2100.0)
    )
    result.check("after all of that, the two renderers still agree", same, detail)

    # -- the known gap, measured rather than hidden -------------------------
    with_caption = looks_the_same(
        python_nodes[0].compose(4200.0), c_nodes[0].compose(4200.0)
    )
    result.metrics["text_divergence_at_4200ms"] = with_caption[1]
    result.metrics["leader_epoch"] = epoch
    result.metrics["renderers"] = {n.node_id: n.renderer_name for n in everyone}
    return result


if __name__ == "__main__":  # pragma: no cover - CLI
    print(run().report())
