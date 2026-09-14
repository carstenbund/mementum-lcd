"""Pictures as assets: LVGL binary images named by the scene, checked by size
and CRC32 before they may be drawn.

A panel reads them from its SD card; the host player reads the same files
through LVGL's stdio driver ("S:"), so the loader, the check and the draw are
the device's own code. The images here are written by hand -- a 12-byte header
and RGB565 rows -- so the test needs no composer.

Skipped where the C player is not built.
"""

import json
import struct
import zlib

import pytest

from mementum_node.core.renderer import render_scene
from mementum_node.core.scene import parse_scene
from mementum_node.players.lvgl import LvglPlayer, is_available

pytestmark = pytest.mark.skipif(
    not is_available(),
    reason="C player not built; run: make -C poc/host-player -j4 lib",
)

WIDTH, HEIGHT = 100, 60
BACKGROUND = (0x10, 0x18, 0x26)


def lvgl_image(w: int, h: int, rgb, alpha: int | None = None) -> bytes:
    r, g, b = rgb
    pixel = struct.pack("<H", ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3))
    if alpha is None:
        return struct.pack("<BBHHHHH", 0x19, 0x12, 0, w, h, w * 2, 0) + pixel * (w * h)
    return (struct.pack("<BBHHHHH", 0x19, 0x14, 0, w, h, w * 2, 0)
            + pixel * (w * h) + bytes([alpha]) * (w * h))


def scene(**crc_override) -> bytes:
    def image(object_id, src, x, data):
        w, h = struct.unpack_from("<HH", data, 4)
        return {"type": "image", "id": object_id, "src": src, "x": x, "y": 10,
                "w": w, "h": h, "size": len(data),
                "crc32": crc_override.get(src, zlib.crc32(data))}

    return json.dumps({
        "version": 1, "width": WIDTH, "height": HEIGHT, "fit": "contain", "duration": 0,
        "layers": [
            {"id": "bg", "z": 0, "objects": [
                {"type": "rect", "id": "bg", "x": 0, "y": 0, "w": WIDTH, "h": HEIGHT,
                 "fill": "#101826"}]},
            {"id": "pictures", "z": 10, "objects": [
                image("solid", "green", 10, GREEN),
                image("ghost", "white", 50, WHITE)]},
        ],
        "animations": [],
    }).encode()


GREEN = lvgl_image(20, 10, (0, 255, 0))
WHITE = lvgl_image(10, 10, (255, 255, 255), alpha=128)


@pytest.fixture
def card(tmp_path, monkeypatch):
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "green.bin").write_bytes(GREEN)
    (tmp_path / "assets" / "white.bin").write_bytes(WHITE)
    # Relative, so the path fits the player's fixed asset path field.
    monkeypatch.chdir(tmp_path)
    return tmp_path


def pixel(frame, x, y):
    i = (y * WIDTH + x) * 4
    return tuple(frame.data[i:i + 3])


def test_pictures_that_match_are_drawn(card):
    player = LvglPlayer()
    player.bind(scene(), None, WIDTH, HEIGHT)

    assert player.load_assets("S:assets/") == 0
    frame = player.render(0.0)

    assert pixel(frame, 15, 12) == pytest.approx((0, 255, 0), abs=4)
    # 50% white over the background
    assert pixel(frame, 55, 15) == pytest.approx((135, 139, 146), abs=6)
    assert pixel(frame, 80, 40) == BACKGROUND


def test_a_picture_from_another_build_is_left_out_and_named(card):
    player = LvglPlayer()
    player.bind(scene(green=12345), None, WIDTH, HEIGHT)

    assert player.load_assets("S:assets/") == 1
    assert "green.bin" in player.library.error() and "CRC" in player.library.error()
    frame = player.render(0.0)
    assert pixel(frame, 15, 12) == BACKGROUND
    assert pixel(frame, 55, 15) != BACKGROUND, "the good picture is still drawn"


def test_a_missing_picture_is_counted(card):
    (card / "assets" / "white.bin").unlink()
    player = LvglPlayer()
    player.bind(scene(), None, WIDTH, HEIGHT)

    assert player.load_assets("S:assets/") == 1
    assert "white.bin is missing" in player.library.error()


def test_an_unchecked_picture_is_not_drawn(card):
    player = LvglPlayer()
    player.bind(scene(), None, WIDTH, HEIGHT)

    assert pixel(player.render(0.0), 15, 12) == BACKGROUND


def test_the_reference_accepts_pictures_and_does_not_draw_them():
    state = parse_scene(json.loads(scene()))
    frame = render_scene(state)

    assert [o.type for layer in state.layers for o in layer.objects] == ["rect", "image", "image"]
    assert pixel(frame, 15, 12) == BACKGROUND
