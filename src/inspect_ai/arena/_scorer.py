from collections import defaultdict
from itertools import combinations

from inspect_ai.scorer import Score, Scorer, Target, scorer
from inspect_ai.solver import TaskState
from inspect_ai.util import collect

from ._judge import Judge
from ._metrics import elo, win_rate
from ._state import ArenaState


@scorer(metrics=[win_rate(), elo()])
def pairwise_scorer(judge: Judge) -> Scorer:
    """Generate pairwise comparisons across contestants and run the judge.

    Reads contestant responses from `ArenaState` (populated by `arena_solver`),
    constructs all N×(N−1)/2 unordered pairs of non-failed contestants, and
    awaits the judge on each pair concurrently.

    Each sample's `Score.value` is `{contestant_name: win_points}` — each
    contestant's contribution to this sample (1.0 per win, 0.5 per tie). The
    full structured list of verdicts is preserved on `Score.metadata` under
    the `"comparisons"` key for downstream metrics to consume:

        metadata = {
            "comparisons": [
                {"a": "<name_a>", "b": "<name_b>", "winner": "a"|"b"|"tie"},
                ...
            ],
            "failed": ["<contestant>", ...],
        }
    """

    async def score(state: TaskState, target: Target) -> Score:
        arena = state.store_as(ArenaState)
        names = list(arena.responses.keys())

        if len(names) < 2:
            return Score(
                value={name: 0.0 for name in names},
                metadata={"comparisons": [], "failed": list(arena.failed)},
                explanation="Fewer than 2 successful contestants; no pairs to judge.",
            )

        prompt = state.input_text
        pairs = list(combinations(names, 2))

        verdicts = await collect(
            *(judge(prompt, arena.responses[a], arena.responses[b]) for a, b in pairs)
        )

        comparisons = [
            {"a": a, "b": b, "winner": v.winner} for (a, b), v in zip(pairs, verdicts)
        ]

        points: dict[str, float] = defaultdict(float)
        for cmp in comparisons:
            a, b, winner = cmp["a"], cmp["b"], cmp["winner"]
            if winner == "a":
                points[a] += 1.0
            elif winner == "b":
                points[b] += 1.0
            else:
                points[a] += 0.5
                points[b] += 0.5
        # Ensure every contestant appears in value even with no wins.
        value: dict[str, float] = {name: points[name] for name in names}

        return Score(
            value=value,
            metadata={
                "comparisons": comparisons,
                "failed": list(arena.failed),
            },
        )

    return score
