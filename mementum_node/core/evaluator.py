"""The evaluator: ``state = scene.evaluate(sceneTime)`` (proposal §10, §19).

Pure by construction. There is no accumulator, no frame counter and no
dependence on call order:

    sceneTime = sharedNow() - displayAt
    state     = evaluate(scene, sceneTime)

Seeking to an arbitrary time therefore gives exactly the result of arriving
there by stepping -- which is what makes a dropped frame, a missed PLAY and a
late join the same problem with one answer.

Hold semantics: before an animation starts the property holds ``from``; after it
ends it holds ``to``.

Where several animations drive the same property, the one that applies is the
last, in declaration order, whose ``start`` has been reached -- so a phase list
(build up, then decay) works, and a property with no animation yet started
keeps its authored value (decision 0006). Blending overlapping animations is
deliberately not a thing in v1.
"""

from __future__ import annotations

from dataclasses import replace

from .easing import ease
from .scene import Animation, Layer, Scene, SceneObject

__all__ = ["evaluate", "value_at"]


def value_at(anim: Animation, scene_time: float) -> float:
    """The animated value at ``scene_time`` in milliseconds. Pure."""
    if scene_time <= anim.start:
        return anim.from_value
    if anim.duration <= 0 or scene_time >= anim.end:
        return anim.to_value
    p = (scene_time - anim.start) / anim.duration
    return anim.from_value + (anim.to_value - anim.from_value) * ease(anim.easing, p)


def evaluate(scene: Scene, scene_time: float) -> Scene:
    """Return a copy of ``scene`` with every animated property resolved at
    ``scene_time`` (milliseconds since ``displayAt``). Pure: the same scene and
    the same time always give the same result, and the input is not mutated."""
    if not scene.animations:
        return scene

    # Pick the governing animation per (object, property) before evaluating
    # any of them: the last one to have started wins, and one that has not
    # started yet must not impose its ``from`` value on earlier phases.
    governing: dict[str, dict[str, Animation]] = {}
    for anim in scene.animations:
        if anim.start > scene_time:
            continue
        governing.setdefault(anim.target, {})[anim.property] = anim

    resolved: dict[str, dict[str, float]] = {
        target: {prop: value_at(anim, scene_time) for prop, anim in props.items()}
        for target, props in governing.items()
    }

    layers: list[Layer] = []
    for layer in scene.layers:
        objects: list[SceneObject] = []
        for obj in layer.objects:
            props = resolved.get(obj.id)
            if props:
                for name, value in props.items():
                    obj = obj.with_property(name, value)
            objects.append(obj)
        layers.append(replace(layer, objects=tuple(objects)))
    return replace(scene, layers=tuple(layers))
