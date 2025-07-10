"""Tests for run_in_background function."""

import asyncio

import anyio
import pytest

from inspect_ai._util._async import run_in_background
from inspect_ai._util.eval_task_group import _eval_task_group, init_eval_task_group


class TestRunInBackground:
    """Test cases for run_in_background function."""

    @pytest.mark.asyncio
    async def test_with_task_group(self):
        """Test run_in_background when task group is set."""
        # Save original state
        original_tg = _eval_task_group

        try:
            result = []

            async def background_task(value: str) -> None:
                result.append(value)

            # Test with a real task group
            async with anyio.create_task_group() as tg:
                init_eval_task_group(tg)
                run_in_background(background_task, "with_tg")
                # Task group waits for completion when exiting

            assert result == ["with_tg"]

        finally:
            init_eval_task_group(original_tg)

    @pytest.mark.asyncio
    async def test_without_task_group_fallback_to_asyncio(self):
        """Test run_in_background falls back to asyncio when no task group is set."""
        # Save original state
        original_tg = _eval_task_group

        try:
            # Clear task group
            init_eval_task_group(None)

            result = []

            async def background_task(value: str) -> None:
                await asyncio.sleep(0.05)  # Small delay to simulate work
                result.append(value)

            # This should work by falling back to asyncio.create_task()
            run_in_background(background_task, "asyncio_fallback")

            # Give background task time to complete
            await asyncio.sleep(0.1)

            assert result == ["asyncio_fallback"]

        finally:
            init_eval_task_group(original_tg)

    def test_trio_backend_raises_error(self):
        """Test that trio backend raises RuntimeError."""
        from unittest.mock import patch

        # Save original state
        original_tg = _eval_task_group

        try:
            init_eval_task_group(None)

            with patch(
                "inspect_ai._util._async.current_async_backend", return_value="trio"
            ):

                async def test_func() -> None:
                    pass

                with pytest.raises(
                    RuntimeError, match="run_coroutine cannot be used with trio"
                ):
                    run_in_background(test_func)
        finally:
            init_eval_task_group(original_tg)

    def test_no_async_context_raises_error(self):
        """Test that running outside async context raises RuntimeError."""
        from unittest.mock import patch

        # Save original state
        original_tg = _eval_task_group

        try:
            init_eval_task_group(None)

            with patch(
                "inspect_ai._util._async.current_async_backend", return_value=None
            ):

                async def test_func() -> None:
                    pass

                with pytest.raises(
                    RuntimeError,
                    match="run_coroutine cannot be used.*outside of an async context",
                ):
                    run_in_background(test_func)
        finally:
            init_eval_task_group(original_tg)

    @pytest.mark.asyncio
    async def test_argument_passing(self):
        """Test that arguments are passed correctly to the background function."""
        original_tg = _eval_task_group

        try:
            init_eval_task_group(None)
            result = []

            async def background_task(a: int, b: str, c: bool) -> None:
                result.append((a, b, c))

            run_in_background(background_task, 42, "hello", True)

            await asyncio.sleep(0.05)
            assert result == [(42, "hello", True)]

        finally:
            init_eval_task_group(original_tg)
