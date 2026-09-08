# 0006 — The active animation is the last one to have started

* Status: accepted
* Date: 2026-09-07
* Found by: drafting the line-wave playbook, before writing any wave code

## Context

A scene with phases — build up, then decay — needs two animations on the same
property at different times. The evaluator applied *every* animation in
declaration order, last one wins, so the later animation's `from`-hold silently
overwrote the earlier one for all time before it started:

```text
opacity: 0→1 over [0, 1000], then 1→0 over [5000, 6000]

    t=0     1.000     ← wrong; the fade-in never happens
    t=500   1.000     ← wrong
    t=5500  0.500     ← right, by accident
```

Every phase list in the line-wave playbook needs this to work, and no scene
written so far had two animations on one property, so nothing caught it.

## Decision

For each property of each object, the animation that applies at `sceneTime` is
**the last one, in declaration order, whose `start <= sceneTime`**. Before any
animation on that property has started, the object keeps its authored value.
Within an animation, hold semantics are unchanged: `from` before it starts,
`to` after it ends.

```text
opacity: 0→1 over [0, 1000], then 1→0 over [5000, 6000]

    t=0     0.000
    t=500   0.500
    t=1000  1.000
    t=3000  1.000     ← the first animation holds its to-value
    t=5500  0.500
    t=6000  0.000
```

## Why this rule

* **It stays pure.** The value at a time is still a function of the time alone;
  seeking equals stepping, which late join and missed-`PLAY` recovery depend on.
* **It needs no new syntax.** Phases are ordinary animations with different
  start times, so the IR does not grow a keyframe track or a phase construct.
* **Declaration order still breaks ties**, so two animations starting at the
  same instant behave as before.

## Consequences

* Authors express a phase list as consecutive animations, which is what anyone
  would write anyway; the previous behaviour would simply have discarded all
  but the last.
* Overlapping animations on one property no longer blend — the later one takes
  over when it starts. Blending is not in v1 and inventing it here would be
  scope creep.
* Both evaluators change identically, and a shared test vector pins them
  together.
* **It exposed a second bug in the C player.** That evaluator writes animated
  state in place, for the device's sake. Once an unstarted animation stops
  imposing its ``from`` value, a property with no active animation keeps
  whatever the *previous* frame left — so rendering 4200 ms and then 700 ms
  showed the caption at 700 ms. The evaluator now resets every animatable
  property to its authored value before applying anything, which is what makes
  it a pure function of the time rather than of the frame history. That is §10's
  rule arriving through the back door: no accumulation, including accumulation
  by leftover state.
* The host Makefile gained header dependency tracking (``-MMD -MP``) in the
  course of finding it. Without that, editing ``scene_model.h`` left half the
  objects compiled against the old struct layout, which presents as heap
  corruption rather than as a build error.
