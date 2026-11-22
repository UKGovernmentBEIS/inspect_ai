from typing import Any, Callable

CanonicalArguments = Callable[[dict[str, Any]], dict[str, Any]]
"""Maps a tool call's arguments to the ones the tool will act on."""


def tool_canonical_arguments(tool: Callable[..., Any]) -> CanonicalArguments | None:
    return getattr(tool, TOOL_CANONICAL_ARGUMENTS, None)


def set_tool_canonical_arguments(
    tool: Callable[..., Any], canonical: CanonicalArguments
) -> None:
    """Approve calls to `tool` on `canonical(arguments)`, and run it with them.

    For a tool that resolves its arguments before acting on them (e.g. a path
    with `..` segments), so approval policies match what the tool will do.
    """
    setattr(tool, TOOL_CANONICAL_ARGUMENTS, canonical)


TOOL_CANONICAL_ARGUMENTS = "__TOOL_CANONICAL_ARGUMENTS__"
