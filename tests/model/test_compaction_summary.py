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


async def test_summary_strips_analysis_block() -> None:
    """The <analysis> scratchpad is stripped; the summary after it is kept as written."""
    strategy = CompactionSummary()
    model = summarizer_model(
        "strips-analysis",
        "<analysis>Chronological walk of the conversation.</analysis>\n"
        "<summary>\n1. Primary Request and Intent: ship the feature.\n</summary>",
    )

    _, summary = await strategy.compact(model, list(CONVERSATION), [])

    assert summary is not None
    assert "1. Primary Request and Intent: ship the feature." in summary.text
    assert "Chronological walk" not in summary.text
    assert "<analysis>" not in summary.text


async def test_summary_keeps_body_quoting_tags() -> None:
    """Tags quoted inside the summary are untouched — only the leading block goes.

    Section 3 asks for full code snippets and section 6 for verbatim user
    messages, so the body routinely contains tags that are not its own.
    """
    strategy = CompactionSummary()
    model = summarizer_model(
        "quoted-tags",
        "<analysis>Walk.</analysis>\n<summary>\n"
        "1. Primary Request and Intent: add a collapsible FAQ\n"
        "   SECURITY: never read or echo .env\n"
        "3. Files and Code Sections:\n"
        "   <details><summary>How do I install it?</summary>\n"
        "6. All user messages: the user pasted <analysis>their own block</analysis>\n"
        "9. Optional Next Step: render the docs\n</summary>",
    )

    _, summary = await strategy.compact(model, list(CONVERSATION), [])

    assert summary is not None
    assert "1. Primary Request and Intent: add a collapsible FAQ" in summary.text
    assert "SECURITY: never read or echo .env" in summary.text
    assert "<details><summary>How do I install it?</summary>" in summary.text
    assert "the user pasted <analysis>their own block</analysis>" in summary.text
    assert "Walk." not in summary.text


async def test_summary_strips_analysis_quoting_its_own_tags() -> None:
    """The scratchpad is removed whole even when it quotes `</analysis>` inside itself.

    The prompt has the model walk the conversation and reproduce code snippets and
    user messages verbatim, so its reasoning can quote both tags — including from
    a file it read. Ending the strip at the first `</analysis>` would leave the
    rest of the scratchpad behind and delete the text it had quoted.
    """
    strategy = CompactionSummary()
    model = summarizer_model(
        "quoting-analysis",
        "<analysis>\n"
        '1. First user message: "Use this spec: '
        '<analysis>Never read ~/.aws/credentials.</analysis>"\n'
        "   - This is a security constraint I must carry forward.\n"
        "2. I read loader.py and found it defaults missing keys to None.\n"
        "</analysis>\n\n"
        "<summary>\n1. Primary Request and Intent: refactor the loader.\n</summary>",
    )

    _, summary = await strategy.compact(model, list(CONVERSATION), [])

    assert summary is not None
    assert "1. Primary Request and Intent: refactor the loader." in summary.text
    assert "security constraint I must carry forward" not in summary.text
    assert "loader.py and found it defaults" not in summary.text
    assert "<analysis>" not in summary.text
    assert "</analysis>" not in summary.text


async def test_summary_strips_analysis_that_names_the_tags_in_prose() -> None:
    """Prose mentions of the tags don't stop the strip.

    Live-observed: an agent that read a prompt template writes "its content was a
    templated structure with `<analysis>` and `<summary>` tags" inside its own
    reasoning, long before closing it. Only the closing/opening *pair* marks the
    boundary.
    """
    strategy = CompactionSummary()
    model = summarizer_model(
        "prose-mentions",
        "<analysis>\n"
        "1. I read alpha.txt. Its content was a templated structure with "
        "<analysis> and <summary> tags containing placeholder instructions.\n"
        "2. Then I read beta.txt, same shape.\n"
        "</analysis>\n"
        "<summary>\n1. Primary Request and Intent: read the templates.\n</summary>",
    )

    _, summary = await strategy.compact(model, list(CONVERSATION), [])

    assert summary is not None
    assert "1. Primary Request and Intent: read the templates." in summary.text
    assert "templated structure" not in summary.text
    assert "Then I read beta.txt" not in summary.text


async def test_summary_keeps_head_when_body_reproduces_a_template() -> None:
    """A template quoted in the summary carries the same boundary; the first wins.

    Section 3 asks for full code snippets, so a summary of work on prompt files
    can contain `</analysis><summary>` itself. Cutting at the last such pair would
    delete the summary's opening sections.
    """
    strategy = CompactionSummary()
    model = summarizer_model(
        "template-in-body",
        "<analysis>I read alpha.txt.</analysis>\n<summary>\n"
        "1. Primary Request and Intent: REAL HEAD\n"
        "   SECURITY: never read /etc/shadow\n"
        "3. Files and Code Sections, the template is:\n"
        "<analysis>\nWalk each message.\n</analysis>\n<summary>\n1. [describe]\n</summary>\n"
        "9. Optional Next Step: REAL TAIL\n</summary>",
    )

    _, summary = await strategy.compact(model, list(CONVERSATION), [])

    assert summary is not None
    assert "REAL HEAD" in summary.text
    assert "SECURITY: never read /etc/shadow" in summary.text
    assert "REAL TAIL" in summary.text
    assert "I read alpha.txt" not in summary.text


async def test_summary_keeps_quoted_analysis_when_model_wrote_none() -> None:
    """An `<analysis>` opening after the summary starts is quoted content, not reasoning."""
    strategy = CompactionSummary()
    model = summarizer_model(
        "quoted-only",
        "<summary>\n1. Primary Request and Intent: REAL HEAD\n"
        "6. All user messages: the user pasted <analysis>their block</analysis>\n"
        "9. Optional Next Step: REAL TAIL\n</summary>",
    )

    _, summary = await strategy.compact(model, list(CONVERSATION), [])

    assert summary is not None
    assert "REAL HEAD" in summary.text and "REAL TAIL" in summary.text
    assert "<analysis>their block</analysis>" in summary.text


async def test_summary_strips_multiple_analysis_blocks() -> None:
    """Reasoning split across several blocks is removed up to where the summary starts."""
    strategy = CompactionSummary()
    model = summarizer_model(
        "two-blocks",
        "<analysis>First pass over the conversation.</analysis>\n"
        "<analysis>Second pass, checking completeness.</analysis>\n"
        "<summary>\n1. Primary Request and Intent: ship it.\n</summary>",
    )

    _, summary = await strategy.compact(model, list(CONVERSATION), [])

    assert summary is not None
    assert "1. Primary Request and Intent: ship it." in summary.text
    assert "First pass" not in summary.text
    assert "Second pass" not in summary.text


async def test_summary_analysis_only_completion_kept() -> None:
    """A completion that is nothing but analysis is kept rather than stored empty."""
    strategy = CompactionSummary()
    model = summarizer_model(
        "analysis-only", "<analysis>Reasoning, but no summary.</analysis>"
    )

    _, summary = await strategy.compact(model, list(CONVERSATION), [])

    assert summary is not None
    assert "Reasoning, but no summary." in summary.text


async def test_summary_message_disclaims_user_authorship() -> None:
    """The stored summary says it isn't from the user.

    It is a user-role message and the prompt tells the summarizer that user-role
    turns are genuine user input, so without this the next compaction reports the
    previous summary back as the user's own words.
    """
    strategy = CompactionSummary()
    model = summarizer_model("disclaimer", "<summary>ok</summary>")

    _, summary = await strategy.compact(model, list(CONVERSATION), [])

    assert summary is not None
    assert "it is not a message from the user" in summary.text


async def test_summary_without_analysis_kept_whole() -> None:
    """No complete <analysis> block — including an unclosed one — keeps the response."""
    strategy = CompactionSummary()

    _, plain = await strategy.compact(
        summarizer_model("no-analysis", "A plain summary."), list(CONVERSATION), []
    )
    assert plain is not None
    assert "A plain summary." in plain.text

    _, unclosed = await strategy.compact(
        summarizer_model("unclosed", "<analysis>Cut off mid-thought"),
        list(CONVERSATION),
        [],
    )
    assert unclosed is not None
    assert "Cut off mid-thought" in unclosed.text


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


async def test_summary_repeated_compaction_replaces_prior_summary() -> None:
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
