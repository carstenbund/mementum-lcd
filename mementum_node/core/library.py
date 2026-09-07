"""The scene library and package manifests (proposal §18 asset plane).

Scenes are content-addressed. The manifest carries what a node needs to decide
whether it can play a scene *before* the schedule is announced -- IR version,
required features, asset hashes and duration.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .cache import asset_hash
from .scene import parse_scene

__all__ = ["ScenePackage", "SceneLibrary"]


@dataclass(frozen=True)
class ScenePackage:
    scene_id: int
    payload: bytes
    digest: str
    ir_version: int
    requires: dict[str, Any]
    duration: int
    name: str = ""


class SceneLibrary:
    """Server-side store of scene packages, keyed by scene id and by hash."""

    def __init__(self) -> None:
        self._by_id: dict[int, ScenePackage] = {}

    def add(self, raw: dict[str, Any], scene_id: int | None = None) -> ScenePackage:
        scene = parse_scene(raw)  # never publish a scene that does not parse
        payload = json.dumps(raw, sort_keys=True, separators=(",", ":")).encode("utf-8")
        package = ScenePackage(
            scene_id=int(scene_id if scene_id is not None else scene.id),
            payload=payload,
            digest=asset_hash(payload),
            ir_version=scene.version,
            requires=self._requirements(scene),
            duration=scene.duration,
            name=scene.name,
        )
        self._by_id[package.scene_id] = package
        return package

    def add_file(self, path: str, scene_id: int | None = None) -> ScenePackage:
        with open(path, "r", encoding="utf-8") as fh:
            return self.add(json.load(fh), scene_id)

    @staticmethod
    def _requirements(scene) -> dict[str, Any]:
        types = {obj.type for layer in scene.layers for obj in layer.objects}
        return {
            "scene_ir": scene.version,
            "vector": "path" in types,
            "text": "text" in types,
            "lottie": False,
        }

    def get(self, scene_id: int) -> ScenePackage | None:
        return self._by_id.get(scene_id)

    def asset(self, digest: str) -> bytes | None:
        for package in self._by_id.values():
            if package.digest == digest:
                return package.payload
        return None

    def __contains__(self, scene_id: object) -> bool:
        return scene_id in self._by_id

    def __len__(self) -> int:
        return len(self._by_id)
