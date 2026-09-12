# 0014 — A panel is a client, because the server hands out scenes

* Status: accepted
* Date: 2026-09-09
* Relates to: [decision 0013](0013-control-server-ported.md),
  `mementum-led`'s `http_controller` firmware, proposal §18 (the asset plane),
  §3.2 (the three substitutions)

## Context

`mementum-led`'s firmware is both client and server: a device reads its config
at boot and either joins a swarm or raises the soft-AP and runs the show. That
is a good arrangement for content that is a *string* — the whole of what a panel
must be told fits in a query parameter, so the thing that holds the content is
no bigger than the thing that shows it.

An LCD panel is told a *scene*: a document of paths, animations and their
measured lengths, kilobytes rather than bytes, referenced by hash and fetched.
Somewhere has to hold the library that a show draws from, and that somewhere
needs a disk, a compiler for handwriting, and room for every scene the guide
names — none of which an ESP32-S3 has.

## Decision

**A panel is a client.** It registers, heartbeats, syncs its clock, fetches
what it is told to show, and draws it. It does not distribute anything.

The wire is `mementum-led`'s, extended by exactly what the difference requires:

```
/register  /heartbeat  /time                        as the LED firmware
/scene/<id>  /manifest/<id>  /asset/<hash>          the asset plane
```

and a panel serves the push routes, as the LED firmware does, because that is
how a push reaches a device with no connection held open:

```
/play?seq&at&scene&hash&duration    take this schedule (idempotent on seq)
/ripple?at&x&y&amplitude            a wave through the ink, now
/clear  /status
```

Dual mode is not refused, only unbuilt: nothing here forecloses a device
running `mementum_node.server` alongside the client one day. It would need
somewhere to keep the scenes, and that is the question to answer first.

## What this is made of

`ParticipantCore` needed **nothing added** to live on a network — the whole
client is three substitutions (§3.2):

| | |
|---|---|
| clock | `CristianClock` querying `/time`, best of three round trips |
| transport | `HttpTransport` — REGISTER, HEARTBEAT, manifest, asset |
| sink | a screen, a headless buffer, or nothing at all |

plus a listener, which is not part of the core because being pushed to is a
property of the binding rather than of participating.

The same is true on the device: `poc/player/schedule.c` is what a panel does
with a push — adopt it if it is new, ignore it if it is not — and it is plain C
with no dependencies, so the sketch and the host tests compile the same lines.
`tests/test_device_schedule.py` pins the three behaviours a wall depends on: a
repeated push does not restart a scene, a late one does not undo a newer one,
and scene time is `now - displayAt` and nothing else.

## The firmware

`poc/firmware/mementum_lcd/` is the ESP32-S3 sketch, deliberately the same
shape as the LED one. Everything it draws with is symlinked from
`poc/player/`; only `net.cpp` is device-only.

**It compiles; it has never run.** CI builds both paths on every push — the
ESP-IDF project at 565 KB and this sketch at 1.32 MB — so `net.cpp` is past a
compiler and ThorVG builds for Xtensa. Nothing is known about how it behaves:
no board, therefore no frame time, no PSRAM bandwidth, no skew. What is
verified without one is the shared C, by the host suite, and the protocol,
end-to-end over real sockets, by the Python node in
`tests/test_client_server.py` — which speaks exactly what the firmware speaks.
The first bring-up will be about the display driver, PSRAM and LVGL's config,
not about the protocol.

## Consequences

* A wall can be simulated on one host — sixteen panels, sixteen ports — and the
  server cannot tell the difference, which makes the whole thing testable
  without hardware.
* A panel that missed a push is put right by its next heartbeat, on a real
  network as in simulation. That is not a recovery mechanism; it is the
  schedule being state (§19).
* Open: the display driver for a specific board; a panel that holds a *scene
  layer* rather than compositing frames (decision 0011's faster path); and dual
  mode, if a device ever has somewhere to keep a library.
