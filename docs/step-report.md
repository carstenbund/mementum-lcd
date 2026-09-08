# Step report — where the project stands

* Date: 2026-09-07
* Revision: `ad3222e` plus the working tree
* Covers: everything built so far — Phase 0c, the Phase 0 host track, and the
  exploratory work that followed.

**On the standard applied throughout.** Numbers are here because measuring is
cheap and repeatable, not because this is instrumentation. What is being built
shows handwriting that appears and is gone in seconds; the test that matters is
whether a person watching would notice something wrong. No hardware has been
touched, so **no hardware gate has been satisfied** and nothing here says
anything about frame rate, memory or real network timing on a device.

---

## 1. What exists

```text
mementum_node/     3932 lines   the real participant core, and the C binding
sim/               2470 lines   the three substitutions, harness, scenarios, tools
poc/player/        2004 lines   the device's player, portable C
tools/                          the handwriting converter
poc/scenes/           7 scenes  signature, three-strokes, linewave, waves, handwriting
tests/              180 tests   ~29 s, no hardware
docs/                 5 reports, 6 decisions, 1 playbook
```

Pinned dependencies, all vendored and fetched by script: **LVGL v9.5.0** (with
ThorVG inside it), **cJSON v1.7.18**, **Hershey stroke fonts**. The core and the
simulator are stdlib-only; the C player needs nothing but gcc.

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

## 6. Where the critical path goes

```text
now      right-size the parsed geometry; the symbol model with named parts;
         transform.rotate
then     a filesystem-backed content-hash cache, so host and device share one
         cache and an SD card is just a directory
gate     hardware: the ESP-IDF build, frame rate, memory, two-unit skew
later    fonts on the asset plane; the interactive layer's own character;
         coupled modes across units
```

The simulator and the C player together mean each of those arrives as a
measurement rather than an argument. What they cannot do is answer for the
board, and every remaining question of consequence is now a board question.
