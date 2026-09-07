# Implementation Plan

Companion to [`../todo.md`](../todo.md) (the architecture proposal, revision 2).
The proposal says *what* and *why*; this document says *what to build, in what
order, and how we know it worked*. Section references (§n) point into the
proposal.

**Status:** nothing is built yet. `mementum-lcd` currently contains only the
proposal.

---

## 1. How to read this

Every phase below has the same four parts:

* **Goal** — one sentence.
* **Deliverables** — files and artefacts that must exist when it is done.
* **Tasks** — the work, in a sensible order.
* **Gate** — falsifiable criteria. A phase is not finished until the gate passes,
  and later phases must not start on assumptions the gate has not confirmed.

Where a task is really a question, it says so. Phase 0 in particular is an
experiment, not a build: its purpose is to find out whether the hardware and the
libraries can do the job at all, and it is allowed to fail.

---

## 2. Tracks

Two tracks run in parallel and meet at the IR:

```text
  ESP32 track            Linux track            Simulation track
  (Phase 0)              (Phase 0b)             (Phase 0c)

  LVGL/ThorVG on host    drm_composer timeline  virtual clock
  then on hardware       stream/record sinks    in-process transport
  two-device skew        offline determinism    headless render sinks
        │                       │                      │
        └───────────────┬───────┴──────────────────────┘
                        │
                   Phase 1 — drm_scene_ir
                   define only what the tracks proved
                        │
             ┌──────────┴──────────┐
       Phase 2 composer      Phase 3 SVG
                        │
                   Phase 4 protocol      ← developed in simulation,
                        │                  validated on hardware
                   Phase 5 recovery + timing
                        │
                Phase 5b transport (deferred)
                        │
                   Phase 6 composition
```

The three tracks are genuinely independent. The Linux track needs no ESP32 and no
IR; the simulation track needs neither hardware nor the IR spec. Do not serialise
them.

---

## 3. Simulation-first development

Almost everything above the display driver can be developed and tested without
hardware, in one Python process, with time under our control. This should be the
default working mode rather than an afterthought.

### 3.1 Why the architecture already permits it

The simulator needs exactly three substitutions, and the proposal already argues
for all three seams on unrelated grounds:

| Swap | Real | Simulated | Seam from |
|---|---|---|---|
| sink | `drm_screen` → DRM/KMS | headless RGBA buffer | §14 — a sink is a sibling backend |
| transport | unicast HTTP | in-process queue | §20 — the control plane is semantics, the binding is replaceable |
| clock | Cristian over HTTP | virtual clock, per-node offset | §20 — `sharedNow()` is the only thing playback depends on |

`drm_display` already ships headless backends and `drm_stack`'s integration tests
already run with no display hardware, so the sink substitution costs nothing
today.

This gives the simulator a second job beyond convenience: **it is a test of the
architecture, not just of the code.** If a simulated node cannot be assembled
from the real participant core by swapping those three adapters, the boundaries
are wrong and we have found that out cheaply.

### 3.2 The rule that makes it worth anything

> The simulated node runs the **real** participant core. Only the clock, the
> transport and the sink are substituted.

A simulator that reimplements the protocol proves nothing. Any logic that exists
only in `sim/` is a bug in the layering.

### 3.3 What simulation buys

* **Deterministic time.** Skew, drift, missed commands, leader change and late
  join become scripted scenarios instead of induced Wi-Fi load. Tests run faster
  than real time and produce identical results on every run — so they belong in
  CI.
* **Frame-level proof of the core claim.** Two simulated nodes rendering the same
  scene at the same `sceneTime` must produce **identical buffers**. That is the
  property the entire architecture rests on, and it is far easier to assert on
  a buffer than to measure on a panel.
* **Scale without a swarm.** 300 simulated participants on a laptop exercise the
  registry, concurrent fan-out timing and the `DISPLAY_LEAD_MS` derivation
  (§20's design bound) long before 300 boards exist — and probably instead of.
* **Injectable failure.** Packet loss, dead clients holding a 2 s timeout, clock
  jitter, a leader disappearing mid-scene. All scriptable, none requiring
  someone to unplug something.

### 3.4 What it cannot answer

State this plainly, because the temptation to let a green simulation stand in for
a hardware gate will be real:

* frame rate, PSRAM bandwidth, LCD flush cost — Phase 0's entire question
* whether ThorVG/LVGL actually expose stroke progress (risk R1)
* real Wi-Fi behaviour: soft-AP contention, multicast basic rates, timeout
  distributions
* real clock jitter — the simulator can *model* a jitter distribution, but its
  parameters must come from hardware measurement

> **Simulation is the development environment; hardware is the validation gate.**
> A number measured in simulation is a design property. A number measured on
> hardware is a physical property. A simulated number never satisfies a hardware
> gate.

### 3.5 Phase 0c — the harness

Runs parallel with Phases 0 and 0b. Needs only the existing `drm_stack` checkout
and the Phase 0 hand-written scene.

```text
mementum-lcd/
  sim/
    clock.py            virtual clock; per-node offset and jitter injection
    transport.py        in-process binding; loss, latency, timeout injection
    node.py             simulated participant = real core + headless sink
    harness.py          spin up 1 server + N nodes, run a scenario, assert
    assert_sync.py      buffer comparison across nodes at the same sceneTime
    capture.py          dump any node's composited buffer to PNG
    wall.py             live tune-in / mosaic of N nodes' buffers
    scenarios/
      basic_play.py
      late_join.py
      missed_command.py
      leader_change.py
      clock_jitter.py
      fanout_scale.py   10 / 100 / 300 nodes
```

**Gate.** Two simulated nodes produce identical buffers at the same `sceneTime`;
a node joining mid-scene converges to the same buffer; a node that misses `PLAY`
recovers on the next heartbeat; any node's buffer can be captured to PNG and the
mosaic renders; the whole suite runs in CI without hardware.

### 3.6 Seeing the result — frame capture and the virtual video wall

A headless node still has a complete composited frame in memory; nothing about
being headless makes it invisible. Capturing that buffer turns the simulation
from a pass/fail suite into something you can *watch*.

**Capture at the sink boundary, not from hardware.** `drm_screen` composites into
an RGBA frame and hands it to a backend adapter — that frame is the capture
point, and it is the same place a sink lives (§14). No dumb-buffer mmap, no
scanout readback, and the identical tool therefore works for a simulated node, a
headless test, and a real Raspberry Pi node. Capture is a property of the sink
layer, not of the simulator.

Three things this makes possible:

* **Tune in to any node.** Pick node *N*, watch its buffer live. With 300
  simulated participants, this is the difference between a legible swarm and a
  log file.
* **The virtual video wall.** Compose every node's buffer into a mosaic — the
  whole installation on one screen. For a heterogeneous set (480×320 beside
  1920×1080 beside a projector) this is how the design-canvas `fit` policy (§6)
  gets checked: by looking at it.
* **Skew, visualised.** Capture every node at one wall-clock instant and diff.
  Who is behind, and by how much, becomes a picture rather than a number — the
  in-simulation counterpart of the GPIO frame markers (§0.4).

**Golden frames.** Store reference PNGs per scene and time, diff them in CI.
Between *identical* renderers the comparison can be exact; between different ones
(Python reference versus C player) it needs a perceptual tolerance, because
antialiasing and text metrics legitimately differ — which is itself the
measurement that answers proposal open question 7. Pin library versions or the
diffs will rot (risk R12).

**On the ESP32, capture is not free.** There is no spare full frame to ship. Two
tiers instead:

* **Frame hash, always on.** Each node hashes its rendered frame at a given
  `sceneTime` and reports it. Cheap, tiny, and a direct check that two devices
  really do render the same picture at the same moment. Valid only between
  *identical* renderers — device against device, or device against the same C
  player on the host (§3.7) — never against the Python reference.
* **Thumbnail on request, debug only.** Downscaled RGB565 over HTTP, on demand,
  never in the frame loop.

The frame hash deserves emphasis: it extends the buffer-identity assertion from
the simulator onto real hardware at almost no cost, and it is the only way to
verify two panels agree without pointing a camera at them.

### 3.7 The C player on the host

The second half of the same idea, and it lands later — after Phase 0 has
established which LVGL/ThorVG APIs actually exist.

The ESP32 player's C sources (scene model, JSON loader, evaluator, and the
renderer above the display driver) should compile for the host, with LVGL's SDL
or fbdev port standing in for the panel. That buys three things:

1. **One evaluator, not two.** The same C code that runs on the device runs in
   the Phase 1 conformance suite, so C-versus-Python divergence (risk R6) is
   caught by construction rather than by discipline.
2. **Debuggable player.** gdb, ASan and valgrind on the player logic, which is
   miserable on-device.
3. **An early answer to proposal open question 7.** A C player running on Linux
   over LVGL — which also has its own DRM/KMS backend — *is* the "shared runtime"
   candidate for the Raspberry Pi node. The choice between it and a native Linux
   player becomes an experiment rather than an argument, at almost no extra cost.

---

## 4. Milestones and gates

| # | Milestone | Repo | Gate |
|---|---|---|---|
| M0 | ESP32 renders an animated path from a JSON scene | `mementum-lcd` | ≥ 30 fps sustained, measured |
| M0.1 | Two devices in visible sync | `mementum-lcd` | skew ≤ 35 ms hard, ≤ 20 ms target |
| M0b | Linux composer animates; frames reach an encoder | `drm_composer`, `drm_screen` | a 4 s scene renders to file, deterministically |
| M0c | Simulated swarm plays a scene in one process | `mementum-lcd` | two nodes produce identical buffers at the same `sceneTime` |
| M1 | `drm_scene_ir 1` specified and versioned | `drm_stack` | both players pass the conformance suite |
| M2 | `drm_composer` emits IR; DRM path unchanged | `drm_composer` | existing integration tests still green |
| M3 | SVG reconciled | `drm_composer`, `drm_resvg` | raster and vector paths both exercised, never confused |
| M4 | Protocol carries scenes | `mementum-lcd` | sim: 300 nodes green in CI · hw: a scene plays on ESP32 + Pi from one `PLAY` |
| M5 | Recovery works | `mementum-lcd` | sim: all scenarios green · hw: late join, missed command, dropped frame self-heal |

---

## 5. Phase 0 — prove the embedded renderer

**Goal.** Establish that an ESP32-S3 with LVGL/ThorVG can render an animated
vector scene at a usable frame rate, and that two of them stay visibly
synchronized from a shared clock.

No `drm_composer` changes. No Python. No Mementum networking beyond the clock.

### 0.0 Decisions to take first

Two choices block everything else and should be made deliberately, not by
inheritance from `mementum-led`.

**Toolchain: ESP-IDF, not Arduino IDE.** `mementum-led` is an Arduino IDE
project. LVGL 9 with vector graphics, PSRAM tuning, RGB/parallel panel drivers
and DMA bounce buffers are all substantially better supported under ESP-IDF, and
the player is where that support matters. Plan on ESP-IDF for the player, and
port the networking layer across at Phase 4 (Arduino-as-component is a fallback
if the port proves expensive). **This is a divergence from the existing firmware
and should be confirmed before work starts.**

**Panel interface.** §14 of the proposal leaves RGB/parallel versus SPI open, and
notes the tension: RGB panels give bandwidth but require a full framebuffer in
PSRAM. Buy one of each if budget allows; measure both (task 0.6). If only one,
take RGB/parallel — it is the harder case and the one the architecture should not
assume away.

Record both decisions in `docs/decisions/` when made.

### 0.1 Deliverables

```text
mementum-lcd/
  poc/
    esp32-player/            ESP-IDF project
      main/
        main.c
        scene_json.c/.h      JSON → in-memory scene
        scene_model.h        Scene / Layer / Object / Animation structs
        evaluator.c/.h       state = evaluate(sceneTime)
        render_lvgl.c/.h     scene state → LVGL/ThorVG objects
        clock_sync.c/.h      serverNow(), Cristian over HTTP
        measure.c/.h         GPIO frame markers, fps counters
      sdkconfig.defaults
    scenes/
      poc-signature.json     the hand-written test scene
  docs/
    phase0-report.md         the measurement report (see 0.7)
    decisions/
      0001-toolchain.md
      0002-panel-interface.md
```

### 0.2 The test scene

480 × 320 design canvas, two layers:

```json
{
  "version": 1,
  "width": 480,
  "height": 320,
  "fit": "contain",
  "layers": [
    { "id": "background", "z": 0, "objects": [
      { "type": "rect", "id": "bg", "x": 0, "y": 0, "w": 480, "h": 320,
        "fill": "#101014" } ] },
    { "id": "writing", "z": 10, "objects": [
      { "type": "path", "id": "signature", "d": "M 40 200 C …",
        "stroke": "#e8e8f0", "stroke_width": 3, "progress": 0 },
      { "type": "text", "id": "caption", "content": "mementum",
        "x": 40, "y": 250, "font_id": "mementum-sans-24",
        "color": "#8890a0" } ] }
  ],
  "animations": [
    { "target": "signature", "property": "progress", "start": 0,
      "duration": 4200, "from": 0, "to": 1, "easing": "ease-in-out" },
    { "target": "caption", "property": "opacity", "start": 3000,
      "duration": 800, "from": 0, "to": 1, "easing": "linear" }
  ]
}
```

Text is in the scene from the first experiment on purpose (§9). If glyph
rendering turns out to be the expensive part, that must surface now, not at
Phase 4.

### 0.3 Bring-up order — host first, then hardware

Steps marked **[host]** need no board. Do them on the desktop with LVGL's SDL
port while hardware is on order; this retires the highest-value unknown (R1)
before anything is soldered, and everything written here is the same C that
later cross-compiles.

1. **[host] LVGL up.** SDL port, a moving rectangle, fps counter in place.
2. **[host] Vector up.** Render one static path via LVGL's vector API (ThorVG
   backed). *Verify what the API actually offers before designing around it.*
3. **[host] Stroke progress — the R1 question.** The classic reveal is a dash
   pattern — `dasharray = [len·p, len]` with the path length precomputed — but
   confirm what ThorVG exposes through LVGL. If dashing is unavailable, fall back
   to path splitting at compile time, which changes the IR (`progress` becomes a
   compile-time slice, not a runtime property) and must be reported before
   Phase 1.
4. **[host] Text.** One preprocessed LVGL font asset, referenced by `font_id`.
   No TTF on device (§9).
5. **Board bring-up.** ESP-IDF project, PSRAM enabled and confirmed, panel
   driving a solid colour. Log free internal RAM and PSRAM at boot. Then re-run
   steps 1–4 on hardware; the deltas are the interesting part.
6. **JSON loader.** Parse the scene from SPIFFS/LittleFS into the structs. Load
   time is measured separately from frame time (§17).
7. **Evaluator.** `state = evaluate(sceneTime)` — pure, no accumulation, no frame
   counters. `seek()` to an arbitrary time must give the same result as arriving
   there by stepping.
8. **Renderer.** Push evaluated properties into LVGL objects; render; flush.
   Keep the display driver behind a thin interface so the host build (§3.7) and
   the device build differ only there.
9. **Clock.** Port `serverNow()` / `syncClock()` from `mementum-led`
   (`ws_wifi.cpp:196`) — Cristian, best of three, refreshed on heartbeat.
10. **Second device.** Same scene, same `T0`, shared clock.

### 0.4 Instrumentation (do this before measuring, not after)

Two mechanisms, both cheap:

* **GPIO frame markers.** Toggle a pin at the start of each rendered frame and
  pulse a second pin at scene start. A two-channel logic analyser or scope across
  both devices measures skew directly at microsecond resolution — far better than
  filming, and it works while the panels are showing anything at all.
* **High-speed video** as the human-facing confirmation: 240 fps phone video
  gives ~4 ms resolution, adequate against a 20 ms budget, and it is what you
  show people.

* **Frame hash** (§3.6). Each device hashes its rendered frame and reports it on
  request. Two devices rendering the same scene at the same `sceneTime` must
  agree — a direct check on buffer identity that costs almost nothing and needs
  no camera. Build it in during Phase 0; it stays useful for the life of the
  project.

Also log per frame: evaluate time, render time, flush time, and free heap. The
1 % low fps figure matters more than the average (§17).

### 0.5 Sync test

```text
ESP32 A         ESP32 B
   │               │
   └── same scene ─┘
         same T0
```

Measure:

* start skew — offset of the scene-start pulses
* stroke-position skew — offset of frame markers mid-animation
* long-run drift — repeat after 30 min without re-sync, then with heartbeat sync
* recovery — under induced load: delayed rendering, deliberately dropped frames,
  heavy Wi-Fi traffic

Playback progress must derive **exclusively** from `serverNow() - displayAt`. Any
accumulator in the render path is a bug, not a tuning parameter.

### 0.6 Performance report

`docs/phase0-report.md` records, per configuration tested (§17):

```text
display resolution      pixel format         display interface
PSRAM type / speed      LVGL draw buffer size
scene complexity        average fps          1 % low fps
CPU usage               PSRAM usage
evaluate / render / flush time
scene load time (separate from frame time)
```

Compare **RGB565 against ARGB8888** where alpha is required, and both panel
interfaces if both were bought.

### 0.7 Gate

| Criterion | Threshold |
|---|---|
| Sustained frame rate | ≥ 30 fps; note whether 60 is reachable |
| Inter-device visual skew | ≤ 20 ms target, ≤ 35 ms hard bound |
| Recovery after induced frame loss | correct state on the next rendered frame |
| Scene load time | recorded; no parsing during the frame loop |
| Stroke progress | achieved at runtime, or the fallback documented |

**Kill criteria.** If ≥ 30 fps is unreachable on both panel interfaces with a
scene this simple, stop and reconsider the runtime before writing any IR spec.
That is the point of doing this first.

---

## 6. Phase 0b — the Linux track (parallel)

**Goal.** Give the existing Linux stack the two things it lacks: a timeline, and
somewhere other than DRM to send frames.

Needs no ESP32 and no IR. Runs concurrently with Phase 0.

### 0b.1 Animation in `drm_composer`

The composer has no timeline at all today. Add one as **metadata plus an
evaluator**, keeping the package stateless (§10) — the evaluator is a pure
function, not a playback loop.

```text
drm_composer/
  animation.py      Animation dataclass; easing functions; evaluate(scene, t)
  parser.py         parse <animate target= property= from= to= start= duration= easing= />
  scene.py          Animation added to the scene model
```

Tasks:

1. `Animation` in the scene model; `<animate>` in the parser.
2. Easing functions — `linear`, `ease-in`, `ease-out`, `ease-in-out` — written to
   be **reimplementable**: exact formulae, documented, unit-tested against fixed
   vectors. These become normative in Phase 1 (§14); getting them right here
   avoids Pi/ESP32 divergence that presents as a sync bug.
3. `evaluate(scene, t) -> Scene` returning a scene with animated properties
   resolved. Pure; same `t` gives the same result.
4. `paint_scene(evaluate(scene, t))` renders a frame at time `t`. No change to
   `paint_scene` itself.

### 0b.2 Stream and record sinks

A sink is a **sibling of `DrmDisplayBackend`** (§14), not a new layer. It receives
a composited RGBA frame from `drm_screen`'s backend adapter.

1. Confirm the seam: `DrmDisplayBackend.write(frame_rgba)` and the headless
   backends beside it.
2. `RecordBackend` — RGBA → encoder → file. Simplest useful form is piping raw
   frames to `ffmpeg`; a library binding can come later.
3. `StreamBackend` — RGBA → encoder → RTMP/SRT. Same conversion, different
   destination.
4. Keep the colour conversion inside the sink (RGBA→YUV420), mirroring the DRM
   backend's RGBA→BGRA. One conversion per adapter, nowhere else (invariant 1).

### 0b.3 Pacers

Three, differing only in what drives evaluation (§14):

| Pacer | Driven by | Clock |
|---|---|---|
| display | page flip | `sharedNow()` |
| stream | wall clock, fixed rate, CFR | `sharedNow()` |
| record | a loop over `t` | scene time directly |

The record pacer is the easiest thing to verify and the best early test of the
whole idea: rendering the same 4 s scene twice must produce byte-identical
output.

### 0b.4 Gate

* a 4 s animated scene renders to a video file, offline, faster than real time
* rendering it twice is byte-identical
* easing unit tests pass against fixed vectors
* the existing `drm_stack` integration tests are unchanged and green
* streaming a scene works at a fixed frame rate, verified by the file's timestamps

---

## 7. Phase 1 — specify `drm_scene_ir`

**Goal.** Turn what Phases 0 and 0b proved into a versioned, neutral contract.

**Not before both gates pass.** The IR is defined by what worked, not by what was
imagined.

### 1.1 Deliverables

```text
drm_scene_ir/                    (own repo, cloned by drm_stack/setup.sh —
                                  consistent with the other four packages;
                                  see proposal open question 3)
  SPEC.md                        normative: schema, semantics, easing formulae
  schema/scene-ir-1.json         JSON Schema for validation
  drm_scene_ir/
    __init__.py
    model.py                     Scene / Layer / Rect / Text / Image / Path
    validate.py
    serialize.py
    evaluate.py                  reference evaluator
  tests/
    conformance/                 scene + time + expected-state vectors
```

### 1.2 Content

Exactly the v1 set (§6): `Scene`, `Layer`, `Rect`, `Text`, `Image`, `Path`,
`Transform`, `Opacity`, `Animation`. No SVG node. `Circle`, `Group`, `Clip` only
when something needs them.

Plus, from the proposal:

* **design canvas** — `width`/`height` are logical; optional `fit` of
  `contain` (default) / `cover` / `stretch` (§6)
* **minimum physical stroke width and text size**, or an explicit statement that
  players clamp — decided by what Phase 0 showed at 480×320 (§6, open question 8)
* **normative easing** — formulae precise enough to reimplement in C++ (§14)
* **version** in every document; `scene_ir: 1` is the registration gate (§18)

### 1.3 Conformance suite

The suite is the deliverable that makes the contract real: a set of
`(scene, t) → expected state` vectors that both the Python reference evaluator and
the ESP32 C evaluator must satisfy. Wire it into `drm_stack`'s `make test` and
into the ESP32 project's test build.

### 1.4 Gate

* the Phase 0 hand-written scene is expressible in `drm_scene_ir 1` without loss
* both evaluators pass the conformance suite
* `SPEC.md` documents easing precisely enough that a third implementation could
  be written from it alone

---

## 8. Phase 2 — `drm_composer` emits IR

**Goal.** A second output alongside the existing command batch.

```text
markup → parser → Scene → ┬→ paint_scene → drm_screen commands   (unchanged)
                          └→ ir_emitter  → drm_scene_ir document  (new)
```

Tasks:

1. `drm_composer/ir_emitter.py` — `Scene → drm_scene_ir` document.
2. Absolute coordinates pass through unchanged. **No `layout.py`** (§0, §25).
3. **No `targets/` package.** Transport stays in `drm_screen` (§4).
4. Round-trip test: markup → IR → reference evaluator → raster, compared against
   `paint_scene` output for a static scene.

**Gate.** The DRM path is byte-identical to before; `drm_stack` integration tests
green; a scene authored in markup runs on the ESP32 player unmodified.

---

## 9. Phase 3 — reconcile SVG

**Goal.** Two distinct capabilities, never confused (§8).

1. **SVG as raster asset** — `<img src="x.svg">` through `drm_resvg`, per
   `drm_stack`'s existing Stage 1. That roadmap text stands unchanged.
2. **SVG as authoring source** — a compile-time converter extracting the
   supported subset (§7) into IR `Path`/`Rect` objects.

Tasks: implement `drm_resvg` per its spec if not already done; write the subset
converter; make it **fail loudly** on unsupported SVG features rather than
silently dropping them; document which features are in the subset.

**Gate.** Both paths exercised in tests. A single SVG file used both ways
produces a visually equivalent result. No code path where one silently becomes
the other.

---

## 10. Phase 4 — Mementum scene protocol

**Goal.** Scenes distributed and played across ESP32 and Pi from one command.

### 4.1 Control plane

Unicast HTTP only — one binding, one protocol (§20). Multicast is Phase 5b.

```text
PLAY   scene=42 seq=283 at=<timecode>
STOP
SYNC
STATUS
```

**Implement the schedule as state, not an event** (§19). The current schedule is
returned on heartbeat. This is not deferrable with multicast — it is what late
join and missed-command recovery both rest on, and skipping it is what would
eventually force a second protocol.

### 4.2 Registration

```text
REGISTER
device:       esp32-s3
role:         display
display:      480x320  rgb565
capabilities: scene_ir=1  vector=true  text=true  lottie=false
```

The sequencer determines playability before scheduling. A node that cannot render
a scheduled scene fails **visibly** — blank or a defined fallback — never
silently drifts (§18).

### 4.3 Asset plane

Pull-based, separate from control (§18):

```text
GET /scene/42/manifest
GET /asset/<hash>
```

Devices fetch what they lack. `READY scene=42` gates scheduling, or `displayAt`
is chosen from observed readiness. Cache in flash by content hash; decide
SPIFFS vs LittleFS here (open question 6).

### 4.4 Linux participant

Turn the server into a node (§13):

```text
mementum-node/
  core/         registration, clock, cache, loader, evaluator, pacer
  nodes/
    display.py  → drm_screen → DRM/KMS
    stream.py   → StreamBackend
    record.py   → RecordBackend
```

Lives in `mementum-lcd` (open question 11) so nothing Mementum-specific leaks
into `drm_stack`. Roles are configuration: a Pi may be AP, sequencer, asset
server and participant at once, or any subset (§13).

### 4.5 Gate

Developed in simulation, validated on hardware — two gates, not one.

**Simulation gate** (in CI, no hardware):

* 300 simulated participants register, receive `PLAY`, and render identical
  buffers at the same `sceneTime`
* fan-out timing recorded at 10 / 100 / 300 nodes; `DISPLAY_LEAD_MS` derived from
  the curve rather than assumed (open question 12)
* a node with an empty cache pulls the scene and joins without delaying anyone

**Hardware gate:**

* one `PLAY` starts the same scene on two ESP32s and a Pi, within the skew budget
* fan-out timing on the real AP is compared against the simulated curve, and the
  divergence is recorded (risk R9)

---

## 11. Phase 5 — recovery and robust timing

**Goal.** All three recovery cases resolve through the one mechanism (§19).

```text
dropped frame        │
missed PLAY          │──→  state = scene.evaluate(sharedNow() - T0)
node joins late      │
```

Tasks:

1. Mid-scene seek on join: `sceneTime = T - T0`, cached scene → seek immediately;
   uncached → pull, then seek to current time.
2. **Clock discontinuity policy — option C** (§11): leader change cancels the
   active scene and the new leader schedules a fresh start. An intentional
   restart, not an unexplained jump. Options A and B are explicitly later work.
3. Confirm unsigned-difference arithmetic throughout so `millis()` rollover is a
   non-event.
4. Define what is displayed between scenes — idle, loop, or blank (open
   question 5). Undefined today.

**Gate.**

**Simulation:** every scenario in `sim/scenarios/` green in CI — late join,
missed command, leader change, clock jitter — each asserted at buffer level, not
by inspection.

**Hardware:** a node power-cycled mid-scene rejoins at the correct position. A
leader killed mid-scene produces a clean restart. A scene shorter than the
asset-pull time is missed *gracefully* by an uncached node — documented
behaviour, not a hang.

---

## 12. Phase 5b — transport (deferred)

Not started until the render stack is done and fan-out is measurably the limit.
The trigger should be named before it is needed (open question 15): concurrent
fan-out to the last node exceeding some fraction of `DISPLAY_LEAD_MS`, or skew
attributable to fan-out.

When taken up, the shape is already decided (§20): repeated-keyframe multicast,
`PLAY` as the keyframe, keyframes alone sufficient, deltas as optimisation only,
control plane only, unicast retained as a fallback binding.

---

## 13. Phase 6 — richer composition

Only once everything above holds: Lottie, clipping, gradients, complex SVG,
nested timelines, additional easing curves, touch interaction, procedural layers.
Each justified by a scene that needs it.

---

## 14. Risk register

| # | Risk | Detect | Response |
|---|---|---|---|
| R1 | ThorVG/LVGL exposes no usable stroke-progress mechanism | Phase 0 task 0.3.4 | Compile-time path splitting; `progress` becomes a compile-time slice — changes the IR, must be reported before Phase 1 |
| R2 | ESP32-S3 cannot hold 30 fps with vector + text | Phase 0 gate | Reduce scene complexity, RGB565 only, or reconsider the runtime. Kill criterion |
| R3 | PSRAM bandwidth, not CPU, is the ceiling | 1 % low fps with large draw buffers | Smaller draw buffers, content-sized object buffers (§16), RGB565 |
| R4 | Clock skew exceeds 35 ms on a loaded soft AP | Phase 0 sync test | Shorter heartbeat sync interval; more Cristian samples; if it persists, revisit the budget with evidence |
| R5 | ESP-IDF port of the Arduino networking is expensive | Phase 4 | Arduino-as-component, or keep networking on the existing firmware and bridge |
| R6 | Easing diverges between Python and C++ | Conformance suite (Phase 1) | Fixed test vectors are the contract; the reference evaluator wins |
| R7 | Text at a scaled-down canvas is illegible | Phase 0 task 0.3.5 | Minimum physical size in the IR, or player clamping — decide in Phase 1 |
| R8 | Scope creep into layout, CSS, general SVG | Review against §25 | §25 is a list of refusals; use it |
| R9 | Simulation diverges from hardware — timing, loss, jitter | Compare the first hardware fan-out and skew numbers against the simulated curve | Re-parameterise the simulator from measurement; record the delta. The simulator is calibrated by hardware, never the reverse |
| R10 | *Process risk:* a green simulation is allowed to satisfy a hardware gate | Review at each phase gate | §3.4 — simulated numbers are design properties, hardware numbers are physical ones. Gates say which they require |
| R11 | Logic drifts into `sim/` and stops being tested in the real path | Anything in `sim/` that is not clock, transport or sink | §3.2 — the simulated node runs the real core; move it back |
| R12 | Golden-frame diffs rot across library versions | CI failures with no code change | Pin LVGL/ThorVG/Pillow versions; perceptual tolerance for cross-renderer comparison; regenerate goldens deliberately, never automatically |

---

## 15. Conventions

* **Branches** — one per phase, e.g. `phase-0/esp32-poc`.
* **Decisions** — `docs/decisions/NNNN-title.md`; short, dated, with the
  alternative that was rejected. The two Phase 0 decisions come first.
* **Measurements** — never asserted in prose without a recorded number. Phase 0's
  report is the template.
* **Open questions** — proposal §27 is the live list. Answering one means editing
  the proposal, not burying it in a commit message.
* **The refusal list** — proposal §25. Check any new dependency or subsystem
  against it before adding it.

---

## 16. Immediate next actions

1. Confirm the toolchain decision (ESP-IDF) — it diverges from `mementum-led`.
2. Order hardware: ESP32-S3 with PSRAM, RGB/parallel panel; a second board for
   the sync test; SPI panel if comparing.
3. Start Phase 0b in parallel — it needs nothing but the existing `drm_stack`
   checkout, and `animation.py` is on the critical path to Phase 1.
4. Write `poc/scenes/poc-signature.json` by hand. It costs an hour and it is the
   first real artefact of the whole project.
5. **Begin the host LVGL/ThorVG bring-up today** (§0.3 steps 1–4). It needs no
   board, and step 3 answers R1 — the single unknown most likely to change the
   IR. Do not wait for hardware to find that out.
6. Stand up `sim/` (§3.5) alongside Phase 0b. Both are pure-Python, both are on
   the critical path, and together they make Phases 4 and 5 mostly a matter of
   turning green scenarios into hardware confirmations.
