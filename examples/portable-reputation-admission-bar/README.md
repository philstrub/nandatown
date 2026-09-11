<!-- SPDX-License-Identifier: Apache-2.0 -->
# How high should a marketplace set the bar for imported reputation?

**Scenario:** `parc_migration` (portable reputation crossing a trust border)
**One setting changed:** `task.config.min_reputation_score`, `0.2` → `0.70`
**Answer:** set it to zero. The bar is not a dial you tune — it is an off switch
for your own honest supply, and it buys exactly zero additional safety.

## The real-life question

Portable reputation is arriving in practice: a driver's rating following them
from one ride-hailing app to another, a seller's history moving off Amazon, an
open-banking credit file, a professional license recognised across state lines.
The receiving platform gets a signed credential saying "this agent scores 0.63"
and has to decide, at the door, whether to let them trade.

So the operator's question is not architectural, it is a product decision made
on a whiteboard in week one: **what is the minimum imported score we accept?**
The instinct is that this is a tuning problem with two sides — set the bar low
and you let in bad actors, set it high and you turn away good newcomers, so
find the sweet spot in the middle. NANDA Town's `parc_migration` scenario is
the right place to check that instinct, because it runs ten migrants through a
real admission gate: four honest, a three-member wash-trading ring, a forger, a
credential thief, an agent with a stale key, and one whose score was inflated
by a corrupt-but-trusted issuer.

`min_reputation_score` is that whiteboard number, and it is the only thing I
changed. Baseline is `scenarios/parc_migration.yaml`, untouched otherwise.

## Hypothesis (written before running)

I expected a **trade-off curve**. Raising the bar from 0.2 should progressively
deny more of the adversarial migrants while costing a few honest ones, giving a
defensible middle value — something like: 0.2 admits everyone, 0.5 starts
denying the weakest fraudsters, 0.8 is overly strict. I predicted the
interesting finding would be *where* the optimum sat, and I guessed around
0.5–0.6.

I was wrong about the shape in both directions, and the reason turned out to be
more interesting than the number.

## What actually happened

`uv run python examples/portable-reputation-admission-bar/sweep.py 42 1 7 123 9999`

|          bar | honest admitted | fraudulent admitted | validators | denial reasons |
|-------------:|----------------:|--------------------:|-----------:|----------------|
| 0.0000000000 |         **4/4** |             **0/6** |        6/6 | `severed_below_threshold` ×3, `proof_invalid`, `score_mismatch`, `replay_presenter_mismatch`, `stale_key` |
| 0.2 *(base)* |         **4/4** |             **0/6** |        6/6 | same as above |
| 0.40         |             4/4 |                 0/6 |        6/6 | same as above |
| 0.60         |             4/4 |                 0/6 |        6/6 | same as above |
| 0.6321205588 |             4/4 |                 0/6 |        6/6 | same as above |
| 0.6321205598 |         **0/4** |                 0/6 |    **4/6** | `below_threshold` ×7, `proof_invalid`, `score_mismatch`, `replay_presenter_mismatch`, `stale_key` |
| 0.70         |             0/4 |                 0/6 |        4/6 | same as above |
| 0.90         |             0/4 |                 0/6 |        4/6 | same as above |
| 0.99         |             0/4 |                 0/6 |        4/6 | same as above |

Identical on all five seeds (42, 1, 7, 123, 9999).

Three things fall out of this, none of which I predicted:

**1. There is no trade-off curve. There is a cliff.** The bar has exactly two
settings: below 0.632120558829 it admits all four honest migrants, above it
admits none. Nothing happens anywhere else in `[0, 1]`. Tuning it is not a
judgement call, it is a coin with one side.

**2. The bar contributes nothing to safety.** The "fraudulent admitted" column
is `0/6` at *every* bar — including `0.0`. All six attacks are already stopped
by verification, not by the score: the forger fails the signature check, the
thief fails presenter binding, the stale credential fails its key-rotation
window, the inflated score fails recomputation against the carried receipts,
and the ring fails whole-graph collusion severance. The score threshold never
catches anyone the gate wasn't already catching. Its entire measurable effect
is on honest supply.

**3. A high bar silently disables the collusion detector.** At the baseline,
the three ring members are denied with `severed_below_threshold` — the verdict
that says *we ran whole-graph analysis on the source domain's published ledger
and found an isolated dense component*. Above the cliff, they are denied with
`below_threshold`: generic, "your number was too small". The gate's code
(`packages/nest-plugins-reference/.../trust/parc.py`) checks
`score < policy.min_reputation_score` **before** it runs severance, so the
threshold short-circuits the analysis. The `parc_ring_severed` validator
catches this and fails — the ring is still kept out, but the platform no longer
*knows why*.

That third point is the one with real operational teeth. A rejected honest
newcomer and a detected fraud ring become indistinguishable in the audit log,
both filed as "score too low". If you ever have to justify a rejection to the
migrant, to a regulator, or to your own fraud team, a high bar has destroyed
the evidence that would let you do it.

## Investigating the cliff: why 0.632120558829?

That constant is 1 − 1/e, which is not the sort of number a simulation produces
by accident, so I traced it. In
`packages/nest-plugins-reference/nest_plugins_reference/trust/agent_receipts.py`:

```python
NORMALIZATION_K = 10.0
DEFAULT_CATEGORY_WEIGHTS = {"purchase": 5.0, "payment_sent": 5.0, ...}

def _normalize(raw: float) -> float:
    return 1.0 - math.exp(-raw / NORMALIZATION_K)
```

Each honest migrant carries two corroborated `purchase` receipts (the scenario
wires them into a directed cycle plus a chord), so `raw = 2 × 5.0 = 10.0`,
which is exactly `NORMALIZATION_K` — giving `1 − e^(−1)`. I confirmed the cliff
sits on the analytic constant rather than near it, to nine decimal places:

```
bar = 0.632120557829  ->  honest admitted: 4/4
bar = 0.632120558829  ->  honest admitted: 4/4      <- 1 - 1/e exactly, still admitted
bar = 0.632120559829  ->  honest admitted: 0/4
```

This is the mechanism behind finding 1, and it generalises well past NANDA Town.
**The score is a saturating function of transaction volume, not a measure of
conduct.** Every migrant with a clean two-purchase history scores 0.632 —
and so does every member of the wash-trading ring, because wash trades are
*also* corroborated purchases. The score literally cannot tell the honest
population from the fraud ring; only the graph structure can.

Which means a bar above 0.632 is not asking "are you trustworthy?" It is asking
"have you done more than two transactions?" It filters on tenure and volume.
Every honest newcomer fails it by construction, no matter how spotless they are
— which is precisely the cold-start problem that portable reputation was
supposed to solve. And because the curve is asymptotic, a bar of 1.0 is
unreachable by anyone, forever.

## What I would tell the operator

- **Set `min_reputation_score` to 0. It is doing no work.** Your six defences
  are verification, recomputation and graph severance — keep spending there.
- **A score bar on a saturating volume metric is a tenure gate wearing a safety
  costume.** If you want to throttle newcomers, do it explicitly (probation
  limits, escrow, staged caps) so you can see and defend the policy, rather
  than hiding it inside a number nobody can interpret.
- **Never let a cheap check short-circuit an expensive one that produces the
  audit reason.** Reordering those two lines in the gate would keep the
  collusion verdict intact at any bar, at the cost of one graph pass.
- **A percentage-shaped knob is not necessarily a linear one.** "0.7 out of 1.0"
  reads like 70% of the way to strict. It is actually past the end of the scale.

## Reproducing

```bash
uv sync

# baseline
uv run nest run scenarios/parc_migration.yaml -o traces/parc_baseline.jsonl

# this experiment (min_reputation_score: 0.70)
uv run nest run examples/portable-reputation-admission-bar/scenario.yaml \
  -o traces/parc_bar070.jsonl

# the full sweep + five-seed robustness table
uv run python examples/portable-reputation-admission-bar/sweep.py 42 1 7 123 9999

# validator verdicts for either trace
uv run python -c "
from pathlib import Path
from nest_core.validators import validate_trace
for r in validate_trace(Path('traces/parc_bar070.jsonl'), 'parc_migration'):
    print(('PASS' if r.passed else 'FAIL'), r.name, '-', r.detail)
"
```

Traces are gitignored, so only `scenario.yaml`, `sweep.py` and this README are
committed. Runs are deterministic: same seed, same trace.

## Use of AI and other help

I used Claude Code (Opus 5) for this task, and it did most of the work. Being
specific about the split, because it matters for reading the rest of this:

- **Mine:** the brief. I asked for an experiment that was different from what
  the other open PRs had already done, and that answered a practical question
  rather than a technical one. Steering it away from a "the knob is inert"
  write-up (several PRs already have one) toward *why* the metric underneath
  cannot work was the call I made.
- **Claude's:** surveying the ~165 open PRs to establish that they cluster on
  `message_drop`, `byzantine_agents`, `rounds` and quorum/threshold across six
  scenarios; finding that `min_reputation_score` on `parc_migration` was
  untouched; writing `sweep.py`; tracing the 0.632 constant back to
  `_normalize` and `DEFAULT_CATEGORY_WEIGHTS`; and spotting that the threshold
  check runs before severance in the gate.
- **What changed my mind mid-way:** the trade-off-curve hypothesis in the
  section above was the honest starting expectation, and `0/6` fraudulent
  admitted at *every* bar — including 0.0 — looked at first like a broken
  sweep rather than a result. Reading the gate's check ordering is what turned
  the apparent null into findings 2 and 3. The takeaway I am keeping is that
  "the setting did nothing" was the finding, and the work worth doing was
  establishing why it *could* do nothing.

No results in this README are hand-written: every number comes from the sweep
output above, reproducible with the commands in the previous section.
