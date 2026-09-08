# 0008 — The animation is the work; interaction is a discovered second layer

* Status: accepted
* Date: 2026-09-07
* Reorders: the priorities in
  [decision 0005](0005-symbols-are-the-payload.md); demotes the modal-attractor
  direction from architecture to possibility.

## Context

A touch ripple was sketched, then propagated to neighbouring units over the
existing unicast plane, and the next step being considered was a coupled
oscillator network with a leader integrating shared state — a substantial piece
of architecture, arrived at in about an hour, for a feature nobody had placed
at the centre of the work.

## Decision

The piece has two layers, in this order:

```text
1  the animation        symbols moving on a shared clock
2  the interactive      a response to touch, found rather than advertised
```

**Layer one is the work.** It must be complete with nobody present: no waiting
state, no affordance announcing itself, nothing that reads as *touch me*. A
room of units is finished whether or not anyone ever touches one.

**Layer two is discovered.** It is additive, and it may fail — a dead touch
controller, a lost message — with no visible damage to layer one.

## What this requires of each layer

**Of layer one.** Nothing changes: composition, the deformation vocabulary, and
units staying in step remain the critical path.

**Of layer two.**

* *Nothing about it may reach the scene or the shared timeline.* Ripples are
  already a runtime overlay rather than scene content, and that stays: the scene
  package, the schedule and `evaluate(sceneTime)` do not know touch exists.
* *The response must differ in kind from the base motion.* This is the part the
  current implementation gets wrong. A ripple is an in-plane offset along the
  stroke — the same thing `sway` already does — so it risks reading as something
  the animation was going to do anyway. A layer nobody can distinguish from the
  animation is a layer nobody discovers. It should be sharper than any base
  motion, or move against the flow, or disturb depth while the base disturbs the
  plane.
* *It must be immediate.* Past roughly 100 ms people stop attributing an effect
  to themselves, and the discovery does not happen. This is why a touch is
  answered locally before it is reported, and why touch sampling must stay out
  of the frame loop on the device.
* *Propagation exists to make a discovery visible to others.* Not "the crowd
  excites the system": one person finds the layer, and the ripple crossing the
  room is how everyone else learns it is there.

## Consequences

* **No leader-side integrator, and no field-as-state.** Both were reasonable
  answers to a question this decision says not to ask yet. The system keeps its
  property that nothing accumulates anywhere.
* **Modal attractors become a possibility**, something the second layer might
  grow into once layer one is finished and on hardware — not something to shape
  the architecture around now.
* The ripple's character is a known gap, recorded here rather than fixed in
  passing: it needs to differ in kind from the base motion before the layer is
  discoverable at all.
* Priorities, restated:

```text
critical path:  the animation — composition, deformations, shared timing,
                the C player on hardware
additive:       touch, local response, propagation to neighbours
possibility:    coupled modes, attractor states, crowd-scale behaviour
```
