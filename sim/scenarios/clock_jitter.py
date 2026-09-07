"""Clock jitter, offset and drift -- scripted instead of induced.

Boards do not boot together (offset), their crystals are not identical (drift),
and every time reading is noisy (jitter). In simulation all three are knobs, so
the questions §0.5 asks of two boards on a bench can be asked of N nodes in a
test:

* does the skew stay inside the 20 ms target / 35 ms hard bound?
* how far does an un-resynced node wander in half an hour?
* does the heartbeat sync pull it back?

The **parameters** here are guesses until hardware measures them (§3.4). What
is being tested is the mechanism -- that playback derives exclusively from
``sharedNow() - displayAt`` and therefore self-corrects -- not the numbers.
"""

from __future__ import annotations

from ..assert_sync import SKEW_HARD_MS, assert_identical_at, skew_report
from ..harness import Harness
from ..transport import DeliveryModel
from . import ScenarioResult

SOAK_MS = 30 * 60 * 1000  # §0.5: "repeat after 30 min without re-sync"


def _clock_error(harness) -> dict[str, float]:
    """Each node's shared clock against true virtual time. The simulator may
    look at this; a node may not."""
    return {
        n.node_id: n.clock.shared_now() - harness.master.now for n in harness.nodes
    }


def run(nodes: int = 4, jitter_ms: float = 4.0, drift_ppm: float = 40.0) -> ScenarioResult:
    model = DeliveryModel(latency_ms=12.0, latency_jitter_ms=6.0, asymmetry_ms=1.5)
    harness = Harness(model=model, seed=7)
    result = ScenarioResult("clock_jitter", harness)

    for i in range(nodes):
        harness.add_node(
            f"node-{i:03d}",
            offset_ms=(i - nodes / 2) * 1500.0,     # boards booted at different times
            drift_ppm=drift_ppm * (1 if i % 2 else -1),
            jitter_ms=jitter_ms,
        )

    harness.play(42)
    harness.advance(harness.sequencer.lead_ms + 1500)

    skew = skew_report(harness.nodes)
    result.check("skew within the hard bound under jitter and offset",
                 skew.within_hard_bound, str(skew))
    result.metrics["skew_under_jitter"] = str(skew)
    result.metrics["clock_error_ms"] = {
        k: round(v, 2) for k, v in _clock_error(harness).items()
    }

    # The claim that matters: a noisy clock changes *when* a node renders, never
    # *what* it renders. At one sceneTime every node still agrees exactly.
    for scene_time in (800.0, 2400.0, 4200.0):
        try:
            digest = assert_identical_at(harness.nodes, scene_time)
            result.check(f"identical buffers at sceneTime={scene_time:.0f}ms", True, digest[:12])
        except AssertionError as exc:
            result.check(f"identical buffers at sceneTime={scene_time:.0f}ms", False, str(exc))

    # Drift soak: half an hour with no re-sync, then one heartbeat.
    harness.set_heartbeats(False)
    before = _clock_error(harness)
    harness.advance(SOAK_MS, step_ms=500.0)
    after = _clock_error(harness)
    drifted = max(after.values()) - min(after.values())
    result.check("drift is visible without re-sync (the reason to re-sync)",
                 drifted > SKEW_HARD_MS,
                 f"spread {drifted:.1f} ms after {SOAK_MS / 60000:.0f} min unsynced")

    harness.set_heartbeats(True)
    harness.advance(harness.heartbeat_ms + 300)
    recovered = _clock_error(harness)
    spread = max(recovered.values()) - min(recovered.values())
    result.check("one heartbeat sync pulls the swarm back inside the bound",
                 spread <= SKEW_HARD_MS,
                 f"spread {spread:.2f} ms after re-sync")

    result.metrics["drift_spread_before_ms"] = round(
        max(before.values()) - min(before.values()), 2
    )
    result.metrics["drift_spread_unsynced_ms"] = round(drifted, 1)
    result.metrics["drift_spread_after_resync_ms"] = round(spread, 2)
    result.metrics["modelled_asymmetry_ms"] = model.asymmetry_ms
    return result


if __name__ == "__main__":  # pragma: no cover - CLI
    print(run().report())
