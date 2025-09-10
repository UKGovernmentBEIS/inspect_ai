"""Test fast_model decorator functionality with EvalSample and related classes."""

import json
import time
from datetime import datetime
from typing import Any

import pytest
from pydantic import BaseModel

from inspect_ai._util.fastmodel import fast_model
from inspect_ai.log._log import EvalSample
from inspect_ai.log._transcript import ModelEvent
from inspect_ai.model import (
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageUser,
    ModelOutput,
    ModelUsage,
)
from inspect_ai.scorer import Score
from inspect_ai.util._sandbox.environment import SandboxEnvironmentSpec


def create_sample_data() -> dict[str, Any]:
    """Create comprehensive synthetic data for EvalSample."""
    return {
        "id": "test_sample_1",
        "epoch": 1,
        "input": "What is 2+2?",
        "choices": ["3", "4", "5"],
        "target": "4",
        "sandbox": {
            "type": "docker",
            "config": None,
        },
        "files": ["test.txt"],
        "setup": "echo 'test'",
        "messages": [
            {
                "role": "system",
                "content": "You are a helpful assistant.",
                "source": "input",
            },
            {
                "role": "user",
                "content": "What is 2+2?",
                "source": "input",
            },
            {
                "role": "assistant",
                "content": "2+2 equals 4.",
                "source": "generate",
                "tool_calls": None,
            },
        ],
        "output": {
            "model": "gpt-4",
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "2+2 equals 4.",
                        "source": "generate",
                    },
                    "stop_reason": "stop",
                    "logprobs": {
                        "content": [
                            {
                                "token": "2",
                                "logprob": -0.5,
                                "top_logprobs": [],
                            }
                        ]
                    },
                }
            ],
            "usage": {
                "input_tokens": 10,
                "output_tokens": 5,
                "total_tokens": 15,
            },
        },
        "scores": {
            "accuracy": {
                "value": 1.0,
                "answer": "4",
                "explanation": "Correct answer",
                "metadata": {"confidence": 0.95},
            }
        },
        "metadata": {
            "test_id": "test_1",
            "difficulty": "easy",
            "timestamp": datetime.now().isoformat(),
        },
        "store": {"key1": "value1", "key2": 42},
        "events": [
            {
                "event": "model",
                "model": "gpt-4",
                "config": {
                    "temperature": 0.0,
                    "max_tokens": 100,
                },
                "input": [
                    {
                        "role": "user",
                        "content": "What is 2+2?",
                    }
                ],
                "output": {
                    "model": "gpt-4",
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": "4",
                            },
                            "stop_reason": "stop",
                        }
                    ],
                    "usage": {
                        "input_tokens": 10,
                        "output_tokens": 1,
                        "total_tokens": 11,
                    },
                },
                "timestamp": datetime.now().isoformat(),
                "working_start": 0.1,
            },
        ],
        "model_usage": {
            "gpt-4": {
                "input_tokens": 10,
                "output_tokens": 5,
                "total_tokens": 15,
            }
        },
        "total_time": 1.5,
        "working_time": 0.8,
        "uuid": "sample-uuid-123",
        "error": None,
        "limit": {
            "type": "token",
            "limit": 1000,
        },
        "attachments": {
            "attachment1": "base64_encoded_content",
        },
    }


def test_basic_fast_construct():
    """Test basic fast_construct functionality."""
    data = create_sample_data()

    # Use fast_construct
    sample = EvalSample.fast_construct(data)

    # Verify basic fields
    assert sample.id == "test_sample_1"
    assert sample.epoch == 1
    assert sample.input == "What is 2+2?"
    assert sample.target == "4"
    assert len(sample.messages) == 3
    assert sample.total_time == 1.5


def test_fast_vs_normal_construction():
    """Compare fast_construct with normal model_validate."""
    # Use simpler data without events (which have complex validation)
    data = {
        "id": "test_sample_1",
        "epoch": 1,
        "input": "What is 2+2?",
        "target": "4",
        "messages": [
            {"role": "system", "content": "You are a helper."},
            {"role": "user", "content": "What is 2+2?"},
            {"role": "assistant", "content": "4"},
        ],
        "metadata": {"test": True},
    }

    # Normal construction
    start_normal = time.perf_counter()
    sample_normal = EvalSample.model_validate(data)
    time_normal = time.perf_counter() - start_normal

    # Fast construction
    start_fast = time.perf_counter()
    sample_fast = EvalSample.fast_construct(data)
    time_fast = time.perf_counter() - start_fast

    # Fast should be faster (though in small examples the difference might be minimal)
    print(f"Normal: {time_normal:.6f}s, Fast: {time_fast:.6f}s")

    # Verify they produce equivalent results
    assert sample_normal.id == sample_fast.id
    assert sample_normal.epoch == sample_fast.epoch
    assert sample_normal.input == sample_fast.input
    assert sample_normal.target == sample_fast.target
    assert len(sample_normal.messages) == len(sample_fast.messages)


def test_nested_models():
    """Test that nested models are properly constructed."""
    data = create_sample_data()
    sample = EvalSample.fast_construct(data)

    # Check nested ChatMessage objects
    assert isinstance(sample.messages[0], ChatMessageSystem)
    assert isinstance(sample.messages[1], ChatMessageUser)
    assert isinstance(sample.messages[2], ChatMessageAssistant)

    # Check nested ModelOutput
    assert isinstance(sample.output, ModelOutput)
    assert isinstance(sample.output.usage, ModelUsage)
    assert sample.output.usage.input_tokens == 10

    # Check nested Score
    assert isinstance(sample.scores["accuracy"], Score)
    assert sample.scores["accuracy"].value == 1.0

    # Check nested SandboxEnvironmentSpec
    assert isinstance(sample.sandbox, SandboxEnvironmentSpec)
    assert sample.sandbox.type == "docker"


def test_complex_nested_structure():
    """Test deeply nested structure with EvalSample data."""
    from inspect_ai.log._log import EvalSample
    from datetime import datetime

    # Create complex EvalSample data with nested structures
    data = {
        "id": "complex_sample",
        "epoch": 1,
        "input": [
            {"role": "system", "content": "You are a helpful assistant"},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ],
        "target": "test_target",
        "messages": [{"role": "user", "content": "Test message"}],
        "output": {
            "model": "gpt-4",
            "choices": [
                {
                    "message": {"role": "assistant", "content": "Response"},
                    "stop_reason": "stop",
                }
            ],
            "usage": {"total_tokens": 100},
        },
        "scores": {
            "accuracy": {"value": 1.0, "answer": "correct"},
            "relevance": {"value": 0.9},
        },
        "events": [
            {
                "event": "sample_init",
                "sample": {
                    "id": "nested_sample",
                    "input": "nested input",
                    "target": "nested target",
                },
                "state": {"key": "value"},
                "timestamp": datetime.now().isoformat(),
                "working_start": 0.0,
            }
        ],
        "metadata": {"test": "complex", "nested": {"level": 2}},
    }

    # Fast construction
    sample_fast = EvalSample.fast_construct(data)

    # Normal construction for comparison
    sample_normal = EvalSample.model_validate(data)

    # Compare nested structures
    assert sample_fast.id == sample_normal.id
    assert len(sample_fast.input) == 3
    assert sample_fast.scores["accuracy"].value == 1.0
    assert sample_fast.metadata["nested"]["level"] == 2
    assert sample_fast.events[0].sample.id == "nested_sample"


def test_datetime_coercion():
    """Test that ISO datetime strings are properly coerced."""
    now = datetime.now()
    data = {
        "event": "model",
        "timestamp": now.isoformat(),
        "working_start": 0.0,
        "model": "test-model",
        "config": {},
        "input": [],
        "output": {
            "model": "test-model",
            "choices": [],
            "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        },
    }

    event = ModelEvent.fast_construct(data)
    assert isinstance(event.timestamp, datetime)


def test_all_event_types():
    """Test that all event types are correctly deserialized with discriminated unions."""
    from inspect_ai.log._transcript import (
        Event,
        SampleInitEvent,
        SampleLimitEvent,
        ModelEvent,
        ToolEvent,
        SandboxEvent,
        ApprovalEvent,
        InputEvent,
        ScoreEvent,
        ErrorEvent,
        LoggerEvent,
        InfoEvent,
        StateEvent,
        StoreEvent,
        SpanBeginEvent,
        SpanEndEvent,
        StepEvent,
        SubtaskEvent,
    )

    now = datetime.now()

    # Create test data for various event types
    events_data = [
        {
            "event": "sample_init",
            "sample": {
                "id": "test_sample",
                "epoch": 1,
                "input": "Test input",
                "target": "Test target",
                "metadata": {},
            },
            "state": {"key": "value"},
            "timestamp": now.isoformat(),
            "working_start": 0.0,
        },
        {
            "event": "sample_limit",
            "type": "token",
            "limit": 1000,
            "message": "Token limit reached",
            "timestamp": now.isoformat(),
            "working_start": 0.1,
        },
        {
            "event": "model",
            "model": "gpt-4",
            "config": {"temperature": 0.7},
            "input": [{"role": "user", "content": "Hello"}],
            "output": {
                "model": "gpt-4",
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "Hi"},
                        "stop_reason": "stop",
                    }
                ],
                "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            },
            "timestamp": now.isoformat(),
            "working_start": 0.2,
        },
        {
            "event": "tool",
            "type": "function",
            "id": "tool_123",
            "function": "calculator",
            "arguments": {"a": 1, "b": 2},
            "result": "3",
            "timestamp": now.isoformat(),
            "working_start": 0.3,
        },
        {
            "event": "sandbox",
            "action": "exec",
            "cmd": "ls",
            "result": 0,
            "output": "file1.txt\nfile2.txt",
            "timestamp": now.isoformat(),
            "working_start": 0.4,
        },
        {
            "event": "approval",
            "message": "Requesting approval",
            "call": {
                "id": "call_123",
                "type": "function",
                "function": "bash",
                "arguments": {"command": "rm -rf /"},
            },
            "approver": "human",
            "decision": "reject",
            "timestamp": now.isoformat(),
            "working_start": 0.5,
        },
        {
            "event": "input",
            "input": "User input text",
            "input_ansi": "User input text",
            "timestamp": now.isoformat(),
            "working_start": 0.6,
        },
        {
            "event": "score",
            "score": {
                "value": 0.95,
                "answer": "Correct",
                "explanation": "Good answer",
            },
            "timestamp": now.isoformat(),
            "working_start": 0.7,
        },
        {
            "event": "error",
            "error": {
                "message": "Test error",
                "traceback": "Traceback...",
                "traceback_ansi": "Traceback with colors...",
            },
            "timestamp": now.isoformat(),
            "working_start": 0.8,
        },
        {
            "event": "logger",
            "message": {"level": "info", "message": "Log message"},
            "timestamp": now.isoformat(),
            "working_start": 0.9,
        },
        {
            "event": "info",
            "data": {"info_key": "info_value"},
            "timestamp": now.isoformat(),
            "working_start": 1.0,
        },
        {
            "event": "state",
            "changes": [{"op": "add", "path": "/state_key", "value": "state_value"}],
            "timestamp": now.isoformat(),
            "working_start": 1.1,
        },
        {
            "event": "store",
            "changes": [{"op": "add", "path": "/key", "value": "value"}],
            "timestamp": now.isoformat(),
            "working_start": 1.2,
        },
        {
            "event": "span_begin",
            "id": "span_123",
            "name": "Test Span",
            "timestamp": now.isoformat(),
            "working_start": 1.3,
        },
        {
            "event": "span_end",
            "id": "span_123",
            "timestamp": now.isoformat(),
            "working_start": 1.4,
        },
        {
            "event": "step",
            "action": "begin",
            "name": "solver",
            "params": {"param1": "value1"},
            "timestamp": now.isoformat(),
            "working_start": 1.5,
        },
        {
            "event": "subtask",
            "name": "subtask_1",
            "input": {"task": "Do something"},
            "result": {"status": "completed"},
            "timestamp": now.isoformat(),
            "working_start": 1.6,
        },
    ]

    # Test that each event type is correctly identified and constructed
    expected_types = [
        SampleInitEvent,
        SampleLimitEvent,
        ModelEvent,
        ToolEvent,
        SandboxEvent,
        ApprovalEvent,
        InputEvent,
        ScoreEvent,
        ErrorEvent,
        LoggerEvent,
        InfoEvent,
        StateEvent,
        StoreEvent,
        SpanBeginEvent,
        SpanEndEvent,
        StepEvent,
        SubtaskEvent,
    ]

    # Test EvalSample with all events
    sample_data = {
        "id": "test_events",
        "epoch": 1,
        "input": "Test input",
        "target": "Test target",
        "events": events_data,
    }

    # Fast construct the sample
    sample = EvalSample.fast_construct(sample_data)

    # Verify we have all events
    assert len(sample.events) == len(events_data)

    # Verify each event is the correct type
    for i, (event, expected_type) in enumerate(zip(sample.events, expected_types)):
        assert isinstance(event, expected_type), (
            f"Event {i} should be {expected_type.__name__}, got {type(event).__name__}"
        )
        assert isinstance(event.timestamp, datetime), (
            f"Event {i} timestamp should be datetime"
        )

    # Test some specific event properties
    assert sample.events[0].sample.id == "test_sample"  # SampleInitEvent
    assert sample.events[2].model == "gpt-4"  # ModelEvent
    assert sample.events[3].function == "calculator"  # ToolEvent
    assert sample.events[7].score.value == 0.95  # ScoreEvent


def test_performance_with_many_samples():
    """Test performance improvement with multiple samples."""

    # Create simple sample data without events
    def simple_sample_data(i: int) -> dict[str, Any]:
        return {
            "id": f"sample_{i}",
            "epoch": 1,
            "input": f"Question {i}",
            "target": f"Answer {i}",
            "messages": [
                {"role": "user", "content": f"Question {i}"},
                {"role": "assistant", "content": f"Answer {i}"},
            ],
        }

    samples_data = [simple_sample_data(i) for i in range(100)]

    # Time normal construction
    start_normal = time.perf_counter()
    samples_normal = [EvalSample.model_validate(data) for data in samples_data]
    time_normal = time.perf_counter() - start_normal

    # Time fast construction
    start_fast = time.perf_counter()
    samples_fast = [EvalSample.fast_construct(data) for data in samples_data]
    time_fast = time.perf_counter() - start_fast

    print(f"100 samples - Normal: {time_normal:.3f}s, Fast: {time_fast:.3f}s")
    print(f"Speedup: {time_normal / time_fast:.2f}x")

    # Verify first and last samples match
    assert samples_normal[0].id == samples_fast[0].id
    assert samples_normal[-1].id == samples_fast[-1].id


def test_missing_fields_with_defaults():
    """Test that missing fields get proper defaults."""
    minimal_data = {
        "id": "minimal",
        "epoch": 1,
        "input": "test input",
        "target": "test target",
    }

    sample = EvalSample.fast_construct(minimal_data)

    # Check defaults are applied
    assert sample.messages == []
    assert sample.metadata == {}
    assert sample.scores is None
    assert sample.events == []


def test_extra_fields_handling():
    """Test handling of extra fields when model allows them."""

    @fast_model()
    class TestModelWithExtras(BaseModel):
        name: str
        model_config = {"extra": "allow"}

    data = {
        "name": "test",
        "extra_field": "extra_value",
        "another_extra": 123,
    }

    obj = TestModelWithExtras.fast_construct(data)
    assert obj.name == "test"
    assert obj.__pydantic_extra__["extra_field"] == "extra_value"
    assert obj.__pydantic_extra__["another_extra"] == 123


def test_model_post_init_called():
    """Test that model_post_init is called when enabled."""

    @fast_model()
    class TestModelWithPostInit(BaseModel):
        value: int
        computed: int | None = None

        def model_post_init(self, __context: Any) -> None:
            if self.computed is None:
                self.computed = self.value * 2

    data = {"value": 5}
    obj = TestModelWithPostInit.fast_construct(data)

    assert obj.value == 5
    assert obj.computed == 10


def test_union_types():
    """Test that Union types are handled correctly."""
    data = {
        "id": "test",
        "epoch": 1,
        "input": [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ],
        "target": ["answer1", "answer2"],
    }

    sample = EvalSample.fast_construct(data)

    # Input can be string or list[ChatMessage]
    assert isinstance(sample.input, list)
    assert len(sample.input) == 2

    # Target can be string or list[str]
    assert isinstance(sample.target, list)
    assert sample.target == ["answer1", "answer2"]


def test_json_serialization_roundtrip():
    """Test that fast_construct works with JSON serialization roundtrip."""
    # Use simple data without events
    original_data = {
        "id": "test_json",
        "epoch": 1,
        "input": "Test question",
        "target": "Test answer",
        "messages": [
            {"role": "user", "content": "Test question"},
            {"role": "assistant", "content": "Test answer"},
        ],
        "scores": {
            "accuracy": {
                "value": 0.9,
                "answer": "Test answer",
            }
        },
    }

    # Create sample with normal validation
    sample = EvalSample.model_validate(original_data)

    # Serialize to JSON and back
    json_str = sample.model_dump_json()
    parsed_data = json.loads(json_str)

    # Use fast_construct on the parsed data
    sample_fast = EvalSample.fast_construct(parsed_data)

    # Verify key fields match
    assert sample.id == sample_fast.id
    assert sample.epoch == sample_fast.epoch
    assert len(sample.messages) == len(sample_fast.messages)
    assert isinstance(sample_fast.scores["accuracy"], Score)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
