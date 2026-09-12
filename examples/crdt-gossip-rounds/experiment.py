# SPDX-License-Identifier: Apache-2.0
"""Sweep `task.config.rounds` on memory_concurrent_writers.

Everything except that one value is the baseline
`scenarios/memory_concurrent_writers.yaml`, including its 10% message loss.

Convergence at a given number of rounds is probabilistic, so each point is a
rate over many seeds rather than a single pass/fail. For the runs that fail, the
script also records the *shape* of the disagreement: how many distinct values the
8 replicas ended up holding, and how many of them were outside the largest group.

Writes `results.png` next to this file. Plotting needs matplotlib::

    uv run --with matplotlib python examples/crdt-gossip-rounds/experiment.py
    uv run --with matplotlib python examples/crdt-gossip-rounds/experiment.py 100
"""

from __future__ import annotations

import asyncio
import collections
import json
import sys
import tempfile
from pathlib import Path

from nest_core.runner import ScenarioRunner
from nest_core.scenario import ScenarioConfig

HERE = Path(__file__).resolve().parent
BASELINE = HERE.parents[1] / "scenarios" / "memory_concurrent_writers.yaml"

ROUNDS = [1, 2, 3, 4, 5, 6, 8, 10, 15, 20]
DROP = 0.1


async def run(rounds: int, seed: int, workdir: Path) -> tuple[int, int]:
    """Run once; return (distinct final states, replicas outside the largest group)."""
    trace = workdir / "t.jsonl"
    config = ScenarioConfig.from_yaml(BASELINE)
    config.task.config["rounds"] = rounds  # <-- the only change
    config.seed = seed
    config.output.trace = str(trace)
    await ScenarioRunner(config).run()

    finals: dict[str, str] = {}
    for line in trace.read_text().splitlines():
        ev = json.loads(line)
        msg = str(ev.get("msg", ""))
        if msg.startswith("final:"):
            finals[str(ev.get("agent", ""))] = msg[len("final:") :]

    held = collections.Counter(json.loads(v)["node"] for v in finals.values())
    sizes = sorted(held.values(), reverse=True)
    return len(held), sum(sizes[1:])


async def main() -> None:
    n_seeds = int(sys.argv[1]) if len(sys.argv) > 1 else 400
    rows: dict[int, tuple[int, int, int]] = {}

    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        print(f"{n_seeds} seeds per point, {DROP:.0%} message loss\n")
        print(
            f"{'rounds':>7} | {'converged':>9} | {'failed':>6} | "
            f"{'max distinct values':>19} | {'worst left behind':>17}"
        )
        print("-" * 76)
        for rounds in ROUNDS:
            ok = worst_states = worst_behind = 0
            for seed in range(1, n_seeds + 1):
                distinct, behind = await run(rounds, seed, workdir)
                if distinct == 1:
                    ok += 1
                else:
                    worst_states = max(worst_states, distinct)
                    worst_behind = max(worst_behind, behind)
            rows[rounds] = (ok, worst_states, worst_behind)
            shown_s = worst_states or "-"
            shown_b = worst_behind or "-"
            print(
                f"{rounds:>7} | {ok / n_seeds:>8.1%} | {n_seeds - ok:>6} | "
                f"{shown_s:>19} | {shown_b:>17}"
            )

    cheapest = min(r for r in ROUNDS if rows[r][0] == n_seeds)
    print(
        f"\ncheapest setting with no failures in {n_seeds} seeds: "
        f"rounds = {cheapest} (default is 20)"
    )

    _plot(rows, n_seeds)


def _plot(rows, n_seeds: int) -> None:
    """Convergence rate against the number of gossip rounds."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("(matplotlib not installed; skipping results.png)")
        return

    xs = sorted(rows)
    rate = [rows[r][0] / n_seeds * 100 for r in xs]

    fig, ax = plt.subplots(figsize=(6, 4))
    ax.plot(xs, rate, "o-")
    ax.set_xlabel("gossip rounds")
    ax.set_ylabel("runs converged (%)")
    ax.set_ylim(0, 105)
    ax.set_xticks(xs)
    ax.grid(alpha=0.3)
    ax.set_title(f"{n_seeds} seeds per point, {DROP:.0%} message loss", fontsize=10)
    fig.tight_layout()

    out = HERE / "results.png"
    fig.savefig(out, dpi=150)
    print(f"wrote {out}")


if __name__ == "__main__":
    asyncio.run(main())
