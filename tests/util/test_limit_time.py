import asyncio

import pytest

from inspect_ai.util._limit import LimitExceededError, time_limit


def test_validates_limit_parameter() -> None:
    with pytest.raises(ValueError):
        time_limit(-0.1)


@pytest.mark.anyio
async def test_can_create_with_none_limit() -> None:
    with time_limit(None):
        pass


@pytest.mark.anyio
async def test_can_create_with_zero_limit() -> None:
    with pytest.raises(LimitExceededError):
        with time_limit(0):
            await asyncio.sleep(0.1)


@pytest.mark.anyio
async def test_does_not_raise_error_when_limit_not_exceeded() -> None:
    with time_limit(10):
        pass


@pytest.mark.anyio
async def test_raises_error_when_limit_exceeded() -> None:
    with pytest.raises(LimitExceededError) as exc_info:
        with time_limit(0.1) as limit:
            await asyncio.sleep(0.5)

    assert exc_info.value.type == "time"
    assert exc_info.value.value == 0.1
    assert exc_info.value.limit == 0.1
    assert exc_info.value.source is limit


@pytest.mark.anyio
async def test_out_of_scope_limits_are_not_checked() -> None:
    with time_limit(0.1):
        pass

    await asyncio.sleep(0.5)


@pytest.mark.anyio
async def test_outer_limits_are_enforced() -> None:
    with pytest.raises(LimitExceededError) as exc_info:
        with time_limit(0.1):
            with time_limit(10):
                await asyncio.sleep(1)

    assert exc_info.value.value == 0.1


@pytest.mark.anyio
async def test_inner_limits_are_enforced() -> None:
    with pytest.raises(LimitExceededError) as exc_info:
        with time_limit(10):
            with time_limit(0.1):
                await asyncio.sleep(1)

    assert exc_info.value.value == 0.1


@pytest.mark.anyio
async def test_cannot_reuse_context_manager() -> None:
    limit = time_limit(10)
    with limit:
        pass

    with pytest.raises(RuntimeError) as exc_info:
        # Reusing the same Limit instance.
        with limit:
            pass

    assert "Each Limit may only be used once in a single 'with' block" in str(
        exc_info.value
    )


@pytest.mark.anyio
async def test_cannot_reuse_context_manager_in_stack() -> None:
    limit = time_limit(10)

    with pytest.raises(RuntimeError) as exc_info:
        with limit:
            # Reusing the same Limit instance in a stack.
            with limit:
                pass

    assert "Each Limit may only be used once in a single 'with' block" in str(
        exc_info.value
    )
