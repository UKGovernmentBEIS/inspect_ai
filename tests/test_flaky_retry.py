from typing import cast

import pytest
from test_helpers.utils import flaky_retry


class _FakeItem:
    """Stands in for a collected pytest.Item, optionally xfail-marked."""

    def __init__(self, xfail: bool):
        self._xfail = xfail

    def get_closest_marker(self, name: str) -> pytest.Mark | None:
        if self._xfail and name == "xfail":
            return pytest.mark.xfail(reason="known failure", strict=True).mark
        return None


class TestFlakyRetry:
    def test_success_on_first_try(self):
        """Test that decorator doesn't interfere with successful tests."""

        @flaky_retry(max_retries=3)
        def always_pass():
            return "success"

        result = always_pass()
        assert result == "success"

    def test_success_after_retries(self):
        """Test that decorator retries until success."""
        call_count = 0

        @flaky_retry(max_retries=3)
        def pass_on_third_try():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError(f"Failed attempt {call_count}")
            return "success"

        result = pass_on_third_try()
        assert result == "success"
        assert call_count == 3

    def test_exhausted_retries(self):
        """Test that decorator raises last exception when retries exhausted."""
        call_count = 0

        @flaky_retry(max_retries=2)
        def always_fail():
            nonlocal call_count
            call_count += 1
            raise ValueError(f"Failed attempt {call_count}")

        with pytest.raises(ValueError, match="Failed attempt 3"):
            always_fail()

        assert call_count == 3  # Initial + 2 retries

    def test_zero_retries(self):
        """Test that decorator works with zero retries (no retry, just initial attempt)."""
        call_count = 0

        @flaky_retry(max_retries=0)
        def fail_immediately():
            nonlocal call_count
            call_count += 1
            raise ValueError("Always fails")

        with pytest.raises(ValueError, match="Always fails"):
            fail_immediately()

        assert call_count == 1

    def test_skip_not_retried(self):
        """Test that pytest.skip() is honored immediately, not retried."""
        call_count = 0

        @flaky_retry(max_retries=3)
        def skip_immediately():
            nonlocal call_count
            call_count += 1
            pytest.skip("deliberate skip")

        with pytest.raises(pytest.skip.Exception):
            skip_immediately()

        assert call_count == 1

    def test_xfail_not_retried(self):
        """Test that pytest.xfail() is honored immediately, not retried."""
        call_count = 0

        @flaky_retry(max_retries=3)
        def xfail_immediately():
            nonlocal call_count
            call_count += 1
            pytest.xfail("deliberate xfail")

        with pytest.raises(pytest.xfail.Exception):
            xfail_immediately()

        assert call_count == 1

    async def test_async_skip_not_retried(self):
        """Test that pytest.skip() in an async test is honored immediately."""
        call_count = 0

        @flaky_retry(max_retries=3)
        async def skip_immediately():
            nonlocal call_count
            call_count += 1
            pytest.skip("deliberate skip")

        with pytest.raises(pytest.skip.Exception):
            await skip_immediately()

        assert call_count == 1

    def test_xfail_marked_item_not_retried(self):
        """An xfail marker on the item (e.g. added during fixture setup) suppresses retries."""
        call_count = 0

        @flaky_retry(max_retries=3, item=cast(pytest.Item, _FakeItem(xfail=True)))
        def known_failure():
            nonlocal call_count
            call_count += 1
            raise AssertionError("expected failure")

        with pytest.raises(AssertionError, match="expected failure"):
            known_failure()

        assert call_count == 1

    async def test_xfail_marked_item_not_retried_async(self):
        call_count = 0

        @flaky_retry(max_retries=3, item=cast(pytest.Item, _FakeItem(xfail=True)))
        async def known_failure():
            nonlocal call_count
            call_count += 1
            raise AssertionError("expected failure")

        with pytest.raises(AssertionError, match="expected failure"):
            await known_failure()

        assert call_count == 1

    def test_unmarked_item_still_retried(self):
        call_count = 0

        @flaky_retry(max_retries=3, item=cast(pytest.Item, _FakeItem(xfail=False)))
        def pass_on_second_try():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ValueError("flake")
            return "success"

        assert pass_on_second_try() == "success"
        assert call_count == 2

    def test_preserves_function_metadata(self):
        """Test that decorator preserves original function metadata."""

        @flaky_retry(max_retries=1)
        def test_function():
            """Test docstring."""
            pass

        assert test_function.__name__ == "test_function"
        assert test_function.__doc__ == "Test docstring."
