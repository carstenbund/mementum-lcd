"""The cue sheet, compiled.

A guide is authored the way a show is: a running order with timecodes, in the
markup this project already uses. This checks what the composer does with it --
scenes resolved, words turned into pen strokes ahead of time, and a `live` cue
left for the server to compile at the moment it fires.
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

from mementum_node.core.guide import Guide  # noqa: E402

guide_tool = pytest.importorskip("guide", reason="tools/ not importable")

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SHEET = """
<guide name="test show">
  <cue at="00:00:00" play="animation" scene="poc/scenes/three-strokes.json" label="opening" />
  <cue at="0:12" play="text">hallo</cue>
  <cue at="0:20" play="text" live>whatever they shout</cue>
  <cue at="0:26" play="effect" unit="unit-11" amplitude="16" />
  <cue at="0:30" play="effect" />
</guide>
"""


@pytest.fixture(scope="module")
def show():
    from handwriting import DEFAULT_FONT

    if not os.path.exists(DEFAULT_FONT):
        pytest.skip("Hershey font not fetched; run tools/fetch-hershey.sh")
    return guide_tool.compile_show(SHEET, base_dir=REPO)


def test_the_running_order_survives_compilation(show):
    guide = Guide.from_document(show)

    assert guide.name == "test show"
    assert [cue.at for cue in guide] == [0, 12_000, 20_000, 26_000, 30_000]
    assert guide.duration == 30_000


def test_a_scene_cue_carries_an_id_and_the_scene_travels_with_the_show(show):
    cue = Guide.from_document(show).cues[0]
    ids = {entry["id"] for entry in show["scenes"]}

    assert cue.scene_id in ids, "a runner needs nothing but this file"
    assert cue.label == "opening"


def test_words_are_pen_strokes_before_the_show_starts(show):
    """The ordinary case: a show should not be doing work at the moment it is
    meant to be showing something."""
    # The source key says which words and which way they were built: a word
    # that is written and the same word that travels are two scenes.
    compiled = [s for s in show["scenes"] if s["src"] == "text:hallo:write"]

    assert len(compiled) == 1
    scene = compiled[0]["scene"]
    assert scene["text"] == "hallo"
    path = scene["layers"][1]["objects"][0]
    assert path["d"].startswith("M"), "strokes, not a font reference"
    assert path["length"] > 0, "measured by the composer, never by the device"


def test_a_live_cue_keeps_its_words_and_gets_no_scene(show):
    """The escape hatch: compiled when it fires, because the line is not known
    until then."""
    live = [cue for cue in Guide.from_document(show) if cue.live]

    assert [cue.text for cue in live] == ["whatever they shout"]
    assert not any("whatever they shout" in s["src"] for s in show["scenes"])


def test_effects_keep_their_parameters(show):
    cues = [cue for cue in Guide.from_document(show) if cue.is_effect]

    assert cues[0].unit == "unit-11" and cues[0].params["amplitude"] == 16
    assert cues[1].unit == "", "no unit means everybody at once"


def test_a_typo_in_a_cue_is_caught_here_rather_than_on_the_night():
    with pytest.raises(ValueError, match="unknown attribute"):
        guide_tool.compile_show('<guide><cue at="0" play="effect" amplitide="9" /></guide>')


def test_a_text_cue_with_no_words_is_refused():
    with pytest.raises(ValueError, match="no words"):
        guide_tool.compile_show('<guide><cue at="0" play="text" /></guide>')


def test_the_package_is_json_and_stays_json(show):
    assert json.loads(json.dumps(show))["name"] == "test show"


# -- the wall as sixteen units --------------------------------------------

SPREADS = """
<guide name="spread">
  <cue at="0:00" play="animation" scene="poc/scenes/three-strokes.json"
       stagger="1s" />
  <cue at="0:12" play="text" spread="deal">du kannst werden</cue>
  <cue at="0:30" play="text" stagger="tile" duration="4s">mementum</cue>
</guide>
"""


@pytest.fixture(scope="module")
def spread_show():
    from handwriting import DEFAULT_FONT

    if not os.path.exists(DEFAULT_FONT):
        pytest.skip("Hershey font not fetched; run tools/fetch-hershey.sh")
    return guide_tool.compile_show(SPREADS, base_dir=REPO)


def test_a_spread_survives_into_the_guide(spread_show):
    cues = Guide.from_document(spread_show).cues

    assert cues[0].stagger == "1s"
    assert cues[1].spread == "deal"
    assert cues[2].stagger == "tile"
    assert cues[2].factor == 1.0, "unset means the server works it out from the travel"


def test_a_dealt_sentence_is_one_scene_per_word(spread_show):
    dealt = Guide.from_document(spread_show).cues[1]

    assert len(dealt.scene_ids) == 3, "du / kannst / werden"
    assert len(set(dealt.scene_ids)) == 3


def test_a_running_word_arrives_written_and_crosses(spread_show):
    """The difference between a word that draws itself and a word that walks:
    one animates `progress`, the other animates where it is."""
    travelling = [s for s in spread_show["scenes"] if s["src"].endswith(":travel")]

    assert len(travelling) == 1
    scene = travelling[0]["scene"]
    path = scene["layers"][1]["objects"][0]
    assert path["progress"] == 1, "already written when it arrives"
    animation = scene["animations"][0]
    assert animation["property"] == "transform.tx"
    assert animation["from"] == -animation["to"] == scene["width"], "a panel either side"


def test_the_same_word_written_and_travelling_are_two_scenes(spread_show):
    """Because they are: one is drawn, the other is moved."""
    sources = {s["src"] for s in spread_show["scenes"]}

    assert "text:mementum:travel" in sources
    assert "text:du:write" in sources
