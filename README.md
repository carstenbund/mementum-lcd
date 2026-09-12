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
mementum_node/server/      the control server — mementum-led's, ported
mementum_node/client/      a panel on the network: register, heartbeat, draw
poc/firmware/mementum_lcd/ the ESP32-S3 sketch — built in CI, never run
poc/firmware/idf/          the same firmware as an ESP-IDF project
docs/esp32-bring-up.md     the plan for putting it on a board — both paths
docs/decisions/0012-the-guide.md  the show controller, and why it has no cursor
docs/decisions/0013-control-server-ported.md  the routes, and mixed LED/LCD walls
```

**The control server is `mementum-led`'s, ported.** Same routes, same parameter
names, same sentences a firmware parses — so a panel that speaks that protocol
works here unmodified, and **one wall can hold both kinds**: an LED matrix
scrolling the string a cue was written from while an LCD beside it draws the
same words as pen strokes.

```bash
python -m mementum_node.server --show poc/shows/opening.json --port 8080
python -m mementum_node.client --server http://localhost:8080 --units 4
curl "localhost:8080/effect?data=hallo&stagger=tile"   # one long marquee
curl "localhost:8080/identify?seconds=10"              # read the wall
```

A panel is a **client**: it registers, syncs its clock, fetches the scenes it
is told to show, and draws them — it never serves the wall, because the server
hands out scenes and a device cannot hold the library
([decision 0014](docs/decisions/0014-panels-are-clients.md)).

**The show is a document.** A guide is a running order — `play text`,
`play animation`, `play effect`, each at a timecode — compiled by
`tools/guide.py` into a package the server runs. A cue's timecode plus the
show's epoch is a `displayAt`, so nothing new reaches the device and nothing
anywhere accumulates: what is on the wall is the last scene cue whose moment
has passed.

```bash
python tools/guide.py poc/shows/opening.html --out poc/shows/opening.json
MM_MODE=1920x1080 python poc/show_demo.py poc/shows/opening.json 60 4x4 drm
```

**The screen is the stack's.** `drm_screen` owns the layer model, the command
records and the service; `drm_screen_lvgl` is the LVGL renderer plugin, binding
the C in `poc/player/`; `drm_composer` compiles screen-HTML, and a layer of
`<path>` elements compiles to a *scene document* rather than a bitmap. That
document is `drm_scene_ir` — the same bytes the ESP32 player loads — so the
composer targets a panel without running on one: compile on a host, ship a
couple of kilobytes, and the C draws it. See
[decision 0011](docs/decisions/0011-one-stack-two-devices.md).

```bash
pip install -e ~/code/drm_screen_lvgl        # or: pip install -r requirements-dev.txt
make -C poc/host-player -j4 lib              # builds libdrm_screen_lvgl.so too
python poc/screen_demo.py poc/scenes/du-kannst.json 10 drm
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
