"""The rule that makes the simulator worth anything (plan §3.2, risk R11).

    The simulated node runs the **real** participant core. Only the clock, the
    transport and the sink are substituted.

A simulator that reimplements the protocol proves nothing, and logic that drifts
into ``sim/`` stops being tested in the real path. This test is the tripwire:
it checks the dependency direction, that a simulated node is assembled from the
real classes, and that nothing in ``sim/`` has quietly grown a second copy of
something the core already owns.
"""

import ast
import importlib
import os
import pkgutil

import pytest

import mementum_node
import sim
from mementum_node.core.clock import CristianClock
from mementum_node.core.participant import ParticipantCore
from mementum_node.core.sequencer import Sequencer
from mementum_node.core.sink import HeadlessSink, NullSink
from sim.harness import Harness

SIM_ROOT = os.path.dirname(os.path.abspath(sim.__file__))
CORE_ROOT = os.path.dirname(os.path.abspath(mementum_node.__file__))

#: Names ``sim/`` may legitimately define despite the core owning the concept:
#: none today, and adding one should require an argument.
ALLOWED_SHADOWS: set[str] = set()


def _python_files(root):
    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            if name.endswith(".py"):
                yield os.path.join(dirpath, name)


def _core_public_names():
    names = set()
    for module_info in pkgutil.walk_packages([CORE_ROOT], "mementum_node."):
        module = importlib.import_module(module_info.name)
        for name in getattr(module, "__all__", ()):
            names.add(name)
    return names


def test_a_simulated_node_is_the_real_core():
    harness = Harness()
    node = harness.add_node("node-a")
    assert type(node.core) is ParticipantCore
    assert type(harness.sequencer) is Sequencer
    # ... with exactly three substitutions.
    assert type(node.clock) is CristianClock          # clock: real class, virtual source
    assert type(node.sink) in (HeadlessSink, NullSink)  # sink: headless buffer
    assert type(node.transport).__module__.startswith("sim.")  # transport: in-process


def test_simulated_and_real_nodes_share_one_implementation():
    """Nothing in the participant core knows the simulator exists."""
    for module_path in _python_files(CORE_ROOT):
        with open(module_path, "r", encoding="utf-8") as fh:
            source = fh.read()
        assert "import sim" not in source, f"{module_path} depends on the simulator"
        assert "from sim" not in source, f"{module_path} depends on the simulator"


def test_sim_does_not_redefine_what_the_core_owns():
    core_names = _core_public_names()
    offences = []
    for module_path in _python_files(SIM_ROOT):
        with open(module_path, "r", encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), module_path)
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if node.name in core_names and node.name not in ALLOWED_SHADOWS:
                    offences.append(f"{os.path.relpath(module_path, SIM_ROOT)}:{node.name}")
    assert not offences, (
        "sim/ redefines core concepts -- move them back into the participant "
        f"core (plan §3.2): {offences}"
    )


@pytest.mark.parametrize(
    "forbidden",
    ["def evaluate", "def render_scene", "def ease", "class Schedule", "class Scene"],
)
def test_sim_contains_no_second_implementation(forbidden):
    for module_path in _python_files(SIM_ROOT):
        with open(module_path, "r", encoding="utf-8") as fh:
            assert forbidden not in fh.read(), f"{module_path} reimplements {forbidden!r}"


def test_the_simulator_touches_only_three_seams():
    """``sim/`` may import anything from the core, but the modules it *stands
    in for* are exactly the clock, the transport and the sink."""
    substituted = {"sim.clock", "sim.transport", "sim.node"}
    modules = {f"sim.{n}" for _, n, _ in pkgutil.iter_modules([SIM_ROOT])}
    assert substituted <= modules
    assert modules >= {"sim.harness", "sim.assert_sync", "sim.capture", "sim.wall"}
