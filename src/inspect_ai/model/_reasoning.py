import base64
import fnmatch
import html
import json
import re
from logging import getLogger
from typing import Literal, NamedTuple

from pydantic import JsonValue

from inspect_ai._util.content import (
    Content,
    ContentReasoning,
    ContentText,
)
from inspect_ai.model._chat_message import ChatMessage, ChatMessageAssistant

logger = getLogger(__name__)


class ReasoningParserRule(NamedTuple):
    families: tuple[str, ...]
    parser: str
    include: tuple[str, ...]


NO_REASONING_MODEL_PATTERNS: tuple[str, ...] = (
    "*[-._/]base*",
    "*[-._/]embedding*",
    "*[-._/]reranker*",
    "*[-._/]guard*",
    "*no*think*",
    "*qwen3*instruct*",
    "*qwen3-coder-next*",
    "*kimi-k2*instruct*",
)

REASONING_PARSER_RULES: tuple[ReasoningParserRule, ...] = (
    ReasoningParserRule(("DeepSeek V4",), "deepseek_v4", ("*deepseek-v4*",)),
    ReasoningParserRule(("DeepSeek V3",), "deepseek_v3", ("*deepseek-v3*",)),
    ReasoningParserRule(
        ("DeepSeek R1", "QwQ", "Intern-S1", "Trinity"),
        "deepseek_r1",
        (
            "*deepseek-r1*",
            "*qwq*",
            "*intern-s1*",
            "*trinity-*think*",
            "*trinity-*reasoning*",
        ),
    ),
    ReasoningParserRule(
        ("Qwen3", "Intern-S2+", "Mellum"),
        "qwen3",
        (
            "*qwen3*",
            "*intern-s[2-9]*",
            "*mellum*-*think*",
            "*mellum*-*reasoning*",
        ),
    ),
    ReasoningParserRule(("Kimi K2",), "kimi_k2", ("*kimi-k2*",)),
    ReasoningParserRule(
        ("Mistral", "Magistral", "Ministral"),
        "mistral",
        (
            "*magistral*",
            "*ministral*reasoning*",
            "*mistral-medium-3.5*",
            "*mistral-small-4*",
        ),
    ),
    ReasoningParserRule(
        ("MiniMax M2", "MM M2"),
        "minimax_m2",
        ("*minimax-m2*", "*mm-m2*"),
    ),
    ReasoningParserRule(
        ("GLM", "Glyph"),
        "glm45",
        (
            "*glm-4.[5-9]*",
            "*glm-4.[1-9][0-9]*",
            "*glm-5*",
            "*glm-ga*",
            "*glyph*",
        ),
    ),
    ReasoningParserRule(("Gemma 4",), "gemma4", ("*gemma-4*",)),
    ReasoningParserRule(("ERNIE 4.5",), "ernie45", ("*ernie-4*-*thinking*",)),
    ReasoningParserRule(
        ("Granite",),
        "granite",
        (
            "*granite-3.[2-9]*",
            "*granite-3.[1-9][0-9]*",
        ),
    ),
    ReasoningParserRule(("Hunyuan A13B",), "hunyuan_a13b", ("*hunyuan-*a13b*",)),
    ReasoningParserRule(
        ("Hunyuan V3", "Hy3"),
        "hy_v3",
        (
            "*hy3*",
            "*hunyuan3*",
            "*hunyuan-3*",
        ),
    ),
    ReasoningParserRule(("Holo2",), "holo2", ("*holo2*",)),
    ReasoningParserRule(
        ("MiMo V2", "Xiaomi MiMo V2"),
        "mimo",
        (
            "*mimo-v2*",
            "*xiaomimimo-v2*",
        ),
    ),
    ReasoningParserRule(
        ("Olmo 3",),
        "olmo3",
        ("*olmo-3*-*think*", "*olmo-3*-*reasoning*"),
    ),
    ReasoningParserRule(
        ("Seed OSS",),
        "seed_oss",
        (
            "*seed-oss*",
            "*seed_oss*",
            "*seedoss*",
        ),
    ),
    ReasoningParserRule(
        ("Nemotron V3", "NVIDIA Nemotron V3"),
        "nemotron_v3",
        (
            "*nemotron-3-super*",
            "*nvidia-nemotron-3-super*",
            "*nemotron-3-ultra*",
            "*nvidia-nemotron-3-ultra*",
            "*nemotron-3-*omni*",
            "*nemotron-3-*reasoning*",
            "*nvidia-nemotron-3-*omni*",
            "*nvidia-nemotron-3-*reasoning*",
        ),
    ),
    ReasoningParserRule(
        ("Step 3.5+",),
        "step3p5",
        ("*step-3.[5-9]*", "*step-3.[1-9][0-9]*"),
    ),
    ReasoningParserRule(("Step 3",), "step3", ("*step-3*",)),
    ReasoningParserRule(
        ("Cohere Command A reasoning",),
        "cohere_command3",
        ("*command-a-*reasoning*",),
    ),
    ReasoningParserRule(
        ("Cohere Command A Plus", "North"),
        "cohere_command4",
        ("*command-a-plus*", "*north-*"),
    ),
    ReasoningParserRule(
        ("Poolside V1", "Laguna"),
        "poolside_v1",
        ("*laguna*", "*poolside-*laguna*"),
    ),
)

# Fixed effort -> token budget table used to bridge `reasoning_effort` onto
# providers that only accept an explicit token budget (Anthropic Claude 3.7-4.5,
# Google Gemini 2.5). Magnitudes mirror the existing Anthropic max_tokens-sizing
# table in anthropic.py (with `minimal` added) and clear Anthropic's 1024-token
# API floor across the board.
_EFFORT_TO_TOKENS: dict[str, int] = {
    "minimal": 2048,
    "low": 4096,
    "medium": 10000,
    "high": 16000,
    "xhigh": 32000,
    "max": 32000,
}


def effort_to_reasoning_tokens(
    effort: Literal["none", "minimal", "low", "medium", "high", "xhigh", "max"]
    | str
    | None,
) -> int | None:
    """Translate a `reasoning_effort` value into a token budget.

    Returns None for `None` and `"none"` (no reasoning requested). Returns the
    mapped int for any supported effort level.
    """
    if effort is None or effort == "none":
        return None
    return _EFFORT_TO_TOKENS.get(effort)


def clamp_reasoning_effort_to_low_medium_high(
    effort: Literal["none", "minimal", "low", "medium", "high", "xhigh", "max"]
    | str
    | None,
) -> Literal["low", "medium", "high"] | None:
    """Clamp a `reasoning_effort` value to the `low`/`medium`/`high` tier.

    Used by providers that pass effort through to upstream APIs which only
    accept the three-level scale (Groq, Ollama, SageMaker). Returns None for
    `None` and `"none"`.
    """
    if effort is None or effort == "none":
        return None
    match effort:
        case "minimal" | "low":
            return "low"
        case "medium":
            return "medium"
        case "high" | "xhigh" | "max":
            return "high"
    return None


class ReasoningCapsule(NamedTuple):
    reasoning: str
    signature: str | None = None
    redacted: bool = False
    summary: str | None = None
    internal: JsonValue | None = None


def parse_content_with_reasoning(content: str) -> tuple[str, ReasoningCapsule | None]:
    """
    Looks for and extracts <think/> tags into reasoning text.

    Returns a tuple:
    - The first element is the input content with the <think> tag and its contents fully removed.
    - The second element is a ReasoningCapsule named tuple (or None if no <think> tag is found).
    """
    # Match <think> tag with any attributes
    pattern = r"<think([^>]*)>(.*?)</think>"
    match = re.search(pattern, content, re.DOTALL)

    if match:
        attrs_str = match.group(1)
        reasoning = match.group(2).strip()

        # Parse attributes from opening tag
        signature = _parse_attr(attrs_str, "signature")
        redacted = _parse_attr(attrs_str, "redacted") == "true"
        internal = _parse_internal_attr(attrs_str)

        # Extract nested <summary> tag from content
        reasoning, summary = _parse_summary(reasoning)
        if redacted and signature and signature.startswith("rs_"):
            # Redacted reasoning bodies carry opaque provider payloads such as
            # encrypted_content. Some text scaffolds wrap long lines; whitespace
            # inserted there is not part of the payload.
            reasoning = re.sub(r"\s+", "", reasoning)

        # Remove the matched <think>...</think> from the input
        start, end = match.span()

        return (
            (content[:start] + content[end:]).strip(),
            ReasoningCapsule(
                reasoning=reasoning,
                signature=signature,
                redacted=redacted,
                summary=summary,
                internal=internal,
            ),
        )
    else:
        return content, None


def reasoning_parser_for_model(model: str | None) -> str | None:
    if not model:
        return None

    if _matches_model_patterns(model, NO_REASONING_MODEL_PATTERNS):
        return None

    for rule in REASONING_PARSER_RULES:
        if _matches_model_patterns(model, rule.include):
            return rule.parser

    return None


def _matches_model_patterns(model: str, patterns: tuple[str, ...]) -> bool:
    model_path = f"/{model}".lower()
    return any(fnmatch.fnmatchcase(model_path, pattern) for pattern in patterns)


def _parse_attr(attrs_str: str, name: str) -> str | None:
    """Extract attribute value from attributes string.

    Values are HTML-unescaped to invert the escaping done by
    `reasoning_to_think_tag`. Plain values without entities are
    unchanged.
    """
    match = re.search(rf'{name}="([^"]*)"', attrs_str)
    return html.unescape(match.group(1)) if match else None


def _parse_internal_attr(attrs_str: str) -> JsonValue | None:
    """Extract and JSON-decode the internal attribute value (base64-encoded JSON)."""
    raw = _parse_attr(attrs_str, "internal")
    if raw is None:
        return None
    try:
        decoded = base64.b64decode(raw).decode("utf-8")
        result: JsonValue = json.loads(decoded)
        return result
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
        return None


def _parse_summary(content: str) -> tuple[str, str | None]:
    """Extract <summary> tag from content, returning (remaining_content, summary)."""
    pattern = r"<summary>(.*?)</summary>\s*"
    match = re.search(pattern, content, re.DOTALL)
    if match:
        summary = match.group(1)
        remaining = content[: match.start()] + content[match.end() :]
        return remaining.strip(), summary
    return content, None


def reasoning_to_think_tag(reasoning: "ContentReasoning") -> str:
    """Convert ContentReasoning to a <think> tag string for text-based serialization.

    This is the inverse of parse_content_with_reasoning - it takes a ContentReasoning
    object and produces a <think> tag string that can be embedded in plain text messages
    for agent bridge scenarios.
    """
    attribs = ""
    if reasoning.signature is not None:
        # HTML-escape so signatures containing quotes, '<', '>', or '&'
        # (e.g. OpenRouter's reasoning-details JSON payload) survive the
        # attribute round-trip. Plain signatures are unchanged.
        signature = html.escape(reasoning.signature, quote=True)
        attribs = f'{attribs} signature="{signature}"'
    if reasoning.redacted:
        attribs = f'{attribs} redacted="true"'
    if reasoning.internal is not None:
        # Base64 encode the JSON for safe embedding in an attribute
        internal_json = json.dumps(reasoning.internal)
        internal_b64 = base64.b64encode(internal_json.encode("utf-8")).decode("ascii")
        attribs = f'{attribs} internal="{internal_b64}"'

    inner = ""
    if reasoning.summary is not None:
        inner = f"<summary>{reasoning.summary}</summary>\n"
    inner = f"{inner}{reasoning.reasoning}"

    return f"<think{attribs}>\n{inner}\n</think>"


def emulate_reasoning_history(messages: list[ChatMessage]) -> list[ChatMessage]:
    emulated_messages: list[ChatMessage] = []
    for message in messages:
        if isinstance(message, ChatMessageAssistant) and isinstance(
            message.content, list
        ):
            content: list[Content] = []
            for c in message.content:
                if isinstance(c, ContentReasoning):
                    content.append(ContentText(text=reasoning_to_think_tag(c)))
                else:
                    content.append(c)
            message = message.model_copy(update={"content": content})

        emulated_messages.append(message)
    return emulated_messages
