from inspect_ai.model._reasoning import parse_content_with_reasoning


def test_reasoning_parse_basic():
    result = parse_content_with_reasoning("<think>Simple reasoning</think>Normal text")
    assert result is not None
    assert result.reasoning == "Simple reasoning"
    assert result.content == "Normal text"
    assert result.signature is None
    assert result.redacted is False


def test_reasoning_parse_with_leading_whitespace():
    result = parse_content_with_reasoning(
        "   \n  <think>Indented reasoning</think>Text"
    )
    assert result is not None
    assert result.reasoning == "Indented reasoning"
    assert result.content == "Text"
    assert result.signature is None
    assert result.redacted is False


def test_reasoning_parse_with_trailing_whitespace():
    result = parse_content_with_reasoning("<think>Reasoning</think>   \n  Text   \n")
    assert result is not None
    assert result.reasoning == "Reasoning"
    assert result.content == "Text"
    assert result.signature is None
    assert result.redacted is False


def test_reasoning_parse_with_newlines_in_reasoning():
    result = parse_content_with_reasoning("<think>Multi\nline\nreasoning</think>Text")
    assert result is not None
    assert result.reasoning == "Multi\nline\nreasoning"
    assert result.content == "Text"
    assert result.signature is None
    assert result.redacted is False


def test_reasoning_parse_empty():
    result = parse_content_with_reasoning("<think></think>Text")
    assert result is not None
    assert result.reasoning == ""
    assert result.content == "Text"
    assert result.signature is None
    assert result.redacted is False


def test_reasoning_parse_empty_content():
    result = parse_content_with_reasoning("<think>Just reasoning</think>")
    assert result is not None
    assert result.reasoning == "Just reasoning"
    assert result.content == ""
    assert result.signature is None
    assert result.redacted is False


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
    assert result.signature is None
    assert result.redacted is False


def test_reasoning_parse_no_think_tag():
    result = parse_content_with_reasoning("No think tag here")
    assert result is None


def test_reasoning_parse_unclosed_tag():
    result = parse_content_with_reasoning("<think>Unclosed reasoning")
    assert result is None


# New tests for signature attribute
def test_reasoning_parse_with_signature():
    result = parse_content_with_reasoning(
        '<think signature="45ef5ab">Reasoning with signature</think>Content'
    )
    assert result is not None
    assert result.reasoning == "Reasoning with signature"
    assert result.content == "Content"
    assert result.signature == "45ef5ab"
    assert result.redacted is False


# New tests for redacted attribute
def test_reasoning_parse_with_redacted():
    result = parse_content_with_reasoning(
        '<think redacted="true">Redacted reasoning</think>Content'
    )
    assert result is not None
    assert result.reasoning == "Redacted reasoning"
    assert result.content == "Content"
    assert result.signature is None
    assert result.redacted is True


# New tests for both attributes
def test_reasoning_parse_with_signature_and_redacted():
    result = parse_content_with_reasoning(
        '<think signature="45ef5ab" redacted="true">Both attributes</think>Content'
    )
    assert result is not None
    assert result.reasoning == "Both attributes"
    assert result.content == "Content"
    assert result.signature == "45ef5ab"
    assert result.redacted is True


# Test with whitespace in attributes
def test_reasoning_parse_with_whitespace_in_attributes():
    result = parse_content_with_reasoning(
        '<think  signature="45ef5ab"  redacted="true" >Whitespace in attributes</think>Content'
    )
    assert result is not None
    assert result.reasoning == "Whitespace in attributes"
    assert result.content == "Content"
    assert result.signature == "45ef5ab"
    assert result.redacted is True


# Test with attributes and multiline content
def test_reasoning_parse_with_attributes_and_multiline():
    result = parse_content_with_reasoning("""
        <think signature="45ef5ab" redacted="true">
            Complex
            reasoning
        </think>
            Content
            here
    """)
    assert result is not None
    assert result.reasoning == "Complex\n            reasoning"
    assert result.content == "Content\n            here"
    assert result.signature == "45ef5ab"
    assert result.redacted is True
