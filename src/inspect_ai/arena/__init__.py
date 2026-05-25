"""Arena-style pairwise evaluation for inspect_ai.

This module defines the core abstractions used to compose arena-style
evaluation on top of the standard `Task` pipeline:

- `ArenaState`: per-sample storage shared between solver and scorer.
- `Judge` / `JudgeVerdict`: the contract any judging strategy implements.

First-party implementations (`arena_solver`, `llm_judge`, `pairwise_scorer`,
`win_rate`, `elo`) build on these contracts and are added separately.

See https://github.com/UKGovernmentBEIS/inspect_ai/issues/3994 for the
design proposal and rationale.
"""

from ._judge import Judge
from ._state import ArenaState
from ._verdict import JudgeVerdict, Winner

__all__ = [
    "ArenaState",
    "Judge",
    "JudgeVerdict",
    "Winner",
]
