# 0013 — The control server is `mementum-led`'s, ported

* Status: accepted
* Date: 2026-09-09
* Relates to: [`mementum-led`](https://github.com/carstenbund/mementum-led)
  `server.py`, [decision 0009](0009-vector-painter-ports-back.md) (don't invent
  where something exists), [decision 0012](0012-the-guide.md), proposal §18–§20

## Context

`mementum-led` already has a control server, running on a Pi, driving a swarm
of ESP32 matrices. It describes itself as *"a faithful port of the ESP32
AP-mode server"* — same routes, same protocol, so a panel can be pointed at
either and the swarm can grow past the soft-AP's twenty clients.

That server had already solved things this project was about to solve again:

| It has | We were calling it |
|---|---|
| `/effect?stagger=auto` — one full go of the content per panel | `spread="stagger"` |
| `/effect?stagger=tile` — one panel width, so it tiles into a single marquee | `spread="run"` |
| `factor` — below 1 a glide, above 1 a gap, or the bezel between panels | *nothing* |
| `order=` — the physical order, because the wall was hung by a person | *nothing* |
| `/identify` — every panel shows its own id, so the wall can be read | *nothing* |
| `effect_until` — an effect holds the sequencer off so it is not overwritten | *nothing* |

And the same clock model, arrived at independently: schedule at
`displayAt = serverNow() + DISPLAY_LEAD_MS`, render from `serverNow() -
displayAt`.

## Decision

**The LCD control server is a port of the LED one**, not a new design. Route
names, parameter names, response shapes and the sentences a firmware parses are
kept. `mementum_node/server/` is `log.py`, `registry.py`, `broadcast.py`,
`app.py` — bindings only, no show logic: that is `core/sequencer.py`, which the
simulator drives and which did not change to gain an HTTP interface.

Vocabulary follows: a cue's `spread="stagger"|"run"` became
`stagger="auto"|"tile"|<time>` with `factor`, `reverse` and `order`. Two
separate questions, kept separate as the LED server keeps them: `spread` is
*what* each unit shows, `stagger` is *when* it starts.

## One wall, two kinds of panel

The reason to keep the wire form is not tidiness. An LED matrix and an LCD
panel can stand on the same wall, registered with the same server, playing the
same cue:

```
/play?seq&at&data=<text>                     an LED matrix scrolls the string
/play?seq&at&scene=<id>&hash=…&url=/scene/…  an LCD panel draws the scene
```

A cue written as words reaches both: the matrix gets the string, the panel gets
the scene compiled from the same words. It works in the other direction too,
because `tools/handwriting.py` keeps `text` in the scene it compiles — so a
*scene* cue still has a string form for a panel that can only scroll. A scene
that was never words (a symbol, a deformation) cannot cross, and the server
says so in the log rather than leaving a panel dark while everybody wonders.

Which panel gets which is not a special case: it is the capability gate that
was already there (§18). An LED client registers as
`Capabilities(scene_ir=0, vector=False, text=True)` and the sequencer's
existing playability check does the rest.

## What was changed rather than copied

* **Identity is address *and* port.** The LED server keys on source IP, which
  is right when every panel is its own device on port 80. A simulated wall is
  sixteen panels at one address; keying on where the server can reach them
  costs nothing and the firmware, which sends no port, is unaffected.
* **An asset plane.** `/scene/<id>` and `/manifest/<id>`: a string fits in a
  query parameter, a scene does not.
* **A show.** `/guide`, `/start`, `/seek`, `/stop`, `/show` — decision 0012's
  running order, which the LED server has no equivalent of (its content is a
  queue of strings with play counts).
* **`/touch`** — a hand on a panel, relayed to the wall at `TOUCH_SPEED_M_S`.

## Consequences

* A panel that speaks the LED protocol works here unmodified.
* `/effect` and a `stagger` cue are the same gesture asked for in two places,
  and go through one method (`Sequencer.sweep`) — a show controller with two of
  those would be a poor one.
* Open: an HTTP *client* — a Pi or an ESP32 that registers, heartbeats and
  fetches scenes from this server. Everything above it exists; the panels in
  `poc/show_demo.py` are still in-process.
* Open: the LED server's queue and its play-count throttle. This server plays a
  guide; a queue of loose lines with repeat limits is a different content model
  and has not been ported.
