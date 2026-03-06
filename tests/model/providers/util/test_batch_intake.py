from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from inspect_ai.model._providers.util.batch import (
    BatchRequest,
    PendingBatch,
    _assess_intake_queue,
)


class TestAssessIntakeQueue:
    def create_batch_request(
        self, request_data: dict, custom_id: str | None = None
    ) -> BatchRequest[str]:
        return BatchRequest[str](
            request=request_data,
            result_stream=MagicMock(),
            custom_id=custom_id or f"req-{id(request_data)}",
        )

    @pytest.mark.parametrize(
        (
            "existing_count",
            "available_size",
            "intake_count",
            "min_count",
            "max_count",
            "timeout_offset",
            "expected_add_count",
            "expected_should_send",
            "description",
        ),
        [
            # Basic scenarios
            pytest.param(
                0, 1000, 0, 5, 10, 10, 0, False, "empty intake queue", id="empty-intake"
            ),
            pytest.param(
                10,
                1000,
                1,
                5,
                10,
                10,
                0,
                True,
                "batch already full by count",
                id="full-by-count",
            ),
            pytest.param(
                1,
                0,
                1,
                5,
                10,
                10,
                0,
                True,
                "batch already full by size",
                id="full-by-size",
            ),
            # Count limit scenarios
            pytest.param(
                1, 10000, 15, 5, 10, 10, 9, True, "hit count limit", id="count-limit"
            ),
            # Minimum requirement scenarios
            pytest.param(
                3,
                1000,
                3,
                5,
                10,
                10,
                3,
                True,
                "meet minimum requirement",
                id="meet-minimum",
            ),
            pytest.param(
                1,
                1000,
                1,
                5,
                10,
                10,
                1,
                False,
                "below minimum requirement",
                id="below-minimum",
            ),
            pytest.param(
                5,
                1000,
                0,
                5,
                10,
                10,
                0,
                True,
                "exact minimum count",
                id="exact-minimum",
            ),
            # Timeout scenarios
            pytest.param(
                1,
                1000,
                1,
                5,
                10,
                -1,
                1,
                True,
                "timeout triggers send",
                id="timeout-trigger",
            ),
            pytest.param(
                5,
                1000,
                0,
                10,
                5,
                -1,
                0,
                True,
                "timeout with no requests added",
                id="timeout-no-add",
            ),
            # Empty batch scenarios
            pytest.param(
                0,
                1000,
                0,
                1,
                10,
                -1,
                0,
                False,
                "no requests despite timeout should not send",
                id="no-requests-timeout",
            ),
            # Size limit scenarios - removed oversized request test as it should raise an error
        ],
    )
    def test_batch_assessment_scenarios(
        self,
        existing_count: int,
        available_size: int,
        intake_count: int,
        min_count: int,
        max_count: int,
        timeout_offset: int,
        expected_add_count: int,
        expected_should_send: bool,
        description: str,
    ):
        # Setup existing requests
        existing_requests = [
            self.create_batch_request({"data": f"existing-{i}"})
            for i in range(existing_count)
        ]

        # Setup pending batch
        timeout = time.time() + timeout_offset
        pending_batch = PendingBatch(
            timeout=timeout,
            available_size=available_size,
            requests=existing_requests,
        )

        # Setup intake queue
        intake_queue = [
            self.create_batch_request({"data": f"new-{i}"}) for i in range(intake_count)
        ]

        # Execute
        result = _assess_intake_queue(
            intake_queue=intake_queue,
            batch=pending_batch,
            min_request_count=min_count,
            max_request_count=max_count,
        )

        # Assert
        add_count, new_available_size, should_send = result
        assert add_count == expected_add_count, (
            f"Expected add_count {expected_add_count}, got {add_count} for {description}"
        )
        assert should_send == expected_should_send, (
            f"Expected should_send {expected_should_send}, got {should_send} for {description}"
        )
        assert isinstance(new_available_size, int), (
            f"new_available_size should be int for {description}"
        )
        assert new_available_size >= 0, (
            f"new_available_size should be >= 0 for {description}"
        )

    def test_oversized_request_raises_error(self):
        """Test that an oversized request in an empty batch raises an error."""
        pending_batch = PendingBatch(
            timeout=time.time() + 10, available_size=50, requests=[]
        )

        # Create a request that's too large for the available size
        large_data = "x" * 100  # Much larger than available size
        intake_queue = [
            self.create_batch_request({"large_data": large_data}),
            self.create_batch_request({"small": "data"}),
        ]

        # Should raise an exception when the first request can't fit in an empty batch
        with pytest.raises(Exception, match="exceeds maximum"):
            _assess_intake_queue(
                intake_queue=intake_queue,
                batch=pending_batch,
                min_request_count=5,
                max_request_count=10,
            )

    def test_add_requests_until_size_limit(self):
        """Test adding requests until hitting size limit."""
        pending_batch = PendingBatch(
            timeout=time.time() + 10,
            available_size=100,  # Small size limit
            requests=[],
        )

        # Create requests that will consume exactly the available size
        # Each small request uses about 13 bytes: {"small":1} = 13 chars
        intake_queue = [
            self.create_batch_request({"small": i})
            for i in range(20)  # More than can fit by size
        ]

        result = _assess_intake_queue(
            intake_queue=intake_queue,
            batch=pending_batch,
            min_request_count=5,
            max_request_count=50,
        )

        add_count, _, should_send = result
        assert add_count > 0
        assert add_count < 20  # Couldn't fit all requests
        assert should_send is True  # Batch is full by size

    def test_mixed_size_requests(self):
        """Test with requests of varying sizes."""
        pending_batch = PendingBatch(
            timeout=time.time() + 10, available_size=100, requests=[]
        )

        intake_queue = (
            [
                self.create_batch_request({"small": i})
                for i in range(5)  # Small requests
            ]
            + [
                self.create_batch_request({"large": "x" * 50})  # One large request
            ]
            + [
                self.create_batch_request({"more_small": i})
                for i in range(3)  # More small
            ]
        )

        result = _assess_intake_queue(
            intake_queue=intake_queue,
            batch=pending_batch,
            min_request_count=3,
            max_request_count=20,
        )

        add_count, _, should_send = result
        # Should add small requests until size limit hit
        assert add_count >= 3  # At least some requests added
        assert should_send is True  # Should meet minimum or hit size limit

    def test_return_format(self):
        """Test that return format matches specification."""
        pending_batch = PendingBatch(
            timeout=time.time() + 10, available_size=1000, requests=[]
        )

        intake_queue = [self.create_batch_request({"data": "test"})]

        result = _assess_intake_queue(
            intake_queue=intake_queue,
            batch=pending_batch,
            min_request_count=5,
            max_request_count=10,
        )

        # Should return tuple[int, int, bool]
        assert isinstance(result, tuple)
        assert len(result) == 3

        add_count, new_available_size, should_send = result
        assert isinstance(add_count, int)
        assert isinstance(new_available_size, int)
        assert isinstance(should_send, bool)
        assert add_count >= 0
        assert new_available_size >= 0
