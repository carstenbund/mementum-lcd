"""Scene model and JSON loader (proposal §6, plan 0.1 ``scene_model.h``).

This is the Python side of the same model the ESP32 player holds in C structs.
It is deliberately a *subset*: rect, path, text, and the v1 animatable
properties (transform, opacity, progress, visible). Anything not in this file is
not in the contract yet -- Phase 1 turns what the tracks proved into
``drm_scene_ir``, and it cannot do that if the model quietly grows here first.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from typing import Any

from . import easing

__all__ = [
    "ANIMATABLE",
    "Animation",
    "Layer",
    "Scene",
    "SceneObject",
    "Transform",
    "load_scene",
    "parse_color",
    "parse_scene",
    "scene_hash",
]

#: v1 animatable properties (proposal §10). ``transform`` is addressed by
#: component: ``transform.tx``, ``transform.ty``, ``transform.scale``.
ANIMATABLE = frozenset(
    {
        "opacity",
        "progress",
        "visible",
        "transform.tx",
        "transform.ty",
        "transform.scale",
    }
)


@dataclass(frozen=True)
class Transform:
    tx: float = 0.0
    ty: float = 0.0
    scale: float = 1.0


@dataclass(frozen=True)
class SceneObject:
    id: str
    type: str
    props: dict[str, Any] = field(default_factory=dict)
    opacity: float = 1.0
    visible: bool = True
    progress: float = 1.0
    transform: Transform = Transform()

    def with_property(self, name: str, value: Any) -> "SceneObject":
        """Return a copy with one animatable property replaced. Pure."""
        if name == "opacity":
            return replace(self, opacity=float(value))
        if name == "progress":
            return replace(self, progress=float(value))
        if name == "visible":
            return replace(self, visible=bool(value))
        if name.startswith("transform."):
            comp = name.split(".", 1)[1]
            return replace(self, transform=replace(self.transform, **{comp: float(value)}))
        raise ValueError(f"property is not animatable in v1: {name!r}")


@dataclass(frozen=True)
class Layer:
    id: str
    z: int
    objects: tuple[SceneObject, ...]


@dataclass(frozen=True)
class Animation:
    target: str
    property: str
    start: int
    duration: int
    from_value: float
    to_value: float
    easing: str = "linear"

    @property
    def end(self) -> int:
        return self.start + self.duration


@dataclass(frozen=True)
class Scene:
    version: int
    width: int
    height: int
    fit: str
    layers: tuple[Layer, ...]
    animations: tuple[Animation, ...]
    id: int = 0
    name: str = ""
    duration: int = 0

    @property
    def ordered_layers(self) -> tuple[Layer, ...]:
        """Layers in paint order. Stable: z first, declaration order second."""
        return tuple(
            layer for _, _, layer in sorted(
                (layer.z, index, layer) for index, layer in enumerate(self.layers)
            )
        )

    def object_ids(self) -> tuple[str, ...]:
        return tuple(o.id for layer in self.layers for o in layer.objects)


def parse_color(value: str | None) -> tuple[int, int, int]:
    """``#rgb`` / ``#rrggbb`` -> (r, g, b). Alpha lives in ``opacity``."""
    if not value:
        return (0, 0, 0)
    s = value.strip().lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    if len(s) != 6:
        raise ValueError(f"unsupported colour: {value!r}")
    return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))


_OBJECT_KEYS = {
    "rect": ("x", "y", "w", "h", "fill"),
    "path": ("d", "stroke", "stroke_width", "fill"),
    "text": ("content", "x", "y", "font_id", "color", "size"),
}


def _parse_object(raw: dict[str, Any]) -> SceneObject:
    otype = raw["type"]
    if otype not in _OBJECT_KEYS:
        raise ValueError(f"unsupported object type: {otype!r}")
    props = {k: raw[k] for k in _OBJECT_KEYS[otype] if k in raw}
    tf = raw.get("transform", {})
    return SceneObject(
        id=raw["id"],
        type=otype,
        props=props,
        opacity=float(raw.get("opacity", 1.0)),
        visible=bool(raw.get("visible", True)),
        progress=float(raw.get("progress", 1.0)),
        transform=Transform(
            tx=float(tf.get("tx", 0.0)),
            ty=float(tf.get("ty", 0.0)),
            scale=float(tf.get("scale", 1.0)),
        ),
    )


def parse_scene(raw: dict[str, Any]) -> Scene:
    """Validate and build a :class:`Scene` from decoded JSON."""
    version = int(raw.get("version", 1))
    if version != 1:
        raise ValueError(f"unsupported scene version: {version}")

    layers = []
    seen: set[str] = set()
    for raw_layer in raw.get("layers", []):
        objects = []
        for raw_object in raw_layer.get("objects", []):
            obj = _parse_object(raw_object)
            if obj.id in seen:
                raise ValueError(f"duplicate object id: {obj.id!r}")
            seen.add(obj.id)
            objects.append(obj)
        layers.append(
            Layer(id=raw_layer["id"], z=int(raw_layer.get("z", 0)), objects=tuple(objects))
        )

    animations = []
    for raw_anim in raw.get("animations", []):
        prop = raw_anim["property"]
        if prop not in ANIMATABLE:
            raise ValueError(f"property is not animatable in v1: {prop!r}")
        curve = raw_anim.get("easing", "linear")
        if not easing.is_known(curve):
            raise ValueError(f"unknown easing curve: {curve!r}")
        if raw_anim["target"] not in seen:
            raise ValueError(f"animation targets unknown object: {raw_anim['target']!r}")
        duration = int(raw_anim["duration"])
        if duration < 0:
            raise ValueError("animation duration must not be negative")
        animations.append(
            Animation(
                target=raw_anim["target"],
                property=prop,
                start=int(raw_anim["start"]),
                duration=duration,
                from_value=float(raw_anim["from"]),
                to_value=float(raw_anim["to"]),
                easing=curve,
            )
        )

    declared = int(raw.get("duration", 0))
    implied = max((a.end for a in animations), default=0)
    return Scene(
        version=version,
        width=int(raw["width"]),
        height=int(raw["height"]),
        fit=raw.get("fit", "contain"),
        layers=tuple(layers),
        animations=tuple(animations),
        id=int(raw.get("id", 0)),
        name=raw.get("name", ""),
        duration=max(declared, implied),
    )


def load_scene(path: str) -> Scene:
    """Load a scene package from disk. Load time is measured separately from
    frame time (proposal §17): never call this from a frame loop."""
    with open(path, "r", encoding="utf-8") as fh:
        return parse_scene(json.load(fh))


def scene_hash(raw: dict[str, Any] | bytes) -> str:
    """Content hash of a scene package (proposal §18 caching).

    Hashes the canonical JSON encoding so that the same scene always yields the
    same key regardless of key order or whitespace.
    """
    if isinstance(raw, (bytes, bytearray)):
        raw = json.loads(bytes(raw).decode("utf-8"))
    canonical = json.dumps(raw, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()[:16]
