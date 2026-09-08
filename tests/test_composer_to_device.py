"""The composer reaches the device, with no Python on the device.

`drm_composer` is a host-side compiler: screen-HTML in, a command batch out.
For a bitmap layer that batch carries pixels, which an ESP32 has no room for
and no way to receive at frame rate. For a layer of `<path>` elements it
carries a *document* -- and that document is `drm_scene_ir`, which is exactly
what the C player loads.

So the composer already targets the panel: compile on a host, ship a couple of
kilobytes, and the same C that runs on an ESP32-S3 draws it. This test is that
claim, checked rather than asserted -- the bytes drm_composer emits are fed
straight to the device player.

Skipped where `drm_composer` is not installed, or the player is not built.
"""

import json

import pytest

from mementum_node.players.lvgl import LvglPlayer, is_available

drm_composer = pytest.importorskip("drm_composer", reason="drm_composer not installed")

pytestmark = pytest.mark.skipif(
    not is_available(),
    reason="C player not built; run: make -C poc/host-player -j4 lib",
)

WIDTH, HEIGHT = 240, 120

HTML = f"""
<screen width="{WIDTH}" height="{HEIGHT}">
  <layer id="ink" z="10">
    <path id="rule" d="M 20 60 L 220 60" stroke="#e8e8f0" stroke-width="3" progress="0">
      <animate property="progress" from="0" to="1" start="0" duration="1000" />
    </path>
  </layer>
</screen>
"""


@pytest.fixture(scope="module")
def placed():
    from drm_composer import paint_scene, parse_scene

    batch = paint_scene(parse_scene(HTML))
    scenes = [c for c in batch if type(c).__name__ == "PlaceScene"]
    assert scenes, "a layer of paths must compile to a scene, not a bitmap"
    return scenes[0]


def ink(frame) -> int:
    return sum(1 for i in range(0, len(frame.data), 4)
               if max(frame.data[i:i + 3]) > 80)


def test_the_document_is_small_enough_to_ship(placed):
    """The whole point of sending a description: a path is a few hundred bytes,
    the same picture rasterised is megabytes, every frame of it."""
    assert len(placed.scene) < 1024
    assert json.loads(placed.scene)["duration"] == 1000


def test_the_device_player_loads_what_the_composer_emitted(placed):
    player = LvglPlayer()
    player.bind(placed.scene, None, WIDTH, HEIGHT)

    assert player.scene_duration() == pytest.approx(1000.0)
    assert player.path_length("rule") == pytest.approx(200.0, abs=1.0)


def test_the_stroke_draws_itself_on_the_device_player(placed):
    """`progress` animated by `<animate>`, evaluated by the C evaluator."""
    player = LvglPlayer()
    player.bind(placed.scene, None, WIDTH, HEIGHT)

    drawn = [ink(player.render(t)) for t in (0.0, 250.0, 500.0, 1000.0)]

    assert drawn[0] == 0, "nothing is drawn at the start"
    assert drawn == sorted(drawn), f"the stroke must only grow: {drawn}"
    assert drawn[-1] > 2 * drawn[1], f"and it must get most of the way: {drawn}"


def test_the_composer_and_this_project_s_own_tools_agree_on_the_format(placed):
    """`tools/compose.py` writes the same documents from this project's own
    screen-HTML. If the two dialects ever stop producing the same shape, the
    device stops being a target either of them can reach."""
    from mementum_node.core.scene import parse_scene as parse_ir

    document = json.loads(placed.scene)
    scene = parse_ir(document)

    assert scene.width, scene.height == (WIDTH, HEIGHT)
    assert [obj.id for layer in scene.layers for obj in layer.objects] == ["rule"]
