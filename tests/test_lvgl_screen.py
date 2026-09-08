"""The screen, now that it is the stack's and not this project's.

`drm_screen` owns the layer model and the service; `drm_screen_lvgl` owns the
binding to the C in `poc/player/`. Both are tested where they live. What is
left to check here is what this repository is still responsible for:

* the C those packages bind is *this* C, and a scene drawn through a screen
  layer must be the same frame the device player draws for that scene -- byte
  for byte, or the two paths have quietly diverged;
* a ripple, which is this project's addition to the vocabulary, reaches it;
* the service works with or without `drm_screen` on the machine, because a node
  is allowed to be one without numpy.

Skipped wholesale where the library has not been built.
"""

import pytest

from mementum_node.players.lvgl import LvglPlayer
from mementum_node.screen import Screen, commands as cmd, is_available, screen_service
from mementum_node.screen.service import HAVE_DRM_SCREEN, SimpleScreenService
from sim.assert_sync import looks_the_same

from .conftest_helpers import SCENE_PATH

pytestmark = pytest.mark.skipif(
    not is_available(),
    reason="C player not built; run: make -C poc/host-player -j4 lib",
)

WIDTH, HEIGHT = 320, 200
RED = (220, 60, 60, 255)


def solid(width: int, height: int, rgba) -> bytes:
    return bytes(rgba) * (width * height)


@pytest.fixture(scope="module")
def payload():
    with open(SCENE_PATH, "rb") as fh:
        return fh.read()


@pytest.fixture
def service():
    service = screen_service(display="memory", width=WIDTH, height=HEIGHT)
    yield service
    service.stop()


def frame_of(service):
    return service.renderer.screen.frame()


# -- the C is the same C --------------------------------------------------


@pytest.mark.parametrize("scene_time", [0.0, 900.0, 2200.0, 4000.0])
def test_a_scene_on_a_layer_draws_what_the_player_draws(service, payload, scene_time):
    """The substitution that matters: through a screen layer and through the
    device player, the same scene is the same frame -- not a similar one."""
    service.submit([
        cmd.CreateLayer("scene", WIDTH, HEIGHT),
        cmd.PlaceScene("scene", payload),
    ])
    service.render_once(scene_time)

    player = LvglPlayer()
    player.bind(payload, None, WIDTH, HEIGHT)

    assert frame_of(service).data == player.render(scene_time).data


def test_a_ripple_reaches_the_ink(service, payload):
    """`StartRipple` is this project's record, not `drm_screen`'s. It applies
    because the renderer dispatches by class name -- which is the whole reason
    the plugin was written that way."""
    service.submit([
        cmd.CreateLayer("scene", WIDTH, HEIGHT),
        cmd.PlaceScene("scene", payload),
    ])
    service.render_once(2200.0)
    calm = frame_of(service)

    service.submit([cmd.StartRipple("scene", origin=0.4, start=2000.0, amplitude=14.0)])
    service.render_once(2200.0)
    excited = frame_of(service)

    assert excited.data != calm.data
    same, detail = looks_the_same(calm, excited)
    assert same, f"a ripple disturbs the ink, it does not replace the picture: {detail}"


def test_a_scene_layer_composites_under_a_bitmap_layer(service, payload):
    service.submit([
        cmd.CreateLayer("scene", WIDTH, HEIGHT, z=1),
        cmd.PlaceScene("scene", payload),
        cmd.CreateLayer("badge", 60, 30, x=10, y=10, z=2),
        cmd.PlaceRawBuffer("badge", 60, 30, data=solid(60, 30, RED)),
    ])
    service.render_once(2200.0)
    frame = frame_of(service)

    assert frame.get(20, 20)[:3] == RED[:3]
    assert frame.get(200, 150)[:3] != RED[:3]


def test_a_screen_frame_is_this_project_s_frame(service):
    """So the same capture, PNG and comparison tools work on a screen as on a
    rendered player frame."""
    screen = Screen(40, 20, "memory")
    try:
        screen.create_layer("box", 40, 20)
        screen.blit("box", solid(40, 20, RED), 40, 20)
        screen.render()
        frame = screen.frame()
    finally:
        screen.close()

    assert (frame.width, frame.height) == (40, 20)
    assert frame.get(10, 10)[:3] == RED[:3]


# -- the service, either way ----------------------------------------------


def test_the_service_reads_the_clock_it_was_given(payload):
    """`state = evaluate(sharedNow() - displayAt)`: the service does not keep
    time of its own, it asks."""
    now = [0.0]
    service = screen_service(display="memory", width=WIDTH, height=HEIGHT,
                             clock=lambda: now[0])
    try:
        service.submit([
            cmd.CreateLayer("scene", WIDTH, HEIGHT),
            cmd.PlaceScene("scene", payload),
        ])
        service.render_once()
        early = frame_of(service)

        now[0] = 2200.0
        service.render_once()
        later = frame_of(service)

        assert early.data != later.data
    finally:
        service.stop()


def test_a_node_without_numpy_gets_the_same_screen(payload):
    """`drm_screen` needs numpy and drm_display. A node that has neither runs
    the stdlib loop instead, and must end up with the same picture -- the
    renderer is the same object in both."""
    upstream = screen_service(display="memory", width=WIDTH, height=HEIGHT)
    from drm_screen_lvgl import LvglRenderer

    from mementum_node.screen.service import Screen as ScreenType

    plain = SimpleScreenService(LvglRenderer(screen=ScreenType(WIDTH, HEIGHT, "memory")))
    try:
        batch = [cmd.CreateLayer("scene", WIDTH, HEIGHT), cmd.PlaceScene("scene", payload)]
        for service in (upstream, plain):
            service.submit(list(batch))
            service.render_once(2200.0)

        assert frame_of(plain).data == frame_of(upstream).data
    finally:
        upstream.stop()
        plain.stop()


def test_a_still_screen_is_not_redrawn():
    """The dirty flag survived every move it has made."""
    service = SimpleScreenService(
        __import__("drm_screen_lvgl").LvglRenderer(screen=Screen(100, 100, "memory"))
    )
    try:
        service.submit([cmd.CreateLayer("box", 40, 20)])
        service.render_once()
        assert service.frames == 1

        service.render_once()
        assert service.frames == 1              # no commands, no scene, no work

        service.submit([cmd.SetPosition("box", 10, 10)])
        service.render_once()
        assert service.frames == 2
    finally:
        service.stop()


def test_the_upstream_service_is_used_when_it_is_installed(service):
    """Not a preference -- a check that this repository stopped keeping its own
    copy of a loop the stack already has."""
    if HAVE_DRM_SCREEN:
        assert type(service).__module__.startswith("drm_screen")
    else:  # pragma: no cover - hosts without drm_screen
        assert isinstance(service, SimpleScreenService)
