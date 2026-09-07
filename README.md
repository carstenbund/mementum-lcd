# mementum-lcd

Continuation of the Mementum project with an LCD scene player: synchronized
vector scenes played across ESP32 panels and Linux nodes from one shared clock.

* [`todo.md`](todo.md) — the architecture proposal (what and why).
* [`docs/implementation-plan.md`](docs/implementation-plan.md) — what to build,
  in what order, and how we know it worked.

## What is built

**Phase 0c — the simulation harness** (plan §3). The participant core and a
simulator that runs it with time, transport and display under our control, so
the protocol can be developed and tested in one process, in CI, without
hardware.

```text
mementum_node/core/   the real participant core — model, evaluator, renderer,
                      protocol, cache, clock, pacers, sequencer
mementum_node/players/  the C/LVGL player, bound with ctypes
poc/player/           that player's C sources, shared with the ESP-IDF build
sim/                  the three substitutions (clock, transport, sink),
                      the harness, and the scenarios
poc/scenes/           the hand-written test scene
tests/                the Phase 0c gate, in CI
docs/phase0c-report.md     measured (simulated) numbers
docs/phase0c-protocol.md   the test run, for the record
poc/host-player/           LVGL/ThorVG player on Linux — the R1 experiment
docs/phase0-host-protocol.md  that experiment, and what follows from it
docs/phase0-c-player-protocol.md  the C player, and the mixed swarm
```

The rule the simulator obeys, and the reason it is worth anything: **a
simulated node runs the real participant core; only the clock, the transport
and the sink are substituted.** `tests/test_layering.py` fails the build if
logic drifts into `sim/`.

**Phase 0, host side** (plan §0.3 steps 1–3, §3.7). LVGL v9.5.0 with ThorVG
builds headless on Linux and answers risk R1: a runtime stroke reveal works, so
`progress` stays a runtime property in the IR. The device player's C sources —
scene model, JSON loader, easing, evaluator, LVGL renderer — compile for the
host as a shared library, and a simulated node can run **that** instead of the
Python reference. A swarm can mix the two. Phase 0b is not started and no board
exists yet. A number measured in simulation or on a desktop is a design
property; a hardware gate needs a hardware number.

## Running it

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
```

The core and the simulator are stdlib-only; the venv exists for `pytest`.

```bash
.venv/bin/python -m pytest -q
```

Run the scenarios and read their checks:

```bash
.venv/bin/python -m sim.scenarios all
```

To include the C player — the same sources the ESP32 will run:

```bash
poc/host-player/fetch-lvgl.sh && poc/host-player/fetch-cjson.sh
make -C poc/host-player -j4 lib
```

Without it everything still runs; the scenarios and tests that need it skip.

```text
basic_play      two nodes, identical buffers at the same sceneTime
late_join       a node joins mid-scene with an empty cache and converges
missed_command  a lost PLAY recovers on the next heartbeat
leader_change   option C — cancel, then a fresh start in a new clock epoch
clock_jitter    offset, drift and jitter; a 30-minute drift soak
fanout_scale    10 / 100 / 300 nodes; DISPLAY_LEAD_MS derived from the curve
mixed_renderers  half the swarm on Python, half on C/LVGL, same failures
```

Watch it rather than read it — capture any node's buffer, or the whole
installation as one mosaic:

```bash
.venv/bin/python -m sim.capture --scenario basic_play --times 0,1050,2100,4200 --out sim-out
```

```bash
.venv/bin/python -m sim.wall --mixed --at 3800 --out sim-out/wall.png
```

`--mixed` builds a heterogeneous set — 480×320 beside 320×240 beside 1920×1080
beside a projector — which is how the design-canvas `fit` policy gets checked:
by looking at it.
