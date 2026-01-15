from __future__ import annotations

import json
from typing import Awaitable, Callable

from inspect_ai._util.content import (
    Content,
    ContentAudio,
    ContentDocument,
    ContentImage,
    ContentReasoning,
    ContentText,
    ContentToolUse,
    ContentVideo,
)
from inspect_ai._util.url import is_data_uri
from inspect_ai.model._chat_message import ChatMessage, ChatMessageAssistant

# Type alias for media content
MediaContent = ContentImage | ContentAudio | ContentVideo | ContentDocument

# Conservative fallback values (for non-data-URIs)
# These intentionally overcount since this is used for context compaction triggering
FALLBACK_IMAGE_TOKENS = 1600  # max high-detail
FALLBACK_AUDIO_TOKENS = 2000  # ~40 seconds at 50 tok/sec
FALLBACK_VIDEO_TOKENS = 8000  # ~20 seconds at 400 tok/sec
FALLBACK_DOCUMENT_TOKENS = 5000  # ~5 pages at 1000 tok/page

# Size estimation constants (for data URIs)
AUDIO_BYTES_PER_SEC_MP3 = 16_000  # ~128kbps
AUDIO_BYTES_PER_SEC_WAV = 176_000  # 44.1kHz/16bit stereo
VIDEO_BYTES_PER_SEC = 500_000  # ~4Mbps
DOCUMENT_BYTES_PER_PAGE = 100_000  # ~100KB/page for PDF

# Token rates (conservative upper bounds)
# These are higher than actual rates to ensure we overcount rather than undercount
AUDIO_TOKENS_PER_SEC = 50  # > Gemini's 32 tok/sec
VIDEO_TOKENS_PER_SEC = 400  # > Gemini's 300 tok/sec
DOCUMENT_TOKENS_PER_PAGE = 1000


async def count_tokens(
    messages: list[ChatMessage],
    count_text: Callable[[str], Awaitable[int]],
    count_media: Callable[[MediaContent], Awaitable[int]],
) -> int:
    """Count tokens in a list of chat messages.

    Args:
        messages: List of chat messages to count tokens for.
        count_text: Async callable to count tokens in text.
        count_media: Async callable to count tokens in media content.

    Returns:
        Total estimated token count.
    """
    # Accumulate text and media to minimize API calls
    text_parts: list[str] = []
    media_items: list[MediaContent] = []

    def collect_content(content: Content) -> None:
        """Collect text and media from a content item."""
        if isinstance(content, ContentText):
            text_parts.append(content.text)
        elif isinstance(content, ContentReasoning):
            # Only count summary - reasoning may be encrypted/redacted
            if content.summary:
                text_parts.append(content.summary)
        elif isinstance(
            content, (ContentImage, ContentAudio, ContentVideo, ContentDocument)
        ):
            media_items.append(content)
        elif isinstance(content, ContentToolUse):
            text_parts.append(content.name)
            text_parts.append(content.arguments)
            text_parts.append(content.result)
            if content.error:
                text_parts.append(content.error)
        # ContentData and unknown types contribute 0 tokens

    # Collect from message content
    for message in messages:
        if isinstance(message.content, str):
            text_parts.append(message.content)
        else:
            for content in message.content:
                collect_content(content)

        # Collect from tool calls in assistant messages
        if isinstance(message, ChatMessageAssistant) and message.tool_calls:
            for tool_call in message.tool_calls:
                text_parts.append(tool_call.function)
                text_parts.append(json.dumps(tool_call.arguments))

    # Count tokens
    total_tokens = 0

    if text_parts:
        combined_text = "\n".join(text_parts)
        total_tokens += await count_text(combined_text)

    for media in media_items:
        total_tokens += await count_media(media)

    return max(1, total_tokens)


def count_text_tokens(text: str) -> int:
    """Estimate tokens from text using tiktoken (o200k_base with 10% buffer).

    Most models used for long-horizon agents (Qwen, DeepSeek, Llama 3) have
    100k-150k vocabularies, so o200k_base systematically undercounts by ~10%.
    We add a 10% buffer since undercounting is worse than overcounting when
    this is used as a trigger for context compaction.
    """
    import tiktoken

    enc = tiktoken.get_encoding("o200k_base")
    token_count = len(enc.encode(text))
    return max(1, int(token_count * 1.1))


def count_media_tokens(media: MediaContent) -> int:
    """Estimate tokens for media content based on type and size.

    For data URIs, estimates are based on decoded size using conservative
    heuristics. For URLs/file paths, uses fixed conservative fallbacks.

    All estimates intentionally overcount since this is used for context
    compaction triggering where undercounting is worse than overcounting.

    Args:
        media: Media content (image, audio, video, or document).

    Returns:
        Estimated token count.
    """
    if isinstance(media, ContentImage):
        return _count_image_tokens(media)
    elif isinstance(media, ContentAudio):
        return _count_audio_tokens(media)
    elif isinstance(media, ContentVideo):
        return _count_video_tokens(media)
    elif isinstance(media, ContentDocument):
        return _count_document_tokens(media)
    else:
        # Unknown media type - return conservative estimate
        return FALLBACK_IMAGE_TOKENS


def _count_image_tokens(image: ContentImage) -> int:
    """Estimate tokens for an image based on detail level.

    Uses OpenAI's vision token formula as the basis:
    - Low detail: 85 tokens
    - High/auto detail: 765 tokens (for ~1024x1024 image)

    This is a reasonable approximation across providers since it's based on
    the most common vision model pricing structure.
    """
    if image.detail == "low":
        return 85
    else:  # "high" or "auto"
        return 765


def _count_audio_tokens(audio: ContentAudio) -> int:
    """Estimate tokens for audio content.

    For data URIs, estimates duration from decoded size and applies
    conservative token rate. For URLs/file paths, uses fixed fallback.
    """
    if is_data_uri(audio.audio):
        # Estimate raw bytes from base64 length (base64 is ~33% larger than raw)
        raw_bytes = len(audio.audio) * 3 // 4

        # Select bytes/sec based on format
        if audio.format == "wav":
            bytes_per_second = AUDIO_BYTES_PER_SEC_WAV
        else:  # mp3
            bytes_per_second = AUDIO_BYTES_PER_SEC_MP3

        duration_seconds = raw_bytes / bytes_per_second
        tokens = int(duration_seconds * AUDIO_TOKENS_PER_SEC)
        return max(50, tokens)  # Minimum 50 tokens
    else:
        return FALLBACK_AUDIO_TOKENS


def _count_video_tokens(video: ContentVideo) -> int:
    """Estimate tokens for video content.

    For data URIs, estimates duration from decoded size and applies
    conservative token rate. For URLs/file paths, uses fixed fallback.
    """
    if is_data_uri(video.video):
        # Estimate raw bytes from base64 length (base64 is ~33% larger than raw)
        raw_bytes = len(video.video) * 3 // 4

        duration_seconds = raw_bytes / VIDEO_BYTES_PER_SEC
        tokens = int(duration_seconds * VIDEO_TOKENS_PER_SEC)
        return max(100, tokens)  # Minimum 100 tokens
    else:
        return FALLBACK_VIDEO_TOKENS


def _count_document_tokens(document: ContentDocument) -> int:
    """Estimate tokens for document content.

    For data URIs, estimates page count from decoded size and applies
    conservative token rate. For URLs/file paths, uses fixed fallback.
    """
    if is_data_uri(document.document):
        # Estimate raw bytes from base64 length (base64 is ~33% larger than raw)
        raw_bytes = len(document.document) * 3 // 4

        pages = raw_bytes / DOCUMENT_BYTES_PER_PAGE
        tokens = int(pages * DOCUMENT_TOKENS_PER_PAGE)
        return max(100, tokens)  # Minimum 100 tokens
    else:
        return FALLBACK_DOCUMENT_TOKENS
