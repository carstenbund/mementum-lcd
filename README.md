# mementum-lcd

A synchronized symbolic display system. Vector symbols — memes as animated
objects with internal structure — revealed, transformed and combined on one
shared clock across ESP32 panels, Raspberry Pi displays and a stream.

```text
Mementum LED          Mementum LCD
  text is the payload    symbols are the payload
  movement is scrolling  movement is composition
```

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
mementum_node/screen/   the screen, adapted from drm_screen + drm_screen_lvgl
poc/player/           that player's C sources, shared with the ESP-IDF build —
                      also what drm_screen_lvgl binds
sim/                  the three substitutions (clock, transport, sink),
                      the harness, and the scenarios
poc/scenes/           the hand-written test scene
tests/                the Phase 0c gate, in CI
docs/step-report.md        where the project stands
poc/screens/               screen-HTML with a timeline — the authoring layer
docs/phase0c-report.md     measured (simulated) numbers
docs/phase0c-protocol.md   the test run, for the record
poc/host-player/           LVGL/ThorVG player on Linux — the R1 experiment
docs/phase0-host-protocol.md  that experiment, and what follows from it
docs/phase0-c-player-protocol.md  the C player, and the mixed swarm
docs/playbooks/linewave.md    the next test: one line, coming in and waving out
docs/decisions/0011-one-stack-two-devices.md  how this repo sits in drm_stack
poc/shows/                 cue sheets — the running order, with timecodes
docs/decisions/0012-the-guide.md  the show controller, and why it has no cursor
```

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
