import pytest
from test_helpers.utils import (
    skip_if_no_anthropic,
    skip_if_no_bedrock,
    skip_if_no_google,
    skip_if_no_mistral,
    skip_if_no_mistral_azure,
    skip_if_no_openai,
    skip_if_no_openai_azure,
    skip_if_no_vertex,
)

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.scorer import match


@pytest.mark.parametrize(
    "model",
    [
        "google/vertex/gemini-2.0-flash",
        "google/gemini-2.0-flash",
    ],
)
@skip_if_no_google
@skip_if_no_vertex
def test_google_canonical_name_in_eval_log(model):
    """Test that vertex and direct google models store same canonical name in logs"""
    log = eval(
        Task(
            dataset=[Sample(input="What is 1 + 1?", target="2")],
            scorer=match(),
        ),
        model=model,
    )[0]

    assert log.eval.model == "google/gemini-2.0-flash"


@pytest.mark.parametrize(
    "model",
    [
        "anthropic/bedrock/claude-3-7-sonnet-latest",
        "anthropic/vertex/claude-3-7-sonnet-latest",
        "anthropic/claude-3-7-sonnet-latest",
    ],
)
@skip_if_no_anthropic
@skip_if_no_vertex
@skip_if_no_bedrock
def test_anthropic_canonical_name_in_eval_log(model):
    """Test that bedrock/vertex and direct anthropic models store same canonical name in logs"""
    log = eval(
        Task(
            dataset=[Sample(input="What is 1 + 1?", target="2")],
            scorer=match(),
        ),
        model=model,
    )[0]

    assert log.eval.model == "anthropic/claude-3-7-sonnet-latest"


@pytest.mark.parametrize(
    "model",
    [
        "openai/azure/gpt-4o",
        "openai/gpt-4o",
    ],
)
@skip_if_no_openai
@skip_if_no_openai_azure
def test_openai_canonical_name_in_eval_log(model):
    """Test that azure and direct openai models store same canonical name in logs"""
    log = eval(
        Task(
            dataset=[Sample(input="What is 1 + 1?", target="2")],
            scorer=match(),
        ),
        model=model,
    )[0]

    assert log.eval.model == "openai/gpt-4o"


@pytest.mark.parametrize(
    "model",
    [
        "mistral/azure/mistral-small-latest",
        "mistral/mistral-small-latest",
    ],
)
@skip_if_no_mistral
@skip_if_no_mistral_azure
def test_mistral_canonical_name_in_eval_log(model):
    """Test that azure and direct mistral models store same canonical name in logs"""
    log = eval(
        Task(
            dataset=[Sample(input="What is 1 + 1?", target="2")],
            scorer=match(),
        ),
        model=model,
    )[0]

    assert log.eval.model == "mistral/mistral-small-latest"
