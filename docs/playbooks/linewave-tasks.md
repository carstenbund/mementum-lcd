# Line-wave — task list

Implementation checklist for [`linewave.md`](linewave.md). Ordered so that each
block leaves the repository working, and so the two IR gaps are closed before
anything depends on them.

## A. IR semantics (blocking everything else)

- [x] **A1** Sequential animations on one property — the active animation is the
      last one whose `start <= sceneTime`
      ([decision 0006](../decisions/0006-animation-phases.md)). Python and C,
      with a shared test vector.
- [x] **A2** `deform` on a path object: `{type, amplitude, wavelength, phase}`,
      with `deform.amplitude`, `deform.phase`, `deform.wavelength` animatable.
      Parse and validate in both loaders; unknown `type` fails visibly.
- [x] **A3** Sine deformation in the Python reference: sample the flattened
      path, offset each sample perpendicular to the baseline by
      `amplitude · sin(2π · (distance / wavelength + phase))`.
- [x] **A4** The same in `poc/player/geometry.c` + `render_lvgl.c`, sampling
      identically. Conformance test against A3 at several phases.
- [x] **A5** Sampling density decided and written into both implementations:
      uniform steps of 2.0 design units along the undeformed arc length, always
      including the final point. It is the one number that changes the wave's
      shape between players, so it is stated in `geometry.h` and `geometry.py`
      rather than left implicit.

## B. Scene and assets

- [x] **B1** `poc/scenes/linewave.json` — the timeline, three instances,
      declared lengths.
- [ ] **B2** `poc/assets/line.svg` — the authored source: one path, stable
      `viewBox`, named id, no filters or metadata.
- [ ] **B3** Preprocessor sketch: SVG → normalized path, bounds, total and
      per-subpath length, content hash, preserved part ids. Enough to produce
      B1 from B2 rather than by hand.

## C. Rendering the scene

- [x] **C1** Python reference renders all seven phases; eyeball a strip.
- [x] **C2** C player renders the same; compare at the sample times.
- [x] **C3** Check the three instances hold their phase offsets (+0, +0.25,
      +0.5 cycle) at several times — the thing a viewer would notice first.

## D. Scenarios

- [x] **D1** `sim/scenarios/linewave.py`: Python + two C nodes, full playback.
- [x] **D2** Late join at ~4200 ms — mid-wave entry matches incumbents.
- [x] **D3** Lost `PLAY` — recovery on the heartbeat, entering at current time.
- [x] **D4** Leader change — cancel and restart, option C.
- [x] **D5** Heterogeneous displays — 1000×300 canvas onto 480×320 and
      1920×1080 via `fit`.

## E. Results package

- [x] **E1** `sim/report.py`: run a scenario, write
      `sim-out/linewave/` with manifest, frames, strips, diffs, metrics, logs.
- [x] **E2** Metrics per compared frame: differing pixels, ink mass, centroid,
      bounds, scene time, client pair — JSON, one row per comparison.
- [x] **E3** Timing metrics per client: adopted `displayAt`, local `sceneTime`
      at capture, clock offset, time-to-ready, late-join catch-up.
- [ ] **E4** Summary report from the package, in the form of the previous
      protocols.

## F. Later, unchanged scene package

- [ ] **F1** Raspberry Pi display node (`nodes/display.py` → DRM/KMS).
- [ ] **F2** Capture / stream node.
- [ ] **F3** ESP32 target: same scene, same checkpoints, frame hashes compared
      against the C player on the host.

## Questions this test answered

* **Sampling density** — per unit length: uniform 2.0 design-unit steps. A fixed
  count would make the wave's smoothness depend on the path's size.
* **`progress` composes with `deform`** by being measured on the *undeformed*
  path. The wave rides on the stroke rather than changing how much of it has
  been drawn, and `test_progress_is_measured_on_the_undeformed_path` pins it.
* **A deformed path is revealed by trimming, not by dashing.** Once the player
  generates the geometry it owns the parameterisation, so the dash mechanism —
  needed for authored paths — is not used here.
* **`wavelength` is in design units.** Simpler, and the design canvas is
  already the coordinate system everything else uses.

## Since added

* `helix` — the same wave in-plane and in depth, projected, with depth-banded
  width and brightness ([decision 0007](../decisions/0007-helix-deformation.md)).
  Scene: `poc/scenes/loop-helix.json`. Tests: `tests/test_helix.py`.
* `sim/record.py` — a record node walking scene time into ffmpeg, so a scene can
  be watched rather than only asserted (plan 0b.2, 0b.3).

## Still open

* Do the instances want a symbol asset reference rather than three copies of
  the same `d`? That is the symbol model from decision 0005, and this scene is
  the natural place to introduce it.
* `transform.rotate` still does not exist in either player (decision 0005).
* Erasing from the start of a path — `progress` removes the tail; a leading
  erase needs a dash offset LVGL may not expose. Ten-minute probe, not yet run.
