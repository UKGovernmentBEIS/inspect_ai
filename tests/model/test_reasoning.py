import pytest

from inspect_ai.model._reasoning import parse_content_with_reasoning


@pytest.mark.parametrize(
    "s,exp_sig,exp_red,exp_reason,exp_content,should_match",
    [
        # Both attributes, tag at start
        (
            '<think signature="sig" redacted="true">reasoning here</think>final content.',
            "sig",
            True,
            "reasoning here",
            "final content.",
            True,
        ),
        # Signature only
        (
            '<think signature="sig">reasoning only</think>content only.',
            "sig",
            False,
            "reasoning only",
            "content only.",
            True,
        ),
        # Redacted only
        (
            '<think redacted="true">redacted reason</think>after content.',
            None,
            True,
            "redacted reason",
            "after content.",
            True,
        ),
        # No attributes
        (
            "<think>plain reason</think>plain content.",
            None,
            False,
            "plain reason",
            "plain content.",
            True,
        ),
        # Empty signature
        (
            '<think signature="">empty sig</think>content.',
            "",
            False,
            "empty sig",
            "content.",
            True,
        ),
        # Multiline reasoning
        (
            "<think>line1\nline2\nline3</think>content here.",
            None,
            False,
            "line1\nline2\nline3",
            "content here.",
            True,
        ),
        # Tag not at start
        (
            'intro <think signature="sig">reasoning</think>main content.',
            "sig",
            False,
            "reasoning",
            "intro main content.",
            True,
        ),
        # No tag (negative)
        ("no think tag here", None, False, None, None, False),
        # Malformed tag (negative)
        ("<think>reason only", None, False, None, None, False),
    ],
)
def test_parse_content_with_reasoning(
    s, exp_sig, exp_red, exp_reason, exp_content, should_match
):
    content, reasoning = parse_content_with_reasoning(s)
    if should_match:
        assert reasoning is not None
        assert reasoning.signature == exp_sig
        assert reasoning.redacted == exp_red
        assert reasoning.reasoning == exp_reason
        assert content == exp_content
    else:
        assert reasoning is None
