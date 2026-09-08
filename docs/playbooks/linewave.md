# Playbook — the line-wave test

A symbolic vector animation used to exercise the whole system at once: one line
that comes in, gathers amplitude, waves, multiplies into synchronized
instances, decays and resolves back to stillness.

```text
flat absence → line enters → amplitude builds → waving
             → instances run in phase-offset loops
             → amplitude decays → flat line → hold
```

Simple enough to reason about, rich enough that any disagreement between two
clients is easy to localise. It is the first test written for symbols rather
than for handwriting ([decision 0005](../decisions/0005-symbols-are-the-payload.md)):
the line is a symbolic carrier — emergence, energy, coherence, dissipation,
stillness — and what is being validated is that a symbol's *transformation over
time* survives being rendered by different implementations on different
machines.

## 1. What it validates

| Concern | How this test reaches it |
|---|---|
| Scene IR expressiveness | a seven-phase timeline on one asset |
| Symbol reuse | three instances of one line, differing only in offset and phase |
| Time-derived playback | every phase is a function of `sceneTime`, nothing accumulates |
| Loop behaviour | periodic motion **without** a loop construct (§4) |
| Cross-renderer conformance | Python reference against the C/LVGL player |
| Cross-client synchronization | the existing failure scenarios, on this scene |
| Capture and comparison | frames, strips, diffs and metrics as artefacts |

## 2. Clients

The minimum useful set today, all of which exist:

```text
A  Python reference renderer      normative baseline
B  C ScenePlayer (LVGL/ThorVG)    the device's own code, on the host
C  a second C node                same-family byte-identity check
```

Later, unchanged scene package: a Raspberry Pi display node, a capture/stream
node, and the ESP32. Adding them is a node configuration, not a scene change —
that is the point of the participant core.

## 3. Timeline

Design canvas 1000 × 300, baseline at y = 150, total 10 000 ms.

| Phase | Start | End | What happens | Meaning |
|---|---:|---:|---|---|
| Come in | 0 | 1200 | `progress` 0 → 1, ease-out | emergence |
| Build up | 1200 | 2600 | amplitude 0 → 46 | activation |
| Waving | 2600 | 3000 | full wave established | motion |
| Instances | 2800 | 3600 | upper and lower revealed | plurality |
| Loops | 3000 | 6200 | phase advances, offsets held | chorus |
| Decay | 6200 | 7600 | amplitude 46 → 12 | calming |
| Flatten | 7600 | 9000 | amplitude → 0 | resolution |
| Hold | 9000 | 10000 | still frame | rest |

The scene package is [`poc/scenes/linewave.json`](../../poc/scenes/linewave.json).

## 4. Two design decisions this test forces

### Loops need no loop construct

A loop expressed as a construct — "repeat this section" — invites an
implementation that counts iterations, and a counter in the render path is
exactly what §10 forbids. It also breaks late join: a node arriving mid-scene
would have to know which iteration it is in.

Instead, `deform.phase` is animated **linearly from 0 to 11 over 5000 ms** and
the renderer takes it modulo one cycle. Periodic motion falls out, and it stays
a pure function of `sceneTime`: seeking to 5500 ms gives the same picture as
arriving there, which is what late join and missed-`PLAY` recovery need.

Phase offsets between instances are then just different `from`/`to` pairs —
+0.25 and +0.5 of a cycle — with no separate notion of "this instance's local
time".

### The wave is a deformation, not a new object type

Three ways to make a line wave:

| | |
|---|---|
| **A** a `wave` object type | easy, but one primitive per artistic idea does not scale, and the geometry stops being authored |
| **B** a `deform` modifier on any path | the authored SVG stays the geometry; Mementum adds the temporal transformation |
| **C** authored path states, interpolated | real morphing; needs point correspondence; deferred (§10) |

**B is the recommendation**, and what the scene package uses:

```json
{ "type": "path", "id": "wave_main", "d": "M 60 150 L 940 150",
  "deform": { "type": "sine", "amplitude": 0, "wavelength": 260, "phase": 0 } }
```

with `deform.amplitude`, `deform.phase` and `deform.wavelength` animatable. It
matches the reframing exactly — SVG contributes geometry, Mementum contributes
the transformation over time — and it applies to any authored symbol, not only
to a line.

The deformation vocabulary must stay small and named. `sine` first; anything
that turns into a general expression language is on the refusal list.

## 5. What this needed, and what it found

Two gaps, both closed:

1. **Sequential animations on one property**
   ([decision 0006](../decisions/0006-animation-phases.md)). Without it the
   build-up was silently erased by the decay and no multi-phase timeline
   worked. Fixing it exposed a second bug — the C evaluator kept stale state
   across frames — and finding *that* exposed a Makefile with no header
   dependencies.
2. **The `deform` modifier** in both players, sampled identically:
   uniform 2.0-design-unit steps, offset perpendicular by
   `amplitude · sin(2π · (distance / wavelength + phase))`.

Two rules were decided while implementing it:

* `progress` is measured on the **undeformed** path, so a reveal and a
  deformation are independent — the wave rides on the stroke.
* A deformed path is revealed by **trimming**, not by dashing: once the player
  generates the geometry it owns the parameterisation.

Rotation is still missing (decision 0005); this test does not use it.

Run it:

```bash
.venv/bin/python -m sim.scenarios linewave      # the checks
.venv/bin/python -m sim.report linewave         # the results package
```

## 6. Scenarios

Run on this scene, reusing the harness rather than inventing a second one:

| # | Scenario | Expected |
|---|---|---|
| 1 | Python alone | stable frame sequence, captures at the sample times |
| 2 | Python + C | same picture: ink and centroid within tolerance |
| 3 | Two C nodes | byte-identical |
| 4 | Late join at ~4200 ms | joiner matches incumbents mid-wave |
| 5 | Lost `PLAY` | recovery on the next heartbeat, entering at current time |
| 6 | Leader change | cancel and restart, per option C |
| 7 | Multi-instance | three instances, offsets held, all time-consistent |
| 8 | Heterogeneous displays | canvas maps onto each display's size via `fit` |

Sample times, chosen to land in every phase:

```text
0   600   1200   2200   3200   4200   5200   6800   8400   9500
```

## 7. Artefacts

```text
sim-out/linewave/
    manifest.json      scene id and hash, clients, renderer versions, capture times
    frames/            <client>_<sceneTime>.png
    strips/            side-by-side per sample time
    diffs/             difference images where clients disagree
    metrics.json       per comparison: differing pixels, ink mass, centroid, bounds
    logs/              schedule events, joins, recoveries, skew samples
```

The tools already exist: `sim/capture.py` for frames, `sim/wall.py` for
side-by-side strips, `sim/assert_sync.py` for diffs, ink mass and centroid.
What is missing is the runner that produces a results package from one command.

## 8. Acceptance

**Functional.** Every client loads the scene, renders every phase, late joiners
catch up, a lost `PLAY` recovers, and the three instances hold their offsets.

**Visual.** Between renderer families, on path-only frames:

```text
differing pixels  < 2 %
ink mass delta    < 2 %
centroid delta    < 1 px
```

Within a family, byte-identical.

These are provisional and exist to catch gross breakage. The real standard is
the one in the previous protocols: whether someone watching for ten seconds
would notice — a stroke arriving in the wrong order, a wave visibly out of
step, an animation that never resolves.

**Synchronization.** Inter-client scene-time skew ≤ 20 ms preferred, ≤ 35 ms
hard, per §10 — a simulated number here, a physical one only on hardware.

## 9. Why this is the right next test

It exercises symbol-first content, the SVG asset path, animation semantics,
symbol reuse, deterministic shared time, multiple clients and the capture path
in one artefact — and because the symbol is a single line, any disagreement is
immediately legible.

The task list is [`linewave-tasks.md`](linewave-tasks.md).
