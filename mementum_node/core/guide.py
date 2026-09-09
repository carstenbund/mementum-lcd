"""The guide -- a running order with timecodes.

Until now the server played one scene at a time and somebody had to decide
when. A show is not that: it is a list of things to happen and the times they
happen at, written down before anybody is in the room. That list is the guide.

    00:00:00  animation  symbols-blend
    00:00:20  text       "du kannst werden was du willst"
    00:00:38  effect     ripple from unit-11

Three properties, and they are the ones the rest of the system already has:

* **A timecode is show-relative.** A cue says 20 s *into the show*, not
  half past four. The show has an epoch in shared time, and a cue's absolute
  moment is ``epoch + at`` -- which is exactly the ``displayAt`` every node
  already evaluates against. A guide is therefore portable: the same file plays
  tomorrow, or in the middle, or twice.
* **The current cue is evaluated, never accumulated.** "What should be on the
  wall now" is *the last scene cue whose timecode has passed* -- the same rule
  the evaluator uses for animation phases (decision 0006), for the same reason:
  a node that joins late, or a server that restarts, gets the right answer by
  asking rather than by having been present.
* **Effects are transient, scenes are state.** A scene cue changes what the
  schedule *is*, and is therefore recovered by a late joiner. An effect cue is
  a moment -- a ripple crossing the wall -- and a unit that misses it simply
  did not ripple. Nothing has to catch up.

Nothing here talks to the network, the library, or the clock. It is the
document and the arithmetic on it; the sequencer does the rest.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "Cue", "Guide", "ACTIONS", "SPREADS", "STAGGERS",
    "format_timecode", "parse_timecode",
]

#: What a cue can ask for. `text` and `animation` are both scenes -- the
#: distinction is what a show caller means by them, not what the wire carries,
#: and keeping them apart is what lets a guide read like a cue sheet.
ACTIONS = ("text", "animation", "effect")

#: How the *content* reaches the units:
#:
#:   all    every unit shows the same thing (the default)
#:   deal   a scene each, in reading order -- a sentence across the wall
#:
#: How the *timing* is spread across them is `stagger`, which is a separate
#: question and is named after `mementum-led`'s, because it is the same thing:
#:
#:   ""      every unit at the same moment
#:   auto    one full go of the content per unit -- a discrete hop
#:   tile    exactly one panel width of travel, so the content tiles into one
#:           long marquee: what leaves one unit enters the next
#:   <time>  a fixed delay between neighbours
#:
#: `factor` tunes auto and tile: below 1 they overlap into a glide, above 1 they
#: leave a gap -- or, on a real wall, compensate for the bezel between panels.
SPREADS = ("all", "deal")
STAGGERS = ("", "auto", "tile")

_TIMECODE = re.compile(
    r"^(?:(?P<h>\d+):)?(?:(?P<m>\d{1,2}):)?(?P<s>\d{1,2})(?:[.,](?P<frac>\d{1,3}))?$"
)


def parse_timecode(value: Any) -> float:
    """A timecode as milliseconds from the top of the show.

    Written the way a show is called -- ``1:23``, ``00:01:23.400`` -- because
    that is how the person holding the running order thinks. Plain numbers are
    milliseconds, so a generated guide needs no formatting, and ``"1200ms"`` /
    ``"1.5s"`` are accepted for the same reason.
    """
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip().lower()
    if not text:
        raise ValueError("empty timecode")
    if text.endswith("ms"):
        return float(text[:-2])
    if text.endswith("s") and ":" not in text:
        return float(text[:-1]) * 1000.0

    match = _TIMECODE.match(text)
    if match is None:
        raise ValueError(f"not a timecode: {value!r}")
    hours = int(match.group("h") or 0)
    minutes = int(match.group("m") or 0)
    seconds = int(match.group("s"))
    # "1:23" is one minute twenty-three, not one hour twenty-three: with two
    # fields the leading one is minutes, which is how a running order is read.
    if match.group("m") is None and match.group("h") is not None:
        hours, minutes = 0, hours
    frac = match.group("frac") or ""
    millis = int(frac.ljust(3, "0")) if frac else 0
    return ((hours * 60 + minutes) * 60 + seconds) * 1000.0 + millis


def format_timecode(ms: float) -> str:
    """``hh:mm:ss.mmm`` -- what a cue sheet shows, and what a log should say."""
    if ms < 0:
        return "-" + format_timecode(-ms)
    total = int(round(ms))
    millis = total % 1000
    seconds = total // 1000
    return f"{seconds // 3600:02d}:{seconds // 60 % 60:02d}:{seconds % 60:02d}.{millis:03d}"


@dataclass(frozen=True)
class Cue:
    """One thing happening at one time.

    A scene cue (``text`` or ``animation``) names a scene the library holds. A
    ``text`` cue may instead carry its words and no scene, which is the escape
    hatch: they are compiled when the cue fires rather than before the show, so
    a line can be decided during it. The device never learns the difference --
    it receives a scene either way, and no node holds a font.
    """

    at: float                                   # timecode, ms from the top
    action: str
    scene_id: int = 0
    text: str = ""
    effect: str = "ripple"
    unit: str = ""                              # which unit an effect starts on
    params: dict[str, float] = field(default_factory=dict)
    label: str = ""
    spread: str = "all"                         # all | deal
    stagger: str = ""                           # "" | auto | tile | a timecode
    factor: float = 1.0                         # tunes auto and tile
    reverse: bool = False                       # sweep the other way along the wall
    order: tuple[str, ...] = ()                 # explicit unit order, overriding position
    scene_ids: tuple[int, ...] = ()             # one per unit, in reading order

    def __post_init__(self) -> None:
        if self.action not in ACTIONS:
            raise ValueError(f"unknown cue action {self.action!r}; expected one of {ACTIONS}")
        if self.spread not in SPREADS:
            raise ValueError(f"unknown spread {self.spread!r}; expected one of {SPREADS}")
        if self.stagger not in STAGGERS:
            # Anything else has to be a time, and saying so now is cheaper than
            # finding out on the night that nothing moved.
            parse_timecode(self.stagger)
        if self.is_scene and not (self.scene_id or self.text or self.scene_ids):
            raise ValueError(f"a {self.action} cue needs a scene or words to compile")

    @property
    def is_scene(self) -> bool:
        return self.action in ("text", "animation")

    @property
    def is_effect(self) -> bool:
        return self.action == "effect"

    @property
    def live(self) -> bool:
        """Words with no scene behind them yet -- compiled when it fires."""
        return self.action == "text" and not (self.scene_id or self.scene_ids)

    @property
    def tiles(self) -> bool:
        """Does this cue need content that *moves*? Only the composer can build
        that, so the flag has to survive from the cue sheet to it."""
        return self.stagger == "tile"

    @property
    def words(self) -> tuple[str, ...]:
        """A dealt text cue is one word per unit; the split belongs here so the
        composer and the server divide a sentence the same way."""
        return tuple(self.text.split())

    @property
    def name(self) -> str:
        if self.label:
            return self.label
        if self.scene_ids:
            return f"{len(self.scene_ids)} scenes"
        if self.action == "text":
            return f"text {self.text!r}" if self.text else f"text scene {self.scene_id}"
        if self.action == "animation":
            return f"scene {self.scene_id}"
        return f"{self.effect}{' from ' + self.unit if self.unit else ''}"

    def __str__(self) -> str:
        how = [self.spread] if self.spread != "all" else []
        if self.stagger:
            how.append(f"stagger {self.stagger}"
                       + (f" x{self.factor:g}" if self.factor != 1.0 else ""))
        if self.reverse:
            how.append("reverse")
        detail = f" [{', '.join(how)}]" if how else ""
        return f"{format_timecode(self.at)}  {self.action:<9} {self.name}{detail}"

    @classmethod
    def from_document(cls, raw: dict[str, Any]) -> "Cue":
        params = dict(raw.get("params") or {})
        return cls(
            at=parse_timecode(raw.get("at", 0)),
            action=str(raw.get("play") or raw.get("action") or "animation"),
            scene_id=int(raw.get("scene", raw.get("scene_id", 0)) or 0),
            text=str(raw.get("text") or ""),
            effect=str(raw.get("effect") or "ripple"),
            unit=str(raw.get("unit") or ""),
            params={key: float(value) for key, value in params.items()},
            label=str(raw.get("label") or ""),
            spread=str(raw.get("spread") or "all"),
            stagger=str(raw.get("stagger") or ""),
            factor=float(raw.get("factor", 1.0) or 1.0),
            reverse=bool(raw.get("reverse", False)),
            order=tuple(str(unit) for unit in raw.get("order") or ()),
            scene_ids=tuple(int(value) for value in raw.get("scenes") or ()),
        )

    def to_document(self) -> dict[str, Any]:
        out: dict[str, Any] = {"at": format_timecode(self.at), "play": self.action}
        if self.scene_id:
            out["scene"] = self.scene_id
        if self.scene_ids:
            out["scenes"] = list(self.scene_ids)
        if self.spread != "all":
            out["spread"] = self.spread
        if self.stagger:
            out["stagger"] = self.stagger
        if self.factor != 1.0:
            out["factor"] = self.factor
        if self.reverse:
            out["reverse"] = True
        if self.order:
            out["order"] = list(self.order)
        if self.text:
            out["text"] = self.text
        if self.is_effect:
            out["effect"] = self.effect
            if self.unit:
                out["unit"] = self.unit
        if self.params:
            out["params"] = dict(self.params)
        if self.label:
            out["label"] = self.label
        return out


@dataclass(frozen=True)
class Guide:
    """A show, as a document: cues in time order and nothing else.

    Compiled, like a scene: whatever it was authored in -- a cue sheet, a
    spreadsheet, screen-HTML -- this is what the server runs.
    """

    name: str = ""
    cues: tuple[Cue, ...] = ()

    def __post_init__(self) -> None:
        # Sorted once, here, so every question below is a search rather than a
        # scan, and so a guide written out of order still plays in order.
        object.__setattr__(self, "cues", tuple(sorted(self.cues, key=lambda cue: cue.at)))

    # -- the document ---------------------------------------------------

    @classmethod
    def from_document(cls, raw: dict[str, Any]) -> "Guide":
        return cls(
            name=str(raw.get("name") or ""),
            cues=tuple(Cue.from_document(cue) for cue in raw.get("cues") or ()),
        )

    def to_document(self) -> dict[str, Any]:
        return {
            "version": 1,
            "name": self.name,
            "duration": format_timecode(self.duration),
            "cues": [cue.to_document() for cue in self.cues],
        }

    # -- the arithmetic -------------------------------------------------

    @property
    def duration(self) -> float:
        """When the last cue is called. What happens after is the last scene."""
        return self.cues[-1].at if self.cues else 0.0

    @property
    def scenes(self) -> tuple[Cue, ...]:
        return tuple(cue for cue in self.cues if cue.is_scene)

    def scene_at(self, show_time: float) -> Cue | None:
        """What should be on the wall at this point in the show.

        The last scene cue whose timecode has passed -- the same rule the
        evaluator uses for animation phases, and the reason a node that joins
        halfway through needs no special path: the answer is a function of the
        clock, not of what it has seen.
        """
        governing = None
        for cue in self.cues:
            if cue.at > show_time:
                break
            if cue.is_scene:
                governing = cue
        return governing

    def due(self, since: float, until: float) -> tuple[Cue, ...]:
        """Cues in ``(since, until]`` -- the window a tick is responsible for.

        Half-open at the bottom so a cue fires exactly once however often the
        server ticks, and closed at the top so a cue landing precisely on the
        boundary is not held over to the next one.
        """
        return tuple(cue for cue in self.cues if since < cue.at <= until)

    def next_after(self, show_time: float) -> Cue | None:
        for cue in self.cues:
            if cue.at > show_time:
                return cue
        return None

    def __len__(self) -> int:
        return len(self.cues)

    def __iter__(self):
        return iter(self.cues)

    def __str__(self) -> str:
        head = f"guide {self.name!r}: {len(self.cues)} cues, {format_timecode(self.duration)}"
        return "\n".join([head] + [f"  {cue}" for cue in self.cues])
