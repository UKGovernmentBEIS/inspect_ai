---
title: "Scanners and Loaders"
---

## Overview

Scanners are a powerful feature in Inspect AI that allow you to analyze agent transcripts by processing messages and events. They can extract insights, compute metrics, and identify patterns in agent interactions.

## Scanners

### Basic Scanner Declaration

Scanners are declared using the `@scanner` decorator. You can either:
1. Explicitly specify filters (messages or events)
2. Let filters be inferred from type annotations (for specific types)
3. Provide a custom loader

#### Explicit Filters

``` python
from inspect_ai.scanner import Scanner, scanner
from inspect_ai.model import ChatMessage, ChatMessageUser, ChatMessageAssistant
from inspect_ai.scanner import Result

@scanner(messages=["user"])
def user_input_analyzer() -> Scanner[ChatMessageUser]:
    """Analyzes user inputs for question complexity and clarity."""
    
    async def scan(message: ChatMessageUser) -> Result | None:
        # Analyze question complexity, detect multi-part questions,
        # assess clarity and specificity of user requests
        complexity_score = analyze_complexity(message.text)
        clarity_score = assess_clarity(message.text)
        
        return Result(value={
            "complexity": complexity_score,
            "clarity": clarity_score,
            "word_count": len(message.text.split()),
            "has_code": "```" in message.text
        })
    
    return scan
```

#### Filter Inference from Type Annotations

For specific message and event types, filters can be automatically inferred from type annotations, making the API more concise.

```python
@scanner
def user_analyzer() -> Scanner[ChatMessageUser]:
    """Filter inferred as messages=['user'] from type."""
    
    async def scan(message: ChatMessageUser) -> Result | None:
        return Result(value={"text": message.text})
    
    return scan

# Works with unions too - infers messages=["system", "user"]
@scanner
def multi_analyzer() -> Scanner[ChatMessageSystem | ChatMessageUser]:
    """Filters inferred from union type."""
    
    async def scan(message: ChatMessageSystem | ChatMessageUser) -> Result | None:
        return Result(value={"role": message.role})
    
    return scan

# Also works with lists
@scanner
def batch_analyzer() -> Scanner[list[ChatMessageAssistant]]:
    """Filter inferred as messages=['assistant'] from list type."""
    
    async def scan(messages: list[ChatMessageAssistant]) -> Result | None:
        return Result(value={"count": len(messages)})
    
    return scan

# Event types work the same way
@scanner
def model_monitor() -> Scanner[ModelEvent]:
    """Filter inferred as events=['model'] from type."""
    
    async def scan(event: ModelEvent) -> Result | None:
        return Result(value={"model": event.model})
    
    return scan
```

**Note**: Filter inference only works for specific types. Base types like `ChatMessage`, `Event`, or `Transcript` still require explicit filters since they're too general to infer intent.

### Message Type Filters

Scanners can filter for specific message types or combinations (either explicitly or through inference):

``` python
# Single message type
@scanner(messages=["assistant"])
def response_quality_scorer() -> Scanner[ChatMessageAssistant]:
    """Scores the quality of assistant responses."""
    
    async def scan(message: ChatMessageAssistant) -> Result | None:
        # Evaluate response completeness, accuracy, helpfulness
        # Check for proper code formatting, citations, etc.
        score = evaluate_response_quality(message.text)
        
        return Result(value={
            "quality_score": score,
            "model": message.model,
            "response_length": len(message.text)
        })
    
    return scan

# Union of message types
@scanner(messages=["system", "user"])
def conversation_starter_detector() -> Scanner[ChatMessageSystem | ChatMessageUser]:
    """Detects conversation initialization patterns."""
    
    async def scan(message: ChatMessageSystem | ChatMessageUser) -> Result | None:
        # Identify system prompts and initial user queries
        # Classify conversation type and intent
        is_starter = message.role == "system" or is_initial_query(message.text)
        
        return Result(value={
            "is_conversation_start": is_starter,
            "message_role": message.role
        })
    
    return scan

# All message types
@scanner(messages="all")
def token_usage_tracker() -> Scanner[ChatMessage]:
    """Tracks token usage across all messages."""
    
    async def scan(message: ChatMessage) -> Result | None:
        # Count tokens for cost estimation
        # Track cumulative token usage
        token_count = estimate_tokens(message.text)
        
        return Result(value={
            "tokens": token_count,
            "role": message.role,
            "estimated_cost": token_count * 0.00001  # Example pricing
        })
    
    return scan
```

### Event Scanners

Scanners can also process events from the transcript:

``` python
from inspect_ai.log import ModelEvent, ToolEvent, ErrorEvent

@scanner(events=["model"])
def model_performance_monitor() -> Scanner[ModelEvent]:
    """Monitors model usage and inputs."""
    
    async def scan(event: ModelEvent) -> Result | None:
        # Track model usage, inputs, and tool availability
        # Analyze conversation patterns
        
        return Result(value={
            "model": event.model,
            "role": event.role,
            "input_message_count": len(event.input),
            "tools_available": len(event.tools),
            "timestamp": event.timestamp.isoformat(),
            "has_system_message": any(m.role == "system" for m in event.input)
        })
    
    return scan

@scanner(events=["tool"])
def tool_usage_analyzer() -> Scanner[ToolEvent]:
    """Analyzes tool usage patterns."""
    
    async def scan(event: ToolEvent) -> Result | None:
        # Track which tools are used most frequently
        # Analyze tool arguments and patterns
        
        return Result(value={
            "tool": event.function,
            "tool_id": event.id,
            "argument_count": len(event.arguments),
            "has_result": event.result is not None,
            "timestamp": event.timestamp.isoformat()
        })
    
    return scan

# Multiple event types
@scanner(events=["model", "tool", "error"])
def event_monitor() -> Scanner[ModelEvent | ToolEvent | ErrorEvent]:
    """Monitors different types of events in agent execution."""
    
    async def scan(event: ModelEvent | ToolEvent | ErrorEvent) -> Result | None:
        # Track different event types
        # Collect statistics on agent behavior
        
        if isinstance(event, ErrorEvent):
            return Result(value={
                "event_type": "error",
                "error_message": event.error.message,
                "error_type": event.error.type,
                "traceback_length": len(event.error.traceback) if event.error.traceback else 0
            })
        elif isinstance(event, ModelEvent):
            return Result(value={
                "event_type": "model",
                "model": event.model,
                "input_count": len(event.input)
            })
        elif isinstance(event, ToolEvent):
            return Result(value={
                "event_type": "tool",
                "function": event.function,
                "args_provided": list(event.arguments.keys())
            })
            
        return None
```

### Combined Message and Event Scanners

When you need both messages and events, the scanner receives the full `Transcript`:

``` python
from inspect_ai.scanner import Transcript

@scanner(messages=["user", "assistant"], events=["model"])
def conversation_analyzer() -> Scanner[Transcript]:
    """Analyzes conversation patterns by examining messages and model events."""
    
    async def scan(transcript: Transcript) -> Result | None:
        # Analyze conversation patterns
        # Track message counts and model usage
        
        user_messages = [m for m in transcript.messages if m.role == "user"]
        assistant_messages = [m for m in transcript.messages if m.role == "assistant"]
        model_events = [e for e in transcript.events if e.event == "model" and isinstance(e, ModelEvent)]
        
        # Calculate average message lengths
        avg_user_length = sum(len(m.text) for m in user_messages) / len(user_messages) if user_messages else 0
        avg_assistant_length = sum(len(m.text) for m in assistant_messages) / len(assistant_messages) if assistant_messages else 0
        
        # Analyze model usage
        models_used = list(set(e.model for e in model_events))
        
        return Result(value={
            "turn_count": len(user_messages),
            "avg_user_message_length": avg_user_length,
            "avg_assistant_message_length": avg_assistant_length,
            "model_calls": len(model_events),
            "models_used": models_used,
            "transcript_id": transcript.id
        })
    
    return scan
```

### List-based Scanners

Scanners can process lists of messages for batch analysis:

``` python
@scanner(messages=["assistant"])
def response_consistency_checker() -> Scanner[list[ChatMessageAssistant]]:
    """Checks consistency across multiple assistant responses."""
    
    async def scan(messages: list[ChatMessageAssistant]) -> Result | None:
        if len(messages) < 2:
            return None
            
        # Compare responses for consistency
        # Detect contradictions or significant variations
        # Measure response stability across the conversation
        
        consistency_scores = []
        for i in range(1, len(messages)):
            score = calculate_similarity(messages[i-1].text, messages[i].text)
            consistency_scores.append(score)
            
        return Result(value={
            "avg_consistency": sum(consistency_scores) / len(consistency_scores),
            "min_consistency": min(consistency_scores),
            "response_count": len(messages)
        })
    
    return scan
```

### Factory Pattern for Parameterized Scanners

Create configurable scanners using the factory pattern:

``` python
@scanner(messages=["assistant"])
def quality_threshold_scanner(
    min_score: float = 0.7,
    check_citations: bool = True,
    max_length: int = 5000
) -> Scanner[ChatMessageAssistant]:
    """Configurable scanner for response quality with custom thresholds."""
    
    async def scan(message: ChatMessageAssistant) -> Result | None:
        # Apply configurable quality checks
        quality_score = calculate_quality(message.text)
        
        issues = []
        if quality_score < min_score:
            issues.append("below_quality_threshold")
        if check_citations and not has_citations(message.text):
            issues.append("missing_citations")
        if len(message.text) > max_length:
            issues.append("response_too_long")
            
        if issues:
            return Result(value={
                "passed": False,
                "issues": issues,
                "quality_score": quality_score
            })
        
        return Result(value={
            "passed": True,
            "quality_score": quality_score
        })
    
    return scan

# Usage with different configurations
strict_scanner = quality_threshold_scanner(min_score=0.9, check_citations=True)
lenient_scanner = quality_threshold_scanner(min_score=0.5, check_citations=False)
```

## Loaders

Loaders transform transcript data before it reaches scanners, enabling custom data preprocessing and type transformations.

### Basic Loader Declaration

Loaders are declared with the `@loader` decorator and can also specify message and event filters:

``` python
from typing import AsyncGenerator, Sequence
from dataclasses import dataclass
from datetime import datetime
from inspect_ai.scanner import Loader, loader

# Custom data types for loader examples
@dataclass
class EnrichedMessage:
    original: ChatMessageAssistant
    sentiment: str
    complexity: float
    topics: list[str]

@dataclass
class EventSummary:
    model_event_count: int
    tool_event_count: int
    models_used: list[str]
    window_start: datetime
    window_end: datetime

@loader(messages=["assistant"])
def assistant_message_enricher() -> Loader[EnrichedMessage]:
    """Enriches assistant messages with additional metadata."""
    
    async def load(
        transcripts: Transcript | Sequence[Transcript]
    ) -> AsyncGenerator[EnrichedMessage, None]:
        if isinstance(transcripts, Transcript):
            transcripts = [transcripts]
            
        for transcript in transcripts:
            for message in transcript.messages:
                if message.role == "assistant" and isinstance(message, ChatMessageAssistant):
                    # Enrich message with additional computed metadata
                    enriched = EnrichedMessage(
                        original=message,
                        sentiment=analyze_sentiment(message.text),
                        complexity=calculate_complexity(message.text),
                        topics=extract_topics(message.text)
                    )
                    yield enriched
    
    return load
```

### Event Loaders

Loaders can filter and transform events:

``` python
@loader(events=["model", "tool"])
def event_aggregator() -> Loader[EventSummary]:
    """Aggregates model and tool events into summaries."""
    
    async def load(
        transcripts: Transcript | Sequence[Transcript]
    ) -> AsyncGenerator[EventSummary, None]:
        if isinstance(transcripts, Transcript):
            transcripts = [transcripts]
            
        for transcript in transcripts:
            # Aggregate events in sliding windows
            window_size = 10
            events = [e for e in transcript.events if e.event in ["model", "tool"]]
            
            for i in range(0, len(events), window_size):
                window = events[i:i+window_size]
                if window:
                    # Count event types
                    model_count = sum(1 for e in window if e.event == "model")
                    tool_count = sum(1 for e in window if e.event == "tool")
                    
                    # Get unique models used
                    models = list(set(e.model for e in window 
                                     if hasattr(e, 'model') and e.model))
                    
                    summary = EventSummary(
                        model_event_count=model_count,
                        tool_event_count=tool_count,
                        models_used=models,
                        window_start=window[0].timestamp,
                        window_end=window[-1].timestamp
                    )
                    yield summary
    
    return load
```

### Combining Loaders with Scanners

Loaders enable scanners to work with custom data types:

``` python
# Define a custom data type
@dataclass
class ConversationTurn:
    user_message: ChatMessageUser
    assistant_response: ChatMessageAssistant
    model_event: ModelEvent
    turn_number: int

# Create a loader that produces conversation turns
@loader(messages=["user", "assistant"], events=["model"])
def conversation_turn_loader() -> Loader[ConversationTurn]:
    """Groups messages and events into conversation turns."""
    
    async def load(
        transcripts: Transcript | Sequence[Transcript]
    ) -> AsyncGenerator[ConversationTurn, None]:
        if isinstance(transcripts, Transcript):
            transcripts = [transcripts]
            
        for transcript in transcripts:
            # Pair user messages with subsequent assistant responses
            # and their associated model events
            user_messages = [m for m in transcript.messages if m.role == "user"]
            assistant_messages = [m for m in transcript.messages if m.role == "assistant"]
            model_events = [e for e in transcript.events if e.event == "model"]
            
            for i, (user_msg, asst_msg, model_evt) in enumerate(
                zip(user_messages, assistant_messages, model_events)
            ):
                yield ConversationTurn(
                    user_message=user_msg,
                    assistant_response=asst_msg,
                    model_event=model_evt,
                    turn_number=i + 1
                )
    
    return load

# Use the loader with a scanner
@scanner(loader=conversation_turn_loader())
def turn_analyzer() -> Scanner[ConversationTurn]:
    """Analyzes individual conversation turns."""
    
    async def scan(turn: ConversationTurn) -> Result | None:
        # Analyze each conversation turn
        # Compare input and output characteristics
        
        input_length = len(turn.user_message.text)
        output_length = len(turn.assistant_response.text)
        
        # Analyze the model event
        tools_available = len(turn.model_event.tools) if hasattr(turn.model_event, 'tools') else 0
        
        return Result(value={
            "turn_number": turn.turn_number,
            "input_length": input_length,
            "output_length": output_length,
            "length_ratio": output_length / input_length if input_length > 0 else 0,
            "model_used": turn.model_event.model,
            "tools_available": tools_available,
            "timestamp": turn.model_event.timestamp.isoformat()
        })
    
    return scan
```

### Advanced Loader Patterns

Loaders can implement complex data transformations:

``` python
@loader(messages="all", events="all")
def context_window_loader(window_size: int = 5) -> Loader[ContextWindow]:
    """Creates sliding context windows over the transcript."""
    
    async def load(
        transcripts: Transcript | Sequence[Transcript]
    ) -> AsyncGenerator[ContextWindow, None]:
        if isinstance(transcripts, Transcript):
            transcripts = [transcripts]
            
        for transcript in transcripts:
            messages = transcript.messages
            
            # Generate sliding windows of messages with surrounding context
            for i in range(len(messages)):
                start = max(0, i - window_size)
                end = min(len(messages), i + window_size + 1)
                
                window = ContextWindow(
                    focal_message=messages[i],
                    before_context=messages[start:i],
                    after_context=messages[i+1:end],
                    relevant_events=[
                        e for e in transcript.events
                        # Include recent events based on position in list
                        if transcript.events.index(e) <= i * 2  # Rough heuristic
                    ][:10]  # Limit to 10 most relevant events
                )
                yield window
    
    return load

# Scanner using the context window loader
@scanner(loader=context_window_loader(window_size=3))
def context_coherence_analyzer() -> Scanner[ContextWindow]:
    """Analyzes coherence within context windows."""
    
    async def scan(window: ContextWindow) -> Result | None:
        # Evaluate how well the focal message fits its context
        # Detect topic shifts, non-sequiturs, or context violations
        
        coherence_score = calculate_coherence(
            window.focal_message,
            window.before_context,
            window.after_context
        )
        
        return Result(value={
            "focal_role": window.focal_message.role,
            "coherence": coherence_score,
            "context_size": len(window.before_context) + len(window.after_context),
            "has_topic_shift": detect_topic_shift(window)
        })
    
    return scan
```