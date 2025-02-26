from inspect_ai.model._reasoning import parse_content_with_reasoning


def test_reasoning_parse_basic():
    result = parse_content_with_reasoning("<think>Simple reasoning</think>Normal text")
    assert result is not None
    assert result.reasoning == "Simple reasoning"
    assert result.content == "Normal text"


def test_reasoning_parse_with_leading_whitespace():
    result = parse_content_with_reasoning(
        "   \n  <think>Indented reasoning</think>Text"
    )
    assert result is not None
    assert result.reasoning == "Indented reasoning"
    assert result.content == "Text"


def test_reasoning_parse_with_trailing_whitespace():
    result = parse_content_with_reasoning("<think>Reasoning</think>   \n  Text   \n")
    assert result is not None
    assert result.reasoning == "Reasoning"
    assert result.content == "Text"


def test_reasoning_parse_with_newlines_in_reasoning():
    result = parse_content_with_reasoning("<think>Multi\nline\nreasoning</think>Text")
    assert result is not None
    assert result.reasoning == "Multi\nline\nreasoning"
    assert result.content == "Text"


def test_reasoning_parse_empty():
    result = parse_content_with_reasoning("<think></think>Text")
    assert result is not None
    assert result.reasoning == ""
    assert result.content == "Text"


def test_reasoning_parse_empty_content():
    result = parse_content_with_reasoning("<think>Just reasoning</think>")
    assert result is not None
    assert result.reasoning == "Just reasoning"
    assert result.content == ""


def test_reasoning_parse_whitespace_everywhere():
    result = parse_content_with_reasoning("""
        <think>
            Messy
            reasoning
        </think>
            Messy
            text
    """)
    assert result is not None
    assert result.reasoning == "Messy\n            reasoning"
    assert result.content == "Messy\n            text"


def test_reasoning_parse_no_think_tag():
    result = parse_content_with_reasoning("No think tag here")
    assert result is None


def test_reasoning_parse_unclosed_tag():
    result = parse_content_with_reasoning("<think>Unclosed reasoning")
    assert result is None
