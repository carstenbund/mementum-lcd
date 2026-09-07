"""Phase 0c -- the simulation harness (implementation plan §3).

The rule this package exists to obey:

    The simulated node runs the **real** participant core. Only the clock, the
    transport and the sink are substituted.

So `sim/` contains a virtual clock, an in-process transport, node assembly and
scenarios -- and nothing else. Any protocol logic, evaluation or rendering that
appears here is a bug in the layering, not a feature of the simulator
(risk R11). A simulator that reimplements the protocol proves nothing.

What this buys and what it cannot answer is §3.3 and §3.4: numbers measured
here are *design* properties. A number measured on hardware is a physical one,
and a simulated number never satisfies a hardware gate.
"""
