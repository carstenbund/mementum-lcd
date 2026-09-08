# 0007 — `helix`: depth without a 3D pipeline

* Status: accepted
* Date: 2026-09-07
* Extends: the `deform` modifier from
  [the line-wave playbook](../playbooks/linewave.md)

## Context

A travelling sine offset applied to the signature's irregular loop reads, in
motion, as if the line were turning in space rather than wobbling on glass. The
observation was worth taking literally: if the eye is already reading depth,
give it depth.

## Decision

`helix` joins `sine` in the named deformation vocabulary. The same travelling
wave is applied twice, a quarter cycle apart:

```text
in-plane   offset = amplitude * sin(2*pi * (distance/wavelength + phase))
in depth   z      = amplitude * cos(2*pi * (distance/wavelength + phase))
```

`z` is projected back onto the design canvas about its centre, which is the
vanishing point:

```text
k = focal / (focal - z)
x' = cx + (x - cx) * k
```

`focal` is a property of the deformation, in design units, defaulting to 520.

**There is no 3D pipeline and there should not be one.** One `z` per sample, one
divide, and the output is the same strokes as everything else — no scene graph,
no camera, no lighting model, nothing on the refusal list.

## Sway and depth are separate numbers

`amplitude` moves the stroke *into* the picture; `sway` moves it *across*. They
were one number at first, and that was wrong for a reason worth writing down.

Offsetting a curve inward by more than its own radius of curvature makes the
curve cross itself. On the signature fixture the tightest loops have a radius of
**14 design units**, and 8 % of the path is tighter than an amplitude of 26 — so
a helix at 26 produced small folds in the loops that read as unexplainable
ripples rather than as motion. Depth cannot do this: a perspective scale about
the vanishing point never folds a curve.

Splitting them fixes it without losing the effect: 34 into the picture and 10
across it keeps the loops legible while the turn still reads.

`sway` defaults to 40 % of the amplitude, and the rule for choosing one is
simply **keep sway below the path's tightest radius**. A test encodes that for
the shipped scene, because it is an artistic property that would otherwise
regress silently.

A curvature-limited offset was tried first — locally clamping the offset to the
radius — and rejected: it facets the tight loops into polygons, trading one
inexplicable artefact for another.

## Depth is drawn, not just projected

Projection alone is a weak cue. What sells the turn is that nearer parts of the
stroke are thicker and brighter, and that requires an awkward accommodation: a
stroke width belongs to a *path*, not to a point — in LVGL and in our own
rasteriser alike. So a helical stroke is drawn once per depth band:

```text
bands       8, far to near
width       base * k(band)
brightness  0.45 (far) .. 1.0 (near)
```

The band's depth factor is analytic — derived from amplitude and focal length
rather than measured per frame — so both players band a stroke identically
without having to agree on anything at run time.

Eight bands is a judgement: enough to read as continuous, few enough that a
stroke costs eight draws rather than one per segment.

## Evidence

Python reference against the C/LVGL player, the signature loop at amplitude 26:

| phase | ink apart | centroid apart |
|---:|---:|---:|
| 0.00 | 0.81 % | 0.06 px |
| 0.15 | 0.78 % | 0.05 px |
| 0.37 | 0.78 % | 0.08 px |
| 0.62 | 0.87 % | 0.05 px |
| 0.85 | 0.76 % | 0.04 px |

That the shading is real rather than incidental is measured too: at the same
amplitude a helix has a mean lit brightness of 147 against a sine's 189, and
carries roughly six times as much mid-grey relative to full brightness.

## Consequences

* **A helical stroke costs eight draws instead of one.** Cheap on a host — 4 ms
  per 960×640 frame through the C player — and unmeasured on an ESP32, where it
  is the first deformation whose cost is not obviously negligible.
* `progress` still measures on the undeformed path, so a reveal and a turn stay
  independent.
* **Ink mass is a poor proxy for "is it drawing" on helical scenes**, since
  dimmed far bands outweigh the near half's growth.
* The vanishing point is the *canvas* centre, so where an object sits decides
  how much perspective it gets. That is correct, and it means moving a symbol
  changes its turn — which should be checked by eye before anyone relies on it.
