import contextlib
from contextvars import ContextVar

from inspect_ai.log._log import EvalStats

_active_eval_stats: ContextVar[EvalStats | None] = ContextVar(
    "_active_eval_stats", default=None
)


def active_eval_stats() -> EvalStats | None:
    return _active_eval_stats.get(None)


def set_active_eval_stats(stats: EvalStats) -> None:
    _active_eval_stats.set(stats)
