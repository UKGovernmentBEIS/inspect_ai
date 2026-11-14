"""Arena-style pairwise evaluation for inspect_ai.

This module defines the core abstractions used to compose arena-style
evaluation on top of the standard `Task` pipeline:

- `ArenaState`: per-sample storage shared between solver and scorer.
- `Judge` / `JudgeVerdict`: the contract any judging strategy implements.

It also ships first-party implementations that plug into the standard
`Task` slots:

- `arena_solver`: fans out to multiple contestants on the same input.
- `llm_judge`: model-backed `Judge` with position-bias controls.
- `pairwise_scorer`: generates all pairs and runs the judge.
- `win_rate`, `elo`: metrics that aggregate pairwise verdicts.

See https://github.com/UKGovernmentBEIS/inspect_ai/issues/3994 for the
design proposal and rationale.
"""

from ._judge import Judge
from ._llm_judge import (
    DEFAULT_JUDGE_INSTRUCTIONS,
    DEFAULT_JUDGE_TEMPLATE,
    DEFAULT_VERDICT_PATTERN,
    llm_judge,
)
from ._metrics import elo, win_rate
from ._scorer import pairwise_scorer
from ._solver import arena_solver
from ._state import ArenaState
from ._verdict import JudgeVerdict, Winner

__all__ = [
    "ArenaState",
    "DEFAULT_JUDGE_INSTRUCTIONS",
    "DEFAULT_JUDGE_TEMPLATE",
    "DEFAULT_VERDICT_PATTERN",
    "Judge",
    "JudgeVerdict",
    "Winner",
    "arena_solver",
    "elo",
    "llm_judge",
    "pairwise_scorer",
    "win_rate",
]
