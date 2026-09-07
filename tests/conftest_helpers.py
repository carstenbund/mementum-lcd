"""Small shared helpers for the test suite."""

import os

SCENE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "poc",
    "scenes",
    "poc-signature.json",
)


def objects_of(scene):
    """Every object in a scene, by id."""
    return {obj.id: obj for layer in scene.layers for obj in layer.objects}
