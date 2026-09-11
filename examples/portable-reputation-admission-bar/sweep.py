# SPDX-License-Identifier: Apache-2.0
"""Sweep the one knob -- `task.config.min_reputation_score` -- on parc_migration.

Everything except that one value is the baseline `scenarios/parc_migration.yaml`.
For each bar the script runs the scenario, reads the gate's `admit:` trace lines,
and prints who got in, who was turned away, and with which reason.

Usage::

    uv run python examples/portable-reputation-admission-bar/sweep.py
    uv run python examples/portable-reputation-admission-bar/sweep.py 42 1 7 123 9999
"""

from __future__ import annotations

import asyncio
import math
import re
import sys
import tempfile
from pathlib import Path

from nest_core.runner import ScenarioRunner
from nest_core.scenario import ScenarioConfig
from nest_core.validators import validate_trace

BASELINE = Path(__file__).resolve().parents[2] / "scenarios" / "parc_migration.yaml"

# 1 - 1/e is where the honest population's recomputed score lands (see README).
CLIFF = 1.0 - math.exp(-1.0)
BARS = [0.0, 0.2, 0.40, 0.60, CLIFF, CLIFF + 1e-9, 0.70, 0.90, 0.99]

ADMIT = re.compile(r"admit:([\w-]+):(granted|denied):(\w+):(\w+)")


Decisions = dict[str, tuple[str, str, str]]
Validators = dict[str, bool]


async def run_one(bar: float, seed: int, workdir: Path) -> tuple[Decisions, Validators]:
    """Run the scenario at one admission bar; return decisions and validator results."""
    trace = workdir / f"bar_{bar:.10f}_seed{seed}.jsonl"
    config = ScenarioConfig.from_yaml(BASELINE)
    config.task.config["min_reputation_score"] = bar  # <-- the only change
    config.seed = seed
    config.output.trace = str(trace)
    await ScenarioRunner(config).run()

    decisions = {m[0]: (m[1], m[2], m[3]) for m in ADMIT.findall(trace.read_text())}
    validators = {r.name: r.passed for r in validate_trace(trace, "parc_migration")}
    return decisions, validators


async def main() -> None:
    seeds = [int(s) for s in sys.argv[1:]] or [42]
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        table: dict[tuple[float, int], tuple[Decisions, Validators]] = {}
        for seed in seeds:
            for bar in BARS:
                table[(bar, seed)] = await run_one(bar, seed, workdir)

        print(f"\nbaseline: {BASELINE}   seeds: {seeds}")
        print(f"honest recomputed score = 1 - 1/e = {CLIFF:.12f}\n")
        head = f"{'bar':>16} | {'honest in':>9} | {'fraud in':>8} | {'pass':>4} | denial reasons"
        print(head)
        print("-" * (len(head) + 30))
        for bar in BARS:
            decisions, validators = table[(bar, seeds[0])]
            honest_in = sum(1 for v in decisions.values() if v[2] == "honest" and v[0] == "granted")
            fraud_in = sum(1 for v in decisions.values() if v[2] != "honest" and v[0] == "granted")
            reasons: dict[str, int] = {}
            for verdict, reason, _role in decisions.values():
                if verdict == "denied":
                    reasons[reason] = reasons.get(reason, 0) + 1
            passed = sum(1 for ok in validators.values() if ok)
            shown = ", ".join(f"{r} x{n}" for r, n in sorted(reasons.items()))
            print(
                f"{bar:>16.10f} | {honest_in:>6}/4   | {fraud_in:>5}/6  | {passed:>2}/6 | {shown}"
            )

        if len(seeds) > 1:
            print("\nseed robustness (honest admitted / fraudulent admitted):")
            for bar in BARS:
                cells = []
                for seed in seeds:
                    decisions, _ = table[(bar, seed)]
                    h = sum(1 for v in decisions.values() if v[2] == "honest" and v[0] == "granted")
                    f = sum(1 for v in decisions.values() if v[2] != "honest" and v[0] == "granted")
                    cells.append(f"s{seed}:{h}/{f}")
                print(f"  bar={bar:<16.10f} " + "  ".join(cells))


if __name__ == "__main__":
    asyncio.run(main())
