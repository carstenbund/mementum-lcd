Here is a proposal framed as the technical direction for evolving `drm_composer` into the reusable composition layer for the LCD-based continuation of Mementum.

# Proposal: Reusable `drm_composer` Architecture for Mementum LCD

## 1. Purpose

This proposal defines an architecture for extending the existing `drm_composer` project into a reusable scene-composition system that can target both:

* Linux/Raspberry Pi displays using the existing DRM stack
* ESP32-S3 LCD devices using a native C/C++ graphics runtime

The immediate application is the successor to `mementum-led`: a synchronized network of small displays capable of fluid text, vector drawing, handwriting-like animation, and more general graphical composition.

The central goal is not to create another ESP32-specific graphics implementation. Instead, the existing `drm_composer` work should become the reusable high-level composition system, while platform-specific renderers remain replaceable.

The architecture should preserve the existing principle of `drm_composer`: the composer describes and compiles screen state but does not own the final display hardware or pixel compositor. The current implementation already explicitly separates scene compilation from `drm_screen` and DRM/KMS.

---

# 2. Existing foundations

Two existing projects provide complementary parts of the proposed system.

## `drm_composer`

`drm_composer` currently implements:

* declarative screen markup
* parsing into a scene model
* named layers with z-order and visibility
* boxes, text, images and interactive elements
* layout interpretation
* rasterization
* generation of `drm_screen` commands
* transport-independent submission through a target abstraction

Its current pipeline is approximately:

```text
screen-HTML
    ↓
parser
    ↓
Scene
    ↓
Pillow painter
    ↓
RGBA layer buffers
    ↓
drm_screen commands
    ↓
DRM/KMS
```

The project deliberately considers itself a stateless scene-to-screen-command compiler.

The scene model is already represented separately from rendering through structures such as `Scene`, `LayerNode`, `BoxNode`, `TextNode`, and `ImageNode`.

This separation should become the basis of the portable architecture.

## `mementum-led`

`mementum-led` already supplies:

* ESP32-S3 firmware
* Wi-Fi networking
* server/client discovery
* a master sequencer
* synchronized clocks
* scheduled playback
* message sequencing
* recovery from dropped frames

Most importantly, animation position is not accumulated locally. Each device derives the current position from:

```text
serverNow() - displayAt
```

The current LED scroll therefore re-synchronizes automatically after dropped frames.

The implementation already computes display state directly from synchronized time.

This model should be generalized from:

```text
time → text scroll position
```

to:

```text
time → complete scene state
```

---

# 3. Architectural objective

The proposed system is:

```text
                         drm_composer
                    reusable scene compiler
                              │
                   Portable Scene Package
                              │
                ┌─────────────┴─────────────┐
                │                           │
             Linux                       ESP32-S3
                │                           │
        DRM raster backend             Scene Player
                │                           │
           drm_screen                  LVGL / ThorVG
                │                           │
             DRM/KMS                        LCD
```

`drm_composer` remains the owner of the declarative scene language and scene compilation.

It does not become an ESP32 library.

The ESP32 does not run Python.

Instead, Python and C/C++ meet at a deliberately defined, serialized scene representation.

---

# 4. Core design principle

The central architectural rule should be:

> No parsing, asset transmission, layout calculation, or animation sequencing is required for every rendered frame.

The runtime should operate on a previously compiled scene.

Per-frame work should approach:

```text
current synchronized time
        ↓
evaluate animation state
        ↓
update affected graphical objects
        ↓
render invalidated area
```

This is essential for efficiency on the ESP32.

---

# 5. Refactoring `drm_composer`

The current implementation combines two operations inside `paint_scene()`:

1. interpreting scene nodes
2. rasterizing them into RGBA pixels

The current painter creates complete RGBA canvases using Pillow for every layer and subsequently emits `PlaceRawBuffer` commands.

That behavior should remain available for the Linux backend, but rasterization should no longer be the canonical output of the composer.

The proposed internal pipeline becomes:

```text
markup
   ↓
parser
   ↓
Scene
   ↓
layout
   ↓
compiler
   ↓
DisplayList / Scene IR
```

The Scene IR then feeds independent backends:

```text
                         Scene IR
                            │
               ┌────────────┴────────────┐
               │                         │
        DRM Raster Backend       Embedded Backend
               │                         │
             Pillow                Scene Package
               │                         │
            RGBA                     ESP32
               │
          drm_screen
```

---

# 6. Proposed package structure

A future `drm_composer` layout could be:

```text
drm_composer/
    parser.py
    scene.py
    layout.py

    compiler.py
    display_list.py

    animation.py
    assets.py

    backends/
        drm_raster.py
        embedded.py
        preview.py

    targets/
        inprocess.py
        socket.py
        http.py
        file.py

    compositor.py
```

Responsibilities should remain sharply separated.

## `scene.py`

Contains declarative scene objects:

```text
Scene
Layer
Rect
Text
Image
Vector
Animation
```

No hardware or rasterization knowledge.

## `compiler.py`

Converts resolved scenes into a stable intermediate representation.

## `display_list.py`

Defines the portable scene/display command model.

## `animation.py`

Defines animation metadata and timing but performs no real-time playback.

## `backends`

Translate the portable representation into platform-specific outputs.

## `targets`

Define transport only.

This preserves the current useful `target.submit(batch)` concept instead of conflating rendering and transport.

---

# 7. Portable Scene IR

A platform-neutral intermediate representation is the critical new component.

It should describe persistent graphical objects rather than pixels.

Conceptually:

```text
Scene
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

Example:

```text
SCENE greeting

LAYER background
    z = 0

RECT bg
    x = 0
    y = 0
    w = 480
    h = 320
    fill = #101014

LAYER writing
    z = 10

VECTOR signature
    asset = signature.svg
    x = 40
    y = 80
    w = 380
    h = 100

ANIMATE signature.progress
    start = 0
    duration = 4200
    from = 0
    to = 1
    easing = ease-in-out
```

The IR must remain independent of:

* Pillow
* DRM
* LVGL
* ThorVG
* ESP32 display drivers

Backends are responsible for translating this model.

---

# 8. SVG and vector graphics

SVG should be introduced as a vector asset type rather than replacing the overall scene model.

For example:

```xml
<layer id="writing" z="10">
    <svg
        id="signature"
        src="signature.svg"
        x="30"
        y="100"
        w="400"
        h="80"
    />
</layer>
```

This retains the useful outer abstraction:

```text
Scene
    Layer
        content
```

A layer may ultimately contain:

* SVG/vector content
* Lottie animation
* bitmap imagery
* text
* procedurally generated content

This is preferable to treating the complete screen as a single SVG document.

It preserves the freedom and independent lifecycle of each layer.

---

# 9. Animation model

Animation should be declarative.

The composer describes animation.

The runtime executes it.

For example:

```xml
<animate
    target="signature"
    property="progress"
    from="0"
    to="1"
    start="0"
    duration="4200"
    easing="ease-in-out"
/>
```

Compilation produces something approximately equivalent to:

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

The animation engine should support, at minimum:

* translation
* rotation
* scale
* opacity
* visibility
* drawing/stroke progress
* clipping/reveal
* playback of embedded Lottie animation

Potential later extensions include:

* path morphing
* color interpolation
* nested timelines
* keyframe sequences
* triggers and events

---

# 10. Time model

The existing Mementum synchronization model should become the canonical playback clock.

The server schedules:

```text
scene = 17
sequence = 283
displayAt = T
```

Each ESP32 computes:

```cpp
sceneTime = serverNow() - displayAt;
```

The player evaluates the complete scene at `sceneTime`.

There should be no requirement to accumulate state such as:

```cpp
frame++;
x++;
progress += delta;
```

Instead:

```text
state = scene.evaluate(sceneTime)
```

This provides an important property:

```text
frame 102
frame 103

frames 104–117 missed

frame 118
```

does not leave the client behind.

At frame 118 the device evaluates the correct scene state for the current synchronized time.

This generalizes one of the strongest properties already present in `mementum-led`.

---

# 11. ESP32 runtime

The ESP32 firmware should contain a reusable C/C++ scene player.

Conceptually:

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

The main interface might resemble:

```cpp
Scene scene;

scene.load(package);
scene.prepare();

scene.seek(sceneTime);
scene.render();
```

Playback should therefore remain independent of networking.

Mementum networking only supplies:

```text
which scene?
when does it start?
```

This separation permits the same player to be used later:

* standalone
* via Wi-Fi
* over serial
* from local flash
* with Raspberry Pi control
* in unrelated display projects

---

# 12. Graphics runtime

For ESP32-S3, the proposed first implementation is:

```text
Scene Player
      ↓
LVGL
      ↓
ThorVG
      ↓
LCD driver
```

ThorVG can provide the vector and Lottie rendering capabilities that should not be hand-written in the application.

LVGL can provide:

* object hierarchy
* invalidation
* clipping
* partial rendering
* display driver abstraction
* text
* images
* integration with ThorVG

The custom project therefore owns composition semantics, not Bézier rasterization or animation interpolation.

---

# 13. Layer implementation

A logical layer must not imply an independent full-screen framebuffer.

This distinction is important.

A layer should be represented conceptually as:

```cpp
struct Layer {
    LayerId id;
    int z;

    bool visible;

    float x;
    float y;
    float scale;
    float rotation;
    float opacity;

    Content *content;
};
```

The renderer determines how it is physically represented.

Therefore:

```text
10 logical layers
```

must not automatically mean:

```text
10 × complete-screen × 32-bit buffers
```

Layers should normally become lightweight scene objects.

Buffers are allocated only where the renderer genuinely requires them.

---

# 14. Scene packaging

Scenes should be distributable as packages.

A package might contain:

```text
scene/
    manifest.cbor
    assets/
        background.svg
        signature.svg
        icon.png
        drawing.json
```

During development, JSON may be useful because it is inspectable.

Production can move to CBOR or another compact binary representation without changing scene semantics.

The package should contain:

* scene metadata
* canvas dimensions
* layers
* objects
* transforms
* animation timeline
* references to assets
* asset hashes
* version of the scene format

A content hash can be used for caching:

```text
sceneId
sceneVersion
sceneHash
```

---

# 15. Network protocol

Large scene packages should not be continuously broadcast.

Typical operation should be:

```text
1. Controller determines required scene.

2. Device checks local cache.

3. Missing scene/assets are transferred once.

4. Server sends:

   PLAY
       scene = 17
       seq = 82
       at = 39817293

5. All devices execute locally.
```

Playback traffic therefore remains very small.

The existing Mementum protocol can evolve from:

```text
/play?seq&at&data
```

toward something such as:

```text
/play?seq=82&at=39817293&scene=17
```

Scene transfer is a separate concern.

---

# 16. Scene caching

ESP32 devices should maintain a local scene/asset cache in flash.

For example:

```text
/scenes/
    00123.pkg
    00417.pkg

/assets/
    a7f93...
    b3091...
```

The controller can ask:

```text
HAS scene 417?
```

and transfer only missing resources.

This prevents repeated network transmission and permits synchronized playback to begin from local data.

---

# 17. Runtime efficiency

The architecture is efficient if expensive work is moved out of the frame loop.

## Compile time

The composer may perform:

* markup parsing
* layout calculation
* SVG validation
* asset resolution
* animation validation
* scene optimization
* asset packaging

These operations occur before playback.

## Load time

The ESP32 may perform:

* package parsing
* SVG/Lottie parsing
* object construction
* resource allocation

These occur when loading the scene.

## Frame time

Frame-time work should be limited to:

```text
read scene time
evaluate animation
update changed properties
render invalidated regions
flush LCD
```

No source document parsing should occur during normal rendering.

---

# 18. Memory strategy

RAM is expected to be the primary constraint.

The target hardware should therefore preferably be:

```text
ESP32-S3
+
PSRAM
```

Lottie/vector animations should use their natural bounding boxes instead of full-screen intermediate buffers.

For example:

```text
screen:
480 × 320

writing animation:
360 × 80
```

An ARGB8888 buffer for the smaller object requires:

```text
360 × 80 × 4
= 115,200 bytes
```

rather than:

```text
480 × 320 × 4
= 614,400 bytes
```

The scene compiler can eventually assist here by calculating content bounds.

---

# 19. Display interface

If fluid animation is a primary requirement, an ESP32-S3 with a parallel/RGB LCD interface is preferable to treating a large SPI panel as the default target.

SPI remains useful for:

* smaller displays
* low update regions
* mostly static composition

but the architecture should not assume SPI bandwidth.

The renderer should expose a generic display backend.

---

# 20. Relationship to existing DRM implementation

The existing Linux path remains supported.

The current `paint_scene()` implementation becomes conceptually:

```text
Scene IR
   ↓
DrmRasterBackend
   ↓
Pillow
   ↓
RGBA
   ↓
drm_screen
```

The current behavior is therefore retained rather than discarded.

This is important because the new architecture is intended to make `drm_composer` more reusable, not replace it.

---

# 21. Preview backend

A useful additional backend would be a desktop preview.

For example:

```text
drm_composer
     ↓
Scene IR
     ↓
Preview backend
     ↓
Linux window
```

This would allow scenes and animations to be developed without flashing an ESP32.

Eventually the preview and ESP32 runtime should use sufficiently similar rendering behavior that the desktop serves as a practical authoring/test environment.

---

# 22. Proposed first proof of concept

The first implementation should intentionally be small.

## Scene

```text
480 × 320
```

with:

```text
background layer
writing layer
```

The writing layer contains one vector path.

## Animation

The line should progressively appear over approximately four seconds.

## Synchronization

Playback progress must be calculated exclusively from:

```cpp
serverNow() - displayAt
```

## Test

During playback:

* temporarily delay rendering
* intentionally drop frames
* generate Wi-Fi activity

The rendered animation must return immediately to the correct synchronized state.

This test validates:

* scene packaging
* vector rendering
* ESP32 memory requirements
* frame rate
* synchronization
* scene seeking
* LCD bandwidth

before substantial changes are made to `drm_composer`.

---

# 23. Proposed implementation phases

## Phase 1 — Extract portable compiler boundary

Refactor:

```text
Scene → paint_scene()
```

into:

```text
Scene → DisplayList
DisplayList → DrmRasterBackend
```

The existing DRM output should remain functionally unchanged.

This proves that the new abstraction does not regress the current project.

## Phase 2 — Extend scene language

Add:

```text
<vector>
<svg>
<animate>
```

Initially support only:

* transform
* opacity
* draw progress

## Phase 3 — Define scene package

Create the first versioned serialized representation.

Prefer readability initially:

```text
JSON manifest + assets
```

Optimize later if measurements justify it.

## Phase 4 — ESP32 scene player

Implement:

```text
SceneLoader
Layer
Timeline
Renderer
```

using LVGL/ThorVG.

No Mementum networking is required yet.

Playback can use local time during this phase.

## Phase 5 — Synchronized player

Integrate the existing Mementum clock.

Replace local playback time with:

```cpp
serverNow() - displayAt
```

## Phase 6 — Scene distribution

Extend the existing Mementum server/controller to distribute and cache scene packages.

## Phase 7 — Broader composition

Add, as justified:

* Lottie
* richer typography
* clipping
* gradients
* nested groups
* additional easing curves
* touch interaction
* procedural layers

---

# 24. What should explicitly not be implemented

To protect the architecture from unnecessary complexity, the initial project should avoid:

* a complete HTML browser
* CSS layout
* JavaScript
* DOM scripting
* a custom SVG rasterizer
* a custom Bézier engine
* a custom Lottie implementation
* per-frame scene transmission
* remote framebuffer streaming
* one framebuffer per logical layer
* animation based on incrementing frame counters
* Python on the ESP32

Existing libraries should solve low-level graphics problems.

The project should concentrate on:

```text
composition
scene semantics
distribution
synchronization
reuse
```

---

# 25. Expected result

The resulting architecture should provide a reusable system in which an authored scene can run on different display classes:

```text
                        Scene Source
                             │
                       drm_composer
                             │
                      Portable Scene
                             │
         ┌───────────────────┼───────────────────┐
         │                   │                   │
     Raspberry Pi          ESP32-S3          future target
         │                   │                   │
        DRM                 LCD                  ...
```

Meanwhile Mementum provides the distributed playback model:

```text
                    master sequencer
                           │
                     shared clock
                           │
                    scheduled scene
                           │
             ┌─────────────┼─────────────┐
             │             │             │
          display A     display B     display C
             │             │             │
          scene(t)      scene(t)      scene(t)
```

Each display therefore renders its own scene locally while sharing the same notion of time.

---

# 26. Architectural conclusion

The proposed work should not be considered a port of `drm_composer` to ESP32.

It is a generalization of `drm_composer`.

The current project already established the important conceptual boundaries:

```text
declarative scene
    ↓
compiler
    ↓
screen abstraction
    ↓
hardware
```

The new work moves the rasterization decision one layer lower.

`drm_composer` becomes:

> A stateless compiler from declarative screen descriptions into portable scene representations.

Platform-specific systems then become players/renderers:

```text
Linux:
Scene → Pillow/DRM

ESP32:
Scene → LVGL/ThorVG/LCD
```

`mementum-led`, in turn, contributes its synchronized distributed playback architecture.

Together these produce a reusable system for synchronized, fluid, vector-capable displays without tying the composition language either to DRM or to ESP32 hardware.

I’d make the next document a **concrete v1 technical specification for the Scene IR/package format**, because that boundary determines whether `drm_composer`, Linux and the ESP32 runtime actually remain independently reusable.
