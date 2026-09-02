"""Tests for the view server's find-messages endpoint and its projection."""

import math
from collections import OrderedDict
from pathlib import Path
from typing import Any, Literal

import anyio
import pytest
from fastapi.testclient import TestClient

import inspect_ai.log
from inspect_ai._util.content import ContentReasoning, ContentText
from inspect_ai._view import fastapi_server
from inspect_ai._view.find import (
    SYSTEM_ROW_ID,
    MessageRow,
    ProjectionOptions,
    _messages,
    find_matches,
    message_rows,
    messages_from_events,
    project_event,
    project_row,
    row_anchors,
    strip_markdown_for_count,
)
from inspect_ai.event import Event
from inspect_ai.event._model import ModelEvent
from inspect_ai.model import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
    GenerateConfig,
    ModelOutput,
)
from inspect_ai.model._model_output import ChatCompletionChoice
from inspect_ai.tool import ToolCall, ToolCallContent, ToolCallError


@pytest.fixture(autouse=True)
def isolated_find_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test depends on wall-clock time or on rows another test cached."""
    monkeypatch.setattr(_messages, "_SCAN_BUDGET_S", math.inf)
    monkeypatch.setattr(_messages, "_cache", OrderedDict())


def texts(messages: list[ChatMessage], **options: Any) -> list[str]:
    opts = ProjectionOptions(**options)
    return ["\n".join(project_row(row, opts)) for row in message_rows(messages)]


def write_sample_log(
    path: Path, messages: list[ChatMessage], format: Literal["eval", "json"] = "eval"
) -> None:
    from inspect_ai.log import EvalSample

    log = inspect_ai.log.EvalLog(
        status="success",
        eval=inspect_ai.log.EvalSpec(
            created="2025-01-01T00:00:00Z",
            task="task",
            task_id="task_id",
            dataset=inspect_ai.log.EvalDataset(),
            model="model",
            config=inspect_ai.log.EvalConfig(),
        ),
        samples=[EvalSample(id="s", epoch=1, input="q", target="", messages=messages)],
    )
    inspect_ai.log.write_eval_log(log, str(path), format)


# The QA conversation: fold cases (İstanbul/ISTANBUL, Straße/STRASSE, café NFC
# and NFD, 検索), a markdown answer whose link URL repeats "istanbul", a tool
# output of 40 LONGTOKEN lines and "kumquat" spread over user, assistant and
# fenced text. Expected counts in the endpoint tests are read off this source
# with markdown syntax stripped (so the link URL does not count); tool
# arguments and every tool output line count.
QA_ANSWER = """## Overview of İstanbul

Visited **İstanbul** and istanbul (lowercase) and ISTANBUL. Straße vs straße vs STRASSE.
Search in Japanese: 検索 and again 検索. Emoji: 🍊 orange 🍊. Accents: caf\u00e9 and cafe\u0301.

- item one with _italic_ text
- item two with [a link](https://example.com/istanbul)

| city | word |
| --- | --- |
| İstanbul | 検索 |

```python
def fetch_records(limit: int) -> list[str]:
    return ["istanbul"] * limit
```

```json
{"key": "value", "検索": 1, "quoted": "say \\"quoted\\""}
```
"""


def qa_messages() -> list[ChatMessage]:
    echo = ToolCall(
        id="c-echo", function="echo", arguments={"text": 'say "quoted" and {"j": 1}'}
    )
    repeat = ToolCall(
        id="c-repeat", function="repeat", arguments={"token": "LONGTOKEN", "times": 40}
    )
    lines = [f"line {i:03d} filler LONGTOKEN filler" for i in range(40)]
    return [
        # row 0: 4 kumquat (plain, bold, code span, plain)
        ChatMessageUser(
            id="u1",
            content="Please help with kumquat research. **kumquat** is a fruit; "
            "`kumquat` in code; kumquat again.",
        ),
        ChatMessageAssistant(id="a1", content=QA_ANSWER),  # row 1
        ChatMessageUser(id="u2", content="Run echo with quotes please. kumquat"),
        ChatMessageAssistant(id="a2", content="", tool_calls=[echo]),  # row 3
        ChatMessageTool(
            id="t2", tool_call_id="c-echo", function="echo", content="echoed: say"
        ),
        ChatMessageAssistant(id="a3", content="Echo done."),  # row 4
        ChatMessageUser(
            id="u3", content="Now produce a long output with LONGTOKEN. kumquat"
        ),
        ChatMessageAssistant(id="a4", content="", tool_calls=[repeat]),  # row 6
        ChatMessageTool(
            id="t4",
            tool_call_id="c-repeat",
            function="repeat",
            content="\n".join(lines) + "\n" + "x" * 3000,
        ),
        ChatMessageAssistant(  # row 7
            id="a5", content="Long output done; LONGTOKEN appeared many times."
        ),
        ChatMessageUser(id="u4", content="```\nkumquat = 1\n```"),  # row 8
        ChatMessageAssistant(  # row 9
            id="a6",
            content=[
                ContentReasoning(reasoning="Thinking about 検索 and İstanbul."),
                ContentText(text="The fence defines kumquat."),
            ],
        ),
        ChatMessageUser(id="u5", content="Think about it."),
        ChatMessageAssistant(  # row 11
            id="a7",
            content=[
                ContentReasoning(reasoning="Second thought, straße.", summary="Short."),
                ContentText(text="Second answer."),
            ],
        ),
        ChatMessageUser(id="u6", content="Think again, redacted."),
        ChatMessageAssistant(  # row 13
            id="a8",
            content=[
                ContentReasoning(
                    reasoning="", redacted=True, summary="Redacted summary about 検索."
                ),
                ContentText(text="Third answer."),
            ],
        ),
    ]


@pytest.fixture(scope="session")
def qa_log(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("find") / "find-qa.eval"
    write_sample_log(path, qa_messages())
    return path


# ═══════════════════════════════════════════════════════════════════════════
# Fold and matching
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    "query,text,expected",
    [
        (
            "istanbul",
            "İstanbul istanbul ISTANBUL ıstanbul",
            ["İstanbul", "istanbul", "ISTANBUL"],
        ),
        ("İstanbul", "istanbul ISTANBUL", ["istanbul", "ISTANBUL"]),
        ("ıstanbul", "İstanbul istanbul", []),
        ("strasse", "Straße straße STRASSE", ["Straße", "straße", "STRASSE"]),
        ("straße", "Straße STRASSE", ["Straße", "STRASSE"]),
        ("cafe", "café café", ["café", "café"]),
        ("café", "cafe café", ["cafe", "café"]),
        ("file", "ﬁle file", ["ﬁle", "file"]),
        ("ﬁle", "FILE", ["FILE"]),
        ("ss", "ßß", ["ß", "ß"]),
        ("sa", "ßa", []),
        ("as", "aß", []),
        ("fi", "ﬁ ﬁle", ["ﬁ", "ﬁ"]),
        ("il", "ﬁle", []),
        ("aa", "aaaaa", ["aa", "aa"]),
        ("", "anything", []),
    ],
)
def test_find_matches_fold(query: str, text: str, expected: list[str]) -> None:
    assert [m.text for m in find_matches(text, query)] == expected


@pytest.mark.parametrize(
    "query,text,spans",
    [
        ("ss", "ßß", [(0, 1), (1, 2)]),  # one source char expands to two folded
        ("aa", "aaaaa", [(0, 2), (2, 4)]),
        ("cafe", "café café", [(0, 4), (5, 10)]),  # NFC, then NFD
        ("e", "é", [(0, 2)]),  # the trailing combining mark belongs to the match
        ("fi", "xﬁle", [(1, 2)]),
        ("sa", "ßa xsa", [(4, 6)]),  # a boundary-straddling hit, then a valid one
    ],
)
def test_find_matches_offsets(
    query: str, text: str, spans: list[tuple[int, int]]
) -> None:
    assert [(m.start, m.end) for m in find_matches(text, query)] == spans


@pytest.mark.parametrize(
    "query,text,options,expected",
    [
        ("cafe", "Café café", {"fold": "case"}, []),
        ("café", "Café café", {"fold": "case"}, ["Café", "café"]),
        ("strasse", "Straße", {"fold": "case"}, ["Straße"]),
        ("café", "Café café", {"fold": "none"}, ["café"]),
        ("a.c", "a.c abc", {"fold": "none"}, ["a.c"]),
        ("a.c", "a.c abc", {"mode": "regex", "fold": "none"}, ["a.c", "abc"]),
        ("A\\d", "a1 A2", {"mode": "regex", "fold": "case"}, ["a1", "A2"]),
        ("A\\d", "a1 A2", {"mode": "regex", "fold": "none"}, ["A2"]),
        ("strasse\\b", "Straße Straßen", {"mode": "regex"}, ["Straße"]),
        ("cat", "cat catalog concat", {"word_boundary": True}, ["cat"]),
        ("ca.", "cat catalog", {"mode": "regex", "word_boundary": True}, ["cat"]),
        ("x*", "xx yy", {"mode": "regex"}, ["xx"]),
        ("x*|y", "y", {"mode": "regex"}, ["y"]),
        ("x*|y", "yxy", {"mode": "regex"}, ["y", "x", "y"]),
        (
            "cat|dog",
            "catalog hotdog dog",
            {"mode": "regex", "word_boundary": True},
            ["dog"],
        ),
    ],
)
def test_find_matches_modes(
    query: str, text: str, options: dict[str, Any], expected: list[str]
) -> None:
    assert [m.text for m in find_matches(text, query, **options)] == expected


def test_find_matches_invalid_regex_raises() -> None:
    import re

    with pytest.raises(re.error):
        find_matches("x", "(", mode="regex")


# ═══════════════════════════════════════════════════════════════════════════
# Rows and anchors
# ═══════════════════════════════════════════════════════════════════════════


def test_rows_fold_tool_messages_and_merge_system() -> None:
    messages: list[ChatMessage] = [
        ChatMessageTool(id="orphan", content="dropped"),
        ChatMessageSystem(id="s1", content="be terse"),
        ChatMessageUser(id="u1", content="hi"),
        ChatMessageSystem(id="s2", content=[ContentText(text="and kind")]),
        ChatMessageAssistant(
            id="a1",
            content="",
            tool_calls=[ToolCall(id="c1", function="bash", arguments={"cmd": "ls"})],
        ),
        ChatMessageTool(id="t1", tool_call_id="c1", function="bash", content="a b"),
        ChatMessageTool(id="t2", tool_call_id="c2", function="bash", content="c"),
    ]
    rows = message_rows(messages)
    assert [row.message.id for row in rows] == [SYSTEM_ROW_ID, "u1", "a1"]
    assert [[t.id for t in row.tool_messages] for row in rows] == [[], [], ["t1", "t2"]]
    system = rows[0].message
    assert isinstance(system.content, list)
    assert [c.text for c in system.content if isinstance(c, ContentText)] == [
        "be terse",
        "and kind",
    ]


def test_row_anchors_first_occurrence_keeps_id() -> None:
    messages: list[ChatMessage] = [
        ChatMessageUser(id="dup", content="a"),
        ChatMessageAssistant(content="no id").model_copy(update={"id": None}),
        ChatMessageUser(id="dup", content="b"),
        ChatMessageUser(id="", content="empty id"),
    ]
    rows = message_rows(messages)
    assert row_anchors(rows) == ["dup", "msg-1", "dup#2", ""]


def test_row_anchors_minted_never_collide_with_literal_ids() -> None:
    messages: list[ChatMessage] = [
        ChatMessageUser(id="dup", content="a"),
        ChatMessageUser(id="dup#2", content="b"),
        ChatMessageUser(id="dup", content="c"),
        ChatMessageUser(id="", content="d"),
        ChatMessageUser(id="", content="e"),
        ChatMessageUser(id="#4", content="f"),
    ]
    anchors = row_anchors(message_rows(messages))
    # only prior rows count: the literal "#4" arriving later takes the suffix
    assert anchors == ["dup", "dup#2", "dup#2#2", "", "#4", "#4#5"]
    assert len(set(anchors)) == len(anchors)


def test_row_anchors_stable_under_append() -> None:
    messages: list[ChatMessage] = [
        ChatMessageUser(id="a", content="1"),
        ChatMessageUser(id="a", content="2"),
    ]
    before = row_anchors(message_rows(messages))
    messages.append(ChatMessageUser(id="a#1", content="3"))
    after = row_anchors(message_rows(messages))
    assert before == ["a", "a#1"]
    assert after == ["a", "a#1", "a#1#2"]


def test_messages_from_events_merges_inputs_and_outputs() -> None:
    u1 = ChatMessageUser(id="u1", content="first")
    a1 = ChatMessageAssistant(id="a1", content="reply")
    u2 = ChatMessageUser(id="u2", content="second")
    a2 = ChatMessageAssistant(id="a2", content="reply two")
    summary = ChatMessageUser(id="sum", content="compaction summary")
    events = [
        model_event([u1], a1),
        model_event([u1, a1, u2], a2, error="boom"),
        model_event([u1, a1, u2], a2),
        model_event(
            [
                summary,
                u2,
                a2,
                ChatMessageUser(content="x").model_copy(update={"id": None}),
            ],
            None,
        ),
    ]
    # an unseen message leading an input lands after the list end, not in front
    assert [m.id for m in messages_from_events(events)] == [
        "u1",
        "a1",
        "u2",
        "a2",
        "sum",
    ]


def test_messages_from_events_inserts_unseen_between_known() -> None:
    u1 = ChatMessageUser(id="u1", content="first")
    a1 = ChatMessageAssistant(id="a1", content="reply")
    mid = ChatMessageUser(id="mid", content="injected")
    events = [model_event([u1], a1), model_event([u1, mid, a1], None)]
    assert [m.id for m in messages_from_events(events)] == ["u1", "mid", "a1"]


def model_event(
    input: list[ChatMessage],
    output: ChatMessageAssistant | None,
    error: str | None = None,
) -> ModelEvent:
    return ModelEvent(
        model="mockllm/model",
        input=input,
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput(
            model="mockllm/model",
            choices=[ChatCompletionChoice(message=output)] if output else [],
        ),
        error=error,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Projection
# ═══════════════════════════════════════════════════════════════════════════


def test_projection_role_heading_and_content() -> None:
    messages: list[ChatMessage] = [
        ChatMessageUser(id="u", content="**bold** kumquat"),
        ChatMessageAssistant(
            id="a", content=[ContentText(text="one"), ContentText(text="two")]
        ),
        ChatMessageUser(id="t", content=""),
    ]
    assert texts(messages) == ["user\nbold kumquat", "assistant\none\ntwo", "user"]
    assert texts(messages, unlabeled_roles=frozenset({"user"})) == [
        "bold kumquat",
        "assistant\none\ntwo",
        "",
    ]


def test_projection_display_mode_raw_keeps_markdown_source() -> None:
    messages: list[ChatMessage] = [
        ChatMessageUser(id="u", content="see [docs](https://example.test)"),
        ChatMessageAssistant(
            id="a", content=[ContentReasoning(reasoning="**deep** `x`")]
        ),
    ]
    assert texts(messages) == ["user\nsee docs", "assistant\nReasoning\ndeep x"]
    assert texts(messages, display_mode="raw") == [
        "user\nsee [docs](https://example.test)",
        "assistant\nReasoning\n**deep** `x`",
    ]


def test_projection_content_data_document_and_citation_fallbacks() -> None:
    from inspect_ai._util.citation import DocumentCitation, UrlCitation
    from inspect_ai._util.content import ContentData, ContentDocument

    message = ChatMessageAssistant(
        id="a",
        content=[
            ContentText(
                text="cited",
                citations=[
                    UrlCitation(url="https://t.example", title="Titled"),
                    UrlCitation(url="https://q.example", cited_text="quoted words"),
                    UrlCitation(url="https://u.example", cited_text=(0, 3)),
                    DocumentCitation(cited_text=(0, 3)),
                ],
            ),
            ContentData(data={"k": "ü"}),
            ContentDocument(document="base64", filename="report.pdf"),
        ],
    )
    row = message_rows([message])[0]
    assert project_row(row, include_chrome=False) == [
        "cited",
        "Titled",
        "quoted words",
        "https://u.example",
        '{"k": "ü"}',
        "report.pdf",
    ]


def test_projection_standalone_tool_row() -> None:
    messages: list[ChatMessage] = [
        ChatMessageUser(id="u", content="go"),
        ChatMessageAssistant(id="a", content="calls", tool_calls=None),
        ChatMessageTool(id="t", function="bash", content="  out  "),
    ]
    rows = message_rows(messages)
    # a folded tool message without a matching tool call renders nothing
    assert project_row(rows[1]) == ["assistant", "calls"]
    standalone = message_rows([ChatMessageTool(id="t", function="bash", content="x")])
    assert standalone == []


def test_projection_tool_calls_plain_text_and_styles() -> None:
    call = ToolCall(
        id="c1",
        function="bash",
        arguments={"cmd": "echo hi", "timeout": 5, "opts": {"x": "ü"}},
        view=ToolCallContent(title="Run {{cmd}}", format="markdown", content="x"),
    )
    messages: list[ChatMessage] = [
        ChatMessageAssistant(id="a", content="visible", tool_calls=[call]),
        ChatMessageTool(id="t", tool_call_id="c1", function="bash", content="hi\n"),
    ]
    row = message_rows(messages)[0]
    complete = [
        "assistant",
        "visible",
        "tool: bash",
        "Run {{cmd}}",
        "bash",
        "echo hi",
        "5",
        '{"x": "ü"}',
    ]
    assert project_row(row) == complete + ["hi\n"]
    compact = ProjectionOptions(tool_call_style="compact")
    assert project_row(row, compact) == complete
    assert project_row(row, include_chrome=False) == [
        "visible",
        "bash",
        "echo hi",
        "5",
        '{"x": "ü"}',
        "hi\n",
    ]
    omit = ProjectionOptions(tool_call_style="omit")
    assert project_row(row, omit) == ["assistant", "visible"]


def test_projection_pairs_tool_messages_by_call_id_out_of_order() -> None:
    calls = [
        ToolCall(id="c1", function="f", arguments={"n": "first"}),
        ToolCall(id="c2", function="f", arguments={"n": "second"}),
    ]
    messages: list[ChatMessage] = [
        ChatMessageAssistant(id="a", content="", tool_calls=calls),
        ChatMessageTool(id="t2", tool_call_id="c2", function="f", content="two"),
        ChatMessageTool(id="t1", tool_call_id="c1", function="f", content="one"),
    ]
    row = message_rows(messages)[0]
    assert project_row(row, include_chrome=False) == [
        "f",
        "first",
        "one",
        "f",
        "second",
        "two",
    ]


def test_projection_server_tool_use_context_and_entities() -> None:
    from inspect_ai._util.citation import UrlCitation
    from inspect_ai._util.content import ContentToolUse

    message = ChatMessageAssistant(
        id="a",
        content=[
            ContentToolUse(
                tool_type="mcp_call",
                id="s1",
                name="search",
                context="docs",
                arguments="q",
                result="r",
            ),
            ContentText(
                text="x", citations=[UrlCitation(url="https://e", title="A &amp; B")]
            ),
        ],
    )
    row = message_rows([message])[0]
    assert project_row(row, include_chrome=False) == [
        "docs",
        "search",
        "q",
        "r",
        "x",
        "A & B",
    ]


def test_projection_tool_error_replaces_output() -> None:
    call = ToolCall(id="c1", function="python", arguments={"code": "1/0"})
    messages: list[ChatMessage] = [
        ChatMessageAssistant(id="a", content="", tool_calls=[call]),
        ChatMessageTool(
            id="t",
            tool_call_id="c1",
            function="python",
            content="ignored",
            error=ToolCallError(type="timeout", message="took too long"),
        ),
    ]
    row = message_rows(messages)[0]
    assert project_row(row) == [
        "assistant",
        "tool: python",
        "python",
        "1/0",
        "took too long",
    ]


def test_projection_reasoning_title_is_chrome() -> None:
    message = ChatMessageAssistant(
        id="a",
        content=[
            ContentReasoning(reasoning="**thinking**"),
            ContentReasoning(reasoning="", summary="short"),
        ],
    )
    row = message_rows([message])[0]
    assert project_row(row) == [
        "assistant",
        "Reasoning",
        "thinking",
        "Reasoning (Summary)",
        "short",
    ]
    assert project_row(row, include_chrome=False) == [
        "thinking",
        "short",
    ]


def test_projection_redacted_reasoning_shows_summary_not_ciphertext() -> None:
    call = ToolCall(id="c1", function="think", arguments={})
    redacted = ContentReasoning(
        reasoning="gAAAAciphertext", summary="thought about cats", redacted=True
    )
    messages: list[ChatMessage] = [
        ChatMessageAssistant(id="a", content=[redacted], tool_calls=[call]),
        ChatMessageTool(
            id="t", tool_call_id="c1", function="think", content=[redacted]
        ),
    ]
    row = message_rows(messages)[0]
    assert project_row(row, include_chrome=False) == [
        "thought about cats",
        "think",
        "thought about cats",
    ]
    unsummarized = ContentReasoning(reasoning="gAAAA", redacted=True)
    row = message_rows([ChatMessageAssistant(id="a", content=[unsummarized])])[0]
    assert project_row(row, include_chrome=False) == []


def test_projection_tool_head_row_emits_error_or_verbatim_output() -> None:
    # scout scans messages one at a time, so a tool message heads its own row
    failed = ChatMessageTool(
        id="t",
        function="python",
        content="ignored",
        error=ToolCallError(type="timeout", message="took too long"),
    )
    assert project_row(MessageRow(failed), include_chrome=False) == ["took too long"]
    plain = ChatMessageTool(id="t", function="bash", content="**not markdown**")
    assert project_row(MessageRow(plain)) == ["tool", "**not markdown**"]
    from inspect_ai._util.content import ContentDocument, ContentText

    with_document = ChatMessageTool(
        id="t",
        function="fetch",
        content=[
            ContentText(text="saved"),
            ContentDocument(document="base64", filename="report.pdf"),
        ],
    )
    assert project_row(MessageRow(with_document), include_chrome=False) == [
        "saved",
        "report.pdf",
    ]


def scout_events() -> list[Event]:
    from inspect_ai._util.error import EvalError
    from inspect_ai.event import (
        ApprovalEvent,
        ErrorEvent,
        InfoEvent,
        LoggerEvent,
        LoggingMessage,
        ToolEvent,
    )

    return [
        model_event([], ChatMessageAssistant(id="a", content="the completion")),
        ToolEvent(
            id="c1",
            function="bash",
            arguments={"cmd": "ls", "timeout": 5},
            result="a\nb",
        ),
        ToolEvent(
            id="c2",
            function="python",
            arguments={"code": "1/0"},
            result="",
            error=ToolCallError(type="unknown", message="boom"),
        ),
        ErrorEvent(
            error=EvalError(message="sample failed", traceback="", traceback_ansi="")
        ),
        InfoEvent(source="scorer", data={"note": "ok"}),
        LoggerEvent(
            message=LoggingMessage(level="warning", message="slow tool", created=0.0)
        ),
        ApprovalEvent(
            message="do it?",
            call=ToolCall(id="c3", function="rm", arguments={"path": "/"}),
            approver="human",
            decision="reject",
            explanation="no",
        ),
    ]


def test_project_event_data_segments() -> None:
    data = [
        "\n".join(project_event(event, include_chrome=False))
        for event in scout_events()
    ]
    assert data == [
        "the completion",
        "ls\n5\na\nb",
        "1/0\nboom",
        "sample failed",
        '{"note": "ok"}',
        "slow tool",
        "do it?\nrm\n/\nno",
    ]


def test_project_event_chrome_and_unsupported() -> None:
    events = scout_events()
    assert project_event(events[1]) == ["bash", "ls", "5", "a\nb"]
    assert project_event(events[5]) == ["warning", "slow tool"]
    from inspect_ai.event import StepEvent

    assert project_event(StepEvent(action="begin", name="x")) == []


def test_project_event_tool_result_document_filename() -> None:
    from inspect_ai._util.content import ContentDocument
    from inspect_ai.event import ToolEvent

    event = ToolEvent(
        id="c1",
        function="read",
        arguments={},
        result=[
            ContentText(text="body"),
            ContentDocument(document="", filename="f.pdf"),
        ],
    )
    assert project_event(event, include_chrome=False) == [
        "body",
        "f.pdf",
    ]


# ═══════════════════════════════════════════════════════════════════════════
# Markdown stripping for counts
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    "name,source,expected",
    [
        (
            "link",
            "see [istanbul docs](https://istanbul.example) now",
            "see istanbul docs now",
        ),
        ("strong", "**bold** and __also__", "bold and also"),
        (
            "emphasis",
            "*slanted* and _italic_ but snake_case_name stays",
            "slanted and italic but snake_case_name stays",
        ),
        ("strikethrough", "~~gone~~ text", "gone text"),
        ("unpaired_markers", "2 * 3 and a_b and **", "2 * 3 and a_b and **"),
        ("heading", "## Overview\n### Sub", "Overview\nSub"),
        ("blockquote", "> quoted\n> more", "quoted\nmore"),
        (
            "list_markers",
            "- one\n* two\n+ three\n1. four\n  - nested",
            "one\ntwo\nthree\nfour\nnested",
        ),
        ("fence_lines", "```python\nx = 1\n```\n~~~\ny\n~~~", "x = 1\n\ny\n"),
        ("task_list", "- [ ] todo\n- [x] done\n1. [X] third", "todo\ndone\nthird"),
        ("indented_code", "    x = 1\n\tkept", "    x = 1\n\tkept"),
        (
            "indented_code_block_kept",
            "para\n\n    - literal\n    **x**\n- item",
            "para\n\n    - literal\n    **x**\nitem",
        ),
        (
            "intraword_double_underscore",
            "foo__bar__baz and __strong__",
            "foo__bar__baz and strong",
        ),
        ("code_span_run_lengths", "`a``b` and ``c`d``", "a``b and c`d"),
        (
            "code_span_content_kept_without_backticks",
            "use `**not bold**` and ``[no link](x)`` here",
            "use **not bold** and [no link](x) here",
        ),
        (
            "nul_bytes_are_text",
            "\x000\x00 and `c` \x001\x00",
            "\x000\x00 and c \x001\x00",
        ),
        ("private_use_is_text", "\ue0000\ue000 `c`", "\ue0000\ue000 c"),
        (
            "fenced_code_kept",
            "```\n# not a heading\n- not a bullet\n| a | b |\n```\n- bullet",
            "# not a heading\n- not a bullet\n| a | b |\n\nbullet",
        ),
    ],
)
def test_strip_markdown_rule(name: str, source: str, expected: str) -> None:
    assert strip_markdown_for_count(source) == expected


def test_strip_markdown_istanbul_link_case() -> None:
    stripped = strip_markdown_for_count(QA_ANSWER)
    # the link URL no longer counts
    assert len(find_matches(QA_ANSWER, "istanbul")) == 7
    assert len(find_matches(stripped, "istanbul")) == 6
    assert "https://example.com/istanbul" not in stripped


# ═══════════════════════════════════════════════════════════════════════════
# Endpoint
# ═══════════════════════════════════════════════════════════════════════════

PROJECTION = {"unlabeled_roles": [], "tool_call_style": "complete"}


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    return TestClient(fastapi_server.view_server_app(default_dir=str(tmp_path)))


def find(
    client: TestClient,
    text: str,
    log: Path,
    sample_id: str = "s",
    **body: Any,
) -> dict[str, Any]:
    request = {
        "sample_id": sample_id,
        "epoch": 1,
        "text": text,
        "projection": PROJECTION,
        **body,
    }
    response = client.post(f"/find-messages/{log}", json=request)
    assert response.status_code == 200, response.text
    return response.json()


def occurrences(page: dict[str, Any]) -> int:
    return sum(row["count"] for row in page["rows"])


@pytest.mark.parametrize(
    "text,rows,count",
    [
        ("kumquat", 5, 8),
        ("istanbul", 2, 7),
        ("İstanbul", 2, 7),
        ("ISTANBUL", 2, 7),
        ("ıstanbul", 0, 0),
        ("strasse", 2, 4),
        ("straße", 2, 4),
        ("café", 1, 2),
        ("検索", 3, 6),
        ("LONGTOKEN", 3, 43),
        ("assistant", 8, 8),
        ("", 0, 0),
    ],
)
def test_endpoint_rows_and_counts(
    client: TestClient, qa_log: Path, text: str, rows: int, count: int
) -> None:
    result = find(client, text, qa_log)
    assert len(result["rows"]) == rows
    assert occurrences(result) == count
    assert result["at_end"] is True
    assert result["complete"] is True


def test_endpoint_row_texts_are_distinct_source_substrings(
    client: TestClient, qa_log: Path
) -> None:
    rows = find(client, "strasse", qa_log)["rows"]
    assert [(r["index"], r["anchor"], r["count"], r["texts"]) for r in rows] == [
        (1, "a1", 3, ["Straße", "straße", "STRASSE"]),
        (11, "a7", 1, ["straße"]),
    ]
    long_row = find(client, "LONGTOKEN", qa_log)["rows"][1]
    # the tool message folds into its calling row: the argument plus 40 lines
    assert (long_row["index"], long_row["count"], long_row["texts"]) == (
        6,
        41,
        ["LONGTOKEN"],
    )


def test_endpoint_pages_forward_until_at_end(
    client: TestClient, qa_log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    everything = find(client, "kumquat", qa_log)["rows"]
    assert len(everything) == 5
    monkeypatch.setattr(_messages, "MAX_ROWS", 2)
    pages: list[dict[str, Any]] = []
    after = None
    while True:
        page = find(client, "kumquat", qa_log, after=after)
        pages.append(page)
        if page["at_end"]:
            break
        after = page["rows"][-1]["anchor"]
    assert [r for page in pages for r in page["rows"]] == everything
    # the cap cuts the first two pages; the third walks off the end
    assert [page["at_end"] for page in pages] == [False, False, True]
    assert all(page["complete"] for page in pages)
    # after the last row there is nothing left, which is still the end
    beyond = find(client, "kumquat", qa_log, after=everything[-1]["anchor"])
    assert beyond == {"rows": [], "at_end": True, "complete": True}


def test_endpoint_unknown_after_restarts_at_the_top(
    client: TestClient, qa_log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    everything = find(client, "kumquat", qa_log)["rows"]
    monkeypatch.setattr(_messages, "MAX_ROWS", 2)
    assert find(client, "kumquat", qa_log, after="gone")["rows"] == everything[:2]


def test_endpoint_empty_anchor_is_a_cursor(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A message with an empty id has the anchor ""; paging after it resumes there."""
    log = tmp_path / "empty-id.eval"
    write_sample_log(
        log,
        [
            ChatMessageUser(content="one kumquat", id="u1"),
            ChatMessageAssistant(content="two kumquat", id=""),
            ChatMessageUser(content="three kumquat", id="u3"),
        ],
    )
    monkeypatch.setattr(_messages, "MAX_ROWS", 1)
    first = find(client, "kumquat", log)["rows"]
    assert [r["anchor"] for r in first] == ["u1"]
    second = find(client, "kumquat", log, after="u1")["rows"]
    assert [r["anchor"] for r in second] == [""]
    third = find(client, "kumquat", log, after="")["rows"]
    assert [r["anchor"] for r in third] == ["u3"]


def test_endpoint_scan_budget_stops_the_page_after_the_first_match(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    budget = 1.0
    monkeypatch.setattr(_messages, "_SCAN_BUDGET_S", budget)
    ticks = {"n": 0}

    def now() -> float:
        ticks["n"] += 1
        return ticks["n"] * budget

    monkeypatch.setattr("inspect_ai._view.find._messages.time.perf_counter", now)
    log = tmp_path / "slow.eval"
    write_sample_log(
        log,
        [ChatMessageUser(id=f"u{i}", content="hit") for i in range(5)],
    )
    page = find(client, "hit", log)
    assert len(page["rows"]) == 1
    assert page["at_end"] is False
    monkeypatch.setattr(
        "inspect_ai._view.find._messages.time.perf_counter", lambda: 0.0
    )
    rest = find(client, "hit", log, after=page["rows"][-1]["anchor"])
    assert len(rest["rows"]) == 4
    assert rest["at_end"] is True


def test_endpoint_scan_budget_continues_after_a_slow_first_match(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from inspect_ai._util.textsearch import FoldedText
    from inspect_ai._view.find._messages import _SampleIndex

    monkeypatch.setattr(_messages, "_SCAN_BUDGET_S", 0.05)
    clock = {"t": 0.0}
    monkeypatch.setattr(
        "inspect_ai._view.find._messages.time.perf_counter", lambda: clock["t"]
    )
    original = _SampleIndex.folded_row

    async def fold(
        self: _SampleIndex, i: int, options: ProjectionOptions
    ) -> FoldedText:
        if clock["t"] == 0.0:
            clock["t"] = 1.0
        return await original(self, i, options)

    monkeypatch.setattr(_SampleIndex, "folded_row", fold)
    log = tmp_path / "slow.eval"
    write_sample_log(
        log,
        [ChatMessageUser(id=f"u{i}", content="hit") for i in range(5)],
    )
    page = find(client, "hit", log)
    # the first fold "took" 1s; the budget starts after that hit, so the rest
    # of this small sample still fits on the first page
    assert len(page["rows"]) == 5
    assert page["at_end"] is True


def test_endpoint_finds_compact_tool_chrome(client: TestClient, tmp_path: Path) -> None:
    log = tmp_path / "tool.eval"
    write_sample_log(
        log,
        [
            ChatMessageAssistant(
                id="a",
                content="",
                tool_calls=[
                    ToolCall(id="c1", function="bash", arguments={"cmd": "ls"})
                ],
            ),
        ],
    )
    compact = {**PROJECTION, "tool_call_style": "compact"}
    page = find(client, "tool: bash", log, projection=compact)
    assert [(r["anchor"], r["count"]) for r in page["rows"]] == [("a", 1)]


def test_endpoint_miss_yields_the_event_loop(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    yields = {"n": 0}
    original = anyio.lowlevel.checkpoint

    async def checkpoint() -> None:
        yields["n"] += 1
        await original()

    monkeypatch.setattr(anyio.lowlevel, "checkpoint", checkpoint)
    log = tmp_path / "miss.eval"
    write_sample_log(
        log,
        [ChatMessageUser(id=f"u{i}", content="aaa") for i in range(40)],
    )
    page = find(client, "zzz", log)
    assert page == {"rows": [], "at_end": True, "complete": True}
    assert yields["n"] >= 1


async def test_huge_row_folds_in_a_thread_with_identical_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from inspect_ai._view.find._messages import (
        FindMessagesRequest,
        _page,
        _SampleIndex,
    )

    threaded = {"n": 0}
    original = anyio.to_thread.run_sync

    async def run_sync(*args: Any, **kwargs: Any) -> Any:
        threaded["n"] += 1
        return await original(*args, **kwargs)

    monkeypatch.setattr(anyio.to_thread, "run_sync", run_sync)
    request = FindMessagesRequest(sample_id="s", epoch=1, text="strasse")
    on_loop = await _page(
        _SampleIndex(qa_messages(), True), ProjectionOptions(), request
    )
    assert threaded["n"] == 0
    monkeypatch.setattr(_messages, "_FOLD_IN_THREAD_CHARS", 0)
    in_thread = await _page(
        _SampleIndex(qa_messages(), True), ProjectionOptions(), request
    )
    assert threaded["n"] == len(message_rows(qa_messages()))
    assert in_thread == on_loop
    assert len(in_thread.rows) == 2


async def test_segments_do_not_glue_across_boundaries() -> None:
    from inspect_ai._view.find._messages import _SampleIndex

    index = _SampleIndex([ChatMessageAssistant(id="a", content="ant hill")], True)
    joined = (await index.folded_row(0, ProjectionOptions())).text
    assert joined == "assistant\nant hill"
    assert len(find_matches(joined, "assistantant")) == 0


def test_endpoint_texts_uncapped(client: TestClient, tmp_path: Path) -> None:
    variants = " ".join(f"{'X' * i}{'x' * (40 - i)}" for i in range(40))
    log = tmp_path / "variants.eval"
    write_sample_log(log, [ChatMessageUser(id="u", content=variants)])
    row = find(client, "x" * 40, log)["rows"][0]
    assert row["count"] == 40 and len(row["texts"]) == 40
    assert row["texts"][0] == "x" * 40 and row["texts"][39] == "X" * 39 + "x"


def test_endpoint_chunked_sample_is_searched_whole(
    client: TestClient, tmp_path: Path
) -> None:
    from inspect_ai.log._recorders.chunked import convert_eval_logs_to_chunked

    # the chunked per-sample shape (samples/{id}_epoch_{epoch}/messages/0.json);
    # the long turn is extracted to the attachments sequence by the converter
    source = tmp_path / "source.eval"
    write_sample_log(
        source,
        [
            ChatMessageUser(id="u", content="kumquat question"),
            ChatMessageAssistant(id="a", content="filler " * 2000 + "kumquat answer"),
            ChatMessageUser(id="u2", content="kumquat again, in the second chunk"),
        ],
    )
    convert_eval_logs_to_chunked(str(source), str(tmp_path / "chunked"), chunk_size=2)
    log = tmp_path / "chunked" / "source.eval"
    result = find(client, "kumquat", log)
    assert result["at_end"] is True
    assert result["complete"] is True
    assert [(r["index"], r["anchor"], r["count"]) for r in result["rows"]] == [
        (0, "u", 1),
        (1, "a", 1),
        (2, "u2", 1),
    ]


def test_endpoint_projection_options(client: TestClient, qa_log: Path) -> None:
    hidden = {**PROJECTION, "unlabeled_roles": ["assistant"]}
    assert find(client, "assistant", qa_log, projection=hidden)["rows"] == []
    # the 40 output lines are hidden in compact mode; the user turn, the
    # compact call line and the final answer remain
    compact = {**PROJECTION, "tool_call_style": "compact"}
    page = find(client, "LONGTOKEN", qa_log, projection=compact)
    assert [(r["index"], r["count"]) for r in page["rows"]] == [(5, 1), (6, 1), (7, 1)]


def test_endpoint_projection_defaults_and_raw_display_mode(
    client: TestClient, qa_log: Path
) -> None:
    # a host echoes only what it changes; omitted projection = viewer defaults
    body = {"sample_id": "s", "epoch": 1, "text": "istanbul"}
    response = client.post(f"/find-messages/{qa_log}", json=body)
    assert response.status_code == 200, response.text
    assert occurrences(response.json()) == 7
    # raw mode shows markdown source, so the link URL counts too
    raw = find(client, "istanbul", qa_log, projection={"display_mode": "raw"})
    assert occurrences(raw) == 8


def test_request_schema_marks_only_the_required_fields() -> None:
    from inspect_ai._view._openapi import build_openapi_schema

    schema = build_openapi_schema(fastapi_server.view_server_app())
    request = schema["components"]["schemas"]["FindMessagesRequest"]
    assert sorted(request["required"]) == ["epoch", "sample_id", "text"]
    response = schema["components"]["schemas"]["FindMessagesResponse"]
    assert sorted(response["required"]) == ["at_end", "complete", "rows"]


def test_endpoint_unknown_sample_is_404(client: TestClient, qa_log: Path) -> None:
    body: dict[str, Any] = {"sample_id": "nope", "epoch": 1, "text": "x"}
    assert client.post(f"/find-messages/{qa_log}", json=body).status_code == 404
    body["sample_id"] = "s"
    missing = qa_log.parent / "missing.eval"
    assert client.post(f"/find-messages/{missing}", json=body).status_code == 404


def test_endpoint_json_log_unknown_sample_is_404(
    client: TestClient, tmp_path: Path
) -> None:
    log = tmp_path / "log.json"
    write_sample_log(log, [ChatMessageUser(id="u", content="hi")], "json")
    assert len(find(client, "hi", log)["rows"]) == 1
    body = {"sample_id": "nope", "epoch": 1, "text": "x"}
    assert client.post(f"/find-messages/{log}", json=body).status_code == 404


def test_endpoint_running_json_log_reaches_the_buffer(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = tmp_path / "running.json"
    inspect_ai.log.write_eval_log(
        inspect_ai.log.EvalLog(
            status="started",
            eval=inspect_ai.log.EvalSpec(
                created="2025-01-01T00:00:00Z",
                task="task",
                task_id="task_id",
                dataset=inspect_ai.log.EvalDataset(),
                model="model",
                config=inspect_ai.log.EvalConfig(),
            ),
        ),
        str(log),
        "json",
    )
    probes: list[tuple[str, str | int, int]] = []

    def running(
        location: str, sample_id: str | int, epoch: int
    ) -> list[ChatMessage] | None:
        probes.append((location, sample_id, epoch))
        return [ChatMessageUser(id="u", content="live kumquat")]

    monkeypatch.setattr(_messages, "_running_messages", running)
    result = find(client, "kumquat", log, sample_id="live")
    assert probes == [(str(log), "live", 1)]
    assert [r["anchor"] for r in result["rows"]] == ["u"]
    assert result["at_end"] is True
    assert result["complete"] is False


def test_endpoint_running_sample_from_buffer(
    client: TestClient, tmp_path: Path
) -> None:
    from inspect_ai.log._condense import ATTACHMENT_PROTOCOL
    from inspect_ai.log._recorders.buffer.filestore import (
        Manifest,
        SampleBufferFilestore,
        SampleManifest,
        Segment,
        SegmentFile,
    )
    from inspect_ai.log._recorders.buffer.types import (
        AttachmentData,
        EventData,
        MessagePoolData,
        SampleData,
    )

    log_path = str(tmp_path / "running.eval")
    inspect_ai.log.write_eval_log(
        inspect_ai.log.EvalLog(
            status="started",
            eval=inspect_ai.log.EvalSpec(
                created="2025-01-01T00:00:00Z",
                task="task",
                task_id="task_id",
                dataset=inspect_ai.log.EvalDataset(),
                model="model",
                config=inspect_ai.log.EvalConfig(),
            ),
        ),
        log_path,
        "eval",
    )
    # the user turn is pooled (the event carries only input_refs) and its text
    # is an attachment, as the recorder writes long content
    u1 = ChatMessageUser(id="u1", content=f"{ATTACHMENT_PROTOCOL}h1")
    a1 = ChatMessageAssistant(id="a1", content="kumquat answer")
    first = model_event([], a1).model_copy(update={"input_refs": [(0, 1)]})
    events = [first, model_event([u1, a1], None)]
    pool = [
        MessagePoolData(
            id=1, sample_id="live", epoch=1, msg_id="u1", data=u1.model_dump_json()
        )
    ]
    attachments = [
        AttachmentData(
            id=1, sample_id="live", epoch=1, hash="h1", content="kumquat question"
        )
    ]
    buffer = SampleBufferFilestore(log_path, create=True)
    buffer.write_segment(
        0,
        [
            SegmentFile(
                id="live",
                epoch=1,
                data=SampleData(
                    events=[
                        EventData(
                            id=i + 1,
                            event_id=f"e{i}",
                            sample_id="live",
                            epoch=1,
                            event=event.model_dump(mode="json", exclude_none=True),
                        )
                        for i, event in enumerate(events)
                    ],
                    attachments=attachments,
                    message_pool=pool,
                ),
            )
        ],
    )
    buffer.write_manifest(
        Manifest(
            samples=[
                SampleManifest(
                    summary=inspect_ai.log.EvalSampleSummary(
                        id="live", epoch=1, input="q", target=""
                    ),
                    segments=[0],
                )
            ],
            segments=[Segment(id=0, last_event_id=2, last_attachment_id=1)],
        )
    )

    result = find(client, "kumquat", Path(log_path), sample_id="live")
    # the scan reached the buffer's current end, but the sample is not sealed
    assert result["at_end"] is True
    assert result["complete"] is False
    assert [(r["index"], r["anchor"], r["texts"]) for r in result["rows"]] == [
        (0, "u1", ["kumquat"]),
        (1, "a1", ["kumquat"]),
    ]


# ═══════════════════════════════════════════════════════════════════════════
# Internals
# ═══════════════════════════════════════════════════════════════════════════


async def test_sample_index_key_distinguishes_id_types_and_canonicalizes_roles() -> (
    None
):
    from inspect_ai._view.find._messages import _index_key, _SampleIndex

    assert _index_key("log", 1, 1) != _index_key("log", "1", 1)
    index = _SampleIndex([ChatMessageUser(id="u", content="hi")], complete=True)
    await index.folded_row(
        0, ProjectionOptions(unlabeled_roles=frozenset({"user", "tool"}))
    )
    await index.folded_row(
        0, ProjectionOptions(unlabeled_roles=frozenset({"user", "system"}))
    )
    assert len(index._folded) == 1


async def test_sample_index_cache_isolates_location_epoch_and_evicts_lru(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reads: list[tuple[str, str | int, int]] = []

    async def logged(
        location: str, sample_id: str | int, epoch: int
    ) -> list[ChatMessage] | None:
        reads.append((location, sample_id, epoch))
        return [ChatMessageUser(id="u", content=location)]

    monkeypatch.setattr(_messages, "_logged_messages", logged)
    a = await _messages._sample_index("a.eval", "s", 1)
    assert await _messages._sample_index("a.eval", "s", 1) is a
    await _messages._sample_index("b.eval", "s", 1)
    await _messages._sample_index("a.eval", "s", 2)
    assert reads == [("a.eval", "s", 1), ("b.eval", "s", 1), ("a.eval", "s", 2)]
    # touching a keeps it recent; filling the cache evicts the oldest (b) first
    await _messages._sample_index("a.eval", "s", 1)
    for i in range(_messages._MAX_CACHED_SAMPLES - 2):
        await _messages._sample_index(f"fill{i}.eval", "s", 1)
    reads.clear()
    assert await _messages._sample_index("a.eval", "s", 1) is a
    await _messages._sample_index("b.eval", "s", 1)
    assert reads == [("b.eval", "s", 1)]


async def test_sample_index_folded_variants_are_bounded() -> None:
    from inspect_ai._view.find._messages import _MAX_FOLDED_VARIANTS, _SampleIndex

    index = _SampleIndex([ChatMessageUser(id="u", content="hi")], complete=True)
    variants = [
        ProjectionOptions(frozenset(roles), style, mode)
        for roles in (set[str](), {"user"})
        for style in ("complete", "compact", "omit")
        for mode in ("rendered", "raw")
    ]
    for options in variants:
        await index.folded_row(0, options)
    assert len(index._folded) == _MAX_FOLDED_VARIANTS
    assert list(index._folded) == variants[-_MAX_FOLDED_VARIANTS:]


async def test_sample_index_reprobes_log_after_buffer_miss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probes: list[str] = []

    async def logged(
        location: str, sample_id: str | int, epoch: int
    ) -> list[ChatMessage] | None:
        probes.append("log")
        return [ChatMessageUser(id="u", content="sealed")] if len(probes) > 2 else None

    def running(
        location: str, sample_id: str | int, epoch: int
    ) -> list[ChatMessage] | None:
        probes.append("buffer")
        return None

    monkeypatch.setattr(_messages, "_logged_messages", logged)
    monkeypatch.setattr(_messages, "_running_messages", running)
    index = await _messages._sample_index("race.eval", "s", 1)
    assert probes == ["log", "buffer", "log"]
    assert index is not None and index.complete
