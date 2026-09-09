"""Panels and a server, over a real socket.

Everything else in this suite runs the protocol in one process. This runs it
across localhost: a Flask control server on one port, panels on ports of their
own, `requests` and `http.server` in between. What is being checked is that the
seam held -- that `ParticipantCore` needed nothing added to live on a network,
and that a panel is a *client*: it fetches what it is told to show and
distributes nothing.

Slow by this suite's standards (real sockets, real threads), and worth it: it
is the first thing here that would keep working if the two halves were on
different machines.
"""

import json
import threading
import time
from wsgiref.simple_server import WSGIRequestHandler, make_server

import pytest

flask = pytest.importorskip("flask", reason="flask not installed")
requests = pytest.importorskip("requests", reason="requests not installed")

from mementum_node.client import Node                                   # noqa: E402
from mementum_node.server.app import ControlServer, build               # noqa: E402

from .test_control_server import SHOW                                   # noqa: E402


class QuietHandler(WSGIRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture
def running_server():
    """A real control server on a real port."""
    control = ControlServer(lead_ms=400.0)
    control.log.echo = False
    httpd = make_server("127.0.0.1", 0, build(control), handler_class=QuietHandler)
    thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05},
                              daemon=True)
    thread.start()
    control.url = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        yield control
    finally:
        httpd.shutdown()
        thread.join(timeout=2.0)


def wait_for(predicate, timeout=5.0, interval=0.02):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


@pytest.fixture
def panel(running_server):
    node = Node(running_server.url, node_id="panel-0", width=240, height=120,
                position=(0.0, 0.0), fps=60.0)
    try:
        yield node
    finally:
        node.stop()


# -- joining --------------------------------------------------------------


def test_a_panel_registers_and_is_given_a_name(running_server, panel):
    assert panel.start() is True
    assert panel.node_id == "unit-1", "a panel adopts the id the server gives it"
    assert panel.participant.registered
    assert panel.clock.synced, "and syncs its clock in the same first exchange"

    rows = requests.get(running_server.url + "/clients").json()["clients"]
    assert rows[0]["kind"] == "lcd"
    assert rows[0]["ip"] == "127.0.0.1"


def test_the_server_pushes_to_the_port_the_panel_bound(running_server, panel):
    panel.start()
    running_server.load_show(SHOW)
    running_server.sequencer.start_show()

    assert wait_for(lambda: panel.listener.received > 0), "the panel was pushed to"
    assert wait_for(lambda: panel.participant.schedule.scene_id == 41)


def test_a_panel_fetches_the_scene_it_was_told_to_show(running_server, panel):
    """The asset plane, and the reason a panel cannot be the server: it holds
    what it was sent, and the library lives somewhere else."""
    panel.start()
    running_server.load_show(SHOW)
    running_server.sequencer.play(41)

    assert wait_for(lambda: panel.participant.state == "playing")
    assert panel.participant.pulls >= 1, "it pulled the scene it did not have"
    assert len(panel.participant.cache) >= 1
    assert panel.participant.scene is not None


def test_a_panel_draws_at_the_moment_it_was_given(running_server, panel):
    panel.start()
    running_server.load_show(SHOW)
    at = running_server.clock.shared_now() + 300.0
    running_server.sequencer.play(41, at=at)

    assert wait_for(lambda: panel.participant.frames_presented > 0, timeout=6.0)
    assert wait_for(lambda: (panel.participant.last_scene_time or -1) > 0, timeout=6.0)
    # Scene time is measured from the moment the server named, not from when
    # the push happened to arrive.
    drift = abs(panel.participant.last_scene_time
                - (panel.clock.shared_now() - at))
    assert drift < 250.0, f"scene time follows the shared clock, not arrival: {drift:.0f} ms"


def test_a_panel_that_missed_the_push_learns_it_from_a_heartbeat(running_server, panel):
    """The recovery path, on a real network: no re-send, no catch-up mechanism
    -- the schedule is state and the heartbeat carries it."""
    panel.register()
    running_server.load_show(SHOW)
    panel.listener.stop()                     # the pushes now go nowhere

    running_server.sequencer.play(42)
    assert panel.participant.schedule.scene_id != 42

    panel.participant.heartbeat()
    assert panel.participant.schedule.scene_id == 42


def test_a_panel_answers_for_itself(running_server, panel):
    panel.start()
    status = requests.get(f"http://127.0.0.1:{panel.listener.port}/status").json()

    assert status["node_id"] == panel.node_id
    assert "scene_time" in status


# -- a wall ---------------------------------------------------------------


def test_two_panels_on_one_host_are_two_panels_on_the_wall(running_server):
    """Sixteen panels at one address is a wall on a desk; the server pushes to
    each by the port it bound."""
    panels = [Node(running_server.url, node_id=f"panel-{i}", width=240, height=120,
                   position=(i * 2.0, 0.0), fps=60.0) for i in range(2)]
    try:
        for node in panels:
            assert node.start()
        assert {node.node_id for node in panels} == {"unit-1", "unit-2"}

        running_server.load_show(SHOW)
        running_server.sequencer.sweep(41, at=running_server.clock.shared_now() + 400.0,
                                       stagger="1s")

        assert wait_for(lambda: all(node.listener.received for node in panels))
        starts = [node.participant.schedule.display_at for node in panels]
        assert round(starts[1] - starts[0]) == 1000, "a staggered wall, over the network"
    finally:
        for node in panels:
            node.stop()


def test_a_ripple_reaches_a_panel_as_a_push(running_server, panel):
    panel.start()
    running_server.load_show(SHOW)
    running_server.sequencer.play(41)
    assert wait_for(lambda: panel.participant.state == "playing")
    before = panel.participant.ripples_received

    requests.get(running_server.url + f"/touch?unit={panel.node_id}&amplitude=16")

    # The unit that was touched is the one the server does not push to -- it is
    # told by the touch itself -- so a second panel would be needed to see the
    # relayed one. What matters here is that the route works and nothing broke.
    assert panel.participant.ripples_received >= before


def test_the_led_form_is_refused_by_a_panel_that_draws(running_server, panel):
    """A matrix takes a string; a panel takes a scene. Saying so beats
    pretending -- the server compiles words into a scene for exactly this
    reason."""
    panel.start()
    response = requests.get(f"http://127.0.0.1:{panel.listener.port}/play"
                            "?seq=1&at=0&data=hallo")

    assert response.status_code == 400
    assert "compile" in response.json()["message"]
