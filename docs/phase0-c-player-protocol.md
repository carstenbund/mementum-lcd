# Phase 0 — the C ScenePlayer, behind the simulator

Test protocol and conclusions for the step that puts the device's own player
inside the existing harness: implementation plan §3.7, using the Phase 0c
simulator unchanged around it.

**On the standard being applied.** Same as the previous round. The numbers are
here because measuring is cheap, not because this is instrumentation. What is
being built shows handwriting that appears and is gone in a few seconds, and
the test that matters is whether a person watching would notice something
wrong. Differences below that threshold are recorded and should not drive
design.

| | |
|---|---|
| Date | 2026-09-07 12:25 UTC |
| Scope | plan §3.7; risk R6; the two `progress` rules from the previous round |
| Revision | `e169f06` plus the working tree at the time of the run |
| LVGL | v9.5.0 (pinned), ThorVG vendored inside it |
| cJSON | v1.7.18 (pinned) — the parser ESP-IDF also ships |
| Compiler | gcc / g++ 13.3.0 |
| Platform | Linux 6.8.0-139-generic aarch64, 4 cores |
| Hardware under test | none |

---

# Part 1 — Protocol

## 1. What was built

`poc/player/` — the player in portable C, intended to compile unchanged under
ESP-IDF later:

| File | Lines | Role |
|---|---:|---|
| `scene_model.h` | 129 | the structs the device holds |
| `scene_json.c` | 289 | package → structs, via cJSON |
| `easing.c` | 37 | the normative curves, second implementation |
| `evaluator.c` | 40 | `state = evaluate(sceneTime)`, pure |
| `geometry.c` | 236 | path parsing, subpaths, arc length |
| `render_lvgl.c` | 226 | evaluated state → LVGL/ThorVG |
| `player.c` | 193 | the library surface ctypes calls |
| headers | 182 | |
| **Total** | **1332** | |

Python side: `core/render_backend.py` (the `Renderer` seam and the reference
implementation), `mementum_node/players/lvgl.py` (the ctypes binding), one new
argument on `ParticipantCore` and on `SimNode`. The simulator itself is
otherwise untouched.

The seam sits at `(scene, sceneTime) → Frame`, above evaluation rather than
below it, so the C player evaluates the scene with its own code. A seam below
evaluation would have kept Python's evaluator in the loop and proved nothing.

## 2. Build

```bash
poc/host-player/fetch-lvgl.sh && poc/host-player/fetch-cjson.sh
make -C poc/host-player -j4 all
```

| Quantity | Value |
|---|---|
| Objects compiled | 539 (LVGL, ThorVG, cJSON, the player, two probes) |
| Clean build, `-j4` | **10 s** |
| `libmementum_player.so` | 10,561,160 bytes (unstripped, `-O2 -g -fPIC`) |
| Warnings from `poc/player/` | 0 (one from LVGL's own `lv_chart.c`) |

## 3. Conformance — does the device's code agree with the reference?

```text
easing, C vs Python, 4 curves x 1001 points: max delta 8.18e-08
evaluator, 201 scene times: max progress delta 6.33e-08, max opacity delta 0.00e+00
path length: python 906.368  C 906.368  (0.0000% apart)

three-strokes, drawn width of each stroke (of 100 px):
  t=    0 ms  progress=0.00      0    0    0
  t=  500 ms  progress=0.17     53    0    0
  t= 1500 ms  progress=0.50    103   53    0
  t= 2500 ms  progress=0.83    103  103   53
  t= 3000 ms  progress=1.00    103  103  103
```

The three-strokes figures are drawn width per stroke, of a 100 px line; 103 px
is the line plus its round caps. The staircase is the point: one stroke
completes before the next begins.

## 4. The mixed swarm

```bash
.venv/bin/python -m sim.scenarios mixed_renderers      # exit status 0
```

Four nodes — two on the Python reference, two on the C/LVGL player — playing one
scene through a lost `PLAY`, two late joins with empty caches, and a leader
change.

```text
scenario: mixed_renderers
  [PASS] both renderer families are playing -- {'py-a': 'playing', 'py-d': 'playing', 'c-b': 'playing', 'c-c': 'playing'}
  [PASS] both families render the same number of frames -- {'py-a': 72, 'py-d': 72, 'c-b': 72, 'c-c': 72}
  [PASS] python nodes are byte-identical to each other -- b2a42492ae32
  [PASS] C/LVGL nodes are byte-identical to each other -- 257fb5927c06
  [PASS] python and C draw the same picture at 700ms -- ink 1.03% apart, centroid 0.02 px apart (ink 34.0k at (49.74, 176.62) vs ink 33.6k at (49.75, 176.60))
  [PASS] python and C draw the same picture at 1400ms -- ink 0.93% apart, centroid 0.10 px apart (ink 131.3k at (84.43, 187.93) vs ink 130.1k at (84.36, 187.83))
  [PASS] python and C draw the same picture at 2100ms -- ink 0.77% apart, centroid 0.09 px apart (ink 289.2k at (126.60, 192.98) vs ink 287.0k at (126.50, 192.96))
  [PASS] python and C draw the same picture at 2900ms -- ink 0.74% apart, centroid 0.15 px apart (ink 466.9k at (186.66, 191.62) vs ink 463.5k at (186.50, 191.57))
  [PASS] the C node missed the pushed PLAY -- seq 1 vs 2
  [PASS] the C node recovered on the heartbeat -- seq 2, 1 heartbeat recoveries
  [PASS] late joiners on both renderers adopted the schedule -- python seq 2, c seq 2
  [PASS] the python joiner matches its family exactly
  [PASS] the C joiner matches its family exactly
  [PASS] both families cancelled on the leader change -- {'py-a': 'idle', 'py-d': 'idle', 'c-b': 'idle', 'c-c': 'idle', 'py-late': 'idle', 'c-late': 'idle'}
  [PASS] both families restarted together -- {'py-a': 'playing', 'py-d': 'playing', 'c-b': 'playing', 'c-c': 'playing', 'py-late': 'playing', 'c-late': 'playing'}
  [PASS] after all of that, the two renderers still agree -- ink 0.77% apart, centroid 0.09 px apart (ink 289.2k at (126.60, 192.98) vs ink 287.0k at (126.50, 192.96))
  leader_epoch: 2
  renderers: {'py-a': 'python', 'py-d': 'python', 'c-b': 'lvgl', 'c-c': 'lvgl', 'py-late': 'python', 'c-late': 'lvgl'}
  text_divergence_at_4200ms: ink 10.06% apart, centroid 7.97 px apart (ink 736.1k at (200.30, 206.07) vs ink 662.0k at (208.27, 199.91))
  => PASSED
```

## 5. Test suite

```bash
.venv/bin/python -m pytest -q
```

```text
117 passed in 18.36s
```

| Test module | Tests |
|---|---:|
| `tests/test_c_player.py` | 31 (new) |
| `tests/test_scenarios.py` | 14 (+2) |
| `tests/test_easing.py` | 13 |
| `tests/test_render_determinism.py` | 12 |
| `tests/test_geometry.py` | 11 |
| `tests/test_capture_and_wall.py` | 10 |
| `tests/test_scene_and_evaluator.py` | 10 |
| `tests/test_layering.py` | 9 |
| `tests/test_clock_and_protocol.py` | 7 |
| **Total** | **117** |

Everything needing the C player skips when the library is absent, so the suite
still runs on a machine with no C toolchain.

---

# Part 2 — Conclusions

## C1. There is one evaluator now, not two

C and Python agree to 8×10⁻⁸ on easing across 4004 sample points, to 6×10⁻⁸ on
evaluated `progress` across 201 scene times, and exactly on opacity. The
remaining difference is `float` against `double` and nothing else.

R6 — easing diverging between the two implementations — was a discipline
problem, to be caught by a conformance suite that did not exist yet. It is now
a build-time check that runs on every push in ten seconds. That is the whole
value of §3.7, and it arrived earlier than the plan expected it to.

## C2. The two renderers draw the same picture, and the swarm can mix them

Within a renderer family, frames are byte-identical. Across families they are
0.74–1.03 per cent apart in ink with the centre of the ink within 0.15 px —
antialiasing, not geometry. Two people looking at the two panels would not be
able to say which was which.

That holds while the protocol is being abused: a lost `PLAY` recovered from the
heartbeat, two nodes joining mid-scene with empty caches, a leader change
cancelling and restarting everything. What is being exercised is therefore the
scene semantics, not one renderer's habits.

## C3. Both visible rules survived contact

* **Strokes arrive one at a time.** The dash restarts at every `moveTo`, so the
  player sequences subpaths itself: completed strokes plain, the current one
  dashed, the rest not drawn. The staircase in §3 is that rule working.
* **The signature finishes.** At `progress >= 1` the dash is dropped entirely,
  and a finished scene stays finished at every later time.

Both are pinned by tests against a new fixture, `poc/scenes/three-strokes.json`,
which is small enough to reason about and exists precisely so these two rules
cannot regress quietly.

## C4. Declared length works, and nobody needs to match anyone's flattening

The player uses the scene's `length` when it carries one and measures only as a
fallback. With both implementations now using the same subdivision rule they
measure *identically* (906.368 px), so the divergence that prompted the
discussion has gone to zero on its own — but the declared value is still the
better arrangement, because it does not depend on that coincidence continuing.

## C5. Text is the one thing that does not agree

10 per cent apart in ink, centre 8 px away. `font_id` resolves to a built-in
Montserrat in the C player and to a 5×7 bitmap in the reference, so the caption
is genuinely a different picture. This is asserted as a *known* divergence
rather than tolerated: a test fails if the two ever silently start agreeing.

The fix is not a tolerance. Fonts belong on the asset plane, addressed by
content hash like everything else (proposal §9, §18), so that both players
rasterise the same glyph outlines. That is the piece to settle before v1 is
frozen.

## C6. What this does not say

* **Nothing about the ESP32.** This is the device's C code on an aarch64
  desktop with a software renderer. Frame rate, PSRAM bandwidth, flush cost and
  whether LVGL builds under ESP-IDF with these switches are all untouched.
* **Nothing about real timing.** Fan-out, clock jitter and skew remain
  simulated.
* **The player is not complete.** No asset loading from flash, no clipping, no
  gradients, no Lottie — the v1 subset and no more.

## C7. Where this leaves the ladder

```text
Phase 0c — Python simulation
  scene semantics, deterministic evaluation, late join,
  lost PLAY recovery, clock model, 300-node protocol model   done

Phase 0 host — C + LVGL + ThorVG
  vector rendering, runtime stroke progress                  done
  scene loader, evaluator, renderer in device C              done
  one evaluator shared by both players                       done
  mixed swarm under the failure scenarios                    done

Outstanding
  font assets on the asset plane                             the v1 blocker
  LVGL text cost, ESP32 build, frame rate, PSRAM, LCD flush  needs hardware
  real network timing, two-node physical skew                needs hardware
```

The remaining Scene IR question before a v1 freeze is fonts. Everything else
outstanding needs a board.
