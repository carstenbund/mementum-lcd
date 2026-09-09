"""The control server: the LED server's routes, for panels that draw.

Two claims are under test here. That the route table behaves as
`mementum-led`'s does -- registration by source IP, monotonic ids, a bare
number from `/time`, a sequencer that schedules a display lead ahead -- and
that one wall can hold **both kinds of panel**: an LED matrix scrolling the
string a cue was written from, an LCD beside it drawing the same words as pen
strokes, from the same cue.

No network: the fan-out's session is a stub that records what each panel was
told, which is the interesting part anyway.
"""

import pytest

flask = pytest.importorskip("flask", reason="flask not installed")

from mementum_node.server.app import ControlServer, build  # noqa: E402


class Response:
    status_code = 200


class Recorder:
    """Stands in for `requests`: records, answers 200."""

    def __init__(self):
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, dict(params or {})))
        return Response()

    def to(self, ip):
        return [params for url, params in self.calls if url.startswith(f"http://{ip}")]

    def clear(self):
        self.calls.clear()


def scene_document(scene_id, name="scene", text=""):
    document = {
        "version": 1, "id": scene_id, "name": name, "width": 240, "height": 120,
        "fit": "contain", "duration": 3000,
        "layers": [{"id": "ink", "z": 10, "objects": [
            {"type": "path", "id": "line", "d": "M 20 60 L 220 60",
             "stroke": "#e8e8f0", "stroke_width": 3, "progress": 0}]}],
        "animations": [{"target": "line", "property": "progress", "start": 0,
                        "duration": 3000, "from": 0, "to": 1, "easing": "linear"}],
    }
    if text:
        document["text"] = text
    return document


SHOW = {
    "version": 1, "name": "test", "cues": [
        {"at": "00:00:00", "play": "animation", "scene": 41},
        {"at": "00:00:10", "play": "animation", "scene": 42},
    ],
    "scenes": [
        {"id": 41, "src": "a", "scene": scene_document(41, "opening", text="hallo")},
        {"id": 42, "src": "b", "scene": scene_document(42, "symbols")},
    ],
}


@pytest.fixture
def server():
    recorder = Recorder()
    control = ControlServer(lead_ms=250.0, session=recorder)
    control.log.echo = False
    control.recorder = recorder
    return control


@pytest.fixture
def client(server):
    app = build(server)
    app.config.update(TESTING=True)
    return app.test_client()


def register(client, ip, kind="lcd", **extra):
    query = "&".join(f"{k}={v}" for k, v in {"kind": kind, **extra}.items())
    return client.get(f"/register?{query}", environ_overrides={"REMOTE_ADDR": ip})


# -- the node plane, as the LED server has it -----------------------------


def test_registration_answers_the_sentence_the_firmware_parses(client):
    first = register(client, "10.0.0.5", kind="led", version="1.3")
    again = register(client, "10.0.0.5", kind="led", version="1.3")

    assert first.data.decode() == "Registered successfully. Your ID: 1"
    assert again.data.decode() == "Already registered. Your ID: 1"


def test_a_client_is_known_by_its_address_not_by_what_it_claims(client):
    register(client, "10.0.0.5")
    register(client, "10.0.0.6")
    rows = client.get("/clients").get_json()["clients"]

    assert [row["id"] for row in rows] == [1, 2]
    assert [row["ip"] for row in rows] == ["10.0.0.5", "10.0.0.6"]


def test_a_heartbeat_from_nobody_is_told_to_register(client):
    assert client.get("/heartbeat", environ_overrides={"REMOTE_ADDR": "10.9.9.9"}).status_code == 400
    register(client, "10.0.0.5")
    assert client.get("/heartbeat", environ_overrides={"REMOTE_ADDR": "10.0.0.5"}).status_code == 200


def test_time_is_a_bare_number_because_a_firmware_parses_it(client):
    body = client.get("/time").data.decode()

    assert body.isdigit()


def test_a_panel_can_fetch_the_scene_it_was_told_to_draw(server, client):
    server.load_show(SHOW)

    assert client.get("/scene/41").get_json()["id"] == 41
    assert client.get("/scene/999").status_code == 404
    assert client.get("/manifest/41").get_json()["duration"] == 3000


# -- the show -------------------------------------------------------------


def test_a_show_is_loaded_started_sought_and_stopped(server, client):
    register(client, "10.0.0.5")

    loaded = client.post("/guide", json=SHOW).get_json()
    assert loaded["cues"] == 2 and loaded["duration"] == "00:00:10.000"

    started = client.get("/start").get_json()
    assert started["running"] and started["scene_id"] == 41

    sought = client.get("/seek?at=0:10").get_json()
    assert sought["scene_id"] == 42

    stopped = client.get("/stop").get_json()
    assert not stopped["running"] and stopped["state"] == "idle"


def test_a_cue_reaches_the_panel_a_display_lead_early(server, client):
    register(client, "10.0.0.5")
    server.load_show(SHOW)
    client.get("/start")

    sent = server.recorder.to("10.0.0.5")
    assert sent, "the panel was told something"
    assert sent[0]["scene"] == 41
    assert sent[0]["at"] >= server.clock.shared_now()


def test_words_can_be_played_without_a_show(server, client):
    register(client, "10.0.0.5")
    played = client.get("/play?text=hallo").get_json()

    assert played["status"] == "ok" and played["delivered"] == 1


# -- one wall, two kinds of panel -----------------------------------------


def test_a_line_of_words_reaches_both_kinds_of_panel(server, client):
    """The whole point of keeping the LED server's wire form: an LED matrix
    scrolls the string, an LCD draws the same words as pen strokes, from one
    cue and one server."""
    register(client, "10.0.0.5", kind="led")
    register(client, "10.0.0.6", kind="lcd")
    server.recorder.clear()

    client.get("/play?text=hallo")

    led = server.recorder.to("10.0.0.5")[0]
    lcd = server.recorder.to("10.0.0.6")[0]
    assert led["data"] == "hallo", "the matrix gets the string"
    assert "scene" in lcd and "data" not in lcd, "the panel gets the scene"
    assert led["seq"] == lcd["seq"] and led["at"] == lcd["at"], "one cue, one moment"


def test_a_scene_made_of_words_can_still_cross_to_an_led_panel(server, client):
    """A compiled writing scene keeps its `text`, so the same scene has a form
    an LED matrix understands."""
    register(client, "10.0.0.5", kind="led")
    server.load_show(SHOW)
    server.recorder.clear()

    client.get("/play?scene=41")

    assert server.recorder.to("10.0.0.5")[0]["data"] == "hallo"


def test_a_scene_that_is_not_words_is_refused_out_loud(server, client):
    """A symbol has no string form. Saying so beats a panel sitting dark while
    everybody wonders."""
    register(client, "10.0.0.5", kind="led")
    server.load_show(SHOW)
    server.recorder.clear()

    client.get("/play?scene=42")

    assert server.recorder.to("10.0.0.5") == []
    assert any("no text form" in event["message"] for event in server.log.recent(20))


def test_a_ripple_is_not_sent_to_a_matrix_that_has_no_ink(server, client):
    register(client, "10.0.0.5", kind="led")
    register(client, "10.0.0.6", kind="lcd")
    server.load_show(SHOW)
    client.get("/play?scene=41")
    server.recorder.clear()

    client.get("/touch?unit=unit-2&amplitude=16")     # the LCD panel

    assert server.recorder.to("10.0.0.5") == []


# -- the sweep ------------------------------------------------------------


@pytest.mark.parametrize("stagger, expected", [
    ("auto", 3000.0),                 # one full go of the content per unit
    ("tile", 1500.0),                 # one panel width of a two-panel travel
    ("800ms", 800.0),
])
def test_the_effect_route_keeps_the_led_servers_stagger_modes(server, client, stagger, expected):
    for index in range(3):
        register(client, f"10.0.0.{index + 5}")
    server.load_show(SHOW)

    body = client.get(f"/effect?scene=41&stagger={stagger}").get_json()

    assert body["stagger_ms"] == expected
    assert body["stagger_mode"] == stagger
    assert len(body["units"]) == 3


def test_an_effect_holds_the_show_off_while_it_sweeps(server, client):
    """`mementum-led` learned this one first: a cue firing mid-sweep overwrites
    it, and the wall goes to pieces in front of everybody."""
    register(client, "10.0.0.5")
    server.load_show(SHOW)
    client.get("/start")
    client.get("/effect?scene=41&stagger=1s&waves=1")

    assert server.status()["effect_for"] > 0
    before = len(server.sequencer.show_history)
    server.tick()
    assert len(server.sequencer.show_history) == before, "the show waited"


def test_an_effect_needs_something_to_sweep(client):
    register(client, "10.0.0.5")
    assert client.get("/effect").status_code == 400


def test_an_effect_needs_somebody_to_sweep_over(server, client):
    server.load_show(SHOW)
    assert client.get("/effect?scene=41").get_json()["message"] == "No active clients."


# -- reading the wall -----------------------------------------------------


def test_identify_puts_each_unit_s_own_id_on_it(server, client):
    """How `order=` gets written: the wall was hung by a person."""
    for index in range(2):
        register(client, f"10.0.0.{index + 5}")

    body = client.get("/identify?seconds=1").get_json()

    assert body["units"] == ["unit-1", "unit-2"]


def test_an_explicit_order_is_taken_by_id(server, client):
    for index in range(3):
        register(client, f"10.0.0.{index + 5}")
    server.load_show(SHOW)

    body = client.get("/effect?scene=41&stagger=1s&order=3,1").get_json()

    assert body["units"] == ["unit-3", "unit-1"]


def test_two_panels_on_one_host_are_two_panels(client):
    """The LED server keys on IP, which is right when every panel is its own
    device. A simulated wall is sixteen panels on one address, and each is
    still somewhere the server can push to -- so identity is address *and*
    port."""
    register(client, "10.0.0.5", port=8101)
    register(client, "10.0.0.5", port=8102)
    rows = client.get("/clients").get_json()["clients"]

    assert [row["id"] for row in rows] == [1, 2]
    assert {row["ip"] for row in rows} == {"10.0.0.5"}
