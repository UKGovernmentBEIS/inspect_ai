"""Regression tests for TaskState limit setters pushing control-channel state.

Setting a limit below current usage raises ``LimitExceededError`` — the push
of the new ceiling to the active sample (what the control channel reports)
must happen before that check, or a tripping check hides the new limit.
Same ordering family as the cost-charging fix in ``record_and_check_model_usage``.
"""

from types import SimpleNamespace

import pytest

from inspect_ai.log._samples import _sample_active
from inspect_ai.model import ModelUsage
from inspect_ai.solver import TaskState
from inspect_ai.util._limit import (
    LimitExceededError,
    record_model_cost,
    record_model_usage,
)


def _state(**kwargs: object) -> TaskState:
    return TaskState(
        model="mockllm/model",
        sample_id="s1",
        epoch=1,
        input="hi",
        messages=[],
        **kwargs,  # type: ignore[arg-type]
    )


def test_cost_limit_setter_pushes_ceiling_even_when_check_trips() -> None:
    """The new ceiling reaches the control channel even when the check trips.

    Lowering the cost ceiling below current usage raises, but the control
    channel must still see the new ceiling — the check must not skip the push.
    """
    active = SimpleNamespace(cost_limit=None)
    _sample_active.set(active)
    try:
        state = _state(cost_limit=5.0)
        with state._cost_limit:
            record_model_cost(3.0)

            with pytest.raises(LimitExceededError) as exc_info:
                state.cost_limit = 1.0

            assert exc_info.value.type == "cost"
            # the new ceiling reached the control channel despite the raise
            assert active.cost_limit == 1.0
    finally:
        _sample_active.set(None)


def test_token_limit_setter_pushes_group_even_when_check_trips() -> None:
    """Pin the token setter's ordering.

    Ceiling, type and usage are pushed before the check, so a tripping check
    cannot hide the new limit.
    """
    active = SimpleNamespace(
        token_limit=None, token_limit_type=None, token_limit_usage=None
    )
    _sample_active.set(active)
    try:
        state = _state(token_limit=5000)
        with state._token_limit:
            record_model_usage(ModelUsage(total_tokens=900))

            with pytest.raises(LimitExceededError) as exc_info:
                state.token_limit = 100

            assert exc_info.value.type == "token"
            assert active.token_limit == 100
            assert active.token_limit_type == "all"
            assert active.token_limit_usage is not None
    finally:
        _sample_active.set(None)
