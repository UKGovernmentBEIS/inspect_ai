"""Tests for sandbox injection functionality."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from inspect_ai.util._sandbox.context import (
    SandboxInjectable,
    sandbox_environments_context_var,
    sandbox_with_injection,
)


@pytest.fixture
def mock_sandbox():
    """Create a mock sandbox environment."""
    sandbox = MagicMock()
    sandbox.name = "test_sandbox"
    return sandbox


@pytest.fixture
def mock_sandboxes():
    """Create multiple mock sandbox environments."""
    sb1 = MagicMock()
    sb1.name = "sandbox1"

    sb2 = MagicMock()
    sb2.name = "sandbox2"

    sb3 = MagicMock()
    sb3.name = "sandbox3"

    return {"sandbox1": sb1, "sandbox2": sb2, "sandbox3": sb3}


@pytest.fixture
def mock_detector():
    """Create a mock detector function."""
    return AsyncMock()


@pytest.fixture
def mock_injector():
    """Create a mock injector function."""
    return AsyncMock()


@pytest.mark.asyncio
async def test_chooses_sandbox_requiring_fewest_injections(mock_sandboxes):
    """Test that it selects the sandbox needing the fewest injections."""
    # Setup: create detectors that return different results for each sandbox
    detector1 = AsyncMock()
    detector2 = AsyncMock()
    injector1 = AsyncMock()
    injector2 = AsyncMock()

    # sandbox1: needs both injections (2 needed)
    # sandbox2: needs only first injection (1 needed)
    # sandbox3: needs only second injection (1 needed)
    def detector1_side_effect(_sandbox):
        if _sandbox.name == "sandbox1":
            return False  # needs injection
        elif _sandbox.name == "sandbox2":
            return False  # needs injection
        else:  # sandbox3
            return True  # already satisfied

    def detector2_side_effect(_sandbox):
        if _sandbox.name == "sandbox1":
            return False  # needs injection
        elif _sandbox.name == "sandbox2":
            return True  # already satisfied
        else:  # sandbox3
            return False  # needs injection

    detector1.side_effect = detector1_side_effect
    detector2.side_effect = detector2_side_effect

    # After injection, detectors should return True
    injector1.side_effect = lambda _sandbox: setattr(
        detector1, "side_effect", lambda _: True
    )
    injector2.side_effect = lambda _sandbox: setattr(
        detector2, "side_effect", lambda _: True
    )

    injection_list = [
        SandboxInjectable(detector1, injector1),
        SandboxInjectable(detector2, injector2),
    ]

    # Mock the context variable
    token = sandbox_environments_context_var.set(mock_sandboxes)

    try:
        result_sandbox = await sandbox_with_injection(injection_list)

        # Should pick sandbox2 or sandbox3 (both need only 1 injection)
        assert result_sandbox.name in ["sandbox2", "sandbox3"]

        # Verify that only the needed injections were performed
        if result_sandbox.name == "sandbox2":
            injector1.assert_called_once_with(result_sandbox)
            injector2.assert_not_called()
        else:  # sandbox3
            injector2.assert_called_once_with(result_sandbox)
            injector1.assert_not_called()

    finally:
        sandbox_environments_context_var.reset(token)


@pytest.mark.asyncio
async def test_returns_immediately_if_no_injections_needed(mock_sandboxes):
    """Test that it returns immediately when a sandbox needs no injections."""
    detector = AsyncMock()
    injector = AsyncMock()

    # sandbox2 already satisfies all requirements
    def detector_side_effect(_sandbox):
        return _sandbox.name == "sandbox2"

    detector.side_effect = detector_side_effect

    injectable = SandboxInjectable(detector, injector)

    token = sandbox_environments_context_var.set(mock_sandboxes)

    try:
        result_sandbox = await sandbox_with_injection(injectable)

        # Should return sandbox2 without any injections
        assert result_sandbox.name == "sandbox2"
        injector.assert_not_called()

    finally:
        sandbox_environments_context_var.reset(token)


@pytest.mark.asyncio
async def test_targets_named_sandbox_correctly(mock_sandboxes):
    """Test that it correctly targets the named sandbox."""
    detector = AsyncMock(return_value=False)  # needs injection
    injector = AsyncMock()

    # After injection, detector should return True
    async def injector_side_effect(_sandbox):
        detector.return_value = True

    injector.side_effect = injector_side_effect

    injectable = SandboxInjectable(detector, injector)

    # Mock sandbox() function to return the named sandbox
    from inspect_ai.util._sandbox.context import sandbox_environments_context_var

    token = sandbox_environments_context_var.set(mock_sandboxes)

    try:
        # Mock the sandbox() function that gets called when name is provided
        from unittest.mock import patch

        with patch("inspect_ai.util._sandbox.context.sandbox") as mock_sandbox_func:
            mock_sandbox_func.return_value = mock_sandboxes["sandbox2"]

            result_sandbox = await sandbox_with_injection(injectable, name="sandbox2")

            # Should target sandbox2 specifically
            assert result_sandbox == mock_sandboxes["sandbox2"]
            injector.assert_called_once_with(mock_sandboxes["sandbox2"])

    finally:
        sandbox_environments_context_var.reset(token)


@pytest.mark.asyncio
async def test_no_injection_when_already_satisfied(mock_sandbox):
    """Test that no injection occurs when detector already returns True."""
    detector = AsyncMock(return_value=True)  # already satisfied
    injector = AsyncMock()

    injectable = SandboxInjectable(detector, injector)

    token = sandbox_environments_context_var.set({"test": mock_sandbox})

    try:
        result_sandbox = await sandbox_with_injection(injectable)

        assert result_sandbox == mock_sandbox
        injector.assert_not_called()

    finally:
        sandbox_environments_context_var.reset(token)


@pytest.mark.asyncio
async def test_mixed_satisfied_and_unsatisfied_requirements(mock_sandbox):
    """Test mixed scenario: some requirements satisfied, others need injection."""
    detector1 = AsyncMock(return_value=True)  # already satisfied
    detector2 = AsyncMock(return_value=False)  # needs injection
    injector1 = AsyncMock()
    injector2 = AsyncMock()

    # After injection, detector2 should return True
    async def injector2_side_effect(_sandbox):
        detector2.return_value = True

    injector2.side_effect = injector2_side_effect

    injection_list = [
        SandboxInjectable(detector1, injector1),
        SandboxInjectable(detector2, injector2),
    ]

    token = sandbox_environments_context_var.set({"test": mock_sandbox})

    try:
        result_sandbox = await sandbox_with_injection(injection_list)

        assert result_sandbox == mock_sandbox
        injector1.assert_not_called()  # was already satisfied
        injector2.assert_called_once()  # needed injection

    finally:
        sandbox_environments_context_var.reset(token)


@pytest.mark.asyncio
async def test_runtime_error_when_injection_fails(mock_sandbox):
    """Test RuntimeError when detector still returns False after injection."""
    detector = AsyncMock(return_value=False)  # always returns False
    injector = AsyncMock()  # injector runs but doesn't fix the problem

    injectable = SandboxInjectable(detector, injector)

    token = sandbox_environments_context_var.set({"test": mock_sandbox})

    try:
        with pytest.raises(RuntimeError, match="Injection failed"):
            await sandbox_with_injection(injectable)

        injector.assert_called_once()

    finally:
        sandbox_environments_context_var.reset(token)


@pytest.mark.asyncio
async def test_process_lookup_error_when_no_sandboxes():
    """Test ProcessLookupError when no sandboxes are available."""
    detector = AsyncMock(return_value=False)
    injector = AsyncMock()

    injectable = SandboxInjectable(detector, injector)

    # No sandboxes in context
    token = sandbox_environments_context_var.set({})

    try:
        with pytest.raises(ProcessLookupError):
            await sandbox_with_injection(injectable)

    finally:
        sandbox_environments_context_var.reset(token)


@pytest.mark.asyncio
async def test_injector_exception_propagation(mock_sandbox):
    """Test that exceptions from injector functions are propagated."""
    detector = AsyncMock(return_value=False)
    injector = AsyncMock(side_effect=ValueError("Injector failed"))

    injectable = SandboxInjectable(detector, injector)

    token = sandbox_environments_context_var.set({"test": mock_sandbox})

    try:
        with pytest.raises(ValueError, match="Injector failed"):
            await sandbox_with_injection(injectable)

    finally:
        sandbox_environments_context_var.reset(token)


@pytest.mark.asyncio
async def test_handles_single_injectable_and_list_input(mock_sandbox):
    """Test that single injectable and list input produce identical results."""
    # Create separate detectors and injectors for each test to avoid state interference
    detector1 = AsyncMock(return_value=False)  # needs injection
    injector1 = AsyncMock()
    detector2 = AsyncMock(return_value=False)  # needs injection
    injector2 = AsyncMock()

    # After injection, detectors should return True
    async def injector1_side_effect(sandbox):
        detector1.return_value = True

    async def injector2_side_effect(sandbox):
        detector2.return_value = True

    injector1.side_effect = injector1_side_effect
    injector2.side_effect = injector2_side_effect

    injectable1 = SandboxInjectable(detector1, injector1)
    injectable2 = SandboxInjectable(detector2, injector2)

    token = sandbox_environments_context_var.set({"test": mock_sandbox})

    try:
        # Test with single injectable (tuple form)
        result1 = await sandbox_with_injection(injectable1)

        # Test with same injectable structure in a list
        result2 = await sandbox_with_injection([injectable2])

        # Both should return the same sandbox
        assert result1 == result2 == mock_sandbox

        # Both injectors should have been called exactly once
        injector1.assert_called_once_with(mock_sandbox)
        injector2.assert_called_once_with(mock_sandbox)

    finally:
        sandbox_environments_context_var.reset(token)
