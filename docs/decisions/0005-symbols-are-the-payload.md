# 0005 — Symbols are the payload; text is a supporting capability

* Status: accepted
* Date: 2026-09-07
* Supersedes: the framing of proposal §9 ("Text and fonts — first-class from
  v1"), and the priority given to fonts in
  [`phase0-c-player-protocol.md`](../phase0-c-player-protocol.md) §C5.

## Context

`mementum-led` had one shape:

```text
message  →  glyphs  →  scroll over time
```

Text was the payload and movement was scrolling. Reading `mementum-lcd` as its
successor made text the primary content type by inheritance rather than by
intent, which is how §9 came to call it "first-class from v1".

The actual artistic intent is different. A meme is not a sentence to be
scrolled; it is a symbolic object with internal structure, and what makes it
alive is transformation over time:

```text
meme / symbolic statement  →  symbols  →  vector composition
                           →  fluid transformation
                           →  shared synchronized time
```

Memes acquiring *momentum* through movement, distribution and synchronized
appearance — which is what the name says.

## Decision

The primary visual primitive is the **symbol**: vector content with named
internal parts that can be revealed, moved, transformed and combined on the
shared timeline. Text is a supporting content type, for captions and labels and
literal text when a piece needs it.

```text
Mementum scene
│
├── symbol          ← primary
│    ├── SVG geometry
│    ├── named parts
│    ├── transforms
│    ├── stroke / fill
│    ├── path reveal
│    ├── opacity
│    └── timeline
│
├── image
│
└── text
     └── font asset  ← supporting
```

**Mementum is a synchronized symbolic display system.** Its authored content is
vector symbols and their temporal transformation.

SVG is the authoring format because it already has the vocabulary — path,
group, transform, fill, stroke, clip, opacity — and Mementum adds the one thing
SVG does not give reliably across targets: a shared deterministic timeline.

```text
SVG  +  Mementum animation semantics  =  animated symbol
```

That is emphatically *not* "animated SVG as the runtime contract". SMIL, CSS
animation and runtime DOM manipulation stay on the refusal list (§25). SVG
contributes geometry; the timeline is ours.

## What this changes

**The object model gains one level of structure.** A symbol is a group with
named parts, and animation targets address them:

```json
{ "type": "symbol", "id": "distracted-face", "asset": "sha256:...",
  "parts": ["outline", "eyes", "mouth"] }
```

```json
{ "target": "distracted-face.outline", "property": "progress",
  "start": 0, "duration": 800, "from": 0, "to": 1 }
```

Transforms compose one level deep — symbol transform, then part transform — so
"rotate the whole symbol" is one animation rather than N. Arbitrary nesting is
not needed and should not be added: the composer flattens everything above the
symbol.

**Rotation is missing and must be added.** Today `transform` carries `tx`, `ty`
and `scale` in both implementations. "Rotate the whole symbol" is in the
vocabulary this decision commits to, so `transform.rotate` and a rotation
anchor are v1 work, not later work.

**The preprocessor becomes a real deliverable.** SVG in, normalized paths plus
bounds, subpath lengths, anchors and preserved part ids out. It is where the
declared path lengths of decision 0004 come from, and it is what makes named
parts addressable without editing SVG at runtime:

```text
SVG source → preprocessor → normalized paths
                            bounds
                            subpath lengths
                            anchors
                            part ids
                          → Scene IR → shared ScenePlayer
```

**Symbols are content-addressed**, like every other asset. Symbol hash plus
timeline plus `T0` is enough for any node to reconstruct exactly what should be
on screen — the ESP32 panel, the Pi public display and the stream showing the
same transformation at the same logical instant.

## What this does not change

Nothing built so far. The control plane, the clock, recovery, fan-out and the
mixed-renderer conformance work are all content-agnostic: they never knew
whether the payload was text or symbols, and `state = evaluate(sceneTime)` is
indifferent to what is being evaluated. This reframing costs no rework of Phase
0c or the C player — it changes what goes *into* the IR, not how the IR is
distributed, timed or recovered.

## v1 priorities, restated

```text
essential:  vector symbol, named parts, path reveal,
            transforms (including rotation), opacity, layering, timing
important:  images, font/text
later:      sophisticated typography, Lottie, arbitrary SVG animation
```

## Consequences worth naming

* **Fonts are no longer the v1 blocker.** The C player and the Python reference
  disagree on text because `font_id` resolves to different assets; under this
  decision that is a divergence in a *secondary* content type, and v1 need not
  wait on it. Content-addressed font assets remain the right fix, at the
  priority "important" rather than "essential".
* **Deformation is not v1.** Of the vocabulary this decision implies — draw in,
  hold, pulse, rotate, deform, fade, erase, replace, combine — every item is
  reachable with transforms, opacity and progress *except* deform, which is
  path morphing and needs point correspondence between shapes. The proposal
  already defers morphing (§10); this decision does not un-defer it.
* **Erasing needs an experiment.** `progress` reveals a leading prefix, so
  animating it downwards removes the tail. Erasing from the *start* instead
  needs a dash offset, and LVGL's wrapper exposes only a pattern and a count. A
  pattern beginning with a zero-length dash may achieve it; that is a
  ten-minute probe, not an assumption.
* **The test scene should grow a symbol.** `poc-signature.json` is a
  handwriting scene, which exercises reveal well and structure not at all. A
  second fixture with named parts is needed before the symbol model can be
  called tested.
