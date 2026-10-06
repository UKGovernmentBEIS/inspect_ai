from ._content import (
    ContentAudio,
    ContentDocument,
    ContentImage,
    ContentText,
    ContentVideo,
)

ToolResult = (
    str
    | int
    | float
    | bool
    | ContentText
    | ContentImage
    | ContentAudio
    | ContentVideo
    | ContentDocument
    | list[ContentText | ContentImage | ContentAudio | ContentVideo | ContentDocument]
)
"""Valid types for results from tool calls."""
