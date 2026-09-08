"""screen-HTML with a timeline -> a scene package.

`drm_composer` already has an authoring language: screen-HTML, an XML subset
with `<screen>`, `<layer>` and primitives at absolute coordinates. What it does
not have is time. The implementation plan (§0b.1) says what to add —

    <animate target= property= from= to= start= duration= easing= />

— so that is the element this compiler reads, and the shorthand below sits in
the same idiom rather than in a second language.

    tools/compose.py poc/screens/symbols.html --out poc/scenes/symbols-blend.json

Elements:

    <screen width height name id>       the canvas
    <layer id z>                        a plane, painted in z order
    <box x y w h color/>                a filled rectangle (screen-HTML)
    <symbol id src stroke stroke-width  a traced mark, drawn as a line
            draw seen excite handover exit gap/>
    <writing src words stroke ...>      a page of handwriting
        <word name draw seen exit gap/> one word from it
    <animate target property from to start duration easing/>

Durations accept `1.4s` or `1400ms`. The phase attributes on `<symbol>` and
`<word>` are shorthand: each expands into ordinary `<animate>` records, and
anything the shorthand cannot say can be written as `<animate>` directly.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from symbol_scene import CHUNK, compact_path, read_contours, simplify  # noqa: E402
from writing_scene import group_words, read_centrelines  # noqa: E402

from mementum_node.core.geometry import flatten_path, polyline_length  # noqa: E402

PHASES = ("draw", "calm", "seen", "excite", "handover", "exit", "gap")
DEFAULTS = {"excited": 24.0, "resting": 3.0, "sway": 5.0, "turn": 16.0}


def duration(value: str | None, fallback: float = 0.0) -> float:
    """`1.4s`, `1400ms`, or a bare number of seconds."""
    if value is None:
        return fallback
    text = str(value).strip().lower()
    if text.endswith("ms"):
        return float(text[:-2]) / 1000.0
    if text.endswith("s"):
        return float(text[:-1])
    return float(text)


def _bounds(points):
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return (min(xs), min(ys), max(xs), max(ys))


def symbol_geometry(source, width, height):
    closed = [simplify(c) + [c[0]] for c in read_contours(open(source, encoding="utf-8").read())]
    if not closed:
        raise ValueError(f"nothing to draw in {source}")
    xs = [p[0] for c in closed for p in c]
    ys = [p[1] for c in closed for p in c]
    scale = min(width * 0.78 / (max(xs) - min(xs)), height * 0.82 / (max(ys) - min(ys)))
    ox = (width - (max(xs) - min(xs)) * scale) / 2
    oy = (height - (max(ys) - min(ys)) * scale) / 2
    chunks = []
    for contour in closed:
        placed = [((x - min(xs)) * scale + ox, (y - min(ys)) * scale + oy) for x, y in contour]
        chunks += [placed[i:i + CHUNK + 1] for i in range(0, len(placed) - 1, CHUNK)]
    return _measured(compact_path(chunks))


def _measured(data: str):
    lengths = [polyline_length(sub) for sub in flatten_path(data)]
    return data, round(sum(lengths), 3), [round(v, 3) for v in lengths]


class Writing:
    """A page of handwriting, addressable by word, all at one scale."""

    def __init__(self, source, names, width, height):
        words = group_words(read_centrelines(open(source, encoding="utf-8").read()))
        if len(words) != len(names):
            raise ValueError(f"{source}: found {len(words)} words but {len(names)} were named")
        self._words = words
        self._boxes = [_bounds([p for s in w for p in s]) for w in words]
        self._scale = min(min(width * 0.86 / (b[2] - b[0]), height * 0.72 / (b[3] - b[1]))
                          for b in self._boxes)
        self._width, self._height = width, height
        self._index: dict[str, list[int]] = {}
        for i, name in enumerate(names):
            self._index.setdefault(name, []).append(i)
        self._taken: dict[str, int] = {}

    def take(self, name):
        if name not in self._index:
            raise ValueError(f"no word {name!r} on this page; have {sorted(self._index)}")
        seen = self._taken.get(name, 0)
        self._taken[name] = seen + 1
        i = self._index[name][seen % len(self._index[name])]
        word, box = self._words[i], self._boxes[i]
        ox = (self._width - (box[2] - box[0]) * self._scale) / 2
        oy = (self._height - (box[3] - box[1]) * self._scale) / 2
        strokes = []
        for s in sorted(word, key=lambda s: min(p[0] for p in s)):
            s = s if s[-1][0] >= s[0][0] else s[::-1]
            strokes.append(simplify([((x - box[0]) * self._scale + ox,
                                      (y - box[1]) * self._scale + oy) for x, y in s], 0.6))
        return _measured(compact_path(strokes))


def compile_screen(path: str) -> dict:
    root = ET.parse(path).getroot()
    if root.tag != "screen":
        raise ValueError("a screen file starts with <screen>")
    base = os.path.dirname(os.path.abspath(path))
    width = int(root.get("width", 450))
    height = int(root.get("height", 250))
    tune = {k: float(root.get(k, v)) for k, v in DEFAULTS.items()}

    layers, animations = [], []
    clock = 0.0
    shots: list[tuple[str, ET.Element]] = []

    def resolve(src):
        return src if os.path.isabs(src) else os.path.join(base, src)

    for layer_el in root.findall("layer"):
        objects = []
        writing = None
        for el in layer_el:
            if el.tag == "box":
                objects.append({"type": "rect", "id": el.get("id", f"box{len(objects)}"),
                                "x": float(el.get("x", 0)), "y": float(el.get("y", 0)),
                                "w": float(el.get("w", width)), "h": float(el.get("h", height)),
                                "fill": el.get("color", "#000000")})
            elif el.tag == "symbol":
                data, total, lengths = symbol_geometry(resolve(el.get("src")), width, height)
                objects.append(_mark(el, data, total, lengths))
                shots.append((el.get("id"), el))
            elif el.tag == "writing":
                writing = Writing(resolve(el.get("src")), el.get("words", "").split(),
                                  width, height)
                for word_el in el.findall("word"):
                    data, total, lengths = writing.take(word_el.get("name"))
                    merged = dict(el.attrib)
                    merged.update(word_el.attrib)
                    merged["id"] = word_el.get("id") or f"{word_el.get('name')}{len(objects)}"
                    objects.append(_mark(_Attrs(merged), data, total, lengths))
                    shots.append((merged["id"], _Attrs(merged)))
            elif el.tag == "animate":
                animations.append({"target": el.get("target"), "property": el.get("property"),
                                   "start": int(duration(el.get("start")) * 1000),
                                   "duration": int(duration(el.get("duration")) * 1000),
                                   "from": float(el.get("from", 0)), "to": float(el.get("to", 1)),
                                   "easing": el.get("easing", "linear")})
            else:
                raise ValueError(f"unsupported element <{el.tag}>")
        layers.append({"id": layer_el.get("id", f"layer{len(layers)}"),
                       "z": int(layer_el.get("z", 0)), "objects": objects})

    # the phase shorthand, expanded into ordinary animations
    ms = lambda seconds: int(round(seconds * 1000))
    end = 0.0
    turning: list[tuple[str, float, float]] = []
    for index, (name, el) in enumerate(shots):
        started_at = clock
        blended = index > 0 and shots[index - 1][1].get("handover") is not None
        excited, resting, sway = tune["excited"], tune["resting"], tune["sway"]
        has_motion = el.get("excite") is not None or el.get("calm") is not None
        turning = []          # filled in once the whole timeline is known
        if el.get("draw") is not None:
            animations.append({"target": name, "property": "progress", "start": ms(clock),
                               "duration": ms(duration(el.get("draw"))), "from": 0, "to": 1,
                               "easing": "ease-in-out"})
            clock += duration(el.get("draw"))
        if el.get("calm") is not None:
            animations += [{"target": name, "property": p, "start": ms(clock),
                            "duration": ms(duration(el.get("calm"))), "from": f, "to": t,
                            "easing": "ease-in-out"}
                           for p, f, t in (("deform.amplitude", excited, resting),
                                           ("deform.sway", sway, 1.0))]
            clock += duration(el.get("calm"))
        clock += duration(el.get("seen"))
        if el.get("excite") is not None:
            animations += [{"target": name, "property": p, "start": ms(clock),
                            "duration": ms(duration(el.get("excite"))), "from": f, "to": t,
                            "easing": "ease-in-out"}
                           for p, f, t in (("deform.amplitude",
                                            resting if el.get("calm") else 0.0, excited),
                                           ("deform.sway",
                                            1.0 if el.get("calm") else 0.0, sway))]
            clock += duration(el.get("excite"))
        peak = ms(clock)
        if el.get("handover") is not None and index + 1 < len(shots):
            span = ms(duration(el.get("handover")))
            animations += [{"target": name, "property": "opacity", "start": peak,
                            "duration": span, "from": 1, "to": 0, "easing": "ease-in-out"},
                           {"target": shots[index + 1][0], "property": "opacity",
                            "start": peak, "duration": span, "from": 0, "to": 1,
                            "easing": "ease-in-out"}]
            clock += duration(el.get("handover"))
        if el.get("exit") is not None:
            animations.append({"target": name, "property": "opacity", "start": peak,
                               "duration": ms(duration(el.get("exit"))), "from": 1, "to": 0,
                               "easing": "linear"})
            clock += duration(el.get("exit"))
        clock += duration(el.get("gap"))
        end = max(end, clock)
        if has_motion:
            turning.append((name, max(0.0, started_at - 1.0), clock))

        for objects in (l["objects"] for l in layers):
            for obj in objects:
                if obj.get("id") == name:
                    obj["progress"] = 0 if el.get("draw") is not None else 1
                    obj["opacity"] = 0 if blended else 1
                    if has_motion or blended:
                        obj["deform"] = {"type": "helix",
                                         "amplitude": excited if blended else 0.0,
                                         "sway": sway if blended else 0.0,
                                         "wavelength": 150, "phase": 0, "focal": 420}

    # A mark turns for exactly as long as it is on screen. A fixed, generous
    # duration would be simpler and wrong: the loader extends a scene to cover
    # every animation, so an over-long turn silently stretches the whole piece.
    for name, begins, ends in turning:
        span = max(0.2, ends - begins)
        animations.append({"target": name, "property": "deform.phase",
                           "start": ms(begins), "duration": ms(span),
                           "from": 0, "to": tune["turn"] * span / max(span, 1.0),
                           "easing": "linear"})

    return {"version": 1, "id": int(root.get("id", 75)), "name": root.get("name", "screen"),
            "width": width, "height": height, "fit": root.get("fit", "contain"),
            "duration": ms(end) or int(duration(root.get("duration")) * 1000),
            "layers": layers, "animations": animations}


class _Attrs(dict):
    """A plain attribute bag, so a merged <word> looks like an element."""

    def get(self, key, default=None):
        return dict.get(self, key, default)


def _mark(el, data, total, lengths):
    return {"type": "path", "id": el.get("id"), "d": data,
            "length": total, "subpaths": lengths,
            "stroke": el.get("stroke", "#e8e8f0"),
            "stroke_width": float(el.get("stroke-width", 2.2)),
            "progress": 1, "opacity": 1}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="screen-HTML with a timeline -> a scene")
    parser.add_argument("screen")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    scene = compile_screen(args.screen)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(scene, fh, indent=1)
    marks = sum(len(l["objects"]) for l in scene["layers"])
    print(f"  {args.screen} -> {args.out}")
    print(f"  {marks} objects, {len(scene['animations'])} animations, "
          f"{scene['duration']/1000:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
