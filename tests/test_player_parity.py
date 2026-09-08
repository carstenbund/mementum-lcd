"""The two players must support the same things.

The layering test guards `sim/` against the core. This one guards the *pair of
renderers* against each other, which is the gap that let the Python reference
sit for weeks applying `progress` to every subpath independently while only the
C player sequenced them — a rule tested in one implementation is not tested.

Everything here is derived from the core's own declarations, so adding a
deformation or an animatable property to the model makes this fail until the
device's player learns it too.
"""

import json

import pytest

from mementum_node.core.protocol import Capabilities
from mementum_node.core.render_backend import ReferenceRenderer, Renderer
from mementum_node.core.scene import ANIMATABLE, DEFORMATIONS, parse_scene
from mementum_node.players.lvgl import LvglPlayer, LvglPlayerError, is_available

pytestmark = pytest.mark.skipif(
    not is_available(), reason="C player not built; run: make -C poc/host-player -j4 lib"
)

#: The surface a node's renderer must offer, whichever implementation it is.
RENDERER_SURFACE = ("bind", "render", "add_ripple", "name")


def _scene(prop=None, deform=None):
    obj = {"type": "path", "id": "p", "d": "M 10 50 L 90 50",
           "stroke": "#ffffff", "stroke_width": 2, "progress": 1}
    if deform:
        obj["deform"] = {"type": deform, "amplitude": 5, "wavelength": 40}
    raw = {"version": 1, "width": 100, "height": 100,
           "layers": [{"id": "l", "z": 0, "objects": [obj]}], "animations": []}
    if prop:
        raw["animations"] = [{"target": "p", "property": prop, "start": 0,
                              "duration": 100, "from": 0, "to": 1, "easing": "linear"}]
    return raw


def _c_accepts(raw) -> bool:
    player = LvglPlayer()
    try:
        player.bind(json.dumps(raw).encode("utf-8"), None, 100, 100)
        return True
    except LvglPlayerError:
        return False


@pytest.mark.parametrize("kind", sorted(DEFORMATIONS))
def test_a_vector_renderer_knows_every_deformation(kind):
    """The rule is not that every renderer draws everything — a plain RGBA
    painter draws none of this. It is that a renderer which *declares* vector
    must handle the whole vector vocabulary, so a scene the sequencer judged
    playable really plays."""
    raw = _scene(deform=kind)
    parse_scene(raw)                      # the reference accepts it by construction
    assert LvglPlayer.capabilities.vector
    assert _c_accepts(raw), f"the device's player does not know the {kind!r} deformation"


@pytest.mark.parametrize("prop", sorted(ANIMATABLE))
def test_a_vector_renderer_knows_every_animatable_property(prop):
    raw = _scene(prop=prop, deform="sine") if prop.startswith("deform.") else _scene(prop=prop)
    parse_scene(raw)
    assert _c_accepts(raw), f"the device's player cannot animate {prop!r}"


@pytest.mark.parametrize("implementation", [ReferenceRenderer, LvglPlayer])
def test_every_renderer_declares_what_it_can_draw(implementation):
    declared = implementation.capabilities
    assert isinstance(declared, Capabilities)
    assert declared.scene_ir >= 1, "a renderer must state which IR version it speaks"


def test_a_node_reports_its_renderers_capabilities():
    """The node and its renderer cannot disagree, because the node does not
    hold a second copy of the answer."""
    from sim.harness import Harness

    harness = Harness()
    node = harness.add_node("c-unit", renderer=LvglPlayer())
    assert node.core.descriptor.capabilities == LvglPlayer.capabilities


@pytest.mark.parametrize("implementation", [ReferenceRenderer, LvglPlayer])
def test_every_renderer_offers_the_whole_surface(implementation):
    missing = [name for name in RENDERER_SURFACE if not hasattr(implementation, name)]
    assert not missing, f"{implementation.__name__} is missing {missing}"


def test_the_surface_matches_the_protocol():
    """If the seam grows a method, this list has to grow with it."""
    declared = {name for name in vars(Renderer) if not name.startswith("_")}
    assert declared <= set(RENDERER_SURFACE) | {"name"}, declared - set(RENDERER_SURFACE)
