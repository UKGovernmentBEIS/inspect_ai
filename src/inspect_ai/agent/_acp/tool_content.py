"""Tool-call content rendering for ACP notifications.

The router and the approval shim both need to turn an Inspect tool
call (its function name, arguments, viewer output, and — for
completed calls — result) into the structured payloads ACP expects:

- A short, distinguishing title (``bash ls -la`` rather than ``bash``)
  so editor cards stay readable in a long transcript.
- A ``ToolKind`` for icon selection.
- Inline ``content`` blocks (text, images, file diffs) so editors can
  render the tool call richly rather than falling back to a raw-args
  dump.

These helpers are split out from ``_router.py`` (which now owns only
the event-mapping plumbing) so the approval shim can reuse them
without pulling in the live router's transcript subscription.
"""

from __future__ import annotations

from typing import Any

from acp.helpers import (
    ToolCallContentVariant,
    tool_diff_content,
)
from acp.schema import (
    ContentToolCallContent,
    FileEditToolCallContent,
    ImageContentBlock,
    TextContentBlock,
    ToolKind,
)

from inspect_ai._util.content import ContentImage, ContentText
from inspect_ai._util.url import (
    data_uri_mime_type,
    data_uri_to_base64,
    is_data_uri,
    is_http_url,
)
from inspect_ai.event._tool import ToolEvent
from inspect_ai.tool._tool_call import ToolCallContent, substitute_tool_call_content

# Built-in Inspect tool name → ACP ``ToolKind`` mapping. The kind
# is what tells the editor "render this row with a file icon" vs
# "render with a search icon" vs etc. Unmapped tools default to
# ``None`` and the client falls back to a generic tool row.
#
# IMPORTANT: never map any Inspect tool to ``"execute"``. ACP's
# execute-kind is paired with the terminal-block content pattern
# (``terminal/create`` → editor runs the command in its own
# terminal → output streams in). That assumes the AGENT asks the
# EDITOR to run shell commands on the user's local machine. Inspect's
# bash/python/etc. tools run inside a sandboxed eval environment
# (often a remote Docker container) — editor-local execution would
# be the wrong filesystem, wrong env, wrong everything. Zed apparently
# suppresses text-content rendering for execute-kind cards in
# expectation of a terminal block, so claiming ``execute`` makes our
# rich-content payload invisible. Leave shell tools without a kind;
# the descriptive title (see :func:`_descriptive_title`) carries the
# command instead.
_TOOL_KIND_BY_NAME: dict[str, ToolKind] = {
    "read_file": "read",
    "list_files": "read",
    "text_editor": "edit",
    "todo_write": "edit",
    "update_plan": "edit",
    "think": "think",
    "grep": "search",
    "web_search": "search",
    "web_fetch": "fetch",
}

_TOOL_KIND_BY_PREFIX: tuple[tuple[str, ToolKind], ...] = (
    # Catch-alls for tool families with suffixed variants.
    ("web_browser_", "fetch"),
)


def _tool_kind_for(function: str) -> ToolKind | None:
    """Heuristic name-based mapping to ``ToolKind``.

    Returns ``None`` for unknown tools (and for shell-execution tools
    — see the module-level comment on why we never use
    ``"execute"``). The client falls back to a generic row treatment.
    """
    kind = _TOOL_KIND_BY_NAME.get(function)
    if kind is not None:
        return kind
    for prefix, mapped in _TOOL_KIND_BY_PREFIX:
        if function.startswith(prefix):
            return mapped
    return None


# Max length for the argument summary embedded in a tool-call title.
# Long bash commands / paths get truncated with an ellipsis; the full
# value is still in ``raw_input`` and in the view content block.
_TITLE_SUMMARY_MAX_LEN = 60


def _short_summary(text: str, max_len: int = _TITLE_SUMMARY_MAX_LEN) -> str:
    """First non-empty line of ``text``, trimmed to ``max_len`` with ellipsis."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            if len(stripped) <= max_len:
                return stripped
            return stripped[: max_len - 1] + "…"
    return ""


def descriptive_title(fn: str, arguments: dict[str, Any] | None) -> str:
    """Build a descriptive one-line title from a tool's name + args.

    Editor cards (Zed et al.) collapse to a single title line in the
    transcript view. A generic title like ``"bash"`` makes a list of
    ten bash calls indistinguishable. Per-tool heuristics here append
    a short argument summary to the literal function name — so the
    user always sees exactly what tool was called PLUS enough of the
    args to scan and distinguish among many calls.

    Format: ``<function_name> <arg_summary>`` (or just ``<function_name>``
    when no informative arg is available). String-typed args that look
    like queries / patterns / element references are quoted; paths
    and URLs are not.

    Falls back to ``fn`` when no heuristic matches — custom user
    tools keep their bare function name.

    Public-to-the-module so the approval shim (which sees a
    ``ToolCall`` rather than a ``ToolEvent``) can reuse it.
    """
    args = arguments or {}

    def _str(key: str) -> str | None:
        v = args.get(key)
        return v if isinstance(v, str) else None

    # Shell-execution family — title carries the command since Zed
    # doesn't render our text content blocks for these (see the
    # comment on _TOOL_KIND_BY_NAME for why).
    if fn == "bash" or fn == "bash_session" or fn.startswith("bash_session_"):
        cmd = _str("command") or _str("cmd")
        if cmd is not None:
            return f"{fn} {_short_summary(cmd)}"
    if fn == "python":
        code = _str("code")
        if code is not None:
            return f"{fn} {_short_summary(code)}"
    if fn == "code_execution":
        code = _str("code") or _str("command")
        if code is not None:
            return f"{fn} {_short_summary(code)}"

    # File reads — path is the key arg. Inspect's built-in read_file
    # uses ``file_path``; some MCP/custom variants use ``file`` or
    # ``path`` — try the canonical name first.
    if fn == "read_file":
        path = _str("file_path") or _str("file") or _str("path")
        if path is not None:
            return f"{fn} {path}"
    if fn == "list_files":
        path = _str("path") or _str("dir") or _str("directory")
        if path is not None:
            return f"{fn} {path}"

    # File edits — text_editor has multiple sub-commands; show the
    # sub-command + path so users can tell create/view/edit apart.
    if fn == "text_editor":
        path = _str("path") or _str("file")
        command = _str("command")
        if path is not None:
            cmd_part = f"{command} " if command else ""
            return f"{fn} {cmd_part}{path}"

    # Search — pattern/query in quotes (looks like a literal string
    # argument, distinct from paths/URLs).
    if fn == "grep":
        pattern = _str("pattern")
        path = _str("path")
        if pattern is not None:
            target = f" in {path}" if path else ""
            return f'{fn} "{pattern}"{target}'
    if fn == "web_search":
        query = _str("query")
        if query is not None:
            return f'{fn} "{query}"'

    # Fetch / browse — URL or element ref. URLs unquoted; element
    # references quoted (they're freeform strings, not addresses).
    if fn == "web_fetch":
        url = _str("url")
        if url is not None:
            return f"{fn} {url}"
    if fn.startswith("web_browser_"):
        url = _str("url")
        if url is not None:
            return f"{fn} {url}"
        element = _str("element_id") or _str("element")
        if element is not None:
            return f'{fn} "{element}"'
        return fn

    # Planning / thinking — bare function name reads fine.
    if fn in ("think", "todo_write", "update_plan"):
        return fn

    # Generic fallback for user-defined tools without a named heuristic
    # above: surface the first non-empty string-valued argument so the
    # card line is distinguishable in a list of many parallel calls.
    # Argument iteration follows the model's tool-call argument dict
    # which preserves declaration order (Python 3.7+ insertion order),
    # so "first" matches the function signature's first string arg.
    # Tools that want a different preview register a custom viewer.
    for value in args.values():
        if isinstance(value, str):
            summary = _short_summary(value)
            if summary:
                return f"{fn} {summary}"

    return fn


def _descriptive_title(event: ToolEvent) -> str:
    """ToolEvent-flavored adapter around :func:`descriptive_title`."""
    return descriptive_title(event.function, event.arguments)


def content_blocks_from_view(
    view: ToolCallContent | None,
) -> list[ContentToolCallContent] | None:
    """Build ACP ``ContentToolCallContent`` from an Inspect tool view.

    Inspect tools register a custom ``ToolCallViewer`` via the
    ``@tool(viewer=...)`` decorator (see ``code_viewer`` in
    ``tool/_tools/_execute.py`` for the bash/python pattern). The
    viewer's output is a ``ToolCallContent`` carrying rendered
    markdown. We forward that as a ``ContentToolCallContent`` so
    editors (Zed etc.) can render the input richly — e.g. bash
    commands as syntax-highlighted code blocks — instead of falling
    back to the raw arguments dict (which most editors don't render
    inline).

    Returns ``None`` when no view is attached (the tool didn't
    declare a viewer) or the view has empty content, so the start
    notification's ``content`` field stays unset and the client
    falls back to its own rendering of ``raw_input``.

    Public-to-the-module so the approval shim (which builds permission
    prompts from a ``ToolCallView``) can reuse it.
    """
    if view is None or not view.content:
        return None
    return [
        ContentToolCallContent(
            type="content",
            content=TextContentBlock(type="text", text=view.content),
        )
    ]


def _content_from_view(event: ToolEvent) -> list[ContentToolCallContent] | None:
    """ToolEvent-flavored adapter around :func:`content_blocks_from_view`.

    Substitutes ``{{param}}`` placeholders in the view from the call's
    ``arguments`` first. Tool viewers emit placeholders (e.g. ``{{content}}``
    in the Write card) that the web viewer fills in via
    ``substituteToolCallContent`` (``tool.ts``); the ACP path must do the same
    or editors/TUI render the literal ``{{content}}``. This covers both real
    ``ToolEvent``s and the synthesized bridged tool cards (claude_code/codex),
    which both flow through here via ``_content_for_start`` / ``_content_for_update``.
    """
    view = event.view
    if view is not None:
        view = substitute_tool_call_content(view, event.arguments)
    return content_blocks_from_view(view)


# Cap result-as-content payloads so a multi-megabyte tool output
# (e.g. a verbose bash command) doesn't flood the wire on every
# tool call. Tools whose result exceeds the cap get a truncation
# marker; the full result is still on ``ToolEvent.result`` for the
# transcript / log writer to consume.
_RESULT_CONTENT_MAX_BYTES = 8192


def _text_block(text: str, *, fence: bool = False) -> ContentToolCallContent:
    """Wrap raw text as a ``ContentToolCallContent(TextContentBlock)``.

    Applies the result-size cap with a truncation marker — the full
    text remains on ``ToolEvent.result`` for log writers / replay.
    When ``fence`` is True, wraps the (possibly truncated) text in a
    markdown code fence so editors render it as monospace / preserve
    whitespace — useful for shell-command stdout that's tabular or
    code-like. The fence is applied AFTER truncation so the closing
    backticks are always present even when the content was cut.
    """
    if len(text) > _RESULT_CONTENT_MAX_BYTES:
        text = text[:_RESULT_CONTENT_MAX_BYTES] + "\n…[truncated]"
    if fence:
        # Strip surrounding whitespace BEFORE fencing — trailing
        # newlines on shell stdout are nearly universal, and leading
        # blank lines occasionally appear too. Inside a code fence
        # those translate directly into blank rows in the rendered
        # output, padding the card with empty space the operator
        # didn't ask for. Stripping here keeps the visible block tight
        # to its actual content.
        text = f"```\n{text.strip()}\n```"
    return ContentToolCallContent(
        type="content",
        content=TextContentBlock(type="text", text=text),
    )


def _image_block(image: ContentImage) -> ContentToolCallContent:
    """Wrap an Inspect ``ContentImage`` as an ACP ``ImageContentBlock``.

    Inspect represents the image source as a single ``image`` field
    that may be a data URI (``data:image/png;base64,...``) or an
    HTTP URL. ACP's ``ImageContentBlock`` separates these — ``data``
    holds inline base64 bytes and ``mime_type`` is required; ``uri``
    is optional for remote-referenced images.

    Three source shapes per the ``ContentImage.image`` docstring
    ("Either a URL of the image or the base64 encoded image data"):

    - Data URI: parse mime + base64 payload.
    - HTTP URL: set ``uri``, leave ``data=""``; mime guessed from
      the URL path's extension or ``application/octet-stream``.
    - Plain base64 (no envelope): forward as-is with a default
      ``image/png`` mime — the dominant tool-produced format
      (screenshots, plots). Callers needing another format should
      wrap in a data URI so the mime is explicit.
    """
    src = image.image
    if is_data_uri(src):
        mime = data_uri_mime_type(src) or "application/octet-stream"
        data = data_uri_to_base64(src)
        return ContentToolCallContent(
            type="content",
            content=ImageContentBlock(type="image", data=data, mime_type=mime),
        )
    if is_http_url(src):
        # Guess mime from the URL path's extension.
        import mimetypes

        guessed, _ = mimetypes.guess_type(src)
        mime = guessed or "application/octet-stream"
        return ContentToolCallContent(
            type="content",
            content=ImageContentBlock(type="image", data="", mime_type=mime, uri=src),
        )
    # Plain base64 — assume PNG (most common). If the caller has
    # something else they should use a data URI to specify it.
    return ContentToolCallContent(
        type="content",
        content=ImageContentBlock(type="image", data=src, mime_type="image/png"),
    )


def _content_blocks_from_result(
    result: Any,
    *,
    fence_text: bool = False,
) -> list[ContentToolCallContent]:
    """Wrap the tool result as a list of ``ContentToolCallContent`` blocks.

    Returns an empty list for empty / unsupported result shapes so
    the caller can decide whether to send a content update at all
    (we never want an empty content list to overwrite the input
    view set at start time).

    When ``fence_text`` is True, all text-derived blocks are wrapped
    in a markdown code fence so editors render them monospace /
    preserve whitespace. Used for shell-execution tool output where
    the result is typically tabular or code-like and looks bad as
    flowed text.

    Supported shapes:
    - Primitives (``str`` / ``int`` / ``float`` / ``bool``) → text block
    - ``ContentText`` → text block
    - ``ContentImage`` → image block (data URI parsed, HTTP URL passed through)
    - ``list[Content...]`` → one block per supported item (text + image),
      unsupported types (audio/video/document) skipped silently
    """
    if result is None or result == "":
        return []
    blocks: list[ContentToolCallContent] = []
    if isinstance(result, (str, int, float, bool)):
        blocks.append(_text_block(str(result), fence=fence_text))
    elif isinstance(result, ContentText):
        blocks.append(_text_block(result.text, fence=fence_text))
    elif isinstance(result, ContentImage):
        blocks.append(_image_block(result))
    elif isinstance(result, list):
        for item in result:
            if isinstance(item, ContentText):
                if item.text:
                    blocks.append(_text_block(item.text, fence=fence_text))
            elif isinstance(item, ContentImage):
                blocks.append(_image_block(item))
            # Other content types (audio, video, document) are
            # currently dropped — adding them is a follow-on once a
            # consumer needs the round-trip.
    return blocks


def _is_shell_execution_tool(function: str) -> bool:
    """Whether ``function`` is one of the shell-execution family.

    Used to decide whether to fence the tool result as a code block
    when forwarding to ACP clients — terminal output is tabular /
    monospace by convention and looks bad as flowed markdown text.
    Mirrors (and is the inverse rationale of) why these tools never
    map to ``kind="execute"`` in :data:`_TOOL_KIND_BY_NAME` —
    everything about them is "shell-like."
    """
    return function in (
        "bash",
        "python",
        "bash_session",
        "code_execution",
    ) or function.startswith("bash_session_")


def _content_for_update(event: ToolEvent) -> list[ToolCallContentVariant] | None:
    """Build the ``content`` payload for an ``update_tool_call`` notification.

    ``ToolCallUpdate.content`` REPLACES the content collection set
    by the prior ``ToolCallStart``, so we have to preserve the
    input view (if any) by prepending it whenever we send result
    blocks — otherwise the editor would lose the rendered command /
    code / input shown at start time.

    File-edit family (text_editor create/str_replace) gets native
    ``FileEditToolCallContent`` so editors render an actual diff. The
    diff replaces both view and result blocks — the diff *is* the
    canonical representation of what changed.

    For shell-execution tools the result text is fenced as a
    markdown code block so editors render it as monospace
    (preserving the alignment of ``ls`` listings, ``wc`` columns,
    etc.). Non-shell tools get the result as plain markdown text
    (web_search/web_fetch/etc. typically return descriptive text
    that's already markdown-friendly).

    Returns ``None`` when there's nothing to add (no result yet, or
    a non-text result shape we don't render inline). The
    notification's ``content`` field stays unset and the start's
    content survives.
    """
    file_edit = _file_edit_content_for_event(event)
    if file_edit is not None:
        return list(file_edit)
    result_blocks = _content_blocks_from_result(
        event.result,
        fence_text=_is_shell_execution_tool(event.function),
    )
    if not result_blocks:
        return None
    view_blocks = _content_from_view(event) or []
    combined: list[ToolCallContentVariant] = [*view_blocks, *result_blocks]
    return combined


def _content_for_start(event: ToolEvent) -> list[ToolCallContentVariant] | None:
    """Build the ``content`` payload for a first-sighting ``ToolCallStart``.

    Live flow: the start fires while the tool is still pending, so
    only the view is available. Returns the view if any, else None.

    Replay flow (late-attach): we see an event that's ALREADY
    completed. The live path would have layered the result in via a
    subsequent ``ToolCallUpdate``, but late attach skips straight to
    the start — so the result has to ride on the start notification
    too, or late clients see an input view and no output (while live
    clients saw both).

    File-edit family (text_editor create/str_replace) gets native
    ``FileEditToolCallContent`` here too — same diff content whether
    we're starting or updating.

    Returns ``None`` only when neither view nor result nor edit-content
    is available.
    """
    file_edit = _file_edit_content_for_event(event)
    if file_edit is not None:
        return list(file_edit)
    view_blocks = _content_from_view(event) or []
    result_blocks = _content_blocks_from_result(
        event.result,
        fence_text=_is_shell_execution_tool(event.function),
    )
    combined: list[ToolCallContentVariant] = [*view_blocks, *result_blocks]
    return combined or None


# Tools whose argument dict carries `command` + `path` + edit args in the
# text_editor shape. Same arg names as Anthropic's str_replace_based_edit_tool
# convention. The Inspect `memory` tool follows the identical shape for its
# create / str_replace commands, so it shares this code path.
_FILE_EDIT_TOOL_FUNCTIONS = ("text_editor", "memory")


def _file_edit_content_for_event(
    event: ToolEvent,
) -> list[FileEditToolCallContent] | None:
    """Build native ``FileEditToolCallContent`` for edit-family tools.

    Returns ``None`` for non-edit tools and for edit-tool commands that
    aren't a true diff (``view`` / ``undo_edit`` / ``insert``). The
    caller falls through to generic content rendering.

    **Only emitted for SUCCESSFUL completed events.** A failed edit
    (e.g. ``str_replace`` whose ``old_str`` wasn't found or wasn't
    unique) would otherwise publish a diff that looks legitimate but
    represents no actual file change. Pending events also return None
    because the edit hasn't happened yet — the start notification
    falls through to the generic content path which shows the input
    view + (if present) the result.

    ``insert`` could be mapped (old_text="" + new_text=insert_text) but
    that loses the line-number context the editor needs to render it
    meaningfully — generic content with the rendered view conveys more.
    Revisit if a specific editor needs the diff form.
    """
    if event.function not in _FILE_EDIT_TOOL_FUNCTIONS:
        return None
    # Don't show a diff until the edit has actually succeeded. Pending,
    # errored, and failed events all skip — the generic content path
    # is right for them (input view + any partial / error message).
    if event.pending or event.error is not None or event.failed:
        return None
    args = event.arguments or {}
    command = args.get("command")
    path = args.get("path")
    if not isinstance(path, str) or not path:
        return None
    if command == "create":
        file_text = args.get("file_text")
        if not isinstance(file_text, str):
            return None
        return [tool_diff_content(path=path, new_text=file_text, old_text=None)]
    if command == "str_replace":
        old_str = args.get("old_str")
        new_str = args.get("new_str")
        if not isinstance(old_str, str):
            return None
        # `new_str` is allowed to be None on str_replace (means "delete
        # old_str"); represent as empty new_text so the diff renders.
        return [
            tool_diff_content(
                path=path,
                new_text=new_str if isinstance(new_str, str) else "",
                old_text=old_str,
            )
        ]
    return None
