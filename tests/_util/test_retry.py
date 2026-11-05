import warnings
from typing import Any, cast

import pytest
from tenacity import RetryCallState, wait_exponential_jitter
from tenacity.wait import WaitBaseT

from inspect_ai._util.retry import backoff_multiplier
from inspect_ai.model._retry import model_retry_config


def _waits(wait: WaitBaseT, attempts: int) -> list[float]:
    """Wait computed after each of attempts 1..`attempts`."""
    state = RetryCallState(cast(Any, None), None, (), {})
    waits: list[float] = []
    for attempt in range(1, attempts + 1):
        state.attempt_number = attempt
        waits.append(wait(state))
    return waits


@pytest.mark.parametrize(
    ("multiplier", "kwargs", "expected"),
    [
        pytest.param(
            3,
            {"max": 30 * 60},
            [3, 6, 12, 24, 48, 96, 192, 384, 768, 1536, 1800, 1800],
            id="model-retry",
        ),
        pytest.param(2, {}, [2, 4, 8, 16, 32], id="exec-remote-poll"),
    ],
)
def test_backoff_multiplier_waits_without_warning(
    multiplier: float, kwargs: dict[str, float], expected: list[float]
) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        wait = wait_exponential_jitter(
            **backoff_multiplier(multiplier), **kwargs, jitter=0
        )
    assert _waits(wait, len(expected)) == expected


@pytest.mark.real_retry_wait
def test_model_retry_default_wait_without_warning() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        config = model_retry_config(
            "m",
            None,
            None,
            lambda ex: True,
            lambda ex: None,
            lambda name, rs: None,
        )
    # 3s doubling capped at 30 minutes, plus up to 3s of jitter
    for attempt, wait in enumerate(_waits(config["wait"], 12), start=1):
        base = min(3 * 2 ** (attempt - 1), 30 * 60)
        assert base <= wait <= min(base + 3, 30 * 60)
