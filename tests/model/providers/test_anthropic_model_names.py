"""Tests for AnthropicAPI model name detection methods.

Covers all known model name formats (API IDs, aliases, Bedrock IDs, Vertex IDs)
across all Claude model generations.
"""

import pytest

from inspect_ai.model._providers.anthropic import AnthropicAPI

# Methods under test
DETECTION_METHODS = [
    "is_claude_3",
    "is_claude_3_5",
    "is_claude_3_7",
    "is_claude_4",
    "is_claude_4_0",
    "is_claude_4_1",
    "is_claude_4_5",
    "is_claude_4_6",
    "is_claude_4_7",
    "is_claude_4_opus",
    "is_thinking_model",
    "is_claude_latest",
]


def _make_stub(model_name: str) -> object:
    """Create a stub with service_model_name() and all detection methods bound."""

    class _Stub:
        pass

    stub = _Stub()
    stub.service_model_name = lambda: model_name  # type: ignore[attr-defined]

    # Bind all detection methods (and private helpers) from AnthropicAPI
    import types

    for name in dir(AnthropicAPI):
        if (
            name.startswith("is_claude")
            or name.startswith("is_thinking")
            or name == "_is_claude_4_x"
        ):
            method = getattr(AnthropicAPI, name)
            if callable(method):
                setattr(stub, name, types.MethodType(method, stub))

    return stub


def _check_model(model_name: str, expected: dict[str, bool]) -> None:
    """Create a stub and verify all detection methods."""
    stub = _make_stub(model_name)

    for method_name in DETECTION_METHODS:
        result = getattr(stub, method_name)()
        assert result == expected[method_name], (
            f"{method_name}('{model_name}') = {result}, expected {expected[method_name]}"
        )


# Expected results for each model family
_CLAUDE_3 = {
    "is_claude_3": True,
    "is_claude_3_5": False,
    "is_claude_3_7": False,
    "is_claude_4": False,
    "is_claude_4_0": False,
    "is_claude_4_1": False,
    "is_claude_4_5": False,
    "is_claude_4_6": False,
    "is_claude_4_7": False,
    "is_claude_4_opus": False,
    "is_thinking_model": False,
    "is_claude_latest": False,
}

_CLAUDE_3_5 = {
    "is_claude_3": False,
    "is_claude_3_5": True,
    "is_claude_3_7": False,
    "is_claude_4": False,
    "is_claude_4_0": False,
    "is_claude_4_1": False,
    "is_claude_4_5": False,
    "is_claude_4_6": False,
    "is_claude_4_7": False,
    "is_claude_4_opus": False,
    "is_thinking_model": False,
    "is_claude_latest": False,
}

_CLAUDE_3_7 = {
    "is_claude_3": False,
    "is_claude_3_5": False,
    "is_claude_3_7": True,
    "is_claude_4": False,
    "is_claude_4_0": False,
    "is_claude_4_1": False,
    "is_claude_4_5": False,
    "is_claude_4_6": False,
    "is_claude_4_7": False,
    "is_claude_4_opus": False,
    "is_thinking_model": True,
    "is_claude_latest": False,
}

_CLAUDE_4_0_SONNET = {
    "is_claude_3": False,
    "is_claude_3_5": False,
    "is_claude_3_7": False,
    "is_claude_4": True,
    "is_claude_4_0": True,
    "is_claude_4_1": False,
    "is_claude_4_5": False,
    "is_claude_4_6": False,
    "is_claude_4_7": False,
    "is_claude_4_opus": False,
    "is_thinking_model": True,
    "is_claude_latest": False,
}

_CLAUDE_4_0_OPUS = {
    "is_claude_3": False,
    "is_claude_3_5": False,
    "is_claude_3_7": False,
    "is_claude_4": True,
    "is_claude_4_0": True,
    "is_claude_4_1": False,
    "is_claude_4_5": False,
    "is_claude_4_6": False,
    "is_claude_4_7": False,
    "is_claude_4_opus": True,
    "is_thinking_model": True,
    "is_claude_latest": False,
}

_CLAUDE_4_1_OPUS = {
    "is_claude_3": False,
    "is_claude_3_5": False,
    "is_claude_3_7": False,
    "is_claude_4": True,
    "is_claude_4_0": False,
    "is_claude_4_1": True,
    "is_claude_4_5": False,
    "is_claude_4_6": False,
    "is_claude_4_7": False,
    "is_claude_4_opus": True,
    "is_thinking_model": True,
    "is_claude_latest": False,
}

_CLAUDE_4_5_SONNET = {
    "is_claude_3": False,
    "is_claude_3_5": False,
    "is_claude_3_7": False,
    "is_claude_4": True,
    "is_claude_4_0": False,
    "is_claude_4_1": False,
    "is_claude_4_5": True,
    "is_claude_4_6": False,
    "is_claude_4_7": False,
    "is_claude_4_opus": False,
    "is_thinking_model": True,
    "is_claude_latest": False,
}

_CLAUDE_4_5_OPUS = {
    "is_claude_3": False,
    "is_claude_3_5": False,
    "is_claude_3_7": False,
    "is_claude_4": True,
    "is_claude_4_0": False,
    "is_claude_4_1": False,
    "is_claude_4_5": True,
    "is_claude_4_6": False,
    "is_claude_4_7": False,
    "is_claude_4_opus": True,
    "is_thinking_model": True,
    "is_claude_latest": False,
}

_CLAUDE_4_5_HAIKU = {
    "is_claude_3": False,
    "is_claude_3_5": False,
    "is_claude_3_7": False,
    "is_claude_4": True,
    "is_claude_4_0": False,
    "is_claude_4_1": False,
    "is_claude_4_5": True,
    "is_claude_4_6": False,
    "is_claude_4_7": False,
    "is_claude_4_opus": False,
    "is_thinking_model": True,
    "is_claude_latest": False,
}

_CLAUDE_4_6_SONNET = {
    "is_claude_3": False,
    "is_claude_3_5": False,
    "is_claude_3_7": False,
    "is_claude_4": True,
    "is_claude_4_0": False,
    "is_claude_4_1": False,
    "is_claude_4_5": False,
    "is_claude_4_6": True,
    "is_claude_4_7": False,
    "is_claude_4_opus": False,
    "is_thinking_model": True,
    "is_claude_latest": False,
}

_CLAUDE_4_6_OPUS = {
    "is_claude_3": False,
    "is_claude_3_5": False,
    "is_claude_3_7": False,
    "is_claude_4": True,
    "is_claude_4_0": False,
    "is_claude_4_1": False,
    "is_claude_4_5": False,
    "is_claude_4_6": True,
    "is_claude_4_7": False,
    "is_claude_4_opus": True,
    "is_thinking_model": True,
    "is_claude_latest": False,
}

_CLAUDE_4_7_OPUS = {
    "is_claude_3": False,
    "is_claude_3_5": False,
    "is_claude_3_7": False,
    "is_claude_4": True,
    "is_claude_4_0": False,
    "is_claude_4_1": False,
    "is_claude_4_5": False,
    "is_claude_4_6": False,
    "is_claude_4_7": True,
    "is_claude_4_opus": True,
    "is_thinking_model": True,
    "is_claude_latest": False,
}

_CLAUDE_4_7_NON_OPUS = {
    **_CLAUDE_4_7_OPUS,
    "is_claude_4_opus": False,
}

_CLAUDE_FUTURE = {
    "is_claude_3": False,
    "is_claude_3_5": False,
    "is_claude_3_7": False,
    "is_claude_4": False,
    "is_claude_4_0": False,
    "is_claude_4_1": False,
    "is_claude_4_5": False,
    "is_claude_4_6": False,
    "is_claude_4_7": False,
    "is_claude_4_opus": False,
    "is_thinking_model": True,
    "is_claude_latest": True,
}

_CLAUDE_FUTURE_4_MINOR = {
    "is_claude_3": False,
    "is_claude_3_5": False,
    "is_claude_3_7": False,
    "is_claude_4": True,
    "is_claude_4_0": False,
    "is_claude_4_1": False,
    "is_claude_4_5": False,
    "is_claude_4_6": False,
    "is_claude_4_7": False,
    "is_claude_4_opus": False,
    "is_thinking_model": True,
    "is_claude_latest": True,
}

_CLAUDE_FUTURE_4_MINOR_OPUS = {
    **_CLAUDE_FUTURE_4_MINOR,
    "is_claude_4_opus": True,
}


# ── Claude 3 (Haiku) ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "model_name",
    [
        # API ID
        "claude-3-haiku-20240307",
        # Bedrock
        "anthropic.claude-3-haiku-20240307-v1:0",
        # Vertex
        "claude-3-haiku@20240307",
    ],
)
def test_claude_3_haiku(model_name: str) -> None:
    _check_model(model_name, _CLAUDE_3)


# ── Claude 3.5 ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "model_name",
    [
        # Sonnet API ID
        "claude-3-5-sonnet-20241022",
        # Haiku API ID
        "claude-3-5-haiku-20241022",
    ],
)
def test_claude_3_5(model_name: str) -> None:
    _check_model(model_name, _CLAUDE_3_5)


# ── Claude 3.7 ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "model_name",
    [
        "claude-3-7-sonnet-20250219",
    ],
)
def test_claude_3_7(model_name: str) -> None:
    _check_model(model_name, _CLAUDE_3_7)


# ── Claude 4.0 Sonnet ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "model_name",
    [
        # API ID (dated, no minor version)
        "claude-sonnet-4-20250514",
        # Alias
        "claude-sonnet-4-0",
        # Bedrock
        "anthropic.claude-sonnet-4-20250514-v1:0",
        # Vertex
        "claude-sonnet-4@20250514",
    ],
)
def test_claude_4_0_sonnet(model_name: str) -> None:
    _check_model(model_name, _CLAUDE_4_0_SONNET)


# ── Claude 4.0 Opus ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "model_name",
    [
        # API ID (dated, no minor version)
        "claude-opus-4-20250514",
        # Alias
        "claude-opus-4-0",
        # Bedrock
        "anthropic.claude-opus-4-20250514-v1:0",
        # Vertex
        "claude-opus-4@20250514",
    ],
)
def test_claude_4_0_opus(model_name: str) -> None:
    _check_model(model_name, _CLAUDE_4_0_OPUS)


# ── Claude 4.1 Opus ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "model_name",
    [
        # API ID
        "claude-opus-4-1-20250805",
        # Alias
        "claude-opus-4-1",
        # Bedrock
        "anthropic.claude-opus-4-1-20250805-v1:0",
        # Vertex
        "claude-opus-4-1@20250805",
    ],
)
def test_claude_4_1_opus(model_name: str) -> None:
    _check_model(model_name, _CLAUDE_4_1_OPUS)


# ── Claude 4.5 Sonnet ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "model_name",
    [
        # API ID
        "claude-sonnet-4-5-20250929",
        # Alias
        "claude-sonnet-4-5",
        # Bedrock
        "anthropic.claude-sonnet-4-5-20250929-v1:0",
        # Vertex
        "claude-sonnet-4-5@20250929",
    ],
)
def test_claude_4_5_sonnet(model_name: str) -> None:
    _check_model(model_name, _CLAUDE_4_5_SONNET)


# ── Claude 4.5 Opus ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "model_name",
    [
        # API ID
        "claude-opus-4-5-20251101",
        # Alias
        "claude-opus-4-5",
        # Bedrock
        "anthropic.claude-opus-4-5-20251101-v1:0",
        # Vertex
        "claude-opus-4-5@20251101",
    ],
)
def test_claude_4_5_opus(model_name: str) -> None:
    _check_model(model_name, _CLAUDE_4_5_OPUS)


# ── Claude 4.5 Haiku ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "model_name",
    [
        # API ID
        "claude-haiku-4-5-20251001",
        # Alias
        "claude-haiku-4-5",
        # Bedrock
        "anthropic.claude-haiku-4-5-20251001-v1:0",
        # Vertex
        "claude-haiku-4-5@20251001",
    ],
)
def test_claude_4_5_haiku(model_name: str) -> None:
    _check_model(model_name, _CLAUDE_4_5_HAIKU)


# ── Claude 4.6 Sonnet ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "model_name",
    [
        # API ID (same as alias for latest)
        "claude-sonnet-4-6",
        # Bedrock
        "anthropic.claude-sonnet-4-6",
    ],
)
def test_claude_4_6_sonnet(model_name: str) -> None:
    _check_model(model_name, _CLAUDE_4_6_SONNET)


# ── Claude 4.6 Opus ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "model_name",
    [
        # API ID (same as alias for latest)
        "claude-opus-4-6",
        # Bedrock
        "anthropic.claude-opus-4-6-v1",
    ],
)
def test_claude_4_6_opus(model_name: str) -> None:
    _check_model(model_name, _CLAUDE_4_6_OPUS)


# ── Future models (is_claude_latest) ─────────────────────────────────────────


@pytest.mark.parametrize(
    "model_name",
    [
        # Future major version
        "claude-sonnet-5-20260101",
        "claude-opus-5-0",
    ],
)
def test_future_major_version(model_name: str) -> None:
    _check_model(model_name, _CLAUDE_FUTURE)


@pytest.mark.parametrize(
    "model_name",
    [
        # Future 4.x minor version (non-opus)
        "claude-sonnet-4-9-20260301",
        "claude-haiku-4-8",
    ],
)
def test_future_4_minor_version(model_name: str) -> None:
    _check_model(model_name, _CLAUDE_FUTURE_4_MINOR)


@pytest.mark.parametrize(
    "model_name",
    [
        # Future 4.x minor version (opus)
        "claude-opus-4-8",
    ],
)
def test_future_4_minor_version_opus(model_name: str) -> None:
    _check_model(model_name, _CLAUDE_FUTURE_4_MINOR_OPUS)


# ── Claude 4.7 Opus ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "model_name",
    [
        # API ID
        "claude-opus-4-7-20260415",
        # Alias
        "claude-opus-4-7",
        # Bedrock
        "anthropic.claude-opus-4-7",
    ],
)
def test_claude_4_7_opus(model_name: str) -> None:
    _check_model(model_name, _CLAUDE_4_7_OPUS)


# ── Claude 4.7 hypothetical non-opus variants ────────────────────────────────
# Sonnet/Haiku 4.7 haven't shipped, but the regex matches them as 4.7
# (not "latest"), so the routing for any future 4.7 variant is correct.


@pytest.mark.parametrize(
    "model_name",
    [
        "claude-sonnet-4-7-20260101",
        "claude-haiku-4-7",
    ],
)
def test_claude_4_7_non_opus(model_name: str) -> None:
    _check_model(model_name, _CLAUDE_4_7_NON_OPUS)


@pytest.mark.parametrize(
    "model_name",
    [
        # Unexpected or unrecognized model names
        "claude-foobar",
        "some-other-model",
    ],
)
def test_unknown_model(model_name: str) -> None:
    _check_model(model_name, _CLAUDE_FUTURE)
