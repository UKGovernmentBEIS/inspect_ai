from inspect_ai.model._reasoning import parse_content_with_reasoning


def test_reasoning_parse_basic():
    content, reasoning = parse_content_with_reasoning(
        "<think>Simple reasoning</think>Normal text"
    )
    assert reasoning is not None
    assert reasoning.reasoning == "Simple reasoning"
    assert content == "Normal text"
    assert reasoning.signature is None
    assert reasoning.redacted is False


def test_reasoning_parse_with_leading_whitespace():
    content, reasoning = parse_content_with_reasoning(
        "   \n  <think>Indented reasoning</think>Text"
    )
    assert reasoning is not None
    assert reasoning.reasoning == "Indented reasoning"
    assert content == "Text"
    assert reasoning.signature is None
    assert reasoning.redacted is False


def test_reasoning_parse_with_trailing_whitespace():
    content, reasoning = parse_content_with_reasoning(
        "<think>Reasoning</think>   \n  Text   \n"
    )
    assert reasoning is not None
    assert reasoning.reasoning == "Reasoning"
    assert content == "Text"
    assert reasoning.signature is None
    assert reasoning.redacted is False


def test_reasoning_parse_with_newlines_in_reasoning():
    content, reasoning = parse_content_with_reasoning(
        "<think>Multi\nline\nreasoning</think>Text"
    )
    assert reasoning is not None
    assert reasoning.reasoning == "Multi\nline\nreasoning"
    assert content == "Text"
    assert reasoning.signature is None
    assert reasoning.redacted is False


def test_reasoning_parse_empty():
    content, reasoning = parse_content_with_reasoning("<think></think>Text")
    assert reasoning is not None
    assert reasoning.reasoning == ""
    assert content == "Text"
    assert reasoning.signature is None
    assert reasoning.redacted is False


def test_reasoning_parse_empty_content():
    content, reasoning = parse_content_with_reasoning("<think>Just reasoning</think>")
    assert reasoning is not None
    assert reasoning.reasoning == "Just reasoning"
    assert content == ""
    assert reasoning.signature is None
    assert reasoning.redacted is False


def test_reasoning_parse_whitespace_everywhere():
    content, reasoning = parse_content_with_reasoning("""
        <think>
            Messy
            reasoning
        </think>
            Messy
            text
    """)
    assert reasoning is not None
    assert reasoning.reasoning == "Messy\n            reasoning"
    assert content == "Messy\n            text"
    assert reasoning.signature is None
    assert reasoning.redacted is False


def test_reasoning_parse_no_think_tag():
    content, reasoning = parse_content_with_reasoning("No think tag here")
    assert reasoning is None


def test_reasoning_parse_unclosed_tag():
    content, reasoning = parse_content_with_reasoning("<think>Unclosed reasoning")
    assert reasoning is None


# New tests for signature attribute
def test_reasoning_parse_with_signature():
    content, reasoning = parse_content_with_reasoning(
        '<think signature="45ef5ab">Reasoning with signature</think>Content'
    )
    assert reasoning is not None
    assert reasoning.reasoning == "Reasoning with signature"
    assert content == "Content"
    assert reasoning.signature == "45ef5ab"
    assert reasoning.redacted is False


# New tests for redacted attribute
def test_reasoning_parse_with_redacted():
    content, reasoning = parse_content_with_reasoning(
        '<think redacted="true">Redacted reasoning</think>Content'
    )
    assert reasoning is not None
    assert reasoning.reasoning == "Redacted reasoning"
    assert content == "Content"
    assert reasoning.signature is None
    assert reasoning.redacted is True


# New tests for both attributes
def test_reasoning_parse_with_signature_and_redacted():
    content, reasoning = parse_content_with_reasoning(
        '<think signature="45ef5ab" redacted="true">Both attributes</think>Content'
    )
    assert reasoning is not None
    assert reasoning.reasoning == "Both attributes"
    assert content == "Content"
    assert reasoning.signature == "45ef5ab"
    assert reasoning.redacted is True


# Test with whitespace in attributes
def test_reasoning_parse_with_whitespace_in_attributes():
    content, reasoning = parse_content_with_reasoning(
        '<think  signature="45ef5ab"  redacted="true" >Whitespace in attributes</think>Content'
    )
    assert reasoning is not None
    assert reasoning.reasoning == "Whitespace in attributes"
    assert content == "Content"
    assert reasoning.signature == "45ef5ab"
    assert reasoning.redacted is True


# Test with attributes and multiline content
def test_reasoning_parse_with_attributes_and_multiline():
    content, reasoning = parse_content_with_reasoning("""
        <think signature="45ef5ab" redacted="true">
            Complex
            reasoning
        </think>
            Content
            here
    """)
    assert reasoning is not None
    assert reasoning.reasoning == "Complex\n            reasoning"
    assert content == "Content\n            here"
    assert reasoning.signature == "45ef5ab"
    assert reasoning.redacted is True
