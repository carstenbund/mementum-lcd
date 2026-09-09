"""The guide: a running order the server plays by timecode.

Two things are being checked. The document and its arithmetic -- a timecode is
what a show caller writes, the current cue is the last one whose moment has
passed, and a tick window fires each cue exactly once. And the sequencer
running it: that a cue becomes an ordinary schedule, that a node joining
halfway through is the ordinary late-join case, and that an effect is a moment
rather than a state.

The rule under all of it is the one the rest of the system already obeys: the
answer is a function of the clock. Nothing accumulates, so ticking finely,
coarsely or late gives the same show.
"""

import pytest

from mementum_node.core.clock import FixedClock
from mementum_node.core.guide import Cue, Guide, format_timecode, parse_timecode
from mementum_node.core.library import SceneLibrary
from mementum_node.core.protocol import (
    Capabilities, Display, NodeDescriptor, Position, Register, RippleCommand,
)
from mementum_node.core.sequencer import Sequencer
from mementum_node.core.transport import PushResult

LEAD = 250.0


class ManualTime:
    """The clock a show is called against, moved by hand."""

    def __init__(self, now: float = 10_000.0):
        self.now = now

    def monotonic_ms(self) -> float:
        return self.now


class RecordingFanout:
    """Every push, kept: what the wall was told and when."""

    def __init__(self):
        self.messages = []

    def push(self, node_ids, message):
        node_ids = list(node_ids)
        self.messages.append((message, node_ids))
        return [PushResult(node_id, True, 1.0) for node_id in node_ids]

    def of_type(self, kind):
        return [m for m, _ in self.messages if type(m).__name__ == kind]

    def pushes_of(self, kind):
        """(message, targets) pairs -- one push may address many nodes at once,
        which is itself the difference between the two effect gestures."""
        return [(m, n) for m, n in self.messages if type(m).__name__ == kind]


def scene_document(scene_id: int, name: str = "a scene") -> dict:
    return {
        "version": 1, "id": scene_id, "name": name, "width": 240, "height": 120,
        "fit": "contain", "duration": 3000,
        "layers": [{"id": "ink", "z": 10, "objects": [
            {"type": "path", "id": "line", "d": "M 20 60 L 220 60",
             "stroke": "#e8e8f0", "stroke_width": 3, "progress": 0}]}],
        "animations": [{"target": "line", "property": "progress", "start": 0,
                        "duration": 3000, "from": 0, "to": 1, "easing": "linear"}],
    }


@pytest.fixture
def show():
    """A sequencer with two scenes, four units and a guide loaded."""
    time = ManualTime()
    fanout = RecordingFanout()
    library = SceneLibrary()
    library.add(scene_document(41, "opening"))
    library.add(scene_document(42, "symbols"))

    sequencer = Sequencer(FixedClock(time), library=library, fanout=fanout, lead_ms=LEAD)
    for index in range(4):
        sequencer.handle(Register(NodeDescriptor(
            node_id=f"unit-{index}", device="linux", roles=("display",),
            display=Display(450, 250, "rgba8888"),
            capabilities=Capabilities(scene_ir=1, vector=True, text=True, lottie=False),
            position=Position(x=index * 2.0, y=0.0),
        )))

    guide = Guide.from_document({"name": "opening", "cues": [
        {"at": "00:00:00", "play": "animation", "scene": 42},
        {"at": "00:00:10", "play": "animation", "scene": 41},
        {"at": "00:00:14", "play": "effect", "effect": "ripple", "unit": "unit-0",
         "params": {"amplitude": 16}},
        {"at": "00:00:20", "play": "effect", "effect": "ripple"},
    ]})
    sequencer.load_guide(guide)
    return sequencer, time, fanout, guide


# -- the timecode ---------------------------------------------------------


@pytest.mark.parametrize("written, ms", [
    ("0", 0.0),
    ("12", 12_000.0),
    ("1:23", 83_000.0),                 # a running order reads this as minutes
    ("00:01:23", 83_000.0),
    ("00:01:23.4", 83_400.0),
    ("00:01:23,400", 83_400.0),
    ("1.5s", 1500.0),
    ("1200ms", 1200.0),
    (1200, 1200.0),
    (1200.5, 1200.5),
])
def test_a_timecode_is_read_the_way_it_is_written(written, ms):
    assert parse_timecode(written) == ms


@pytest.mark.parametrize("written", ["", "soon", "1:2:3:4", "half past"])
def test_nonsense_is_refused_rather_than_guessed(written):
    with pytest.raises(ValueError):
        parse_timecode(written)


def test_a_timecode_survives_being_written_down():
    for ms in (0.0, 83_400.0, 3_600_000.0, 3_723_456.0):
        assert parse_timecode(format_timecode(ms)) == ms


# -- the document ---------------------------------------------------------


def test_cues_are_kept_in_time_order_however_they_were_written():
    guide = Guide(cues=(
        Cue(at=20_000, action="animation", scene_id=2),
        Cue(at=0, action="animation", scene_id=1),
        Cue(at=10_000, action="effect"),
    ))

    assert [cue.at for cue in guide] == [0, 10_000, 20_000]
    assert guide.duration == 20_000


def test_a_cue_must_be_able_to_do_what_it_says():
    with pytest.raises(ValueError, match="unknown cue action"):
        Cue(at=0, action="fireworks")
    with pytest.raises(ValueError, match="needs a scene or words"):
        Cue(at=0, action="animation")


def test_the_guide_survives_being_written_down(show):
    _, _, _, guide = show
    assert Guide.from_document(guide.to_document()) == guide


# -- what should be on the wall -------------------------------------------


def test_the_current_scene_is_the_last_one_whose_moment_has_passed(show):
    _, _, _, guide = show

    assert guide.scene_at(-1) is None
    assert guide.scene_at(0).scene_id == 42
    assert guide.scene_at(9_999).scene_id == 42
    assert guide.scene_at(10_000).scene_id == 41
    assert guide.scene_at(60_000).scene_id == 41, "the last scene stands until told otherwise"


def test_an_effect_does_not_become_the_picture(show):
    """Effects are moments. Asking what is on the wall at 15 s must give the
    scene playing, not the ripple that happened at 14."""
    _, _, _, guide = show

    assert guide.scene_at(15_000).scene_id == 41


def test_a_tick_window_is_half_open_so_a_cue_fires_once(show):
    _, _, _, guide = show

    assert [cue.at for cue in guide.due(-1, 0)] == [0]
    assert guide.due(0, 0) == ()
    assert [cue.at for cue in guide.due(0, 14_000)] == [10_000, 14_000]
    assert guide.due(14_000, 19_999) == ()


# -- the show, running ----------------------------------------------------


def test_starting_a_show_pushes_the_first_cue_before_its_moment(show):
    sequencer, _, fanout, _ = show
    tick = sequencer.start_show()

    assert [cue.scene_id for cue in tick.fired] == [42]
    play = fanout.of_type("Play")[0]
    # Pushed now, displayed a lead later: that is what the lead is for.
    assert play.schedule.display_at == sequencer.show_epoch
    assert play.schedule.display_at == pytest.approx(10_000 + LEAD)


def test_a_cue_fires_once_however_often_the_server_ticks(show):
    sequencer, time, fanout, _ = show
    sequencer.start_show()

    for step in range(0, 21_000, 100):      # 210 ticks across the whole show
        time.now = 10_000 + step
        sequencer.tick()

    assert len(fanout.of_type("Play")) == 2, "two scene cues, two PLAYs"
    fired = [cue.at for tick in sequencer.show_history for cue in tick.fired]
    assert fired == [0, 10_000, 14_000, 20_000]


def test_a_tick_that_arrives_late_fires_what_it_missed(show):
    """A server that was busy is not a server that skips the show."""
    sequencer, time, fanout, _ = show
    sequencer.start_show()

    time.now = 10_000 + 15_000              # one tick, fifteen seconds later
    tick = sequencer.tick()

    assert [cue.at for cue in tick.fired] == [10_000, 14_000]
    assert len(fanout.of_type("Play")) == 2


def test_a_node_joining_halfway_through_is_told_where_the_show_is(show):
    """Not a new mechanism: the running schedule comes back in the ordinary
    registration reply, with its own displayAt in the past, and the node
    evaluates into the middle of the scene."""
    sequencer, time, _, _ = show
    sequencer.start_show()
    time.now = 10_000 + 12_000
    sequencer.tick()

    ack = sequencer.handle(Register(NodeDescriptor(
        node_id="latecomer", device="esp32", roles=("display",),
        display=Display(450, 250, "rgb565"),
        capabilities=Capabilities(scene_ir=1, vector=True, text=True, lottie=False),
    )))

    assert ack.schedule.playing and ack.schedule.scene_id == 41
    assert ack.schedule.display_at < time.now, "it started before this node arrived"


def test_seeking_puts_the_right_scene_on_the_wall(show):
    sequencer, time, fanout, _ = show
    sequencer.start_show()
    time.now = 10_000 + 1_000

    tick = sequencer.seek("00:00:15")

    assert [cue.scene_id for cue in tick.fired] == [41], "the scene running at 15 s"
    assert sequencer.show_time() == pytest.approx(15_000 - LEAD)
    # The cues before the seek point must not fire again on the next tick.
    time.now += 100
    assert sequencer.tick().fired == []


def test_stopping_the_show_idles_the_wall_and_keeps_the_guide(show):
    sequencer, _, fanout, _ = show
    sequencer.start_show()
    sequencer.stop_show()

    assert sequencer.schedule.state == "idle"
    assert sequencer.guide is not None
    assert sequencer.show_time() is None
    assert sequencer.tick().fired == []


# -- effects --------------------------------------------------------------


def test_an_effect_from_a_unit_travels_from_there(show):
    sequencer, time, fanout, _ = show
    sequencer.start_show()
    time.now = 10_000 + 14_000
    tick = sequencer.tick()

    assert tick.touches, "an effect on a unit is a touch, because that is what it is"
    ripples = fanout.of_type("RippleCommand")
    starts = sorted(r.start_at for r in ripples)
    assert len(ripples) == 3, "everybody but the unit it started on"
    assert starts[-1] > starts[0], "it arrives at the far unit later"
    assert all(r.amplitude == 16 for r in ripples), "the cue said how hard"


def test_an_effect_with_no_unit_excites_everybody_at_once(show):
    """A different gesture, and it should look like one: one command, every
    unit, one moment -- not a wave with an origin."""
    sequencer, time, fanout, _ = show
    sequencer.start_show()
    time.now = 10_000 + 20_000
    sequencer.tick()

    command, targets = fanout.pushes_of("RippleCommand")[-1]
    assert sorted(targets) == ["unit-0", "unit-1", "unit-2", "unit-3"]
    assert command.origin_node == ""
    assert command.start_at == pytest.approx(sequencer.show_epoch + 20_000)


# -- live text ------------------------------------------------------------


def test_words_decided_during_the_show_are_compiled_when_the_cue_fires(show):
    """The escape hatch. It is still the composer that compiles and still a
    scene that reaches the device -- no node holds a font."""
    sequencer, time, fanout, _ = show
    calls = []

    def compiler(text):
        calls.append(text)
        return scene_document(0, text)

    sequencer.load_guide(Guide.from_document({"cues": [
        {"at": 0, "play": "text", "text": "du kannst"},
        {"at": 5_000, "play": "text", "text": "du kannst"},
    ]}), text_compiler=compiler)
    sequencer.start_show()
    time.now = 10_000 + 5_000
    sequencer.tick()

    assert calls == ["du kannst"], "the same line is compiled once, not twice"
    assert len(fanout.of_type("Play")) == 2
    assert len(sequencer.library) == 3


def test_a_guide_says_what_is_wrong_with_it_while_there_is_time(show):
    sequencer, _, _, _ = show
    problems = sequencer.load_guide(Guide.from_document({"cues": [
        {"at": 0, "play": "animation", "scene": 999},
        {"at": 1_000, "play": "text", "text": "no compiler here"},
        {"at": 2_000, "play": "effect", "unit": "unit-9"},
    ]}))

    assert len(problems) == 3
    assert "unknown scene 999" in problems[0]
    assert "no text compiler" in problems[1]
    assert "unit-9" in problems[2]


def test_a_line_that_cannot_be_compiled_does_not_stop_the_show(show):
    sequencer, time, _, _ = show

    def compiler(text):
        raise ValueError("no glyph for that")

    sequencer.load_guide(Guide.from_document({"cues": [
        {"at": 0, "play": "text", "text": "???"},
        {"at": 1_000, "play": "animation", "scene": 42},
    ]}), text_compiler=compiler)
    sequencer.start_show()
    time.now = 10_000 + 1_000
    tick = sequencer.tick()

    assert any("no glyph" in why for tick in sequencer.show_history for why in tick.refused)
    assert [cue.scene_id for cue in tick.fired] == [42], "the next cue still happens"


# -- the wall as sixteen units --------------------------------------------


def test_a_staggered_cue_starts_each_unit_after_the_last(show):
    """The same scene, one unit at a time: every unit gets its own displayAt
    and evaluates against it, so nothing has to be rendered twice."""
    sequencer, _, _, _ = show
    sequencer.load_guide(Guide.from_document({"cues": [
        {"at": 0, "play": "animation", "scene": 42, "stagger": "1s"},
    ]}))
    tick = sequencer.start_show()

    schedules = tick.plays[0].schedules
    starts = [schedules[node_id].display_at for node_id in sequencer.units_in_order()]
    assert starts == sorted(starts)
    assert [round(start - starts[0]) for start in starts] == [0, 1000, 2000, 3000]
    assert len({s.scene_id for s in schedules.values()}) == 1, "one scene, four moments"


def test_a_dealt_sentence_gives_each_unit_its_own_word(show):
    sequencer, _, _, _ = show
    sequencer.load_guide(Guide.from_document({"cues": [
        {"at": 0, "play": "text", "spread": "deal", "scenes": [41, 42]},
    ]}))
    tick = sequencer.start_show()

    schedules = tick.plays[0].schedules
    units = sequencer.units_in_order()
    assert [schedules[node_id].scene_id for node_id in units] == [41, 42, 41, 42], \
        "a sentence shorter than the wall repeats along it"
    assert len({s.display_at for s in schedules.values()}) == 1, "dealt, not staggered"


def test_units_are_dealt_to_in_reading_order(show):
    """"the first unit" has to mean something physical, and where a unit stands
    is the only thing that knows."""
    sequencer, _, _, _ = show
    for node_id, node in sequencer.nodes.items():
        assert node.descriptor.position is not None
    assert sequencer.units_in_order() == ["unit-0", "unit-1", "unit-2", "unit-3"]


def test_a_tiling_word_starts_each_unit_half_a_travel_later(show):
    """`tile` is mementum-led's word and means the same thing: the content
    tiles into one long marquee, so what leaves one unit enters the next. A
    travelling scene crosses two panel widths, so a panel is half of it."""
    sequencer, _, _, _ = show
    sequencer.load_guide(Guide.from_document({"cues": [
        {"at": 0, "play": "text", "text": "mementum", "scene": 42, "stagger": "tile"},
    ]}))
    tick = sequencer.start_show()

    schedules = tick.plays[0].schedules
    starts = [schedules[node_id].display_at for node_id in sequencer.units_in_order()]
    duration = sequencer.library.get(42).duration
    assert [round(start - starts[0]) for start in starts] == [
        0, duration // 2, duration, duration + duration // 2
    ]


def test_a_unit_keeps_its_own_schedule_across_a_restart(show):
    """Per-unit schedules are still state: each node recovers its own from the
    ordinary registration reply, not a shared one."""
    sequencer, time, _, _ = show
    sequencer.load_guide(Guide.from_document({"cues": [
        {"at": 0, "play": "animation", "scene": 42, "stagger": "1s"},
    ]}))
    sequencer.start_show()

    third = sequencer.units_in_order()[2]
    ack = sequencer.handle(Register(sequencer.nodes[third].descriptor))

    assert ack.schedule.display_at == pytest.approx(sequencer.show_epoch + 2000)


def test_a_ripple_still_crosses_a_staggered_wall(show):
    """Two clocks at once: the wave travels in shared time while each unit is
    at a different point of the scene. Neither is allowed to disturb the other."""
    sequencer, time, fanout, _ = show
    sequencer.load_guide(Guide.from_document({"cues": [
        {"at": 0, "play": "animation", "scene": 42, "stagger": "1s"},
        {"at": 5_000, "play": "effect", "unit": "unit-0", "params": {"amplitude": 16}},
    ]}))
    sequencer.start_show()
    time.now = 10_000 + 5_000
    sequencer.tick()

    ripples = fanout.of_type("RippleCommand")
    assert len(ripples) == 3
    assert len({r.start_at for r in ripples}) == 3, "distance, not schedule, times a ripple"


@pytest.mark.parametrize("stagger, factor, expected", [
    ("", 1.0, 0.0),                       # everybody at once
    ("auto", 1.0, 3000.0),                # one full go of the content per unit
    ("auto", 0.5, 1500.0),                # overlapped into a glide
    ("tile", 1.0, 1500.0),                # one panel width of a two-panel travel
    ("tile", 1.1, pytest.approx(1650.0)),  # a touch more, for the bezel
    ("1.2s", 1.0, 1200.0),                # exactly that
])
def test_the_stagger_modes_mean_what_mementum_led_means_by_them(show, stagger, factor, expected):
    sequencer, _, _, _ = show

    assert sequencer.stagger_ms(stagger, scene_id=42, factor=factor) == expected


def test_an_explicit_order_beats_where_the_units_say_they_stand(show):
    """The positions were typed in by a person and the wall was hung by one:
    /identify is how you find out which unit is actually where."""
    sequencer, _, _, _ = show

    assert sequencer.units_in_order(order=("unit-3", "unit-1")) == ["unit-3", "unit-1"]
    assert sequencer.units_in_order(order=("unit-3", "nobody")) == ["unit-3"]
    assert sequencer.units_in_order(reverse=True)[0] == "unit-3"


def test_a_sweep_can_run_the_other_way(show):
    sequencer, _, _, _ = show
    sequencer.load_guide(Guide.from_document({"cues": [
        {"at": 0, "play": "animation", "scene": 42, "stagger": "1s", "reverse": True},
    ]}))
    tick = sequencer.start_show()

    schedules = tick.plays[0].schedules
    assert schedules["unit-3"].display_at < schedules["unit-0"].display_at
