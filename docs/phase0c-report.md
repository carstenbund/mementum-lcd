# Phase 0c report — the simulation harness

Companion to [`implementation-plan.md`](implementation-plan.md) §3. Conventions
§15: no measurement asserted in prose without a recorded number.

> **Every number in this document is a design property, not a physical one.**
> The simulator models a network and a clock; it does not measure one. Frame
> rate, PSRAM bandwidth, LCD flush cost, real Wi-Fi behaviour and real clock
> jitter are Phase 0's questions and no result here bears on them (§3.4). When
> hardware produces its first fan-out and skew numbers, the simulator gets
> re-parameterised from them — never the reverse (risk R9).

The run these numbers come from is recorded verbatim in
[`phase0c-protocol.md`](phase0c-protocol.md). Reproduce everything below with:

```bash
python -m pytest -q          # 84 tests
python -m sim.scenarios all  # the six scenarios, with their metrics
```

## Status against the Phase 0c gate

| Gate criterion (§3.5) | Result | Where |
|---|---|---|
| Two simulated nodes produce identical buffers at the same `sceneTime` | pass | `basic_play`, at 0 / 700 / 2100 / 3400 / 4200 ms |
| A node joining mid-scene converges to the same buffer | pass | `late_join` — joins at 2000 ms, empty cache, pulls, seeks |
| A node that misses `PLAY` recovers on the next heartbeat | pass | `missed_command` — recovered 1250 ms after the lost push |
| Any node's buffer can be captured to PNG | pass | `sim/capture.py`, asserted equal to the node's own frame |
| The mosaic renders | pass | `sim/wall.py`, including a heterogeneous set |
| The whole suite runs in CI without hardware | pass | `.github/workflows/sim.yml`; stdlib only |

Suite runtime: **~15 s** for 84 tests, of which ~14 s is the six scenarios.
A 4.2 s scene plays in well under 4.2 s of wall clock because time is virtual.

## Measured (simulated) numbers

Delivery model unless stated otherwise: 8 ms one-way latency, ±3 ms jitter, no
asymmetry, 6 ms server-side cost per unicast push, 32 concurrent workers.

### Sync

| Quantity | Value | Scenario |
|---|---|---|
| Scene-time skew, 2 nodes, clean clocks | 0.00 ms | `basic_play` |
| Scene-time skew, 4 nodes, ±4 ms jitter, ±40 ppm drift, 1.5 ms asymmetry | 3.07 ms | `clock_jitter` |
| Residual clock error after Cristian sync | equals the modelled asymmetry, exactly | `test_sync_error_equals_the_modelled_asymmetry` |
| Clock spread after 30 min with no re-sync (±40 ppm) | 150.8 ms | `clock_jitter` |
| Clock spread one heartbeat after re-sync resumes | 4.21 ms | `clock_jitter` |

The 20 ms target and 35 ms hard bound (§10) are encoded in
`sim/assert_sync.py` and asserted, not merely reported.

### Fan-out and `DISPLAY_LEAD_MS`

Concurrent fan-out, time to the **last** node:

| Participants | Fan-out to last node |
|---|---|
| 10 | 16.2 ms |
| 100 | 33.5 ms |
| 300 | 70.3 ms |

* Sequential fan-out (`fanout_concurrency = 1`) at 300 nodes: **1806 ms**,
  against a 2000 ms lead. This is §20's argument, measured: concurrency is not
  an optimisation at the design bound, it is the requirement.
* `DISPLAY_LEAD_MS` derived from the 300-node curve with a 2× safety factor:
  **250 ms**, against the 2000 ms inherited from `mementum-led`. The inherited
  constant has ~8× more headroom than this model needs — but the number that
  replaces it must come from a real AP, not from here (open question 12).
* One unreachable node holds a worker for its full 2 s timeout and delays no
  healthy node (slowest healthy delivery: 33.5 ms).

### Recovery

| Case | Latency | Mechanism |
|---|---|---|
| Missed `PLAY` push | 1250 ms (one heartbeat interval + round trip) | schedule returned on heartbeat |
| Late join, scene cached | immediate seek | schedule returned on REGISTER |
| Late join, empty cache | one manifest + one asset pull, then seek | pull-based asset plane |
| Leader change | active scene cancelled, new schedule at a new epoch | option C (§11) |

All four resolve through the one mechanism — `state = evaluate(sceneTime)` —
with no retry path, no replay and no catch-up animation (§19).

## What this exercise found

* **The boundaries hold.** A simulated node is `ParticipantCore` with three
  adapters swapped; nothing in `sim/` reimplements protocol, evaluation or
  rendering, and `tests/test_layering.py` fails the build if that changes
  (risk R11). The architecture claim in §3.1 survived contact.
* **Serialised node I/O was the first thing that broke at scale.** An early
  transport model advanced global virtual time for every request, which
  serialises 300 nodes' heartbeats and made the swarm fall out of the scene
  entirely. Requests now cost the *requesting* node a stall and no global time.
  The residual limitation is recorded in `sim/transport.py`: server-side
  queueing under simultaneous requests is not modelled, only fan-out is.
* **`DISPLAY_LEAD_MS = 2000` looks generous** at every population inside the
  design bound, in this model. Worth measuring on hardware early, because it is
  pure latency between "play" and anything appearing.

## Not answered here

Phase 0's entire question — frame rate, PSRAM bandwidth, flush cost, whether
ThorVG/LVGL exposes usable stroke progress (R1), real Wi-Fi behaviour, real
clock jitter distributions. Also not answered: whether this reference renderer
and LVGL/ThorVG agree closely enough for cross-renderer golden frames, which is
Phase 1 conformance work and proposal open question 7.
