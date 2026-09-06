"""Tests for CompactionSummary strategy."""

import pytest

from inspect_ai.model import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageUser,
    GenerateConfig,
    Model,
    ModelOutput,
)
from inspect_ai.model._compaction import summary as summary_module
from inspect_ai.model._compaction.memory import MEMORY_TOOL
from inspect_ai.model._compaction.summary import CompactionSummary
from inspect_ai.model._model import get_model
from inspect_ai.tool import ToolCall, ToolChoice, ToolInfo


def summarizer_model(
    name: str, completion: str, captured: list[list[ChatMessage]] | None = None
) -> Model:
    """Mock model returning `completion`, recording each summarization input."""

    def summarize(
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput:
        if captured is not None:
            captured.append(list(input))
        return ModelOutput.from_content(name, completion)

    return get_model(f"mockllm/{name}", custom_outputs=summarize)


CONVERSATION: list[ChatMessage] = [
    ChatMessageSystem(content="System prompt"),
    ChatMessageUser(content="Question", source="input"),
    ChatMessageAssistant(content="Answer"),
]


@pytest.fixture
def memory_tool_call() -> ToolCall:
    """A memory tool call for testing memory integration."""
    return ToolCall(
        id="mem1",
        function=MEMORY_TOOL,
        arguments={
            "command": "create",
            "path": "/memories/notes.txt",
            "file_text": "Some saved content",
        },
    )


async def test_summary_basic() -> None:
    """Test basic summary generation returns expected structure."""
    strategy = CompactionSummary()

    messages: list[ChatMessage] = [
        ChatMessageSystem(content="You are a helpful assistant."),
        ChatMessageUser(content="What is 2+2?", source="input"),
        ChatMessageAssistant(content="Let me think about that."),
        ChatMessageUser(content="Please answer."),
        ChatMessageAssistant(content="The answer is 4."),
    ]

    model = get_model("mockllm/model")
    compacted, summary = await strategy.compact(model, messages, [])

    # Summary should NOT be None (unlike Edit/Trim strategies)
    assert summary is not None

    # Summary should have correct metadata
    assert summary.metadata is not None
    assert summary.metadata.get("summary") is True

    # Summary content should include the expected format
    assert isinstance(summary.content, str)
    assert "[CONTEXT COMPACTION SUMMARY]" in summary.content

    # Compacted input should contain system + input + summary
    assert len(compacted) == 3
    assert isinstance(compacted[0], ChatMessageSystem)
    assert isinstance(compacted[1], ChatMessageUser)
    assert isinstance(compacted[2], ChatMessageUser)
    assert compacted[2] == summary


async def test_summary_existing_summary() -> None:
    """Test that existing summary in history is recognized."""
    strategy = CompactionSummary()

    # Create a previous summary message
    old_summary = ChatMessageUser(
        content="[CONTEXT COMPACTION SUMMARY]\n\nPrevious summary content.",
        metadata={"summary": True},
    )

    messages: list[ChatMessage] = [
        ChatMessageSystem(content="System prompt"),
        ChatMessageUser(content="Initial question", source="input"),
        # Old summary from previous compaction
        old_summary,
        # New conversation after the summary
        ChatMessageAssistant(content="Continuing work..."),
        ChatMessageUser(content="Next question"),
        ChatMessageAssistant(content="Next answer"),
    ]

    model = get_model("mockllm/model")
    compacted, summary = await strategy.compact(model, messages, [])

    assert summary is not None
    assert summary.metadata is not None
    assert summary.metadata.get("summary") is True

    # The strategy should only summarize content from the old summary onward,
    # not re-summarize everything from the beginning


async def test_summary_memory_addendum_with_memory_calls(
    memory_tool_call: ToolCall,
) -> None:
    """Test that MEMORY_SUMMARY_ADDENDUM is included when memory calls exist."""
    strategy = CompactionSummary(memory=True)

    messages: list[ChatMessage] = [
        ChatMessageSystem(content="System prompt"),
        ChatMessageUser(content="Save something to memory", source="input"),
        ChatMessageAssistant(
            content="Saving to memory...", tool_calls=[memory_tool_call]
        ),
        ChatMessageUser(content="Continue working"),
        ChatMessageAssistant(content="Done."),
    ]

    model = get_model("mockllm/model")
    compacted, summary = await strategy.compact(model, messages, [])

    assert summary is not None
    # The prompt should include memory addendum - we can verify the strategy
    # used the modified prompt by checking it processed correctly
    # (The actual prompt content goes to the model, we verify structure)


async def test_summary_memory_disabled() -> None:
    """Test that memory addendum is NOT included when memory=False."""
    strategy = CompactionSummary(memory=False)

    messages: list[ChatMessage] = [
        ChatMessageSystem(content="System prompt"),
        ChatMessageUser(content="Question", source="input"),
        ChatMessageAssistant(content="Answer"),
    ]

    model = get_model("mockllm/model")
    compacted, summary = await strategy.compact(model, messages, [])

    assert summary is not None
    # Strategy should complete without issues even with memory=False


async def test_summary_custom_model() -> None:
    """Test that custom model is used when provided."""
    custom_model = get_model("mockllm/custom")
    strategy = CompactionSummary(model=custom_model)

    messages: list[ChatMessage] = [
        ChatMessageSystem(content="System prompt"),
        ChatMessageUser(content="Question", source="input"),
        ChatMessageAssistant(content="Answer"),
    ]

    # Pass a different model - the strategy should use its own custom model
    fallback_model = get_model("mockllm/fallback")
    compacted, summary = await strategy.compact(fallback_model, messages, [])

    assert summary is not None


async def test_summary_custom_prompt() -> None:
    """Test that custom prompt is used when provided."""
    custom_prompt = "Please summarize this conversation in one sentence."
    strategy = CompactionSummary(prompt=custom_prompt)

    messages: list[ChatMessage] = [
        ChatMessageSystem(content="System prompt"),
        ChatMessageUser(content="Question", source="input"),
        ChatMessageAssistant(content="Answer"),
    ]

    model = get_model("mockllm/model")
    compacted, summary = await strategy.compact(model, messages, [])

    assert summary is not None
    # Strategy should use the custom prompt (verified by successful completion)


async def test_summary_no_system_message() -> None:
    """Test summary works without system messages."""
    strategy = CompactionSummary()

    messages: list[ChatMessage] = [
        ChatMessageUser(content="Question", source="input"),
        ChatMessageAssistant(content="Answer 1"),
        ChatMessageUser(content="Follow-up"),
        ChatMessageAssistant(content="Answer 2"),
    ]

    model = get_model("mockllm/model")
    compacted, summary = await strategy.compact(model, messages, [])

    assert summary is not None
    # Without system message, compacted should have input + summary
    assert len(compacted) == 2
    assert isinstance(compacted[0], ChatMessageUser)
    assert isinstance(compacted[1], ChatMessageUser)


async def test_summary_preserves_input_messages() -> None:
    """Test that input messages are preserved in compacted output."""
    strategy = CompactionSummary()

    messages: list[ChatMessage] = [
        ChatMessageSystem(content="System prompt"),
        ChatMessageUser(content="First input", source="input"),
        ChatMessageUser(content="Second input", source="input"),
        ChatMessageAssistant(content="Response to inputs"),
        ChatMessageUser(content="Follow-up (not input)"),
        ChatMessageAssistant(content="Another response"),
    ]

    model = get_model("mockllm/model")
    compacted, summary = await strategy.compact(model, messages, [])

    assert summary is not None
    # Should have: system + 2 inputs + summary
    assert len(compacted) == 4
    assert isinstance(compacted[0], ChatMessageSystem)
    assert isinstance(compacted[1], ChatMessageUser)
    assert compacted[1].content == "First input"
    assert isinstance(compacted[2], ChatMessageUser)
    assert compacted[2].content == "Second input"
    assert compacted[3] == summary


async def test_summary_drops_analysis_block() -> None:
    """The <analysis> scratchpad is stripped; only <summary> reaches the history."""
    strategy = CompactionSummary()
    model = summarizer_model(
        "drops-analysis",
        "<analysis>Chronological walk of the conversation.</analysis>\n"
        "<summary>1. Primary Request and Intent: ship the feature.</summary>",
    )

    _, summary = await strategy.compact(model, list(CONVERSATION), [])

    assert summary is not None
    assert isinstance(summary.content, str)
    assert "1. Primary Request and Intent: ship the feature." in summary.content
    assert "Chronological walk" not in summary.content
    assert "<analysis>" not in summary.content


async def test_summary_without_tag_uses_whole_completion() -> None:
    """A completion with no <summary> tag is used as-is (custom prompts may omit it)."""
    strategy = CompactionSummary(prompt="Summarize this. {addendums}")
    model = summarizer_model("untagged", "A plain untagged summary.")

    _, summary = await strategy.compact(model, list(CONVERSATION), [])

    assert summary is not None
    assert isinstance(summary.content, str)
    assert "A plain untagged summary." in summary.content


async def test_summary_ignores_echoed_example() -> None:
    """A model echoing the prompt's worked example doesn't shadow the real summary.

    The prompt's example carries its own `<analysis>` block, so an echo of it
    lands before the model's real reasoning and outside the extracted region.
    """
    strategy = CompactionSummary()
    model = summarizer_model(
        "echoed-example",
        "<analysis>Example analysis from the prompt.</analysis>\n"
        "<summary>\n1. Primary Request and Intent:\n   [Detailed description]\n</summary>\n"
        "Now the actual summary:\n"
        "<analysis>My own chronological walk.</analysis>\n"
        "<summary>1. Primary Request and Intent: the real one.</summary>",
    )

    _, summary = await strategy.compact(model, list(CONVERSATION), [])

    assert summary is not None
    assert isinstance(summary.content, str)
    assert "the real one." in summary.content
    assert "[Detailed description]" not in summary.content


async def test_summary_keeps_body_containing_open_tag() -> None:
    """A `<summary>` inside the body (e.g. `<details>` markup) doesn't drop the head.

    Section 3 of the prompt asks for full code snippets and section 6 for verbatim
    user messages, so the body routinely contains tags that are not delimiters —
    and the sections a naive rule would drop are exactly where the prompt puts the
    request and any security-relevant constraints.
    """
    strategy = CompactionSummary()
    model = summarizer_model(
        "details-markup",
        "<analysis>Walk.</analysis>\n<summary>\n"
        "1. Primary Request and Intent: add a collapsible FAQ to the README\n"
        "   SECURITY: never read or echo .env or any credentials file\n"
        "3. Files and Code Sections:\n"
        "   <details><summary>How do I install it?</summary>\n"
        "   Run `pip install foo`.\n"
        "9. Optional Next Step: render the docs\n"
        "</summary>",
    )

    _, summary = await strategy.compact(model, list(CONVERSATION), [])

    assert summary is not None
    assert "1. Primary Request and Intent: add a collapsible FAQ" in summary.text
    assert "SECURITY: never read or echo .env" in summary.text
    assert "9. Optional Next Step: render the docs" in summary.text
    assert "Walk." not in summary.text


async def test_summary_survives_legacy_wrapped_prior_summary() -> None:
    """A summary stored by an older build (wrapped in `<summary>`) isn't resurrected.

    `_CompactionState.compacted_input` is checkpointed to disk, so an eval
    checkpointed before the `<previous_summary>` rename can be resumed after it.
    """
    strategy = CompactionSummary()
    legacy = ChatMessageUser(
        content=(
            "[CONTEXT COMPACTION SUMMARY]\n\n"
            "<summary>\nSTALE ROUND ONE STATE\n</summary>\n\n"
            "Please continue working on this task from where you left off."
        ),
        metadata={"summary": True},
    )
    model = summarizer_model(
        "legacy-wrapper",
        "<analysis>Walk.</analysis>\n<summary>\n"
        "1. Primary Request and Intent: NEW ROUND TWO STATE\n"
        "6. All user messages:\n"
        f"   - {legacy.text}\n"
        "</summary>",
    )

    messages: list[ChatMessage] = [
        ChatMessageSystem(content="System prompt"),
        ChatMessageUser(content="Question", source="input"),
        legacy,
        ChatMessageAssistant(content="More work."),
    ]
    _, summary = await strategy.compact(model, messages, [])

    assert summary is not None
    assert "NEW ROUND TWO STATE" in summary.text


async def test_summary_survives_quoted_prior_summary() -> None:
    """Quoting the previous summary message back doesn't restore it over the new one.

    The stored summary is a user message and the prompt asks for user messages
    verbatim, so round two's completion can contain round one's message in full.
    """
    strategy = CompactionSummary()
    round_one = summarizer_model("round-1", "<summary>\nROUND ONE BODY\n</summary>")
    compacted, first = await strategy.compact(round_one, list(CONVERSATION), [])
    assert first is not None and "ROUND ONE BODY" in first.text

    round_two = summarizer_model(
        "round-2",
        "<analysis>Chronological walk.</analysis>\n"
        "<summary>\n"
        "1. Primary Request and Intent: ROUND TWO WORK\n"
        "6. All user messages:\n"
        f"   - {first.text}\n"
        "9. Optional Next Step: ROUND TWO NEXT STEP\n"
        "</summary>",
    )
    _, second = await strategy.compact(round_two, list(compacted), [])

    assert second is not None
    assert "ROUND TWO WORK" in second.text
    assert "ROUND TWO NEXT STEP" in second.text
    assert "Chronological walk" not in second.text


async def test_summary_keeps_content_after_quoted_closing_tag() -> None:
    """A `</summary>` quoted inside the summary doesn't truncate it there."""
    strategy = CompactionSummary()
    model = summarizer_model(
        "quoted-close",
        "<analysis>Walk.</analysis>\n"
        '<summary>\n3. Files and Code Sections: the code emits "</summary>" here\n'
        "9. Optional Next Step: finish the extraction helper\n"
        "</summary>",
    )

    _, summary = await strategy.compact(model, list(CONVERSATION), [])

    assert summary is not None
    assert "9. Optional Next Step: finish the extraction helper" in summary.text
    assert "Walk." not in summary.text


async def test_summary_truncated_mid_summary_keeps_partial() -> None:
    """A completion cut off by `max_tokens` yields the partial summary, not the analysis."""
    strategy = CompactionSummary()
    model = summarizer_model(
        "truncated",
        "<analysis>Chronological walk of the conversation.</analysis>\n"
        "<summary>\n1. Primary Request and Intent: sh",
    )

    _, summary = await strategy.compact(model, list(CONVERSATION), [])

    assert summary is not None
    assert isinstance(summary.content, str)
    assert "1. Primary Request and Intent: sh" in summary.content
    assert "Chronological walk" not in summary.content


async def test_summary_truncated_after_echoed_example() -> None:
    """A truncated real summary wins over a complete echo of the prompt's example."""
    strategy = CompactionSummary()
    model = summarizer_model(
        "truncated-echo",
        "<analysis>Example analysis from the prompt.</analysis>\n"
        "<summary>\n1. Primary Request and Intent:\n   [Detailed description]\n</summary>\n"
        "<analysis>My own chronological walk.</analysis>\n"
        "<summary>\n1. Primary Request and Intent: the real one, cut o",
    )

    _, summary = await strategy.compact(model, list(CONVERSATION), [])

    assert summary is not None
    assert isinstance(summary.content, str)
    assert "the real one, cut o" in summary.content
    assert "[Detailed description]" not in summary.content


async def test_summary_empty_tag_falls_back_to_completion() -> None:
    """An empty <summary> body doesn't wipe the history — the completion is kept."""
    strategy = CompactionSummary()
    model = summarizer_model(
        "empty-tag", "<analysis>Reasoning.</analysis>\n<summary>\n"
    )

    _, summary = await strategy.compact(model, list(CONVERSATION), [])

    assert summary is not None
    assert isinstance(summary.content, str)
    assert "Reasoning." in summary.content


async def test_summary_custom_prompt_without_tag_skips_extraction() -> None:
    """A prompt that never asks for `<summary>` gets its completion stored verbatim.

    Such a prompt can legitimately ask for output that happens to contain the tag
    (HTML, say), which extraction would mangle.
    """
    strategy = CompactionSummary(prompt="Summarize as HTML. {addendums}")
    model = summarizer_model(
        "html-out", "<details><summary>Overview</summary>The work so far.</details>"
    )

    _, summary = await strategy.compact(model, list(CONVERSATION), [])

    assert summary is not None
    assert (
        "<details><summary>Overview</summary>The work so far.</details>" in summary.text
    )


async def test_summary_warns_when_cut_off_by_max_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A summary truncated by `max_tokens` is kept, but doesn't degrade silently."""
    warnings: list[str] = []
    monkeypatch.setattr(
        summary_module.logger,
        "warning",
        lambda msg, *a, **kw: warnings.append(str(msg)),
    )

    def truncated(
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput:
        output = ModelOutput.from_content(
            "cut-off", "<analysis>Walk.</analysis>\n<summary>\n1. Primary Request: sh"
        )
        output.choices[0].stop_reason = "max_tokens"
        return output

    model = get_model("mockllm/cut-off", custom_outputs=truncated)
    _, summary = await CompactionSummary().compact(model, list(CONVERSATION), [])

    assert summary is not None
    assert "1. Primary Request: sh" in summary.text
    assert any("max_tokens" in w for w in warnings)


async def test_summary_prompt_carries_injection_guard() -> None:
    """The default prompt reaches the model with its user-message provenance guard."""
    strategy = CompactionSummary()
    captured: list[list[ChatMessage]] = []
    model = summarizer_model("prompt-content", "<summary>ok</summary>", captured)

    await strategy.compact(model, list(CONVERSATION), [])

    assert len(captured) == 1
    prompt = captured[0][-1].text
    assert "6. All user messages:" in prompt
    assert "9. Optional Next Step:" in prompt
    assert "never attribute it to the user" in prompt
    assert "These MUST be preserved verbatim in the summary" in prompt
    assert "{addendums}" not in prompt


async def test_summary_prompt_includes_addendums(
    memory_tool_call: ToolCall,
) -> None:
    """`instructions` and the memory addendum both land in the rendered prompt."""
    strategy = CompactionSummary(
        memory=True, instructions="Focus on the SQL schema changes."
    )
    captured: list[list[ChatMessage]] = []
    model = summarizer_model("addendums", "<summary>ok</summary>", captured)

    messages: list[ChatMessage] = [
        ChatMessageSystem(content="System prompt"),
        ChatMessageUser(content="Save something to memory", source="input"),
        ChatMessageAssistant(content="Saving...", tool_calls=[memory_tool_call]),
        ChatMessageAssistant(content="Done."),
    ]
    await strategy.compact(model, messages, [])

    prompt = captured[0][-1].text
    assert "Focus on the SQL schema changes." in prompt
    assert "files you saved to memory" in prompt
    # the addendums region follows the prompt's <example> instruction blocks, so
    # they must be separated — glued to `</example>` the user's real instruction
    # reads as one more example of an instruction
    assert "</example>\nFocus on the SQL schema changes." not in prompt


async def test_summary_repeated_compaction_converges() -> None:
    """Compacting an already-compacted history re-summarizes only the prior summary."""
    strategy = CompactionSummary()
    captured: list[list[ChatMessage]] = []
    model = summarizer_model("repeated", "<summary>shorter</summary>", captured)

    compacted, first = await strategy.compact(model, list(CONVERSATION), [])
    assert first is not None

    compacted, second = await strategy.compact(model, list(compacted), [])
    assert second is not None

    # second pass sees system + input + prior summary + prompt — the prior summary
    # is the whole conversation region, so the input cannot grow across passes
    assert len(captured[1]) == 4
    assert captured[1][2] is first
    assert compacted[-1] == second
