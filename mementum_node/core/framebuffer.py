"""The composited RGBA frame -- the sink boundary (proposal §14, plan §3.6).

`drm_screen` composites into an RGBA frame and hands it to a backend adapter.
That frame is both where a sink lives and where capture happens, which is why
the same capture tool works for a simulated node, a headless test and a real
Pi. Nothing here knows about DRM, about the simulator, or about PNG.

Colour conversion is a property of the *backend adapter*, not of this buffer
(invariant 1): a DRM backend converts RGBA->BGRA, an encoder sink RGBA->YUV420,
and neither happens anywhere else.
"""

from __future__ import annotations

import hashlib

__all__ = ["Frame", "blend_pixel"]


class Frame:
    """A composited RGBA8888 frame. Row-major, 4 bytes per pixel."""

    __slots__ = ("width", "height", "data")

    def __init__(self, width: int, height: int, data: bytearray | None = None):
        self.width = int(width)
        self.height = int(height)
        if data is None:
            data = bytearray(self.width * self.height * 4)
        elif len(data) != self.width * self.height * 4:
            raise ValueError("frame buffer size does not match dimensions")
        self.data = data

    # -- construction ---------------------------------------------------

    @classmethod
    def filled(cls, width: int, height: int, rgba: tuple[int, int, int, int]) -> "Frame":
        f = cls(width, height)
        f.fill(rgba)
        return f

    def copy(self) -> "Frame":
        return Frame(self.width, self.height, bytearray(self.data))

    # -- pixel access ---------------------------------------------------

    def fill(self, rgba: tuple[int, int, int, int]) -> None:
        self.data[:] = bytes(rgba) * (self.width * self.height)

    def get(self, x: int, y: int) -> tuple[int, int, int, int]:
        i = (y * self.width + x) * 4
        return tuple(self.data[i : i + 4])  # type: ignore[return-value]

    def set(self, x: int, y: int, rgba: tuple[int, int, int, int]) -> None:
        i = (y * self.width + x) * 4
        self.data[i : i + 4] = bytes(rgba)

    def fill_rect(self, x: int, y: int, w: int, h: int, rgba: tuple[int, int, int, int]) -> None:
        """Opaque axis-aligned fill. The fast path: no coverage, no blending."""
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(self.width, x + w), min(self.height, y + h)
        if x1 <= x0 or y1 <= y0:
            return
        row = bytes(rgba) * (x1 - x0)
        stride = self.width * 4
        for yy in range(y0, y1):
            off = yy * stride + x0 * 4
            self.data[off : off + len(row)] = row

    def blit(self, source: "Frame", x: int, y: int) -> None:
        """Copy ``source`` into this frame at (x, y), clipped."""
        stride, src_stride = self.width * 4, source.width * 4
        for sy in range(source.height):
            dy = y + sy
            if dy < 0 or dy >= self.height:
                continue
            dx0 = max(0, x)
            dx1 = min(self.width, x + source.width)
            if dx1 <= dx0:
                continue
            src_off = sy * src_stride + (dx0 - x) * 4
            dst_off = dy * stride + dx0 * 4
            self.data[dst_off : dst_off + (dx1 - dx0) * 4] = source.data[
                src_off : src_off + (dx1 - dx0) * 4
            ]

    def scaled(self, width: int, height: int) -> "Frame":
        """Nearest-neighbour resample. Deterministic and dependency-free: this
        is a viewing convenience for the video wall, never a render path."""
        out = Frame(width, height)
        src_stride, dst_stride = self.width * 4, width * 4
        for y in range(height):
            sy = min(self.height - 1, (y * self.height) // height)
            row_off = sy * src_stride
            base = y * dst_stride
            for x in range(width):
                sx = min(self.width - 1, (x * self.width) // width)
                src = row_off + sx * 4
                out.data[base + x * 4 : base + x * 4 + 4] = self.data[src : src + 4]
        return out

    # -- identity -------------------------------------------------------

    def hash(self) -> str:
        """Frame hash (plan §3.6). Cheap enough to run on an ESP32 every frame,
        and the only way to check that two panels agree without a camera.
        Valid only between *identical* renderers."""
        h = hashlib.sha256()
        h.update(b"%d:%d:" % (self.width, self.height))
        h.update(self.data)
        return h.hexdigest()

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Frame):
            return NotImplemented
        return (
            self.width == other.width
            and self.height == other.height
            and self.data == other.data
        )

    def __repr__(self) -> str:
        return f"<Frame {self.width}x{self.height} {self.hash()[:12]}>"


def blend_pixel(
    data: bytearray, index: int, rgb: tuple[int, int, int], alpha: float
) -> None:
    """Source-over blend of ``rgb`` at ``alpha`` into an RGBA byte buffer."""
    if alpha <= 0.0:
        return
    if alpha >= 1.0:
        data[index] = rgb[0]
        data[index + 1] = rgb[1]
        data[index + 2] = rgb[2]
        data[index + 3] = 255
        return
    inv = 1.0 - alpha
    data[index] = int(rgb[0] * alpha + data[index] * inv + 0.5)
    data[index + 1] = int(rgb[1] * alpha + data[index + 1] * inv + 0.5)
    data[index + 2] = int(rgb[2] * alpha + data[index + 2] * inv + 0.5)
    data[index + 3] = int(255 * alpha + data[index + 3] * inv + 0.5)
