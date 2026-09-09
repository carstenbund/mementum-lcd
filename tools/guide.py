#!/usr/bin/env python3
"""Cue sheet -> show package. The composer side of the guide.

A show is written the way a show is written: a running order with timecodes.
The markup is the one this project already uses -- screen-HTML -- with one
element added, because a guide is a list of cues and nothing else.

    <guide name="opening">
      <cue at="00:00:00" play="animation" scene="poc/scenes/symbols-blend.json" />
      <cue at="00:00:20" play="text">du kannst werden was du willst</cue>
      <cue at="00:00:26" play="effect" unit="unit-11" amplitude="16" />
      <cue at="00:00:34" play="effect" />
    </guide>

A cue reaches the whole wall at one moment unless it says otherwise. Two
separate questions can say otherwise, and they are `mementum-led`'s, because
they are the same two questions there:

    <cue at="0:00" play="animation" scene="..." stagger="1s" />
    <cue at="0:12" play="text" spread="deal">du kannst werden was du willst</cue>
    <cue at="0:30" play="text" stagger="tile" factor="1.05">mementum</cue>

`spread` is *what* each unit shows: `all` (the default) or `deal`, one word per
unit in reading order, repeating along the wall if the sentence is shorter than
it. `stagger` is *when* each one starts: `auto` (one full go of the content per
unit), `tile` (one panel width of travel, so the content tiles into a single
long marquee), or a time. `factor` tunes the first two, `reverse` sweeps the
other way, and `order` names the units explicitly -- which is what `/identify`
on the wall is for.

A `tile` cue is compiled differently: the words arrive already written and
cross the panel, because tiling is about content that moves.

Everything that can be decided now is: scene files are resolved and given ids,
and the words of a `text` cue are compiled to pen strokes -- unless the cue says
`live="true"`, in which case they are compiled when the cue fires, which is the
escape hatch for a line decided during the show.

    tools/guide.py poc/shows/opening.html --out poc/shows/opening.json

The output is a show package: the guide document the server runs, plus the
scenes it refers to, so a runner needs nothing else.
"""

import argparse
import json
import os
import sys
from html.parser import HTMLParser

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mementum_node.core.guide import (  # noqa: E402
    SPREADS, STAGGERS, Guide, format_timecode, parse_timecode,
)

#: Ids for scenes compiled here. High enough not to collide with the
#: hand-written scenes in poc/scenes/, which carry their own.
FIRST_ID = 600

#: Effect parameters a cue may set. Anything else is a typo, and saying so here
#: is cheaper than wondering on the night why nothing happened.
EFFECT_PARAMS = ("amplitude", "strength", "x", "y")


class _GuideParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.name = ""
        self.cues = []
        self._cue = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "guide":
            self.name = a.get("name", "")
        elif tag == "cue":
            action = (a.get("play") or "animation").strip().lower()
            params = {}
            for key in EFFECT_PARAMS:
                if key in a:
                    params[key] = float(a[key])
            unknown = set(a) - {"at", "play", "scene", "text", "effect", "unit",
                                "label", "live", "spread", "stagger", "factor",
                                "reverse", "order", "duration"} - set(EFFECT_PARAMS)
            if unknown:
                raise ValueError(f"cue at {a.get('at')!r}: unknown attribute(s) "
                                 f"{', '.join(sorted(unknown))}")
            spread = (a.get("spread") or "all").strip().lower()
            if spread not in SPREADS:
                raise ValueError(f"cue at {a.get('at')!r}: unknown spread {spread!r}; "
                                 f"expected one of {', '.join(SPREADS)}")
            stagger = (a.get("stagger") or "").strip().lower()
            if stagger not in STAGGERS:
                parse_timecode(stagger)          # a time, or an error, here and now
            self._cue = {
                "at": parse_timecode(a.get("at", 0)),
                "play": action,
                "spread": spread,
                "stagger": stagger,
                "factor": float(a.get("factor", 1.0) or 1.0),
                "reverse": (a.get("reverse", "") or "").strip().lower()
                           in ("1", "true", "yes", "") and "reverse" in a,
                "order": [u.strip() for u in (a.get("order") or "").split(",") if u.strip()],
                "duration": parse_timecode(a["duration"]) if a.get("duration") else 0.0,
                "src": a.get("scene", ""),
                "text": a.get("text", ""),
                "effect": (a.get("effect") or "ripple").strip().lower(),
                "unit": a.get("unit", ""),
                "label": a.get("label", ""),
                "live": (a.get("live", "") or "").strip().lower() in ("true", "yes", "1", ""),
                "params": params,
            }
            # `live` present with no value means live; absent means compiled.
            self._cue["live"] = "live" in a and self._cue["live"]
            self.cues.append(self._cue)

    def handle_data(self, data):
        if self._cue is not None and data.strip():
            self._cue["text"] = (self._cue["text"] + " " + data.strip()).strip()

    def handle_endtag(self, tag):
        if tag == "cue":
            self._cue = None


def compile_show(html: str, base_dir: str = ".", width: int = 450, height: int = 250,
                 stroke_width: float = 2.5) -> dict:
    """Cue sheet in, show package out."""
    parser = _GuideParser()
    parser.feed(html)
    parser.close()

    scenes = []
    cues = []
    next_id = FIRST_ID
    by_source = {}

    for raw in parser.cues:
        cue = {"at": format_timecode(raw["at"]), "play": raw["play"]}
        if raw["label"]:
            cue["label"] = raw["label"]
        if raw["spread"] != "all":
            cue["spread"] = raw["spread"]
        if raw["stagger"]:
            cue["stagger"] = raw["stagger"]
        if raw["factor"] != 1.0:
            cue["factor"] = raw["factor"]
        if raw["reverse"]:
            cue["reverse"] = True
        if raw["order"]:
            cue["order"] = raw["order"]

        if raw["play"] in ("animation", "text") and raw["src"]:
            path = os.path.join(base_dir, raw["src"])
            if path not in by_source:
                with open(path, "r", encoding="utf-8") as fh:
                    document = json.load(fh)
                scene_id = int(document.get("id") or 0) or next_id
                next_id = max(next_id, scene_id + 1)
                document["id"] = scene_id
                scenes.append({"id": scene_id, "src": raw["src"], "scene": document})
                by_source[path] = scene_id
            cue["scene"] = by_source[path]

        elif raw["play"] == "text":
            if not raw["text"]:
                raise ValueError(f"text cue at {cue['at']} has no words")
            cue["text"] = raw["text"]
            if not raw["live"]:
                # Compiled now: the ordinary case. A show should not be doing
                # work at the moment it is meant to be showing something.
                from handwriting import build_scene

                # Tiling is about content that moves: the words arrive already
                # written and cross the panel, so that what leaves one unit
                # enters the next.
                travel = raw["stagger"] == "tile"
                # A dealt sentence is one scene per word; anything else is one
                # scene for the line.
                pieces = raw["text"].split() if raw["spread"] == "deal" else [raw["text"]]
                ids = []
                for piece in pieces:
                    key = f"text:{piece}:{'travel' if travel else 'write'}"
                    if key not in by_source:
                        kwargs = {}
                        if raw["duration"]:
                            kwargs["duration"] = int(raw["duration"])
                        document = build_scene(piece, width=width, height=height,
                                               scene_id=next_id, stroke_width=stroke_width,
                                               travel=travel, **kwargs)
                        scenes.append({"id": next_id, "src": key, "scene": document})
                        by_source[key] = next_id
                        next_id += 1
                    ids.append(by_source[key])
                if len(ids) == 1:
                    cue["scene"] = ids[0]
                else:
                    cue["scenes"] = ids

        elif raw["play"] == "effect":
            cue["effect"] = raw["effect"]
            if raw["unit"]:
                cue["unit"] = raw["unit"]

        if raw["params"]:
            cue["params"] = raw["params"]
        cues.append(cue)

    document = {"version": 1, "name": parser.name, "cues": cues}
    guide = Guide.from_document(document)          # never ship one that does not load
    document["duration"] = format_timecode(guide.duration)
    document["scenes"] = scenes
    return document


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="cue sheet -> show package")
    parser.add_argument("source", help="a screen-HTML file holding a <guide>")
    parser.add_argument("--out", default=None)
    parser.add_argument("--width", type=int, default=450)
    parser.add_argument("--height", type=int, default=250)
    parser.add_argument("--stroke-width", type=float, default=2.5)
    args = parser.parse_args(argv)

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    with open(args.source, "r", encoding="utf-8") as fh:
        html = fh.read()

    show = compile_show(html, base_dir=os.path.dirname(os.path.abspath(args.source)) + "/../..",
                        width=args.width, height=args.height, stroke_width=args.stroke_width)

    payload = json.dumps(show, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(payload + "\n")
        size = len(payload)
        print(f"{args.out}: {len(show['cues'])} cues, {len(show['scenes'])} scenes, "
              f"{show['duration']}, {size / 1024:.1f} KB")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
