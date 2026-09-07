# Proposal: `drm_scene_ir` and the Mementum LCD Scene Player

**Revision 2.** Supersedes the original `drm_composer`-centric proposal (see git
`cd04b3c` for v1). Revised after review; the substantive changes are listed in
§0.

---

## 0. What changed from v1

v1 proposed generalizing `drm_composer` into the reusable composition system for
both Linux and ESP32. Review found that this pushes future responsibilities into
an existing 644-line package and quietly conflicts with `drm_stack`'s own
roadmap. The corrected principle:

> Do not make `drm_composer` the new runtime. Make it **one producer** of a
> portable scene representation.

Concretely:

| v1 | v2 |
|---|---|
| `drm_composer` owns the portable IR, backends, targets | New neutral package `drm_scene_ir` owns the contract |
| `layout.py` in the proposed structure | Dropped — there is nothing to abstract yet |
| `targets/` moved into `drm_composer` | Left where it is (`drm_screen`) |
| SVG becomes a dynamic scene primitive | SVG stays a raster asset; a *vector subset* compiles to first-class IR objects |
| Phase 1 = refactor `drm_composer` | Phase 0 = prove the ESP32 renderer with a hand-written IR, no Python at all |
| "synchronized" asserted | Explicit fps / skew / recovery budget, measured on **two** devices |
| Text a later concern | `Text` + font assets first-class in IR v1 |
| Leader-change clock discontinuity unaddressed | Explicit policy (restart on election; seamless handoff later) |
| Scene packages pushed by the server | Pull-based asset plane, separate from the control plane |
| Raspberry Pi is infrastructure (AP + server) | Raspberry Pi is also a first-class **display participant** |
| Audience size tied to node count | Participant scaling separated from audience scaling |
| Raspberry Pi renderer to be written | Linux path largely exists; the gap is animation, participant client, sinks |
| Streaming as an output mode | Display / stream / record are node implementations of one framework |
| Server is the ESP32, or a Pi replacing it | Server class follows installation size, bounded at ~300 participants |
| — | One control protocol on unicast; multicast deferred to a later binding |

---

## 1. Purpose

Define a portable scene representation that lets an authored scene run on both:

* Linux/Raspberry Pi via the existing DRM stack
* ESP32-S3 LCD devices via a native C/C++ runtime

The immediate application is the successor to `mementum-led`: a synchronized
network of small displays capable of fluid text, vector drawing,
handwriting-like animation, and general graphical composition.

`drm_composer` remains what it already is — a declarative authoring/compiler
system. The reusable contribution is not the package; it is the **contract** that
lets that work escape DRM. `mementum-lcd` becomes the first serious proof that
the abstraction is genuinely portable rather than theoretically portable.

Two consequences of the neutral contract are treated as design goals, not as
optional features:

* **Anything that speaks Scene IR + scene time is a participant.** The Raspberry
  Pi stops being a special-case "server that happens to run Linux" and becomes a
  first-class display node alongside the ESP32s (§13).
* **Separate participant scaling from audience scaling.** Mementum nodes
  participate in synchronized scene playback; broadcast outputs distribute that
  playback to arbitrarily larger audiences without joining each viewer to the
  control network (§22).

---

## 2. Existing foundations (verified)

### `drm_composer` — what it actually is

Verified against the real source, not from memory. The package is ~644 lines
across `parser.py`, `scene.py`, `painter.py`, `compositor.py`, `actions.py`.

It implements:

* declarative screen-HTML parsing into a pure-data scene model
  (`Scene`, `LayerNode`, `BoxNode`, `TextNode`, `ImageNode`, `ButtonNode`)
* rasterization to RGBA via Pillow
* emission of `drm_screen` commands (`CreateLayer`, `PlaceRawBuffer`)
* handoff through `target.submit(batch)`, where the target itself comes from
  `drm_screen` (`InProcessTarget` / `SocketTarget`)

It does **not** implement:

* **layout.** Coordinates are absolute `x/y/w/h`, parsed and used directly.
  There is attribute resolution, not layout resolution.
* transport. That belongs to `drm_screen`.

Two facts matter for this proposal:

1. `paint_scene()` interleaves node interpretation and rasterization in a single
   loop. That is the seam to split.
2. `painter.py` allocates **one full-screen RGBA canvas per layer**
   (`Image.new("RGBA", (W, H))`). Every logical layer already is a full-screen
   32-bit buffer. On Linux nobody notices; on an ESP32 this is fatal. See §16.

### `drm_stack` — the constraints we inherit

`drm_stack` is the umbrella repo: docs, bootstrap, integration tests. The four
packages live in their own repos. Its README defines six **design invariants**
that every proposal must preserve:

1. one RGBA→BGRA boundary, in `drm_screen`'s backend adapter
2. commands are data, not calls
3. one service, one async boundary (`drm_screen`); `drm_composer` is a stateless
   synchronous utility
4. composition lives in `drm_screen`, not `drm_composer`
5. the blend is isolated in `Composer.render()`
6. input mirrors output; the app stays in control

This proposal is compatible with all six. §4 records how.

`drm_stack` also has an existing roadmap whose **Stage 1** adds SVG to
`drm_composer` through a new Rust/PyO3 package, `drm_resvg` (resvg + usvg +
tiny-skia), with the explicit scope statement:

> SVG is a raster-target image format here; it is never an interactive or
> dynamic UI primitive.

v1 of this proposal contradicted that. §8 resolves it.

### `mementum-led` — the distributed playback model

Verified in the firmware:

* `serverNow()` = `millis() + clockOffset`; the offset is estimated with
  Cristian's algorithm, best of three `/time` samples, refreshed on register and
  on every heartbeat (`ws_wifi.cpp:196`).
* the server is the sequencer: it picks `displayAt = serverNow() + DISPLAY_LEAD_MS`
  and broadcasts `/play?seq&at&data` (`ws_wifi.cpp:161`).
* every device derives the scroll column purely from
  `elapsed = serverNow() - displayAt` (`ws_flow.cpp:53`). Nothing is accumulated,
  so a dropped frame self-corrects on the next one.
* `SCROLL_INTERVAL_MS = 120`, `DISPLAY_LEAD_MS = 2000` (`ws_flow.h:55-56`).
* SPIFFS is already mounted and used for config and web assets.
* broadcast is **sequential unicast HTTP GET** per client, 2 s timeouts
  (`broadcastTask`). Appropriate for tiny commands; not for packages. See §18.
* `docs/failover-design.md` describes role-agnostic server election. A promoted
  server comes up with a **fresh `millis()` domain**. See §11.

The model to generalize is:

```text
time → text scroll position
```

into:

```text
time → complete scene state
```

---

## 3. Architecture

```text
                           drm_stack
                              │
                     ┌────────┴────────┐
                     │                 │
               drm_composer       drm_scene_ir
                Python parser       neutral spec
                     │                 │
                     └──── emits ──────┘
                                       │
                  ┌────────────────────┼────────────────────┐
                  │                    │                    │
           Linux raster path     Linux player          ESP32 player
           (existing DRM path)   (RPi participant)     (mementum-lcd)
                  │                    │                    │
            drm_resvg/Pillow      ScenePlayer          ScenePlayer
                  │                    │                    │
             drm_screen           DRM / encoder        LVGL / ThorVG
                  │                    │                    │
                 DRM             screen / stream            LCD
```

`drm_scene_ir` is a **data contract**, not a transport layer and not a runtime:

```text
              representation            transport

Scene ──────→ Scene IR ──────────────→ file / HTTP / whatever
                    │
                    ↓
                 player
```

Transport belongs to whichever application moves the package. For
`mementum-lcd`, that is Mementum networking.

---

## 4. Repository ownership

This is the most important organizational correction in v2. A child repo cannot
contain a refactor of its parent, so the work is split by ownership rather than
by topic.

### `drm_stack` owns `drm_scene_ir/`

Deliberately small responsibility:

```text
schema
versioning
validation
serialization
semantics
```

It must not know:

```text
ESP32   LVGL   Wi-Fi   Pillow   DRM   ThorVG
```

### `drm_composer` gains one output

```text
Scene → drm_scene_ir
```

Existing rendering is untouched. The DRM path remains:

```text
drm_composer
   ↓
DRM command backend (today's paint_scene)
   ↓
existing drm_screen target
```

No `targets/` package is added to `drm_composer`; no `layout.py` is added.

### `mementum-lcd` owns

```text
ESP32 Scene IR loader
Scene player (ScenePlayer)
LVGL/ThorVG renderer

Linux node framework
    participant core
    display / streaming / recording node implementations

asset cache
network integration
synchronization
```

Everything Mementum-specific — protocol, shared clock, cache, node roles — lives
here, on both the ESP32 and the Linux side. That is what keeps `drm_stack` free
of Wi-Fi and sequencing concerns. The Linux sinks are the exception worth noting:
a stream/record backend is generic enough that it belongs beside
`DrmDisplayBackend` in the stack, not here (§14).

This lets `mementum-lcd` inherit from both parents without moving code ownership
around artificially. It depends on a released `drm-composer` / `drm-scene-ir`;
it does not fork them.

### Invariant check

| Invariant | Status |
|---|---|
| 1 — one RGBA→BGRA boundary | untouched; IR carries no pixels |
| 2 — commands are data | preserved; IR is also data, a second serializable contract |
| 3 — one service, one async boundary | preserved; transport stays in `drm_screen`, the ESP32 player is a separate application |
| 4 — composition in `drm_screen` | preserved; the IR emitter blends nothing |
| 5 — blend isolated | untouched |
| 6 — input mirrors output | out of scope for v1; interaction is Phase 6 |

### Licensing note

`drm_composer` is GPL-3.0-or-later with a separate commercial option. Python code
in `mementum-lcd` that imports it inherits that. The ESP32 side links LVGL and
ThorVG (both MIT) and need not. `mementum-led` currently has **no LICENSE file
at all** — decide this before `mementum-lcd` grows a dependency graph.

---

## 5. Core design principle

> No parsing, asset transmission, layout calculation, or animation sequencing is
> required for every rendered frame.

Per-frame work approaches:

```text
current synchronized time
        ↓
evaluate animation state
        ↓
update affected graphical objects
        ↓
render invalidated area
```

One caveat worth stating rather than discovering: *invalidation* and *seek* pull
against each other. A small monotonic step invalidates a region; an arbitrary
seek invalidates the frame. This is fine for the synchronized playback case,
where steps are small and forward, but the player must not assume seek is cheap.

---

## 6. `drm_scene_ir` v1

The IR describes persistent graphical objects, not pixels. v1 stays deliberately
small — small enough to prove nearly the entire concept:

```text
Scene
Layer

Rect
Text
Image
Path

Transform
Opacity

Animation
```

**No SVG node in v1.** See §8.

Structure:

```text
Scene
    version
    id
    width
    height

Layer
    id
    z
    visible
    opacity
    transform

Object
    id
    type
    geometry
    style
    asset
```

Development format is JSON — inspectable, diffable, trivially parsed on the
device. CBOR or another compact binary form can follow later without changing
scene semantics, once measurement justifies it.

```json
{
  "version": 1,
  "width": 480,
  "height": 320,
  "layers": [
    { "id": "background", "z": 0,  "objects": [
        { "type": "rect", "id": "bg", "x": 0, "y": 0, "w": 480, "h": 320,
          "fill": "#101014" } ] },
    { "id": "writing",    "z": 10, "objects": [
        { "type": "path", "id": "signature", "d": "...", "x": 40, "y": 80,
          "stroke": "#e8e8f0", "width": 3 } ] }
  ],
  "animations": [
    { "target": "signature", "property": "progress",
      "start": 0, "duration": 4200, "from": 0, "to": 1,
      "easing": "ease-in-out" }
  ]
}
```

### Design canvas, not physical resolution

A heterogeneous installation can only share one authored scene if IR coordinates
are logical. So `width`/`height` declare a **design canvas**; each player maps it
onto its own display:

```text
same synchronized work

ESP32       480 × 320
ESP32       320 × 240
Raspberry   1920 × 1080
Raspberry   projector
```

An optional `fit` selects the mapping — `contain` (letterbox; preserves the
composition, the default), `cover` (crop), `stretch`. Phase 0 may use a 1:1
canvas, but the field exists from v1 so scenes never encode a panel size.

One consequence is visible immediately and needs deciding early: a `Path` stroke
of 3 logical units on a 1000-unit canvas is under 1.5 physical pixels at 480×320.
Either the IR carries a minimum physical stroke width and text size, or players
clamp. The same applies to font selection — `font_id` resolution (§9) becomes
per-player, which is an argument for a registry rather than embedded faces.

The IR must remain independent of Pillow, DRM, LVGL, ThorVG, and ESP32 display
drivers. Version it from the beginning (`drm-scene-ir 1`) — the version is the
compatibility gate the sequencer checks at registration (§18).

---

## 7. Vector subset

The IR exposes a useful vector subset rather than arbitrary SVG:

```text
Path      Rect      Circle    Group
Transform Fill      Stroke    Clip
Text      Image
```

plus animation metadata. v1 implements only the subset in §6; `Circle`, `Group`,
and `Clip` follow when something needs them.

The reason for a subset rather than an `SVGObject` is direct: a generic SVG node
would require **every** renderer to implement arbitrary SVG. That is exactly the
kind of obligation this architecture exists to avoid.

---

## 8. SVG — two distinct capabilities

The apparent conflict with the `drm_stack` roadmap dissolves once SVG stops
being the portable runtime contract:

```text
SVG source
   │
   ├── Linux backend:
   │       drm_resvg → raster
   │
   └── compiler:
           SVG/path information
                  ↓
              Scene IR
```

So:

* **SVG as raster asset.** On Linux, arbitrary SVG is accepted as an image and
  flattened through `drm_resvg`. The roadmap's Stage 1 statement stands unchanged
  and remains correct.
* **SVG as authoring source.** Selected vector semantics are compiled into
  first-class Scene IR objects (`Path`, `Rect`, …) at compile time.

These are different capabilities with different renderers. Do not confuse them,
and do not let one silently become the other.

---

## 9. Text and fonts — first-class from v1

The lineage of Mementum is textual; text is an architectural requirement, not a
later gap.

```text
Text {
    id
    content
    x
    y
    font_id
    size
    color
    opacity
    alignment
}
```

Scene packages carry fonts:

```text
manifest
assets/
    fonts/
        inter-regular.bin
```

Do **not** distribute arbitrary TTFs to the ESP32. Either:

```text
authoring font
    ↓
build/preprocess
    ↓
LVGL-compatible font asset
```

or a small pre-installed font registry. The scene references an ID, never a
desktop font path:

```text
font_id = "mementum-sans-24"
```

Font subsetting and asset generation become a compiler responsibility later.

### Handwriting is `Path`, not animated `Text`

For fluid writing, keep these distinct:

* `Text` — glyph rendering
* `Path` — handwriting/calligraphic motion via stroke progress

Trying to animate glyph rendering into handwriting conflates two unrelated
problems.

---

## 10. Animation and time

Animation is declarative. The composer describes it; the runtime executes it.
`animation.py` (or its equivalent) holds metadata and timing and performs **no**
real-time playback — this is what keeps `drm_composer` stateless.

```text
Animation
    target = signature
    property = progress
    start = 0 ms
    duration = 4200 ms
    from = 0
    to = 1
    easing = ease-in-out
```

v1 properties: `transform`, `opacity`, `progress` (stroke/draw), `visible`.
Later: color interpolation, path morphing, nested timelines, keyframes, triggers,
Lottie playback.

Playback derives everything from the shared clock:

```cpp
sceneTime = serverNow() - displayAt;
state     = scene.evaluate(sceneTime);
```

Never:

```cpp
frame++;  x++;  progress += delta;   // forbidden
```

so that

```text
frame 102, 103, [104-117 missed], 118
```

leaves the device correct at 118 rather than behind.

### Performance requirements

"Self-correcting clock" does not mean "visually synchronized." The LED version
tolerates crude synchronization because 120 ms/pixel makes a 20–30 ms offset
barely visible. At 60 fps (16.7 ms/frame) or even 30 fps (33.3 ms/frame), the
same error becomes visible. Requirements, to be validated in Phase 0:

```text
Target playback rate:      >= 30 fps sustained
Preferred:                 60 fps where scene complexity permits

Inter-device visual skew:  <= 20 ms target
Hard acceptable bound:     <= 35 ms

Recovery after missed frames:  next rendered frame

Playback clock:            monotonic synchronized timeline,
                           not accumulated frame state
```

Whether ±20 ms is the correct perceptual target is itself a Phase 0 question.
Having a number beats saying "synchronized."

---

## 11. Clock domain and leader change

`millis()` rollover (~49.7 days) is manageable with unsigned-difference
arithmetic and already handled that way. The real problem is election:

```text
server A dies
     ↓
client B promoted
     ↓
new clock origin
```

A scene running against A's clock cannot interpret B's `millis()` as continuity.
Three options:

* **A — epoch + monotonic offset.** The leader publishes `clockEpochId`,
  `clockBase`, `monotonicTime`; a new leader preserves the logical time domain.
* **B — scene-relative continuity.** Clients retain scene start logical timestamp
  and last known master offset; the new leader adopts the existing epoch.
* **C — reschedule on election.** Leader change cancels the active scene; the new
  leader schedules a fresh start.

**Choose C for the first system, explicitly.** It produces an intentional restart
rather than an unexplained jump. Seamless handoff (A or B) is Phase 5 work;
attempting to hide discontinuous clock leadership up front adds substantial
distributed-systems complexity for a failure mode that is visible and rare.

---

## 12. ESP32 runtime

```text
mementum-player/
    Scene
    Layer
    Asset
    Timeline
    Animation
    Renderer
    SceneLoader
```

```cpp
ScenePlayer player;

player.load(package);
player.prepare();

player.seek(sceneTime);
player.render();
```

Playback is independent of networking. Mementum networking supplies only:

```text
which scene?   when does it start?
```

so the same player can run standalone, over Wi-Fi, over serial, from local flash,
under Raspberry Pi control, or in unrelated projects.

### Graphics runtime

```text
ScenePlayer → LVGL → ThorVG → LCD driver
```

ThorVG provides vector and Lottie rasterization. LVGL provides object hierarchy,
invalidation, clipping, partial rendering, display driver abstraction, text,
images, and the ThorVG integration. The project owns **composition semantics**,
not Bézier rasterization or animation interpolation.

---

## 13. Linux nodes — turning the server into a participant

The Raspberry Pi no longer needs to be a special-case "server that happens to run
Linux." It participates as an ordinary Mementum node, using the same scene,
timing and playback protocol as the ESP32s.

```text
                         Mementum network
                               │
                     master / sequencer
                               │
                  PLAY scene=42 at=T0
                               │
             ┌─────────────────┼─────────────────┐
             │                 │                 │
          ESP32 #1          ESP32 #2          RPi #1
             │                 │                 │
        ScenePlayer       ScenePlayer       ScenePlayer
             │                 │                 │
       LVGL/ThorVG       LVGL/ThorVG       Linux renderer
             │                 │                 │
            LCD               LCD             DRM/KMS
```

All three consume the same logical instruction:

```text
scene = 42
start = T0
```

and independently compute `sceneTime = sharedNow() - T0`. **The Pi is not
streaming frames to the ESP32s.** Every device renders the same scene at the same
logical time. This is the same property `mementum-led` already relies on, applied
to complete scenes instead of a scroll column.

### What exists, and what is missing

The Linux rendering path is largely built. `drm_composer` → `drm_screen` →
`drm_display` already takes a declarative scene to DRM/KMS pixels, and
`drm_screen`'s backend adapter (`DrmDisplayBackend.write(frame_rgba)`, with
headless backends beside it) is a clean seam for other sinks. The remaining Linux
work is narrow and specific:

```text
done        scene markup → layers → composited frame → DRM/KMS
missing     animation — the composer has no timeline at all
missing     participant client — registration, clock sync, cache, PLAY
missing     output sinks — stream, record
```

None of it depends on the ESP32, so the Linux track can proceed **in parallel
with Phase 0**. The two tracks meet at the IR.

### Roles are configuration, not separate builds

`mementum-led` already treats server and client as roles of one firmware: every
node runs identical code and elects a server (`docs/failover-design.md`). The
Linux side should inherit that property rather than keeping a `server.py` that
can only serve.

```text
Raspberry Pi
    ├── network / AP
    ├── master sequencer
    ├── scene / asset server
    └── participant                  ← the new role
```

The first three already exist in `mementum-led`'s `raspberry/` server, which
replicates the ESP32 AP and speaks the same protocol. This architecture adds the
fourth, and a node may hold any subset of the four — including participant alone.
*Which* machine serves is a separate axis, decided by installation size (§20).

### The contract is Scene IR, not LVGL

Players need not share an implementation:

```text
ESP32:                      RPi:

Scene IR                    Scene IR
   ↓                           ↓
ScenePlayer C++             Linux ScenePlayer
   ↓                           ↓
LVGL / ThorVG               DRM renderer
```

But sharing the runtime and changing only the bottom driver is more attractive,
because visual equivalence then comes for free rather than being maintained by
hand:

```text
                    Scene IR
                        │
                   ScenePlayer
                        │
                  LVGL / ThorVG
                    /         \
                 ESP32        Linux
                   │            │
                LCD driver     DRM
```

The trade-off is real in both directions: a shared LVGL/ThorVG runtime buys
pixel-level agreement and one codebase, but bypasses the existing `drm_screen`
compositor and its hit-testing on the Linux side. A native Linux player keeps
`drm_screen` intact but makes text metrics and antialiasing diverge — the same
problem noted for the preview backend (§21). Decide after Phase 0, when there is
a rendered reference to compare against — and note that the decision is cheap to
inform: the ESP32 player's C sources built for the host, over LVGL's SDL or
DRM/KMS port, *are* the shared-runtime candidate. See the implementation plan.

---

## 14. Node implementations — one framework, several sinks

A participant is not one executable with modes. It is one framework with several
node implementations that share a participant core and differ only in their sink
and their pacer.

```text
mementum-node  (Linux framework)

    participant core
        registration + capabilities
        clock sync — sharedNow()
        scene / asset cache + pull
        Scene IR loader
        evaluator — state = scene.evaluate(t)
        pacer
             │
             ├── display node    → drm_screen → drm_display → DRM/KMS
             ├── streaming node  → encoder    → RTMP / SRT / HLS
             └── recording node  → encoder    → file
```

### The seam already exists

A stream or record sink is a **sibling of `DrmDisplayBackend`**, not a new layer.
`drm_screen` already ends at a backend adapter that receives a composited RGBA
frame, and `drm_display` already ships headless backends alongside the DRM one.

This does not weaken invariant 1. The rule is one colour conversion *per backend
adapter*, at the same architectural position: the DRM backend converts
RGBA→BGRA, an encoder sink converts RGBA→YUV420. Neither conversion happens
anywhere else, and neither backend knows about the other.

### The pacer is what actually differs

| Node | Driven by | Clock | Real time |
|---|---|---|---|
| display | the display (vsync / page flip) | `sharedNow()` | yes |
| streaming | wall clock at a fixed rate | `sharedNow()` | yes |
| recording | nothing — a loop over `t` | scene time directly | no |

A display node evaluates whenever it can present. A streaming node must emit a
constant frame rate whether or not anything changed, because encoders want CFR —
so "render only invalidated regions" (§5) becomes an internal optimisation, not a
reason to skip a frame. A recording node is not bound to wall clock at all
(§22).

### Easing must be normative

If the Pi and the ESP32 interpolate `ease-in-out` differently, they diverge
visibly with perfectly synchronized clocks — and it looks exactly like a sync bug
while being nothing of the kind. The IR spec must therefore define easing curves
precisely enough to be reimplemented, and `drm_scene_ir` should ship a reference
evaluator that both players are tested against. Whether that reference is
normative or merely illustrative is an open question (§27).

The same argument applies, more weakly, to text metrics and antialiasing (§13,
§21) — but those degrade gracefully, while a wrong easing curve does not.

---

## 15. Display interface

If fluid animation is a primary requirement, an ESP32-S3 with a parallel/RGB LCD
interface is preferable to a large SPI panel.

Note the tension this creates with §16: **RGB panels are precisely the ones that
require a full framebuffer in PSRAM**, typically with bounce buffers. "Avoid
full-screen buffers" applies to *per-layer* and *per-object* allocation, not to
the panel's own framebuffer. Phase 0 must measure both interfaces if both remain
candidates.

SPI remains useful for smaller displays, low update regions, and mostly static
composition. The renderer exposes a generic display backend either way.

---

## 16. Layer implementation

A logical layer must not imply an independent full-screen framebuffer. This is
not hypothetical: `drm_composer`'s painter does exactly that today, and it is the
single behaviour that would not survive the port.

```cpp
struct Layer {
    LayerId id;
    int z;
    bool visible;
    float x, y, scale, rotation, opacity;
    Content *content;
};
```

```text
10 logical layers
```

must never automatically mean:

```text
10 × full-screen × 32-bit buffers
```

Layers are lightweight scene objects. Buffers are allocated only where the
renderer genuinely requires them, sized to content bounds — which the compiler
can eventually compute.

---

## 17. Memory is a bandwidth problem

The useful question is not "can we fit one 614 KB buffer?" — an S3 with PSRAM
often can. The loop that matters is:

```text
PSRAM read/write
    +
ThorVG rasterization
    +
LVGL composition
    +
RGB DMA
```

all competing for memory bandwidth. The Phase 0 performance report must capture:

```text
display resolution
pixel format
display interface
PSRAM type / speed
LVGL draw buffer size
scene complexity
average fps
1% low fps
CPU usage
PSRAM usage
render time
flush time
```

and specifically compare:

```text
RGB565   vs   ARGB8888 where required
```

because alpha-heavy objects are the likely cost centre.

---

## 18. Protocol: control plane and asset plane

Separate the two. The current sequential fan-out is right for tiny commands and
wrong for packages.

**Control plane** stays tiny and pushed:

```text
PLAY scene=42 at=<timecode>
STOP
SYNC
STATUS
```

**Asset plane** is pulled by each device:

```text
GET /scene/42/manifest
GET /asset/<hash>
```

Each device independently fetches what it is missing, which makes caching fall
out naturally and keeps `DISPLAY_LEAD_MS` from having to cover the transfer of
hundreds of kilobytes to twenty devices over sequential unicast.

Scheduling happens after devices report readiness:

```text
READY scene=42
```

or the server picks a `displayAt` far enough out based on observed readiness.

### Registration and capabilities

Today a node effectively says "I am here." A scene-playing node should say what
it can render:

```text
REGISTER

device:      esp32-s3
role:        display
display:     480x320  rgb565
capabilities:
    scene_ir: 1
    vector:   true
    text:     true
    lottie:   false
```

```text
REGISTER

device:      raspberry-pi
role:        display, stream, record
display:     1920x1080
capabilities:
    scene_ir: 1
    vector:   true
    text:     true
    lottie:   true
```

`role` says which node implementations (§14) this participant is running; a
single Pi may report several. The sequencer can then determine whether a scene is
playable by every participant *before* scheduling it, rather than discovering it
at `displayAt`. `scene_ir` is
the version gate; the rest are feature gates.

Keep the policy explicit rather than implicit — when a participant cannot render
a scheduled scene, it must fail **visibly** (blank, or a defined fallback), never
silently drift out of the shared timeline. Which policy the sequencer applies
(refuse the scene, skip the incapable node, or schedule a downgraded variant) is
an open question (§27).

### Caching

```text
/scenes/            /assets/
    00042.pkg           a7f93...
    00417.pkg           b3091...
```

Package manifest carries scene metadata, canvas dimensions, layers, objects,
transforms, animation timeline, asset references, asset hashes, and the IR
version. Content hashes drive the cache: `sceneId`, `sceneVersion`, `sceneHash`.

---

## 19. Recovery — late join, missed frames, missed commands

The timecode already answers all three. They look like different problems and are
one: a node that does not know the correct picture **reassembles the scene at the
closest possible opportunity and steps back into sync**, because the correct
picture is a function of the shared clock and nothing else.

```text
dropped frame        │
missed PLAY datagram │──→  state = scene.evaluate(sharedNow() - T0)
node joins late      │
```

No retry protocol, no replay, no catch-up animation. Each case differs only in
how long the node takes to notice and how much it must load first.

### The schedule is state, not an event

This is the one property the protocol has to provide. Today `/play` is delivered
once and held; a node that misses it stays dark until the next message. If the
current schedule is instead **obtainable on demand** — announced periodically, or
returned on heartbeat — then every delivery failure degrades from a correctness
problem to a latency one, and the multicast question (§20) stops needing a retry
path at all.

The announce or heartbeat interval therefore sets worst-case recovery latency,
and should be short relative to scene duration. Under multicast this takes the
concrete form of a repeated keyframe (§20).

### Late join

A joining client is told:

```text
scene = 42
start = T0
currentMasterTime = T
```

and evaluates `sceneTime = T - T0`, entering mid-animation.

```text
late join
   ↓
does client have scene?
   │
   ├── yes → seek immediately
   │
   └── no  → pull scene
             ↓
          seek current time
```

Nobody else is delayed. (`mementum-led`'s README lists late join as an open
todo; with multi-second scenes it matters more, not less.)

### What actually bounds recovery

Reassembly is only free when the node already has the scene package. If it does
not, recovery is dominated by the asset pull, so the node re-enters some seconds
in — or misses a short scene entirely.

That is the real argument for pre-distribution: `READY` before `PLAY` (§18), so
that by the time a schedule is announced every participant can seek to it
immediately. Retry logic would not have helped here; having the assets already is
the only thing that does.

---

## 20. Scale tiers and the design bound

Whether `mementum-led`'s `server.py` becomes the sequencer or is retired is the
wrong question. The answer is neither: **the server implementation is chosen by
the size of the installation, and protocol compatibility is what makes the choice
free.** But the range over which that choice is free has a hard edge, and it is
worth naming rather than discovering.

```text
nodes         server class        network              status
────────────────────────────────────────────────────────────────────
  ≤ ~20       ESP32-S3            its own soft AP      works today
  ~20 – 50    Raspberry Pi        AP hardware          works today
  ~50 – 300   Raspberry Pi        AP hardware, tuned   design target
  thousands   dedicated amd64     mesh / wired         out of scope
```

The first two tiers already exist: `mementum-led`'s `raspberry/` server "fully
replicates the ESP32 AP-mode server (same SSID/PSK, IP, and protocol)" to grow
the swarm past the soft-AP limit. The tiering property is established, not
hypothetical.

### The bound, and why it is where it is

Two components are O(n), and both break well before a thousand nodes.

**Sequential unicast fan-out.** `broadcastTask` iterates the client list one at a
time. A healthy HTTP GET to an ESP32 over Wi-Fi costs tens of milliseconds, so a
few hundred nodes serialized is *seconds* — already past `DISPLAY_LEAD_MS`
(2000 ms). Worse, a single unreachable node costs up to its own 2 s connect plus
2 s read timeout. The Raspberry Pi server already broadcasts concurrently, which
is the only reason the low-hundreds tier is reachable at all; an ESP32 server
cannot get there.

**The registration table.** An in-RAM client vector is right for tens of nodes —
the firmware already had to stop spawning a task per client to avoid heap
exhaustion at around twenty. In a Pi process, hundreds are unremarkable.
Thousands would need persistent state and a different query model, including
reasoning about capability *classes* rather than enumerating individual records
(§18).

So the supported range is set deliberately:

> **Design bound: up to roughly 300 participants, served by a Raspberry Pi with
> concurrent fan-out.** Beyond that, the registry and the control-plane transport
> both need redesign — a distribution hierarchy in place of push, and persistent
> registration state. That work is deliberately deferred, not planned.

A thousand-node installation on dedicated infrastructure remains an interesting
direction, and the rule below keeps it *available*. It is not an invitation to
build for it now.

### What holds at the bound

**Fan-out must be concurrent.** This is the one hard requirement the bound
imposes on the server, and the Pi already satisfies it. `DISPLAY_LEAD_MS` then
follows from measured fan-out to the last node rather than being a constant —
that measurement is a deliverable, not an assumption.

**Clock sync scales fine.** It is client-initiated: each node performs its own
three `/time` samples on register and heartbeat, so the server only has to answer
cheaply. There is no fan-out cost here, and no reason to reach for PTP inside the
bound.

**Asset transfer is already pull-based** (§18), so package distribution does not
inherit the fan-out problem — which is exactly why the control plane and the
asset plane were separated.

### Multicast — deferred, not discarded

**Decision: stay on unicast for now.** Two parallel control protocols is a cost
worth refusing, the unicast path already exists and works, and nothing in the
render stack is blocked by fan-out. Multicast is deferred until the rendering
problems are solved — the ESP32 PoC, the IR, animation, the player — and revisited
when unicast fan-out is measurably the limiting factor (§20 open questions).

What makes this a deferral rather than a fork is that **it is one protocol with a
different binding, not a second protocol** — provided one property is implemented
now, on unicast, where it is needed anyway:

> The schedule is state, not an event (§19).

Concretely that means the current schedule is returned on heartbeat. It is cheap,
it is required for late join regardless of transport, and it is the same property
a keyframe provides. Do **not** defer this along with multicast; deferring it is
what would eventually force two protocols.

The rest of this subsection records the shape multicast should take when it is
picked up, so the decision is deferred with its reasoning intact.

### The shape it should take

The model to borrow is **MPEG streaming, not reliable messaging.** A transport
stream carries no acknowledgements and no retransmission; it repeats enough state
often enough — PSI tables, IDR frames — that any receiver can tune in mid-stream
and be correct shortly after, with no back-channel. That is exactly the property
§19 asks for.

The keyframe needs no new message: it is the existing `PLAY`, **repeated**. It is
already self-contained and already idempotent — the firmware ignores a repeat
whose `seq` matches the active schedule — so periodic retransmission costs a
receiving node nothing and needs no dedup logic written for it.

```text
keyframe        PLAY  scene=42  seq=283  at=T0  hash=a7f93…   (repeated)
delta           STOP, schedule change, parameter update       (between)
```

Two rules would keep this from decaying into reliable messaging:

* **Keyframes alone must be sufficient.** Deltas are latency optimisations. If
  correctness ever depends on having seen one, the design has drifted back into
  needing delivery guarantees.
* **The keyframe interval is the worst-case recovery latency** (§19). A schedule
  datagram is tiny, so the interval can be short — a few hundred milliseconds is
  cheap even at the top of the bound — and should be chosen against scene
  duration, not against bandwidth.

What it buys, when it is taken up: the sequencer stops paying O(n) per scheduled
scene, and every node receives the schedule at effectively the same instant,
removing the fan-out skew that unicast push contributes to the §10 budget.

Two caveats to carry forward. Wi-Fi multicast is sent at a low basic rate and is
handled inconsistently by access points, so it has to be measured on the actual
AP rather than assumed. And a keyframe could carry `serverNow` as a free coarse
clock reference, but one-way multicast delay is unmeasurable — good for detecting
a badly wrong clock, not for holding the ±20 ms budget (§10).

This would apply to the **control plane only**. Assets stay on the pull-based,
reliable HTTP path (§18); reliable multicast of scene packages is a different and
much worse problem.

### The rule

> No component above the transport may assume a node count, a server class, or a
> network topology. Scale is chosen at deployment; the scene, the timeline and
> `sharedNow()` are identical at every tier.

Keeping this true costs nothing today and is what would make a larger tier a
transport change rather than a rewrite. Within the stated bound, nothing further
is engineered for scale.

---

## 21. Linux path, unchanged

```text
Scene IR
   ↓
DrmRasterBackend  (today's paint_scene)
   ↓
Pillow
   ↓
RGBA
   ↓
drm_screen
```

Current behaviour is retained, not discarded. The point of v2 is to let
`drm_composer`'s work escape DRM, not to replace it.

### Preview backend

A desktop preview reading the same IR lets scenes and animations be developed
without flashing an ESP32:

```text
Scene IR → Preview backend → Linux window
```

Over time the preview and the ESP32 runtime should agree closely enough that the
desktop is a practical authoring environment. Expect divergence in text metrics
and antialiasing; the preview is an authoring aid, not a reference renderer.

---

## 22. Broadcast outputs — participant vs audience scaling

Once any Scene IR renderer is a participant, the Raspberry Pi can publish the
same scene outward while the installation stays a small, controlled swarm:

```text
Mementum scene
     │
     ├── local ESP32 displays
     ├── public HDMI / projector display
     ├── live stream
     └── recorded output
```

The design goal, stated as a rule:

> Mementum nodes **participate** in synchronized scene playback. Broadcast
> outputs **distribute** that playback to arbitrarily larger audiences without
> joining each viewer to the control network.

Adding ten thousand viewers does not add ten thousand Mementum clients. The swarm
stays small; a distribution platform handles audience fan-out. This is an
architectural consequence of the neutral contract, not an optional streaming
feature bolted on later.

The stream need not be a secondary camera feed. It is a first-class rendering of
the same scene at a higher resolution, driven by the same `displayAt` and shared
clock — so the public screen, the remote stream and the embedded devices are
conceptually one work rather than a performance plus a separate production layer.
A broadcast output registers like any other node (§18) and is built as one of
the node implementations in §14 — the same participant core, a different sink.

### In-room and remote outputs have different budgets

These must not be conflated:

* An **in-room** output — a projector or HDMI screen beside the ESP32s — is bound
  by the full skew budget of §10 (≤ 20 ms target). A viewer sees both at once.
* A **remote** stream has no local reference, so encoder and transport latency of
  seconds is harmless. It needs only *internal* consistency: the frames it emits
  must be a correct evaluation of the scene at their own timestamps.

Treating the projector as "just another stream sink" would silently apply the
wrong budget to the one output where skew is visible.

### Recording is deterministic, not real-time

Because state is a pure function of scene time (§5, §10), a recorded output does
not need to be captured in real time. The same scene can be rendered offline,
faster or slower than wall clock, at any frame rate, and the result is exact:

```text
for t in 0 .. duration step (1/fps):
    frame = scene.evaluate(t)
```

This is the same property that makes dropped frames self-correcting, used for a
different purpose. It is also why streaming and recording are different *pacers*
over one evaluator rather than different renderers (§14).

---

## 23. Phase 0 — prove the embedded renderer

**No `drm_composer` changes. No Python.** This reverses the dependency risk.

Instead of:

```text
refactor Python architecture → design IR → write ESP32 runtime
        → discover whether it performs
```

we get:

```text
define tiny IR → prove ESP32 runtime → stabilize semantics
        → make drm_composer emit it
```

### Setup

Hand-write a JSON scene (§6) onto the ESP32 filesystem. 480 × 320, containing:

```text
layer  ·  path  ·  text  ·  animation
```

The path appears progressively over ~4 seconds. Prove the chain:

```text
JSON → C++ parser → Scene → ThorVG/LVGL → LCD
```

### Two devices, not one

```text
ESP32 A         ESP32 B
   │               │
   └── same scene ─┘
         same T0
```

A single device cannot test the actual Mementum property. Film both together at
high frame rate and measure:

```text
start skew
stroke-position skew
long-run drift
recovery after network load
```

Playback progress must come exclusively from `serverNow() - displayAt`.

### Also test

* temporarily delay rendering
* intentionally drop frames
* generate Wi-Fi activity

The animation must return immediately to the correct synchronized state.

### Phase 0 decides

whether LVGL/ThorVG and the selected LCD hardware are viable at all — before any
change is made to `drm_composer`, and before the IR is frozen.

---

## 24. Phases

```text
Phase 0  prove the embedded renderer          (above) — the ESP32 track

Phase 0b prove the Linux track    parallel    extend drm_composer with a
                                              timeline; add stream/record sinks
                                              behind the existing drm_screen
                                              backend seam.  Needs no ESP32.

Phase 1  specify drm_scene_ir                 new neutral package in drm_stack;
                                              define only what Phases 0/0b
                                              proved; versioned from day one;
                                              normative easing + reference
                                              evaluator
Phase 2  integrate with drm_composer          add Scene → Scene IR as a second
                                              output; DRM path unchanged
Phase 3  reconcile SVG                        raster path via drm_resvg and/or
                                              vector subset → IR; never confused
Phase 4  Mementum scene protocol              SCENE / READY / PLAY / STOP as
                                              semantics, unicast HTTP as the
                                              only binding; schedule returned on
                                              heartbeat; capabilities +
                                              role at registration, pull-based
                                              asset fetch; the Linux server gains
                                              its participant role
Phase 5  late join and robust timing          mid-scene seek, clock discontinuity
                                              policy, leader-election playback
Phase 5b transport, if measurement asks       repeated-keyframe multicast as a
                                              second binding (§20).  Deferred
                                              until the render stack is done and
                                              fan-out is the actual limit.
Phase 6  richer composition                   Lottie, clipping, gradients,
                                              complex SVG, nested timelines,
                                              touch interaction, procedural layers
```

---

## 25. Explicitly not to be implemented

* a complete HTML browser
* CSS layout
* JavaScript / DOM scripting
* a custom SVG rasterizer
* a custom Bézier engine
* a custom Lottie implementation
* a layout subsystem before something needs one
* a control plane that assumes a node count, a server class, or a transport
* a second control-plane binding before the render stack is proven — one
  protocol at a time (§20)
* delivery verification on the control plane — acknowledgements, per-node
  delivery tracking, retransmission buffers, sequence-gap detection (§20)
* scaling work beyond the ~300-participant bound (§20) — distribution
  hierarchies, persistent registries, capability classes.  Multicast is
  explicitly *not* on this list: it is a transport binding, not scaling
  machinery (§20)
* per-frame scene transmission
* remote framebuffer streaming
* one framebuffer per logical layer
* animation based on incrementing frame counters
* Python on the ESP32

Existing libraries solve low-level graphics. The project concentrates on:

```text
composition   scene semantics   distribution   synchronization   reuse
```

---

## 26. Naming

Stop multiplying "composer." The vocabulary:

```text
drm_composer            authors/compiles scenes
drm_scene_ir            represents scenes
ScenePlayer             evaluates scenes in time  (ESP32)
drm_screen.Composer     blends pixels             (existing, leave alone)
```

The `drm_composer.Compositor` / `drm_screen.Composer` collision already exists
and stays. We do not create a third.

---

## 27. Open questions

1. Is ±20 ms the right perceptual skew target for adjacent displays? Phase 0.
2. RGB/parallel vs SPI panel — resolved by Phase 0 measurement, not preference.
3. Does `drm_scene_ir` ship as its own repo (like the other stack packages,
   cloned by `setup.sh`) or as a directory inside `drm_stack`? The other four are
   separate repos; consistency argues for separate.
4. `mementum-led` has no LICENSE. Decide before `mementum-lcd` takes a GPL
   dependency on `drm_composer`.
5. What is displayed between scenes — idle, loop, or blank? Undefined today.
6. Does the ESP32 keep SPIFFS or move to LittleFS for the scene/asset cache?
   Wear and directory behaviour differ.
7. Shared LVGL/ThorVG runtime on the Raspberry Pi, or a native Linux player over
   `drm_screen`? Visual equivalence versus keeping the existing compositor and
   hit-testing. Decide after Phase 0 (§13) — building the player for the host
   makes this an experiment rather than an argument.
8. Minimum physical stroke width and text size when a logical canvas scales down
   to 480×320 — clamped by the player, or carried in the IR? (§6)
9. When a participant cannot render a scheduled scene: refuse the scene, skip the
   node, or schedule a downgraded variant? (§18)
10. Does `drm_scene_ir` ship a **normative** reference evaluator — easing maths
    and property semantics — or only prose plus a conformance suite? Divergence
    here presents as an apparent sync bug. (§14)
11. Where does the Linux node framework live: `mementum-lcd` beside the ESP32
    player, or its own repo? Recommendation is `mementum-lcd`, so nothing
    Mementum-specific leaks into `drm_stack`. (§4)
12. What is the measured concurrent fan-out time on the Pi server at 100 and at
    300 participants, and what does `DISPLAY_LEAD_MS` have to become? This sets
    the real bound; the ~300 figure is an estimate until measured. (§20)
13. Does the Pi's registration table need to become persistent within the bound —
    i.e. does a sequencer restart have to preserve participant state — or is
    re-registration on reconnect sufficient, as it is today? (§18)
14. What keyframe interval? It is the worst-case recovery latency (§19, §20), so
    it should be set against the shortest scene the work uses, not against
    bandwidth. Under unicast the equivalent question is announce-periodically
    versus return-on-heartbeat.
15. What measurement triggers picking multicast up — concurrent fan-out to the
    last node exceeding some fraction of `DISPLAY_LEAD_MS`, or observed skew
    attributable to fan-out? Deferred, but worth naming the trigger so the
    decision is not made on impulse. (§20)

---

## References

* Full stack / Linux — https://github.com/carstenbund/drm_stack
* Mementum LED — https://github.com/carstenbund/mementum-led
* `drm_composer` — https://github.com/carstenbund/drm_composer
