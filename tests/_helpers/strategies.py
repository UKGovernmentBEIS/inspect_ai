"""Hypothesis strategies for retry-timing property tests."""

# pyright: reportAny=false, reportExplicitAny=false, reportUnnecessaryCast=false

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, cast

import pytest

st = cast(Any, pytest.importorskip("hypothesis").strategies)

AttemptOutcome = Literal["success", "fail-retryable", "fail-permanent", "cache"]
CacheState = Literal["hit", "miss-then-write", "miss-then-fail"]


@dataclass(frozen=True)
class RetryScenario:
    """Generated retry-attempt scenario."""

    outcomes: list[AttemptOutcome]
    max_retries: int


@dataclass(frozen=True)
class CacheScenario:
    """Generated cache scenario."""

    state: CacheState
    pre_call_failures: int = 0


def attempt_outcome_sequences(*, min_attempts: int = 1, max_attempts: int = 10) -> Any:
    """Generate retryable prefixes ending in one terminal outcome."""

    def build(prefix_count: int, terminal: AttemptOutcome) -> list[AttemptOutcome]:
        retryable: AttemptOutcome = "fail-retryable"
        outcomes: list[AttemptOutcome] = [retryable for _ in range(prefix_count)]
        outcomes.append(terminal)
        return outcomes

    return st.builds(
        build,
        prefix_count=st.integers(
            min_value=min_attempts - 1, max_value=max_attempts - 1
        ),
        terminal=st.sampled_from(["success", "fail-permanent", "cache"]),
    )


def retry_scenarios() -> Any:
    """Generate retry scenarios with bounded attempt counts."""
    return st.builds(
        RetryScenario,
        outcomes=attempt_outcome_sequences(min_attempts=1, max_attempts=8),
        max_retries=st.integers(min_value=1, max_value=10),
    )


def cache_scenarios() -> Any:
    """Generate cache states for property tests."""
    return st.builds(
        CacheScenario,
        state=st.sampled_from(["hit", "miss-then-write", "miss-then-fail"]),
        pre_call_failures=st.integers(min_value=0, max_value=5),
    )
