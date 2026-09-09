# Step report — where the project stands

* Date: 2026-09-09
* Revision: `4657939`
* Covers: everything built so far — Phase 0c, the Phase 0 host track, the
  exploratory work that followed, and the three things that came out of it:
  the screen, the show, and the wire.

**On the standard applied throughout.** Numbers are here because measuring is
cheap and repeatable, not because this is instrumentation. What is being built
shows handwriting that appears and is gone in seconds; the test that matters is
whether a person watching would notice something wrong. No hardware has been
touched, so **no hardware gate has been satisfied** and nothing here says
anything about frame rate, memory or real network timing on a device.

---

## 1. What exists

```text
mementum_node/core     4311 lines  the participant core: model, evaluator,
                                   renderer, protocol, guide, sequencer, clock
mementum_node/screen    340 lines  the screen, adapted from drm_screen + the plugin
mementum_node/server    989 lines  the control server — mementum-led's, ported
mementum_node/client    591 lines  a panel on the network
mementum_node/players   222 lines  the C player, bound with ctypes
sim/                   2469 lines  the three substitutions, harness, scenarios
tools/                 1367 lines  handwriting, symbols, the composer, the guide
poc/player/            2821 lines  the device's player and its schedule, portable C
poc/firmware/           478 lines  the ESP32-S3 sketch (never compiled — no board)
tests/                 3205 lines  309 tests, ~31 s, no hardware
docs/                  5 reports, 14 decisions, 1 playbook
```

Pinned dependencies, all vendored and fetched by script: **LVGL v9.5.0** (with
ThorVG inside it), **cJSON v1.7.18**, **Hershey stroke fonts**. The core and the
simulator are stdlib-only; the C player needs nothing but gcc. The screen comes
from `drm_screen` + `drm-screen-lvgl` and the control server from flask +
requests — all of which are *this project consuming the stack it belongs to*
rather than dependencies it went looking for.

## 2. What has been proven

### The simulator (Phase 0c)

Two nodes render identical buffers at the same `sceneTime`; a node joining
mid-scene converges; a node that misses `PLAY` recovers on the next heartbeat;
300 participants register and play in CI. Concurrent fan-out reaches the last of
300 nodes in **70 ms** against **1806 ms** sequential — §20's argument, measured.
`DISPLAY_LEAD_MS` derived from that curve is **250 ms** against the 2000 ms
inherited from `mementum-led`.

### The renderer, on the host (Phase 0)

LVGL 9.5 with ThorVG builds headless in **10 seconds** with nothing but gcc.
Risk **R1 is closed**: a runtime stroke reveal works through
`lv_draw_vector_dsc_set_stroke_dash`, tracking arc length to within 1 %, so
`progress` stays a runtime property and the IR was never forced to carry
pre-sliced geometry.

### One evaluator, not two

The device's C sources — scene model, JSON loader, easing, evaluator, renderer —
compile for the host and run inside the unchanged simulator. C and Python agree
to **8x10⁻⁸** on easing across 4004 sample points and **6x10⁻⁸** on evaluated
properties. Risk **R6 is closed**: divergence is now a build-time check rather
than a matter of discipline.

A mixed swarm — two nodes on each renderer — survives a lost `PLAY`, two
late joins and a leader change. Within a renderer family frames are
byte-identical; across families they are the same picture (worst case **1.5 %
ink apart, 0.13 px centroid**).

### The content vocabulary

| | |
|---|---|
| `progress` | fraction of the total ordered drawing length; strokes drawn in sequence |
| `sine` | a travelling wave across the picture |
| `helix` | the same wave into the picture as well, projected, with depth drawn as width and brightness |
| ripple | a transient disturbance from a touch, travelling along the stroke |
| phases | several animations on one property, at different times |

All of it evaluated identically by both players, and all of it a pure function
of time — nothing accumulates anywhere.

### The second layer

A touch is answered locally and reported over the existing unicast plane; the
sequencer schedules the same ripple on every other unit at a time set by how far
away it stands, so a gesture crosses a room of nine units in **946 ms** from a
corner and **431 ms** from the centre. Ripples are transient, so unlike the
schedule they are deliberately fire-and-forget.

## 3. Decisions taken

| | |
|---|---|
| [0003](decisions/0003-simulation-reference-renderer.md) | the reference renderer is stdlib-only, so golden frames cannot rot |
| [0004](decisions/0004-stroke-progress.md) | `progress` is a runtime dash reveal; the composer declares path length |
| [0005](decisions/0005-symbols-are-the-payload.md) | symbols are the payload; text is a supporting capability |
| [0006](decisions/0006-animation-phases.md) | the governing animation is the last one to have started |
| [0007](decisions/0007-helix-deformation.md) | depth without a 3D pipeline; sway and depth are separate numbers |
| [0008](decisions/0008-two-layers.md) | the animation is the work; interaction is a discovered second layer |
| [0009](decisions/0009-vector-painter-ports-back.md) | the vector renderer extends `drm_stack`, it does not depart from it |
| [0010](decisions/0010-drm-screen-on-lvgl.md) | `drm_screen`'s vocabulary, LVGL's compositor, and scenes on layers |
| [0011](decisions/0011-one-stack-two-devices.md) | this repository consumes the stack rather than shadowing it |
| [0012](decisions/0012-the-guide.md) | a show is a document evaluated against a clock, not a cursor |
| [0013](decisions/0013-control-server-ported.md) | the control server is `mementum-led`'s, ported; one wall, two kinds of panel |
| [0014](decisions/0014-panels-are-clients.md) | a panel is a client, because the server hands out scenes |

## 4. What the experiments found

The value was rarely the feature. It was the defects that only appear when real
content meets the real code path.

* **A multi-phase timeline was inexpressible.** Two animations on one property
  did not compose — the later one's `from` value silently erased the earlier
  phase. Found by drafting a playbook, before any code was written for it.
* **The C evaluator kept stale state across frames.** Fixing the above exposed
  it: a property with no active animation held whatever the last frame left, so
  rendering 4200 ms and then 700 ms showed the wrong picture. That is §10's rule
  broken by leftover state rather than by a counter.
* **The host Makefile had no header dependencies.** Editing a struct left half
  the objects on the old layout, which presented as heap corruption rather than
  as a build error.
* **The dash restarts at every subpath.** Measured, not assumed — so
  "one pen trajectory across several strokes" cannot be one dash pattern, and
  the player has to sequence the strokes itself.
* **An in-plane offset folds a curve** when it exceeds the local radius of
  curvature — 14 units at the signature's tightest loops. That was the
  unexplainable rippling, and it is why sway and depth became separate numbers.
* **The Python reference never sequenced subpaths.** It applied `progress` to
  every stroke independently, so all sixteen letters of a handwritten phrase
  grew at once. Only the C player was right, because the multi-stroke fixture
  had only ever been run through the C player.
* **The C player refused real handwriting** — 31 pen strokes against a limit of
  16, 4247 characters against 4096 — and was **re-parsing the path text every
  frame** into a 98 KB stack local. Parsing in the frame loop is what §17
  forbids, and that stack local alone would be fatal on an ESP32.
* **Ripples were Python-only, and failed silently.** Half a feature crossed into
  production while its renderer half stayed a sketch, and a `getattr` guard hid
  it. The units run the C player, so the second layer did not exist where it
  matters.

## 5. What is not proven

* **Everything about the hardware.** Frame rate, PSRAM bandwidth, LCD flush
  cost, whether LVGL builds under ESP-IDF with these switches, real Wi-Fi
  timing, and skew between two physical units.
* **Memory.** Parsed geometry is ~73 KB per path object where the content needs
  11.5 KB — fixed arrays sized for a worst case that does not occur. Free RAM,
  once right-sized.
* **The symbol model.** Named parts, one geometry reused as instances, and
  `transform.rotate` — which does not exist in either player — are the last IR
  pieces before v1 could freeze (decision 0005).
* **Fonts.** `font_id` resolves to different assets in each player, so text is
  the one thing the two renderers genuinely disagree about. Now "important"
  rather than "essential", since text is a supporting content type.
* **What is displayed between scenes** (open question 5). Still undefined, and
  it broke a render for real when a scene ended underneath it.
* **The firmware.** `poc/firmware/mementum_lcd/` has never been compiled or
  flashed — there is no board here and no toolchain. Everything it draws with
  is shared C the host suite exercises, and the protocol it speaks is exercised
  end to end over real sockets by the Python client, but neither of those is
  the same as working.

## 6. The screen, the show, and the wire

Three things were built after the exploratory work, each because the previous
one made the gap obvious.

**The screen is the stack's.** `drm_screen`'s API was implemented on LVGL here
to find out whether it worked, then moved upstream where it belongs: the
renderer seam and `PlaceScene` into `drm_screen`, the binding into
`drm-screen-lvgl`, `<path>`/`<animate>` into `drm_composer`, Stage 4b into the
`drm_stack` roadmap. What is left here is an adapter, and ~500 lines left with
it. The same batch of commands gives a byte-identical frame from the numpy
compositor and from LVGL; a scene on a layer draws what the device player
draws, byte for byte. Measured: 1.5 ms per frame at 1920×1080 for a full-screen
animated scene from a 1.4 KB document, and 2.8 ms for a sixteen-panel wall with
sixteen clocks (decisions 0009–0011, 0013).

**The show is a document.** A guide is a running order with timecodes —
`play text`, `play animation`, `play effect` — and the server plays it by
evaluating rather than by advancing a cursor: what is on the wall is the last
scene cue whose moment has passed. Late join is the ordinary registration
reply, a seek is the epoch moving, a tick that arrives late fires what it
missed. A schedule belongs to a *unit*, so a wall can also be sixteen units
standing together: `spread` (what each shows) and `stagger` (when it starts,
`auto` / `tile` / a time, with `factor`, `reverse` and an explicit order) —
`mementum-led`'s vocabulary, adopted rather than reinvented (decision 0012).

**The wire is `mementum-led`'s.** Its Pi server is a faithful port of the
ESP32's own; this one is a port of that, with the same routes, the same
parameter names and the same sentences a firmware parses. So an LED matrix and
an LCD panel can stand on one wall and take the same cue — the matrix gets the
string, the panel gets the scene compiled from the same words, and a scene that
was never words is refused out loud. `ParticipantCore` needed nothing added to
live on a network: the client is the three substitutions, plus a listener,
because being pushed to is a property of the binding (decisions 0013, 0014).

## 7. Where the critical path goes

```text
now      the ESP32 sketch has never been compiled: the display driver, PSRAM,
         lv_conf.h — everything above them is already tested on the host
then     per-layer timing in markup (the renderer takes an offset per layer and
         drm_composer cannot say one); a filesystem-backed content-hash cache,
         so host and device share one cache and an SD card is just a directory
gate     hardware: the ESP-IDF build, frame rate, memory, two-unit skew
later    <symbol src> and an SVG converter; fonts on the asset plane; the
         interactive layer's own character; coupled modes across units;
         drm_scene_ir as its own versioned repo with a conformance suite
```

The simulator, the C player and now a real socket between the two halves mean
each of those arrives as a measurement rather than an argument. What they
cannot do is answer for the board, and every remaining question of consequence
is now a board question.
