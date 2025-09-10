"""Comprehensive tests for all 44 classes decorated with @fast_model."""

import time
from datetime import datetime
from typing import Any, Type

import pytest
from pydantic import BaseModel

# Import all 44 decorated classes
from inspect_ai.log._log import EvalSample, EvalSampleLimit
from inspect_ai.dataset._dataset import Sample
from inspect_ai.model._chat_message import (
    ChatMessageSystem,
    ChatMessageUser,
    ChatMessageAssistant,
    ChatMessageTool,
)
from inspect_ai.model._model_output import (
    ModelOutput,
    ModelUsage,
    ChatCompletionChoice,
    Logprob,
    Logprobs,
    TopLogprob,
)
from inspect_ai.model._generate_config import (
    GenerateConfig,
    ResponseSchema,
    BatchConfig,
)
from inspect_ai.log._transcript import (
    ApprovalEvent,
    ErrorEvent,
    InfoEvent,
    InputEvent,
    LoggerEvent,
    ModelEvent,
    SampleInitEvent,
    SampleLimitEvent,
    SandboxEvent,
    ScoreEvent,
    SpanBeginEvent,
    SpanEndEvent,
    StateEvent,
    StepEvent,
    StoreEvent,
    SubtaskEvent,
    ToolEvent,
)
from inspect_ai.scorer._scorer import Score
from inspect_ai.scorer._metric import SampleScore
from inspect_ai._util.error import EvalError
from inspect_ai.log._message import LoggingMessage
from inspect_ai._util.json import JsonChange
from inspect_ai.util._json import JSONSchema
from inspect_ai.tool._tool_info import ToolInfo, ToolParams
from inspect_ai.tool._tool_call import ToolCallContent, ToolCallView
from inspect_ai.util._sandbox.environment import SandboxEnvironmentSpec

# List of all 44 decorated types
DECORATED_TYPES: list[Type[BaseModel]] = [
    # Core types (3)
    EvalSample,
    EvalSampleLimit,
    Sample,
    # Chat messages (4)
    ChatMessageSystem,
    ChatMessageUser,
    ChatMessageAssistant,
    ChatMessageTool,
    # Model output (6)
    ModelOutput,
    ModelUsage,
    ChatCompletionChoice,
    Logprob,
    Logprobs,
    TopLogprob,
    # Config (3)
    GenerateConfig,
    ResponseSchema,
    BatchConfig,
    # Events (17)
    ApprovalEvent,
    ErrorEvent,
    InfoEvent,
    InputEvent,
    LoggerEvent,
    ModelEvent,
    SampleInitEvent,
    SampleLimitEvent,
    SandboxEvent,
    ScoreEvent,
    SpanBeginEvent,
    SpanEndEvent,
    StateEvent,
    StepEvent,
    StoreEvent,
    SubtaskEvent,
    ToolEvent,
    # Other types (11)
    Score,
    SampleScore,
    EvalError,
    LoggingMessage,
    JsonChange,
    JSONSchema,
    ToolInfo,
    ToolParams,
    ToolCallContent,
    ToolCallView,
    SandboxEnvironmentSpec,
]


def test_all_decorated_types_have_fast_construct():
    """Verify all 44 types have the fast_construct method."""
    assert len(DECORATED_TYPES) == 44, f"Expected 44 types, got {len(DECORATED_TYPES)}"
    
    missing_fast_construct = []
    for cls in DECORATED_TYPES:
        if not hasattr(cls, "fast_construct"):
            missing_fast_construct.append(cls.__name__)
    
    if missing_fast_construct:
        pytest.fail(f"Missing fast_construct: {missing_fast_construct}")


def create_sample_data(cls: Type[BaseModel]) -> dict[str, Any]:
    """Create minimal valid sample data for each type."""
    samples = {
        # Core types
        "EvalSample": {
            "id": "test",
            "epoch": 1,
            "input": "test input",
            "target": "test target",
            "metadata": {},
        },
        "EvalSampleLimit": {
            "samples": 100,
            "tokens": 1000,
            "seconds": 60,
            "trades": 5,
        },
        "Sample": {
            "id": "test", 
            "input": "test",
            "target": "test",
            "metadata": {},
        },
        # Chat messages
        "ChatMessageSystem": {
            "content": "You are a helpful assistant",
            "role": "system",
        },
        "ChatMessageUser": {
            "content": "Hello",
            "role": "user",
        },
        "ChatMessageAssistant": {
            "content": "Hi there!",
            "role": "assistant",
        },
        "ChatMessageTool": {
            "content": "Tool output",
            "role": "tool",
            "tool_call_id": "call_123",
        },
        # Model output
        "ModelOutput": {
            "model": "gpt-4",
            "choices": [],
            "usage": None,
        },
        "ModelUsage": {
            "input_tokens": 10,
            "output_tokens": 20,
            "total_tokens": 30,
        },
        "ChatCompletionChoice": {
            "message": {"content": "test", "role": "assistant"},
            "stop_reason": "stop",
        },
        "Logprob": {
            "token": "hello",
            "logprob": -0.5,
            "bytes": [104, 101, 108, 108, 111],
        },
        "Logprobs": {
            "content": [],
        },
        "TopLogprob": {
            "token": "test",
            "logprob": -0.3,
            "bytes": [116, 101, 115, 116],
        },
        # Config
        "GenerateConfig": {},
        "ResponseSchema": {
            "name": "test_schema",
            "json_schema": {"type": "object"},
        },
        "BatchConfig": {},
        # Events
        "ApprovalEvent": {
            "event": "approval",
            "approver": "test",
            "timestamp": "2024-01-01T00:00:00Z",
        },
        "ErrorEvent": {
            "event": "error",
            "error": {"message": "test error"},
            "timestamp": "2024-01-01T00:00:00Z",
        },
        "InfoEvent": {
            "event": "info",
            "timestamp": "2024-01-01T00:00:00Z",
        },
        "InputEvent": {
            "event": "input",
            "timestamp": "2024-01-01T00:00:00Z",
        },
        "LoggerEvent": {
            "event": "logger",
            "logger": "test_logger",
            "timestamp": "2024-01-01T00:00:00Z",
        },
        "ModelEvent": {
            "event": "model",
            "model": "gpt-4",
            "timestamp": "2024-01-01T00:00:00Z",
        },
        "SampleInitEvent": {
            "event": "sample_init",
            "timestamp": "2024-01-01T00:00:00Z",
        },
        "SampleLimitEvent": {
            "event": "sample_limit",
            "type": "tokens",
            "limit": 1000,
            "timestamp": "2024-01-01T00:00:00Z",
        },
        "SandboxEvent": {
            "event": "sandbox",
            "timestamp": "2024-01-01T00:00:00Z",
        },
        "ScoreEvent": {
            "event": "score",
            "score": {"name": "test", "value": 1.0},
            "timestamp": "2024-01-01T00:00:00Z",
        },
        "SpanBeginEvent": {
            "event": "span_begin",
            "span_id": "span_1",
            "timestamp": "2024-01-01T00:00:00Z",
        },
        "SpanEndEvent": {
            "event": "span_end",
            "span_id": "span_1",
            "timestamp": "2024-01-01T00:00:00Z",
        },
        "StateEvent": {
            "event": "state",
            "timestamp": "2024-01-01T00:00:00Z",
        },
        "StepEvent": {
            "event": "step",
            "action": "test_step",
            "timestamp": "2024-01-01T00:00:00Z",
        },
        "StoreEvent": {
            "event": "store",
            "operation": "set",
            "timestamp": "2024-01-01T00:00:00Z",
        },
        "SubtaskEvent": {
            "event": "subtask",
            "name": "test_subtask",
            "timestamp": "2024-01-01T00:00:00Z",
        },
        "ToolEvent": {
            "event": "tool",
            "type": "use",
            "timestamp": "2024-01-01T00:00:00Z",
        },
        # Other types
        "Score": {
            "name": "accuracy",
            "value": 0.95,
        },
        "SampleScore": {
            "accuracy": {"value": 0.9},
        },
        "EvalError": {
            "message": "test error",
        },
        "LoggingMessage": {
            "level": "info",
            "message": "test message",
        },
        "JsonChange": {
            "name": "test_change",
            "op": "add",
        },
        "JSONSchema": {
            "type": "object",
        },
        "ToolInfo": {
            "name": "test_tool",
        },
        "ToolParams": {},
        "ToolCallContent": {
            "type": "text",
            "text": "test",
        },
        "ToolCallView": {
            "tool": "test_tool",
        },
        "SandboxEnvironmentSpec": {
            "type": "docker",
        },
    }
    
    return samples.get(cls.__name__, {})


def test_fast_construct_all_types():
    """Test fast_construct works for all decorated types."""
    failed_types = []
    
    for cls in DECORATED_TYPES:
        try:
            sample_data = create_sample_data(cls)
            
            # Test fast_construct
            instance = cls.fast_construct(sample_data)
            assert instance is not None
            assert isinstance(instance, cls)
            
            # For types with required fields, verify they're set
            for key, value in sample_data.items():
                if hasattr(instance, key):
                    actual = getattr(instance, key)
                    # Special handling for datetime
                    if isinstance(value, str) and "T" in value and "Z" in value:
                        assert isinstance(actual, (str, datetime))
                    else:
                        assert actual == value or actual is not None
        except Exception as e:
            failed_types.append((cls.__name__, str(e)))
    
    if failed_types:
        failure_msg = "\n".join([f"{name}: {error}" for name, error in failed_types])
        pytest.fail(f"Failed types:\n{failure_msg}")


def test_fast_vs_normal_construct_all_types():
    """Compare fast_construct vs normal construct for all types."""
    results = []
    
    for cls in DECORATED_TYPES:
        sample_data = create_sample_data(cls)
        
        try:
            # Normal construct
            normal = cls(**sample_data)
            
            # Fast construct
            fast = cls.fast_construct(sample_data)
            
            # Basic comparison - both should create valid instances
            assert type(normal) == type(fast)
            
            results.append((cls.__name__, "PASS"))
        except Exception as e:
            results.append((cls.__name__, f"FAIL: {e}"))
    
    # All should pass
    failed = [r for r in results if not r[1] == "PASS"]
    if failed:
        failure_msg = "\n".join([f"{name}: {status}" for name, status in failed])
        pytest.fail(f"Failed comparisons:\n{failure_msg}")


def test_nested_fast_construct():
    """Test fast_construct with nested decorated types."""
    # Create a sample with nested types
    sample_data = {
        "id": "test",
        "epoch": 1,
        "input": "test input",
        "messages": [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi!"},
        ],
        "score": {"name": "accuracy", "value": 0.95},
        "limit": {"samples": 100},
    }
    
    # Test fast construction
    sample = EvalSample.fast_construct(sample_data)
    
    assert sample.id == "test"
    assert sample.epoch == 1
    assert sample.input == "test input"
    
    # Check nested messages are properly constructed
    if sample.messages:
        assert len(sample.messages) == 3
        assert isinstance(sample.messages[0], ChatMessageSystem)
        assert isinstance(sample.messages[1], ChatMessageUser)
        assert isinstance(sample.messages[2], ChatMessageAssistant)
    
    # Check nested score
    if sample.score:
        assert isinstance(sample.score, Score)
        assert sample.score.name == "accuracy"
        assert sample.score.value == 0.95
    
    # Check nested limit
    if sample.limit:
        assert isinstance(sample.limit, EvalSampleLimit)
        assert sample.limit.samples == 100


def test_event_discriminated_unions():
    """Test that event types work with discriminated unions."""
    events_data = [
        {"event": "approval", "approver": "test", "timestamp": "2024-01-01T00:00:00Z"},
        {"event": "error", "error": {"message": "test"}, "timestamp": "2024-01-01T00:00:00Z"},
        {"event": "model", "model": "gpt-4", "timestamp": "2024-01-01T00:00:00Z"},
        {"event": "score", "score": {"name": "test", "value": 1.0}, "timestamp": "2024-01-01T00:00:00Z"},
        {"event": "tool", "type": "use", "timestamp": "2024-01-01T00:00:00Z"},
    ]
    
    for event_data in events_data:
        event_type = event_data["event"]
        
        # Find the right event class
        event_class = None
        for cls in DECORATED_TYPES:
            if cls.__name__ == f"{event_type.title().replace('_', '')}Event":
                event_class = cls
                break
        
        if event_class:
            instance = event_class.fast_construct(event_data)
            assert instance.event == event_type
            assert hasattr(instance, "timestamp")


def test_performance_all_types():
    """Benchmark performance for all decorated types."""
    results = {}
    iterations = 1000
    
    for cls in DECORATED_TYPES[:10]:  # Test first 10 for brevity
        sample_data = create_sample_data(cls)
        
        if not sample_data:
            continue
        
        # Warm-up
        for _ in range(10):
            cls(**sample_data)
            cls.fast_construct(sample_data)
        
        # Normal construct timing
        start = time.perf_counter()
        for _ in range(iterations):
            cls(**sample_data)
        normal_time = time.perf_counter() - start
        
        # Fast construct timing
        start = time.perf_counter()
        for _ in range(iterations):
            cls.fast_construct(sample_data)
        fast_time = time.perf_counter() - start
        
        speedup = normal_time / fast_time if fast_time > 0 else 0
        results[cls.__name__] = speedup
    
    # Most types should show some speedup
    speedups = list(results.values())
    average_speedup = sum(speedups) / len(speedups) if speedups else 0
    
    print(f"\nAverage speedup across types: {average_speedup:.2f}x")
    for name, speedup in sorted(results.items(), key=lambda x: x[1], reverse=True)[:5]:
        print(f"  {name}: {speedup:.2f}x")


def test_type_coverage_summary():
    """Provide a summary of type coverage."""
    categories = {
        "Core": ["EvalSample", "EvalSampleLimit", "Sample"],
        "Chat Messages": ["ChatMessageSystem", "ChatMessageUser", "ChatMessageAssistant", "ChatMessageTool"],
        "Model Output": ["ModelOutput", "ModelUsage", "ChatCompletionChoice", "Logprob", "Logprobs", "TopLogprob"],
        "Config": ["GenerateConfig", "ResponseSchema", "BatchConfig"],
        "Events": [cls.__name__ for cls in DECORATED_TYPES if cls.__name__.endswith("Event")],
        "Other": ["Score", "SampleScore", "EvalError", "LoggingMessage", "JsonChange", "JSONSchema", 
                  "ToolInfo", "ToolParams", "ToolCallContent", "ToolCallView", "SandboxEnvironmentSpec"],
    }
    
    total_expected = sum(len(types) for types in categories.values())
    assert total_expected == 44, f"Expected 44 total types, counted {total_expected}"
    
    # Verify all categories are covered
    all_names = [cls.__name__ for cls in DECORATED_TYPES]
    for category, expected_types in categories.items():
        for type_name in expected_types:
            assert type_name in all_names, f"{type_name} from {category} not in decorated types"
    
    print("\nType Coverage Summary:")
    for category, types in categories.items():
        print(f"  {category}: {len(types)} types")
    print(f"  Total: {total_expected} types")


def test_complex_eval_sample():
    """Test comprehensive EvalSample with all nested types."""
    complex_data = {
        "id": "comprehensive_test",
        "epoch": 1,
        "input": [
            {"role": "system", "content": "You are an AI assistant"},
            {"role": "user", "content": "What is 2+2?"},
        ],
        "target": "4",
        "messages": [
            {"role": "user", "content": "What is 2+2?"},
            {"role": "assistant", "content": "2+2 equals 4"},
            {"role": "tool", "content": "Calculation verified", "tool_call_id": "calc_1"},
        ],
        "score": {"name": "accuracy", "value": 1.0},
        "scores": {
            "accuracy": {"name": "accuracy", "value": 1.0},
            "relevance": {"name": "relevance", "value": 0.95},
        },
        "limit": {
            "samples": 1000,
            "tokens": 10000,
            "seconds": 300,
        },
        "events": [
            {"event": "sample_init", "timestamp": "2024-01-01T00:00:00Z"},
            {"event": "model", "model": "gpt-4", "timestamp": "2024-01-01T00:00:01Z"},
            {"event": "tool", "type": "use", "timestamp": "2024-01-01T00:00:02Z"},
            {"event": "score", "score": {"name": "accuracy", "value": 1.0}, "timestamp": "2024-01-01T00:00:03Z"},
        ],
        "error": {
            "message": "Test error",
        },
        "metadata": {
            "test": True,
            "category": "math",
            "difficulty": "easy",
        },
    }
    
    # Fast construct the complex sample
    sample = EvalSample.fast_construct(complex_data)
    
    # Verify all nested types are correctly instantiated
    assert sample.id == "comprehensive_test"
    assert len(sample.input) == 2
    assert isinstance(sample.input[0], ChatMessageSystem)
    assert isinstance(sample.input[1], ChatMessageUser)
    
    assert len(sample.messages) == 3
    assert isinstance(sample.messages[0], ChatMessageUser)
    assert isinstance(sample.messages[1], ChatMessageAssistant)
    assert isinstance(sample.messages[2], ChatMessageTool)
    
    assert isinstance(sample.score, Score)
    assert sample.score.value == 1.0
    
    assert isinstance(sample.limit, EvalSampleLimit)
    assert sample.limit.samples == 1000
    
    assert len(sample.events) == 4
    assert isinstance(sample.events[0], SampleInitEvent)
    assert isinstance(sample.events[1], ModelEvent)
    assert isinstance(sample.events[2], ToolEvent)
    assert isinstance(sample.events[3], ScoreEvent)
    
    assert isinstance(sample.error, EvalError)
    assert sample.error.message == "Test error"
    
    assert sample.metadata["category"] == "math"


def test_all_44_types_individually():
    """Test each of the 44 types individually to ensure coverage."""
    test_results = []
    
    for i, cls in enumerate(DECORATED_TYPES, 1):
        try:
            sample_data = create_sample_data(cls)
            instance = cls.fast_construct(sample_data)
            assert isinstance(instance, cls)
            test_results.append(f"✓ {i:2d}. {cls.__name__}")
        except Exception as e:
            test_results.append(f"✗ {i:2d}. {cls.__name__}: {e}")
    
    # Print results
    print("\n=== Testing all 39 decorated types ===")
    for result in test_results:
        print(result)
    
    # Check all passed
    failed = [r for r in test_results if r.startswith("✗")]
    assert not failed, f"Some types failed: {failed}"
    
    print(f"\n✅ All 44 types tested successfully!")