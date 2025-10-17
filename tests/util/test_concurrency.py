"""Test suite for inspect_ai.util._concurrency module.

Tests the public interface of concurrency control functionality including
the concurrency context manager, status display, and initialization.
"""

import anyio
import pytest

from inspect_ai.util._concurrency import (
    concurrency,
    concurrency_status_display,
    get_or_create_semaphore,
    init_concurrency,
)

# get_or_create_sem Tests


@pytest.mark.anyio
async def test_get_or_create_sem_creates_new_semaphore() -> None:
    """Test that get_or_create_sem creates a new semaphore on first call."""
    init_concurrency()

    sem = await get_or_create_semaphore("test-resource", 5, None, True)

    assert sem.name == "test-resource"
    assert sem.concurrency == 5
    assert sem.visible is True
    assert sem.value == 5  # All slots available


@pytest.mark.anyio
async def test_get_or_create_sem_returns_existing_semaphore() -> None:
    """Test that get_or_create_sem returns the same semaphore for the same key."""
    init_concurrency()

    sem1 = await get_or_create_semaphore("test-resource", 3, None, True)
    sem2 = await get_or_create_semaphore("test-resource", 3, None, True)

    assert sem1 is sem2


@pytest.mark.anyio
async def test_get_or_create_sem_respects_explicit_key() -> None:
    """Test that get_or_create_sem uses explicit key parameter when provided."""
    init_concurrency()

    # Same name, different keys should create different semaphores
    sem1 = await get_or_create_semaphore("display-name", 2, "key-1", True)
    sem2 = await get_or_create_semaphore("display-name", 3, "key-2", True)

    assert sem1 is not sem2
    assert sem1.name == "display-name"
    assert sem2.name == "display-name"
    assert sem1.concurrency == 2
    assert sem2.concurrency == 3


@pytest.mark.anyio
async def test_get_or_create_sem_key_defaults_to_name() -> None:
    """Test that key defaults to name when key is None."""
    init_concurrency()

    # Both calls use name as key
    sem1 = await get_or_create_semaphore("test-resource", 4, None, True)
    sem2 = await get_or_create_semaphore("test-resource", 4, "test-resource", True)

    assert sem1 is sem2


@pytest.mark.anyio
async def test_get_or_create_sem_visibility() -> None:
    """Test that get_or_create_sem properly sets visibility flag."""
    init_concurrency()

    sem_visible = await get_or_create_semaphore("visible-resource", 1, None, True)
    sem_hidden = await get_or_create_semaphore("hidden-resource", 1, None, False)

    assert sem_visible.visible is True
    assert sem_hidden.visible is False


@pytest.mark.anyio
async def test_get_or_create_sem_semaphore_is_usable() -> None:
    """Test that semaphore returned by get_or_create_sem is functional."""
    init_concurrency()

    sem = await get_or_create_semaphore("test-resource", 2, None, True)

    # Use the semaphore
    async with sem.semaphore:
        assert sem.value == 1  # One slot taken

        async with sem.semaphore:
            assert sem.value == 0  # Both slots taken

    assert sem.value == 2  # Both slots released


# Basic Concurrency Control Tests


@pytest.mark.anyio
@pytest.mark.parametrize(
    "limit,num_tasks,expected_max",
    [
        (1, 5, 1),  # Serialization
        (2, 4, 2),  # Limit of 2
        (3, 5, 3),  # Limit of 3
        (100, 10, 10),  # High limit
    ],
)
async def test_concurrency_limits(
    limit: int, num_tasks: int, expected_max: int
) -> None:
    """Test that concurrency limits are properly enforced."""
    init_concurrency()
    max_concurrent = 0
    entered_count = 0
    barrier = anyio.Event()

    async def task() -> None:
        nonlocal max_concurrent, entered_count
        async with concurrency("test-resource", limit):
            status = concurrency_status_display()
            max_concurrent = max(max_concurrent, status["test-resource"][0])
            entered_count += 1
            # If we're at the expected max, release all waiting tasks
            if entered_count >= expected_max:
                barrier.set()
            # Wait for barrier to ensure tasks stay concurrent long enough
            await barrier.wait()

    async with anyio.create_task_group() as tg:
        for _ in range(num_tasks):
            tg.start_soon(task)

    assert max_concurrent == expected_max


# Semaphore Reuse Tests


@pytest.mark.anyio
async def test_semaphore_reuse_same_key() -> None:
    """Test that same name/key reuses the same semaphore."""
    init_concurrency()

    # Nested contexts with same name should share semaphore
    async with concurrency("test-resource", 2):
        status1 = concurrency_status_display()
        assert status1["test-resource"] == (1, 2)

        async with concurrency("test-resource", 2):
            status2 = concurrency_status_display()
            assert status2["test-resource"] == (2, 2)  # Both active


@pytest.mark.anyio
async def test_semaphore_isolation() -> None:
    """Test that different names/keys create separate semaphores."""
    init_concurrency()

    # Different names create independent semaphores
    async with concurrency("resource-a", 1):
        async with concurrency("resource-b", 1):
            status = concurrency_status_display()
            assert status["resource-a"] == (1, 1)
            assert status["resource-b"] == (1, 1)

    # Explicit keys create independent semaphores
    init_concurrency()
    async with concurrency("name-1", 1, key="key-1"):
        async with concurrency("name-2", 1, key="key-2"):
            status = concurrency_status_display()
            assert "name-1" in status
            assert "name-2" in status


# Status Display Tests


@pytest.mark.anyio
@pytest.mark.parametrize("visible", [True, False])
async def test_status_display_visibility(visible: bool) -> None:
    """Test that visibility flag controls whether resource appears in status."""
    init_concurrency()

    async with concurrency("test-resource", 1, visible=visible):
        status = concurrency_status_display()
        if visible:
            assert "test-resource" in status
            assert status["test-resource"] == (1, 1)
        else:
            assert "test-resource" not in status


@pytest.mark.anyio
async def test_status_display_prefix_shortening_single() -> None:
    """Test that model prefix is shortened when there's only one with that prefix."""
    init_concurrency()

    async with concurrency("openai/gpt-4o", 1):
        status = concurrency_status_display()
        assert "openai" in status
        assert status["openai"] == (1, 1)


@pytest.mark.anyio
async def test_status_display_prefix_shortening_multiple() -> None:
    """Test that full names are kept when multiple models share a prefix."""
    init_concurrency()

    async with concurrency("openai/gpt-4o", 1):
        async with concurrency("openai/gpt-3.5", 1):
            status = concurrency_status_display()
            assert "openai/gpt-4o" in status
            assert "openai/gpt-3.5" in status


@pytest.mark.anyio
async def test_status_display_concurrent_updates() -> None:
    """Test that status display reflects concurrent task execution."""
    init_concurrency()
    status_snapshots: list[tuple[int, int]] = []
    entered_count = 0
    barrier = anyio.Event()

    async def task() -> None:
        nonlocal entered_count
        async with concurrency("test-resource", 3):
            status = concurrency_status_display()
            status_snapshots.append(status["test-resource"])
            entered_count += 1
            # Once all 3 tasks have entered, release them
            if entered_count >= 3:
                barrier.set()
            await barrier.wait()

    async with anyio.create_task_group() as tg:
        for _ in range(3):
            tg.start_soon(task)

    # Verify status was tracking correctly
    active_counts = [s[0] for s in status_snapshots]
    assert max(active_counts) <= 3
    assert all(s[1] == 3 for s in status_snapshots)  # Total always 3


# Context Manager Behavior Tests


@pytest.mark.anyio
async def test_context_manager_exception_handling() -> None:
    """Test that exceptions properly release semaphore slots."""
    init_concurrency()

    # Exception should release semaphore
    with pytest.raises(RuntimeError):
        async with concurrency("test-resource", 1):
            raise RuntimeError("Test error")

    # Verify semaphore was released by acquiring it again
    async with concurrency("test-resource", 1):
        status = concurrency_status_display()
        assert status["test-resource"] == (1, 1)


@pytest.mark.anyio
async def test_nested_contexts() -> None:
    """Test nested context behavior with same and different resources."""
    init_concurrency()

    # Nested contexts with different resources
    async with concurrency("outer-resource", 2):
        async with concurrency("inner-resource", 3):
            status = concurrency_status_display()
            assert status["outer-resource"] == (1, 2)
            assert status["inner-resource"] == (1, 3)

    # Nested contexts with same resource
    init_concurrency()
    async with concurrency("test-resource", 5):
        async with concurrency("test-resource", 5):
            status = concurrency_status_display()
            assert status["test-resource"] == (2, 5)


@pytest.mark.anyio
async def test_concurrent_context_usage() -> None:
    """Test multiple tasks concurrently using the same context."""
    init_concurrency()
    results: list[tuple[int, int]] = []
    entered_count = 0
    barrier = anyio.Event()

    async def task() -> None:
        nonlocal entered_count
        async with concurrency("test-resource", 3):
            status = concurrency_status_display()
            results.append(status["test-resource"])
            entered_count += 1
            # Once 3 tasks have entered (the limit), release all
            if entered_count >= 3:
                barrier.set()
            await barrier.wait()

    async with anyio.create_task_group() as tg:
        for _ in range(5):
            tg.start_soon(task)

    # All tasks should complete
    assert len(results) == 5
    # Should have seen varying active counts
    active_counts = [r[0] for r in results]
    assert len(set(active_counts)) > 1


# Initialization Tests


@pytest.mark.anyio
async def test_init_concurrency() -> None:
    """Test that init_concurrency clears and allows recreation of semaphores."""
    init_concurrency()

    # Create some semaphores
    async with concurrency("resource-1", 2):
        pass
    async with concurrency("resource-2", 3):
        pass

    # Should see them in status (persist after exit)
    status_before = concurrency_status_display()
    assert len(status_before) >= 2

    # init_concurrency() should clear everything
    init_concurrency()
    status_after = concurrency_status_display()
    assert len(status_after) == 0

    # Should be able to recreate with different limit
    async with concurrency("resource-1", 5):
        status = concurrency_status_display()
        assert status["resource-1"] == (1, 5)


# Edge Cases and Stress Tests


@pytest.mark.anyio
async def test_rapid_concurrent_access_multiple_resources() -> None:
    """Test rapid concurrent access across multiple independent resources."""
    init_concurrency()
    completion_count = {"a": 0, "b": 0}

    async def task_a() -> None:
        async with concurrency("resource-a", 5):
            completion_count["a"] += 1

    async def task_b() -> None:
        async with concurrency("resource-b", 3):
            completion_count["b"] += 1

    async with anyio.create_task_group() as tg:
        for _ in range(20):
            tg.start_soon(task_a)
        for _ in range(15):
            tg.start_soon(task_b)

    assert completion_count["a"] == 20
    assert completion_count["b"] == 15


@pytest.mark.anyio
async def test_long_running_task_holds_slot() -> None:
    """Test that tasks properly hold their slots while executing."""
    init_concurrency()
    task_holding = anyio.Event()
    check_done = anyio.Event()

    async def holding_task() -> None:
        async with concurrency("test-resource", 1):
            # Signal that we're holding the slot
            task_holding.set()
            # Wait until checker has verified
            await check_done.wait()

    async def checker() -> tuple[int, int]:
        # Wait for task to acquire slot
        await task_holding.wait()
        # Check status while task is holding
        status = concurrency_status_display()
        result = status.get("test-resource", (0, 0))
        # Signal task can release
        check_done.set()
        return result

    async with anyio.create_task_group() as tg:
        tg.start_soon(holding_task)
        result = await checker()

    # Task should have been holding the slot when we checked
    assert result == (1, 1)
