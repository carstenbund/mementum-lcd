"""Scenarios -- scripted, deterministic, and asserted at buffer level.

Skew, drift, missed commands, leader change and late join stop being things you
induce with Wi-Fi load and become things you write down. Each scenario returns a
:class:`ScenarioResult` so the same code serves both the test suite and the CLI
tools (``python -m sim.scenarios.late_join``).
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from typing import Any

__all__ = ["NAMES", "ScenarioResult", "run"]

NAMES = (
    "basic_play",
    "late_join",
    "missed_command",
    "leader_change",
    "clock_jitter",
    "fanout_scale",
    "mixed_renderers",
)


@dataclass
class ScenarioResult:
    name: str
    harness: Any
    checks: list[tuple[str, bool, str]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    def check(self, description: str, passed: bool, detail: str = "") -> bool:
        self.checks.append((description, bool(passed), detail))
        return bool(passed)

    @property
    def passed(self) -> bool:
        return all(ok for _, ok, _ in self.checks)

    def assert_passed(self) -> "ScenarioResult":
        failed = [f"{desc}: {detail}" for desc, ok, detail in self.checks if not ok]
        if failed:
            raise AssertionError(f"scenario {self.name} failed:\n  " + "\n  ".join(failed))
        return self

    def report(self) -> str:
        lines = [f"scenario: {self.name}"]
        for description, ok, detail in self.checks:
            mark = "PASS" if ok else "FAIL"
            lines.append(f"  [{mark}] {description}" + (f" -- {detail}" if detail else ""))
        for key, value in sorted(self.metrics.items()):
            lines.append(f"  {key}: {value}")
        lines.append(f"  => {'PASSED' if self.passed else 'FAILED'}")
        return "\n".join(lines)


def run(name: str, **kwargs) -> ScenarioResult:
    if name not in NAMES:
        raise KeyError(f"unknown scenario: {name!r} (have {', '.join(NAMES)})")
    module = importlib.import_module(f"{__name__}.{name}")
    return module.run(**kwargs)


def main(argv=None) -> int:  # pragma: no cover - CLI
    import argparse

    parser = argparse.ArgumentParser(description="run simulation scenarios")
    parser.add_argument("scenario", nargs="?", default="all", choices=("all",) + NAMES)
    args = parser.parse_args(argv)
    names = NAMES if args.scenario == "all" else (args.scenario,)
    failures = 0
    for name in names:
        result = run(name)
        print(result.report())
        failures += 0 if result.passed else 1
    return 1 if failures else 0


if __name__ == "__main__":  # pragma: no cover - CLI
    raise SystemExit(main())
