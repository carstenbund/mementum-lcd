# Phase 0c test protocol

A record of what was run and what it returned. Analysis and the numbers in
context are in [`phase0c-report.md`](phase0c-report.md); this file is the raw
result, kept for the record.

| | |
|---|---|
| Date | 2026-09-07 11:07 UTC |
| Phase | 0c — the simulation harness (implementation plan §3.5) |
| Revision | `345b6b8` plus the working tree at the time of the run (16 files added or modified) |
| Python | 3.12.3 (venv `.venv`, `pytest` 9.1.1, `pluggy` 1.6.0) |
| Platform | Linux 6.8.0-139-generic aarch64 |
| Hardware under test | none — no ESP32, no panel, no network |

Runtime dependencies of the code under test: none beyond the standard library.

## 1. Test suite

```bash
.venv/bin/python -m pytest -q
```

```text
84 passed in 15.08s
```

| Test module | Tests | Result |
|---|---:|---|
| `tests/test_easing.py` | 13 | passed |
| `tests/test_scene_and_evaluator.py` | 10 | passed |
| `tests/test_geometry.py` | 11 | passed |
| `tests/test_render_determinism.py` | 12 | passed |
| `tests/test_clock_and_protocol.py` | 7 | passed |
| `tests/test_scenarios.py` | 12 | passed |
| `tests/test_capture_and_wall.py` | 10 | passed |
| `tests/test_layering.py` | 9 | passed |
| **Total** | **84** | **84 passed, 0 failed, 0 skipped** |

## 2. Scenarios

```bash
.venv/bin/python -m sim.scenarios all      # exit status 0
```

61 checks across six scenarios, 0 failed. Full output:

```text
scenario: basic_play
  [PASS] PLAY accepted and fanned out -- delivered 2/2
  [PASS] scene-time skew within the hard bound -- max skew 0.00 ms across 2 nodes (within target; target 20 ms, hard 35 ms)
  [PASS] every node rendered frames -- 2/2 presented at least one frame
  [PASS] identical buffers at sceneTime=0ms -- a0a585cf19a1
  [PASS] identical buffers at sceneTime=700ms -- 30f2ccc1bca7
  [PASS] identical buffers at sceneTime=2100ms -- b2a42492ae32
  [PASS] identical buffers at sceneTime=3400ms -- 900950237ad7
  [PASS] identical buffers at sceneTime=4200ms -- af68baebd4cf
  [PASS] the scene actually animates -- e88ba7a8 vs d8160983
  derived_display_lead_ms: 250.0
  fanout_ms: 15.33
  frames_presented: 253
  skew_mid_scene: max skew 0.00 ms across 2 nodes (within target; target 20 ms, hard 35 ms)
  => PASSED
scenario: late_join
  [PASS] joiner adopted the running schedule -- seq 1 vs 1
  [PASS] joiner pulled the scene it did not have -- 1 asset pull(s)
  [PASS] joiner is playing -- playing
  [PASS] joiner entered mid-animation, not at zero -- sceneTime=2399.999999999999, joined after 2000ms
  [PASS] joiner matches at sceneTime=2100ms -- b2a42492ae32
  [PASS] joiner matches at sceneTime=3400ms -- 900950237ad7
  [PASS] joiner matches at sceneTime=4200ms -- af68baebd4cf
  [PASS] the join delayed nobody -- frames before={'node-000': 60, 'node-001': 60}
  joiner_frames: 12
  joiner_scene_time: 2400.0
  scene_time_at_join: 2000.0
  => PASSED
scenario: missed_command
  [PASS] PLAY was delivered to one node and lost for the other -- {'node-000': True, 'node-001': False}
  [PASS] the node that missed PLAY knows nothing yet -- missed seq=0, good seq=1
  [PASS] the missed schedule arrived on the heartbeat -- seq=1
  [PASS] recovery was by heartbeat, not by a retried push -- 1 heartbeat recovery/recoveries
  [PASS] both nodes are playing -- playing / playing
  [PASS] identical buffers at sceneTime=1200ms -- 5cc088a16adf
  [PASS] identical buffers at sceneTime=3400ms -- 900950237ad7
  heartbeat_interval_ms: 1000
  pushes_dropped: 1
  recovery_by_ms: 1250.0
  => PASSED
scenario: leader_change
  [PASS] the scene is running before the leader dies -- ['playing', 'playing', 'playing']
  [PASS] the clock epoch advanced -- 1 -> 2
  [PASS] every node cancelled the active scene -- ['idle', 'idle', 'idle']
  [PASS] no node is still reporting a scene position -- [None, None, None]
  [PASS] nodes adopted the new epoch -- [2, 2, 2]
  [PASS] the restart is a new schedule, not the old one resumed -- seq 1 -> 3
  [PASS] every node is playing again -- ['playing', 'playing', 'playing']
  [PASS] the restart began at the beginning -- [1200.0, 1200.0, 1200.0]
  [PASS] identical buffers after the restart -- 11563919e01b
  clock_resyncs: [9, 9, 8]
  epoch: 1 -> 2
  => PASSED
scenario: clock_jitter
  [PASS] skew within the hard bound under jitter and offset -- max skew 3.07 ms across 4 nodes (within target; target 20 ms, hard 35 ms)
  [PASS] identical buffers at sceneTime=800ms -- 27fbcc639557
  [PASS] identical buffers at sceneTime=2400ms -- ec4c5367c7f3
  [PASS] identical buffers at sceneTime=4200ms -- af68baebd4cf
  [PASS] drift is visible without re-sync (the reason to re-sync) -- spread 150.8 ms after 30 min unsynced
  [PASS] one heartbeat sync pulls the swarm back inside the bound -- spread 4.21 ms after re-sync
  clock_error_ms: {'node-000': 4.05, 'node-001': 2.4, 'node-002': 2.48, 'node-003': -1.17}
  drift_spread_after_resync_ms: 4.21
  drift_spread_before_ms: 4.05
  drift_spread_unsynced_ms: 150.8
  modelled_asymmetry_ms: 1.5
  skew_under_jitter: max skew 3.07 ms across 4 nodes (within target; target 20 ms, hard 35 ms)
  => PASSED
scenario: fanout_scale
  [PASS] 10 nodes registered -- 10/10
  [PASS] PLAY reached all 10 nodes -- 10/10
  [PASS] all 10 nodes adopted the schedule -- 10/10
  [PASS] all 10 nodes are playing -- 10/10
  [PASS] all 10 nodes are presenting frames -- 10/10
  [PASS] 10 nodes pulled the scene independently -- 10 pulls
  [PASS] 100 nodes registered -- 100/100
  [PASS] PLAY reached all 100 nodes -- 100/100
  [PASS] all 100 nodes adopted the schedule -- 100/100
  [PASS] all 100 nodes are playing -- 100/100
  [PASS] all 100 nodes are presenting frames -- 100/100
  [PASS] 100 nodes pulled the scene independently -- 100 pulls
  [PASS] 300 nodes registered -- 300/300
  [PASS] PLAY reached all 300 nodes -- 300/300
  [PASS] all 300 nodes adopted the schedule -- 300/300
  [PASS] all 300 nodes are playing -- 300/300
  [PASS] all 300 nodes are presenting frames -- 300/300
  [PASS] 300 nodes pulled the scene independently -- 300 pulls
  [PASS] concurrent fan-out beats sequential at the design bound -- sequential 1806 ms vs concurrent 70 ms
  [PASS] sequential fan-out would blow DISPLAY_LEAD_MS at the bound -- 1806 ms against a 2000 ms lead
  [PASS] a single unreachable node does not delay the healthy ones -- slowest healthy delivery 33.5 ms
  [PASS] the unreachable node is reported, not silently dropped -- ['timeout']
  derived_display_lead_ms: 250.0
  fanout_ms_by_population: {10: 16.24, 100: 33.48, 300: 70.25}
  inherited_display_lead_ms: 2000
  sequential_fanout_ms_at_bound: 1805.7
  => PASSED
```

## 3. Capture and video wall

```bash
.venv/bin/python -m sim.wall --mixed --at 3800 --out sim-out/wall.png
```

```text
sim-out/wall.png  504x416  4 nodes
```

```bash
.venv/bin/python -m sim.capture --scenario basic_play --times 0,2100,4200 --out sim-out
```

```text
sim-out/node-000_t000000.png
sim-out/node-000_t002100.png
sim-out/node-000_t004200.png
```

## 4. Gate

Criteria as written in implementation plan §3.5.

| Criterion | Result | Evidence |
|---|---|---|
| Two simulated nodes produce identical buffers at the same `sceneTime` | pass | `basic_play`, 5 sample times; `test_the_gate_two_nodes_identical_buffers` |
| A node joining mid-scene converges to the same buffer | pass | `late_join`; `test_the_gate_late_join_converges` |
| A node that misses `PLAY` recovers on the next heartbeat | pass | `missed_command`; `test_the_gate_missed_play_recovers_on_heartbeat` |
| Any node's buffer can be captured to PNG | pass | §3 above; `test_capture_writes_the_nodes_own_frame` |
| The mosaic renders | pass | §3 above; `test_the_wall_renders_every_node` |
| The whole suite runs in CI without hardware | pass | §1 above; `.github/workflows/sim.yml` (Python 3.11 and 3.12) |

**Verdict: the Phase 0c gate passes.**

Recorded per conventions §15. Every number above was produced in simulation and
is a design property; no hardware gate is affected by this run (§3.4).
