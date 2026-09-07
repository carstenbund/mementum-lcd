# 0003 — The Phase 0c reference renderer is stdlib-only

* Status: accepted
* Date: 2026-09-07
* Scope: Phase 0c (`mementum_node/core/`, `sim/`). Does not bind the device
  player or the Linux node.

## Context

Phase 0c needs a renderer so that "two nodes produce identical buffers at the
same `sceneTime`" is a checkable claim rather than a wish. The obvious choice
was Pillow, which is available, fast and pretty.

## Decision

The reference renderer — rasteriser, PNG codec and font asset — is written
against the Python standard library only. `requirements-dev.txt` contains
`pytest` and nothing else, and nothing under `mementum_node/` or `sim/` imports
a third-party package at runtime.

## Why

1. **Golden frames rot across library versions** (risk R12). A Pillow upgrade
   changing an antialiasing detail would fail CI with no code change. Owning
   the rasteriser means the only thing that can change a frame is our code.
2. **Determinism is the product.** The rasteriser combines coverage with `max`
   per subsample row and uses fixed subdivision counts, both chosen so that a
   frame is a pure function of the geometry. That is easier to guarantee than
   to verify in someone else's library.
3. **CI without hardware means CI without setup.** `pip install pytest` is the
   whole environment.

## Rejected

* **Pillow** — faster and better looking; rejected for R12 and because the
  quality is not what is being tested.
* **numpy** — would speed the rasteriser up considerably. Reconsider if frame
  rendering ever dominates suite runtime; it does not today (~15 s for 84
  tests).

## Consequences

* The renderer is slow in absolute terms (~17 ms for the test scene at
  480×320). Scale scenarios therefore run with a counting sink and composite
  only where a buffer is actually asserted.
* Text is a 5×7 bitmap asset, not a real font. Text *metrics* consequently do
  not match LVGL's font asset, so cross-renderer golden frames need a
  perceptual tolerance — a Phase 1 conformance question (open question 7),
  which this decision does not prejudge.
* Comparison between two instances of *this* renderer stays exact, which is all
  the Phase 0c gate requires.
