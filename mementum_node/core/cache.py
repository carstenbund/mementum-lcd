"""Content-addressed scene and asset cache (proposal §18 "Caching").

    /scenes/00042.pkg        /assets/a7f93...

Content hashes drive the cache, so a node knows what it is missing without
asking, and a scene it already holds is free to seek into. On the device this is
flash (SPIFFS vs LittleFS is open question 6); here it is a dict, and in a real
Linux node it is a directory. Only the storage differs -- the keying does not.
"""

from __future__ import annotations

import hashlib

__all__ = ["AssetCache", "asset_hash"]


def asset_hash(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()[:16]


class AssetCache:
    def __init__(self) -> None:
        self._assets: dict[str, bytes] = {}
        self._scenes: dict[int, str] = {}
        self.hits = 0
        self.misses = 0

    # -- assets ---------------------------------------------------------

    def has(self, digest: str) -> bool:
        present = digest in self._assets
        if present:
            self.hits += 1
        else:
            self.misses += 1
        return present

    def put(self, payload: bytes, digest: str | None = None) -> str:
        digest = digest or asset_hash(payload)
        stored = asset_hash(payload)
        if stored != digest:
            raise ValueError(f"asset hash mismatch: expected {digest}, got {stored}")
        self._assets[digest] = payload
        return digest

    def get(self, digest: str) -> bytes | None:
        return self._assets.get(digest)

    # -- scenes ---------------------------------------------------------

    def bind_scene(self, scene_id: int, digest: str) -> None:
        self._scenes[scene_id] = digest

    def scene_digest(self, scene_id: int) -> str | None:
        return self._scenes.get(scene_id)

    def holds_scene(self, scene_id: int, digest: str) -> bool:
        return self._scenes.get(scene_id) == digest and digest in self._assets

    def __len__(self) -> int:
        return len(self._assets)
