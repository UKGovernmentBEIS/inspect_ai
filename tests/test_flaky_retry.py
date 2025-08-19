import pytest
from test_helpers.utils import flaky_retry


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

    def test_preserves_function_metadata(self):
        """Test that decorator preserves original function metadata."""

        @flaky_retry(max_retries=1)
        def test_function():
            """Test docstring."""
            pass

        assert test_function.__name__ == "test_function"
        assert test_function.__doc__ == "Test docstring."
