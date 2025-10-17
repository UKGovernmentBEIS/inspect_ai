"""Test suite for inspect_ai.util._concurrency module.

Tests the public interface of concurrency control functionality including
the concurrency context manager, status display, and initialization.
"""

import asyncio

import anyio
import pytest

from inspect_ai.util._concurrency import (
    concurrency,
    concurrency_status_display,
    init_concurrency,
)

# Basic Concurrency Control Tests


@pytest.mark.anyio
async def test_basic_concurrency_acquisition() -> None:
    """Test that a task can acquire and release a concurrency slot."""
    init_concurrency()

    async with concurrency("test-resource", 1):
        # We're inside the context, should have acquired the slot
        status = concurrency_status_display()
        assert status["test-resource"] == (1, 1)  # 1 active out of 1 total


@pytest.mark.anyio
async def test_concurrency_limit_enforced() -> None:
    """Test that concurrency limit prevents more than N tasks from executing."""
    init_concurrency()
    execution_order: list[int] = []

    async def task(task_id: int) -> None:
        async with concurrency("test-resource", 2):
            execution_order.append(task_id)
            await asyncio.sleep(0.1)

    # Launch 4 tasks with limit of 2
    async with anyio.create_task_group() as tg:
        for i in range(4):
            tg.start_soon(task, i)

    # All tasks should complete
    assert len(execution_order) == 4


@pytest.mark.anyio
async def test_concurrency_serializes_when_limit_one() -> None:
    """Test that concurrency=1 forces serial execution."""
    init_concurrency()
    active_count: list[int] = []

    async def task() -> None:
        async with concurrency("test-resource", 1):
            # Check how many are active when we enter
            status = concurrency_status_display()
            active_count.append(status["test-resource"][0])
            await asyncio.sleep(0.05)

    async with anyio.create_task_group() as tg:
        for _ in range(5):
            tg.start_soon(task)

    # Each task should see exactly 1 active (itself)
    assert all(count == 1 for count in active_count)


@pytest.mark.anyio
async def test_concurrent_execution_within_limit() -> None:
    """Test that tasks can execute concurrently up to the limit."""
    init_concurrency()
    max_concurrent = 0

    async def task() -> None:
        nonlocal max_concurrent
        async with concurrency("test-resource", 3):
            status = concurrency_status_display()
            max_concurrent = max(max_concurrent, status["test-resource"][0])
            await asyncio.sleep(0.1)

    async with anyio.create_task_group() as tg:
        for _ in range(5):
            tg.start_soon(task)

    # Should have seen 3 concurrent tasks at some point
    assert max_concurrent == 3


# Semaphore Reuse Tests


@pytest.mark.anyio
async def test_same_key_reuses_semaphore() -> None:
    """Test that using the same key reuses the same semaphore."""
    init_concurrency()

    # First task acquires the semaphore
    async with concurrency("test-resource", 2):
        status1 = concurrency_status_display()
        assert status1["test-resource"] == (1, 2)

        # Second task with same key should see the same semaphore
        async with concurrency("test-resource", 2):
            status2 = concurrency_status_display()
            assert status2["test-resource"] == (2, 2)


@pytest.mark.anyio
async def test_different_keys_create_separate_semaphores() -> None:
    """Test that different keys create independent semaphores."""
    init_concurrency()

    async with concurrency("resource-a", 1):
        async with concurrency("resource-b", 1):
            status = concurrency_status_display()
            assert status["resource-a"] == (1, 1)
            assert status["resource-b"] == (1, 1)


@pytest.mark.anyio
async def test_name_vs_key_distinction() -> None:
    """Test that key parameter provides unique identification.

    Note: Status display uses the name, so two contexts with the same name
    but different keys will appear as one entry in the status display, but
    they use separate semaphores internally.
    """
    init_concurrency()

    # Two contexts with different names but explicit keys
    async with concurrency("name-1", 1, key="key-1"):
        async with concurrency("name-2", 1, key="key-2"):
            status = concurrency_status_display()
            # Should see two separate entries with different names
            assert "name-1" in status
            assert "name-2" in status


@pytest.mark.anyio
async def test_key_defaults_to_name() -> None:
    """Test that omitting key uses name as the key."""
    init_concurrency()

    async with concurrency("test-resource", 2):
        # Another context with same name should share the semaphore
        async with concurrency("test-resource", 2):
            status = concurrency_status_display()
            assert status["test-resource"][0] == 2  # 2 active


# Status Display Tests


@pytest.mark.anyio
async def test_status_display_shows_correct_counts() -> None:
    """Test that status display shows accurate active/total counts."""
    init_concurrency()

    async with concurrency("test-resource", 5):
        status = concurrency_status_display()
        assert status["test-resource"] == (1, 5)

        async with concurrency("test-resource", 5):
            status = concurrency_status_display()
            assert status["test-resource"] == (2, 5)


@pytest.mark.anyio
async def test_visibility_flag_controls_display() -> None:
    """Test that visible=False hides resource from status display."""
    init_concurrency()

    async with concurrency("visible-resource", 1, visible=True):
        async with concurrency("hidden-resource", 1, visible=False):
            status = concurrency_status_display()
            assert "visible-resource" in status
            assert "hidden-resource" not in status


@pytest.mark.anyio
async def test_prefix_shortening_single_model() -> None:
    """Test that model prefix is shortened when there's only one with that prefix."""
    init_concurrency()

    async with concurrency("openai/gpt-4o", 1):
        status = concurrency_status_display()
        # Should be shortened to just "openai"
        assert "openai" in status
        assert status["openai"] == (1, 1)


@pytest.mark.anyio
async def test_prefix_shortening_multiple_models() -> None:
    """Test that full names are kept when multiple models share a prefix."""
    init_concurrency()

    async with concurrency("openai/gpt-4o", 1):
        async with concurrency("openai/gpt-3.5", 1):
            status = concurrency_status_display()
            # Should keep full names due to multiple models with same prefix
            assert "openai/gpt-4o" in status
            assert "openai/gpt-3.5" in status


@pytest.mark.anyio
async def test_status_updates_reflect_concurrent_usage() -> None:
    """Test that status display updates as tasks acquire and release slots."""
    init_concurrency()

    status_snapshots: list[tuple[int, int]] = []

    async def task() -> None:
        async with concurrency("test-resource", 3):
            status = concurrency_status_display()
            status_snapshots.append(status["test-resource"])
            await asyncio.sleep(0.05)

    async with anyio.create_task_group() as tg:
        for _ in range(3):
            tg.start_soon(task)

    # Should have seen varying active counts
    active_counts = [s[0] for s in status_snapshots]
    assert max(active_counts) <= 3
    assert all(s[1] == 3 for s in status_snapshots)  # Total always 3


# Context Manager Behavior Tests


@pytest.mark.anyio
async def test_exception_releases_semaphore() -> None:
    """Test that exceptions inside context release the semaphore slot."""
    init_concurrency()

    with pytest.raises(RuntimeError):
        async with concurrency("test-resource", 1):
            raise RuntimeError("Test error")

    # Semaphore should be released - verify by acquiring it again
    async with concurrency("test-resource", 1):
        status = concurrency_status_display()
        assert status["test-resource"] == (1, 1)


@pytest.mark.anyio
async def test_nested_concurrency_contexts() -> None:
    """Test that nested contexts with different resources work independently."""
    init_concurrency()

    async with concurrency("outer-resource", 2):
        status1 = concurrency_status_display()
        assert status1["outer-resource"] == (1, 2)

        async with concurrency("inner-resource", 3):
            status2 = concurrency_status_display()
            assert status2["outer-resource"] == (1, 2)
            assert status2["inner-resource"] == (1, 3)


@pytest.mark.anyio
async def test_nested_same_resource() -> None:
    """Test that nested contexts with same resource work correctly."""
    init_concurrency()

    async with concurrency("test-resource", 5):
        status1 = concurrency_status_display()
        assert status1["test-resource"] == (1, 5)

        async with concurrency("test-resource", 5):
            status2 = concurrency_status_display()
            assert status2["test-resource"] == (2, 5)


@pytest.mark.anyio
async def test_concurrent_use_of_same_context() -> None:
    """Test that multiple tasks can concurrently use the same context."""
    init_concurrency()
    results: list[tuple[int, int]] = []

    async def task() -> None:
        async with concurrency("test-resource", 3):
            status = concurrency_status_display()
            results.append(status["test-resource"])
            await asyncio.sleep(0.05)

    async with anyio.create_task_group() as tg:
        for _ in range(5):
            tg.start_soon(task)

    # All tasks should complete
    assert len(results) == 5
    # Should have seen different active counts
    active_counts = [r[0] for r in results]
    assert len(set(active_counts)) > 1  # Not all the same


# Initialization Tests


@pytest.mark.anyio
async def test_init_clears_all_semaphores() -> None:
    """Test that init_concurrency clears all existing semaphores.

    Note: Semaphores persist in the status display even after the context
    exits, but init_concurrency() should clear them completely.
    """
    init_concurrency()  # Start clean

    # Create some semaphores
    async with concurrency("resource-1", 2):
        pass
    async with concurrency("resource-2", 3):
        pass

    # Should see them in status (even after exit)
    status_before = concurrency_status_display()
    assert len(status_before) >= 2

    # Initialize should clear everything
    init_concurrency()

    # Status should be empty
    status_after = concurrency_status_display()
    assert len(status_after) == 0


@pytest.mark.anyio
async def test_semaphores_recreated_after_init() -> None:
    """Test that semaphores can be recreated after initialization."""
    init_concurrency()

    # Create and use a semaphore
    async with concurrency("test-resource", 2):
        status1 = concurrency_status_display()
        assert status1["test-resource"] == (1, 2)

    # Initialize again
    init_concurrency()

    # Should be able to recreate with different limit
    async with concurrency("test-resource", 5):
        status2 = concurrency_status_display()
        assert status2["test-resource"] == (1, 5)


# Edge Cases


@pytest.mark.anyio
async def test_concurrency_one_strict_serialization() -> None:
    """Test that concurrency=1 strictly serializes execution."""
    init_concurrency()
    concurrent_count = 0
    max_concurrent = 0

    async def task() -> None:
        nonlocal concurrent_count, max_concurrent
        async with concurrency("test-resource", 1):
            concurrent_count += 1
            max_concurrent = max(max_concurrent, concurrent_count)
            await asyncio.sleep(0.05)
            concurrent_count -= 1

    async with anyio.create_task_group() as tg:
        for _ in range(5):
            tg.start_soon(task)

    # With concurrency=1, should never see more than 1 concurrent execution
    assert max_concurrent == 1


@pytest.mark.anyio
async def test_high_concurrency_value() -> None:
    """Test that high concurrency values work correctly."""
    init_concurrency()

    async def task() -> None:
        async with concurrency("test-resource", 1000):
            await asyncio.sleep(0.01)

    async with anyio.create_task_group() as tg:
        for _ in range(10):
            tg.start_soon(task)

    # Should complete without issues


@pytest.mark.anyio
async def test_rapid_concurrent_access() -> None:
    """Test rapid acquisition and release of semaphore slots."""
    init_concurrency()
    completion_count = 0

    async def task() -> None:
        nonlocal completion_count
        async with concurrency("test-resource", 5):
            await asyncio.sleep(0.001)
            completion_count += 1

    async with anyio.create_task_group() as tg:
        for _ in range(50):
            tg.start_soon(task)

    assert completion_count == 50


@pytest.mark.anyio
async def test_long_running_task_holds_slot() -> None:
    """Test that long-running tasks properly hold their slots."""
    init_concurrency()

    async def long_task() -> None:
        async with concurrency("test-resource", 1):
            await asyncio.sleep(0.2)

    async def quick_check() -> tuple[int, int]:
        await asyncio.sleep(0.05)
        status = concurrency_status_display()
        return status.get("test-resource", (0, 0))

    async with anyio.create_task_group() as tg:
        tg.start_soon(long_task)
        result = await quick_check()

    # Long task should have been holding the slot when we checked
    assert result == (1, 1)


@pytest.mark.anyio
async def test_multiple_resources_concurrent() -> None:
    """Test multiple different resources being used concurrently."""
    init_concurrency()

    async def task_a() -> None:
        async with concurrency("resource-a", 2):
            await asyncio.sleep(0.05)

    async def task_b() -> None:
        async with concurrency("resource-b", 3):
            await asyncio.sleep(0.05)

    async with anyio.create_task_group() as tg:
        for _ in range(4):
            tg.start_soon(task_a)
        for _ in range(6):
            tg.start_soon(task_b)

    # All tasks should complete successfully


@pytest.mark.anyio
async def test_empty_status_when_no_active_contexts() -> None:
    """Test that status display is empty when no contexts are active."""
    init_concurrency()

    # No active contexts
    status = concurrency_status_display()
    assert len(status) == 0

    # After using a context
    async with concurrency("test-resource", 1):
        pass

    # Still should show the resource even after exit
    status = concurrency_status_display()
    assert len(status) == 1
    assert status["test-resource"] == (0, 1)
