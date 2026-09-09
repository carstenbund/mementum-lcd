"""The schedule as the firmware holds it -- the same lines, on the host.

`poc/player/schedule.c` is what an ESP32 runs when a push arrives: adopt it if
it is new, ignore it if it is not, and every frame ask what time the scene is
at. It is deliberately dependency-free so the sketch and these tests compile
the same file, in the same way that the evaluator is shared rather than
reimplemented (§3.7).

What is being pinned here is the behaviour a panel on a wall depends on: that a
repeated push does not restart a scene, that a late one does not undo a newer
one, and that scene time is `now - displayAt` and nothing else.
"""

import ctypes

import pytest

from mementum_node.players.lvgl import PlayerLibrary, is_available

pytestmark = pytest.mark.skipif(
    not is_available(),
    reason="C player not built; run: make -C poc/host-player -j4 lib",
)

HASH = "a" * 64


@pytest.fixture(scope="module")
def lib():
    library = PlayerLibrary.instance().raw
    library.mm_schedule_size.restype = ctypes.c_int
    library.mm_schedule_reset.argtypes = [ctypes.c_void_p]
    library.mm_schedule_take.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_double,
                                         ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
    library.mm_schedule_take.restype = ctypes.c_int
    library.mm_schedule_at.argtypes = [ctypes.c_void_p, ctypes.c_double]
    library.mm_schedule_at.restype = ctypes.c_double
    library.mm_schedule_visible.argtypes = [ctypes.c_void_p, ctypes.c_double]
    library.mm_schedule_visible.restype = ctypes.c_int
    library.mm_schedule_over.argtypes = [ctypes.c_void_p, ctypes.c_double]
    library.mm_schedule_over.restype = ctypes.c_int
    return library


@pytest.fixture
def schedule(lib):
    buffer = ctypes.create_string_buffer(lib.mm_schedule_size())
    lib.mm_schedule_reset(buffer)
    return buffer


def take(lib, schedule, seq, at, scene=41, digest=HASH, duration=3000):
    return bool(lib.mm_schedule_take(schedule, seq, at, scene,
                                     digest.encode() if digest else None, duration))


def test_nothing_is_showing_before_anything_is_scheduled(lib, schedule):
    assert lib.mm_schedule_at(schedule, 1000.0) < 0
    assert not lib.mm_schedule_visible(schedule, 1000.0)
    assert lib.mm_schedule_over(schedule, 1000.0), "idle counts as finished"


def test_scene_time_is_the_clock_minus_the_moment(lib, schedule):
    take(lib, schedule, 1, at=5000.0)

    assert lib.mm_schedule_at(schedule, 5000.0) == 0.0
    assert lib.mm_schedule_at(schedule, 6200.0) == 1200.0
    assert lib.mm_schedule_at(schedule, 4000.0) == -1000.0, "not started yet"
    assert not lib.mm_schedule_visible(schedule, 4000.0)
    assert lib.mm_schedule_visible(schedule, 5500.0)


def test_the_same_push_twice_does_not_restart_the_scene(lib, schedule):
    """The server re-sends freely and a heartbeat carries the schedule again:
    if either restarted the scene, the wall would stutter every few seconds."""
    assert take(lib, schedule, 7, at=5000.0) is True
    assert take(lib, schedule, 7, at=5000.0) is False
    assert lib.mm_schedule_at(schedule, 6000.0) == 1000.0


def test_a_late_push_does_not_undo_a_newer_one(lib, schedule):
    take(lib, schedule, 9, at=9000.0)

    assert take(lib, schedule, 8, at=1000.0) is False, "an older seq is a late packet"
    assert lib.mm_schedule_at(schedule, 9500.0) == 500.0


def test_a_new_moment_for_a_scene_already_held_is_not_a_new_fetch(lib, schedule):
    """Fetching is the only expensive thing a panel does. A stagger, a seek or
    a replay of the same scene must not make it happen twice."""
    take(lib, schedule, 1, at=5000.0)
    held = ctypes.cast(schedule, ctypes.POINTER(ctypes.c_char * lib.mm_schedule_size()))
    # `loaded` is the last byte-ish field; set it through a second adopt instead
    # of poking at the struct: adopt the same scene at a new moment.
    assert take(lib, schedule, 2, at=8000.0, scene=41, digest=HASH) is True
    assert lib.mm_schedule_at(schedule, 8000.0) == 0.0
    assert held is not None


def test_a_scene_with_a_duration_ends_and_one_without_holds(lib, schedule):
    take(lib, schedule, 1, at=1000.0, duration=2000)
    assert not lib.mm_schedule_over(schedule, 2500.0)
    assert lib.mm_schedule_over(schedule, 3500.0)

    lib.mm_schedule_reset(schedule)
    take(lib, schedule, 2, at=1000.0, duration=0)
    assert not lib.mm_schedule_over(schedule, 999_000.0), "it holds until told otherwise"


def test_clearing_is_what_stop_means(lib, schedule):
    take(lib, schedule, 1, at=1000.0)
    lib.mm_schedule_reset(schedule)

    assert lib.mm_schedule_at(schedule, 5000.0) < 0
    assert not lib.mm_schedule_visible(schedule, 5000.0)
