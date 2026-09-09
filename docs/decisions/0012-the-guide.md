# 0012 — The guide: a running order, not a remote control

* Status: accepted
* Date: 2026-09-09
* Relates to: proposal §19 (schedule as state), §20 (fan-out and the display
  lead), [decision 0006](0006-animation-phases.md) (the governing animation),
  `core/guide.py`, `core/sequencer.py`

## Context

The control server could play one scene, when somebody told it to. That is a
remote control, and it is the wrong shape for the thing being built: an
installation runs a *show*, and a show is written down before anybody is in the
room — a running order of what happens and when.

The temptation is to reach for a scheduler: a thread, a list of pending timers,
a cursor through the cue list that advances as things fire. Everything in this
project that has gone wrong has gone wrong that way. State that advances has to
be recovered when a node joins late, when the server restarts, when a tick is
missed, when somebody seeks — four mechanisms where there should be none.

## Decision

**A guide is a document, and the show is a function of the clock.**

* A **cue** has a timecode: milliseconds from the top of the show. The show has
  an **epoch** in shared time, so a cue's moment is `epoch + at` — which is
  precisely the `displayAt` every node already evaluates against. The guide is
  therefore portable: the same file plays tomorrow, or from the middle, or
  twice, unedited.
* **What is on the wall is evaluated, never accumulated.** It is the last scene
  cue whose timecode has passed — the same rule the evaluator uses for
  animation phases, for the same reason. A node joining halfway through gets
  the answer from the ordinary registration reply; seeking is the epoch moving;
  a server that ticked late fires what it missed. None of these is a mechanism.
* **Scenes are state, effects are moments.** A `text` or `animation` cue
  becomes the schedule and is therefore recovered. An `effect` cue — a ripple
  crossing the wall — is pushed and forgotten, exactly like a touch. A unit
  that misses one did not ripple, and nothing has to catch up.
* **Cues are pushed one display lead early.** `tick()` is responsible for the
  window `(fired_through, show_time + lead]`, half-open below so a cue fires
  once however finely the host ticks.

**No new wire message was needed.** A cue becomes `PLAY` or `RippleCommand`.
The device learns nothing about shows, guides or timecodes, which is the test of
whether the abstraction sits in the right place.

## Text

`play text` compiles to pen strokes, like everything else in this project: the
composer measures, the device draws (decision 0004). A `text` cue normally
carries a scene id compiled before the show — a show should not be doing work at
the moment it is meant to be showing something.

A cue marked `live` keeps its words instead, and they are compiled when it
fires. That is the escape hatch for a line decided during the show. It is still
the composer that compiles — the callable is handed to the sequencer from
outside the core, so `mementum_node/core/` keeps its stdlib-only rule — and it
is still a scene that reaches the panel. **No node holds a font**, and there is
no second rendering path on the device to keep in step with the first.

A line that will not compile is refused visibly and the show continues to the
next cue. Failing silently on the night is worse than a gap.

## Authoring

The cue sheet is screen-HTML, because that is this project's authoring language
and inventing a second one has already been rejected once
([decision 0009](0009-vector-painter-ports-back.md)):

```html
<guide name="opening">
  <cue at="00:00:00" play="animation" scene="poc/scenes/symbols-blend.json" />
  <cue at="00:00:19" play="text">du kannst werden was du willst</cue>
  <cue at="00:00:27" play="effect" unit="unit-11" amplitude="16" />
  <cue at="00:00:41" play="effect" amplitude="10" />
</guide>
```

`tools/guide.py` compiles it into a **show package**: the guide document plus
every scene it refers to, so a runner needs nothing else. An unknown attribute
is an error at compile time — cheaper than wondering on the night why nothing
happened.

An effect naming a unit travels from there at `TOUCH_SPEED_M_S`; an effect
naming none excites every unit at once. Those are different gestures and should
look like it.

## The clock

The server is the master: it owns the epoch, and transport is `start_show`,
`seek`, `stop_show`. Following an external timecode source (LTC/MTC from a
lighting desk) would replace the epoch with a chase, and nothing above it would
change — the cue logic asks the clock for the show time and does not care where
that came from. Not built, deliberately: two clock domains want drift policy and
a dropout policy, and neither is worth designing before there is a desk to lock
to.

## Consequences

* `Sequencer` is now a show controller: `load_guide`, `start_show`, `tick`,
  `seek`, `stop_show`, `show_time`. `play()` is unchanged and still means what
  it did, so calling a scene by hand mid-show still works.
* A hand on the glass is not a special case during a show: `touch()` was
  already there, and the ripple crosses the wall while the scene keeps playing.
* Open: an external timecode source; a cue that changes *deformation* rather
  than scene; per-unit cues (a wall that is not one picture but sixteen).
