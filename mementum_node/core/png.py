"""Minimal deterministic PNG writer/reader (stdlib only).

Capture is a property of the sink layer, not of the simulator (plan §3.6), so it
lives in the core beside the frame it captures. Written by hand rather than with
Pillow for two reasons: the harness stays dependency-free, and golden frames
cannot rot across an image library's version bumps (risk R12).
"""

from __future__ import annotations

import struct
import zlib

from .framebuffer import Frame

__all__ = ["encode_png", "write_png", "read_png"]


def _chunk(tag: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + tag
        + payload
        + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
    )


def encode_png(frame: Frame) -> bytes:
    """RGBA8 PNG bytes. Filter type 0 on every row and a fixed compression
    level, so the same frame always produces byte-identical output."""
    stride = frame.width * 4
    raw = bytearray()
    for y in range(frame.height):
        raw.append(0)
        raw += frame.data[y * stride : (y + 1) * stride]
    header = struct.pack(">IIBBBBB", frame.width, frame.height, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(bytes(raw), 6))
        + _chunk(b"IEND", b"")
    )


def write_png(frame: Frame, path: str) -> str:
    with open(path, "wb") as fh:
        fh.write(encode_png(frame))
    return path


def read_png(path: str) -> Frame:
    """Read back an RGBA8 PNG written by :func:`encode_png` (goldens in CI)."""
    with open(path, "rb") as fh:
        data = fh.read()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG file")
    pos, width, height, idat = 8, 0, 0, bytearray()
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        tag = data[pos + 4 : pos + 8]
        payload = data[pos + 8 : pos + 8 + length]
        if tag == b"IHDR":
            width, height, depth, colour = struct.unpack(">IIBB", payload[:10])
            if (depth, colour) != (8, 6):
                raise ValueError("only 8-bit RGBA PNGs are supported")
        elif tag == b"IDAT":
            idat += payload
        elif tag == b"IEND":
            break
        pos += 12 + length

    raw = zlib.decompress(bytes(idat))
    stride = width * 4
    out = bytearray(width * height * 4)
    prev = bytearray(stride)
    for y in range(height):
        off = y * (stride + 1)
        ftype = raw[off]
        row = bytearray(raw[off + 1 : off + 1 + stride])
        if ftype == 1:
            for i in range(4, stride):
                row[i] = (row[i] + row[i - 4]) & 0xFF
        elif ftype == 2:
            for i in range(stride):
                row[i] = (row[i] + prev[i]) & 0xFF
        elif ftype == 3:
            for i in range(stride):
                left = row[i - 4] if i >= 4 else 0
                row[i] = (row[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif ftype == 4:
            for i in range(stride):
                a = row[i - 4] if i >= 4 else 0
                b = prev[i]
                c = prev[i - 4] if i >= 4 else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pred = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                row[i] = (row[i] + pred) & 0xFF
        elif ftype != 0:
            raise ValueError(f"unsupported PNG filter {ftype}")
        out[y * stride : (y + 1) * stride] = row
        prev = row
    return Frame(width, height, out)
