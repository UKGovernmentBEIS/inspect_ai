import pytest
from test_helpers.utils import skip_if_no_transformer_lens

from inspect_ai.model import (
    ChatMessageUser,
    GenerateConfig,
    get_model,
)


@pytest.mark.anyio
@skip_if_no_transformer_lens
async def test_transformer_lens_api() -> None:
    """Test basic TransformerLens provider functionality."""
    # Import here to avoid import errors if transformer_lens is not installed
    from transformer_lens import HookedTransformer  # type: ignore

    # Create a small HookedTransformer model for testing
    tl_model = HookedTransformer.from_pretrained(
        "gpt2",  # Using small GPT-2 for testing
        device="cpu",  # Use CPU for testing to avoid GPU requirements
    )

    # Set up model args for the TransformerLens provider
    model_args = {
        "tl_model": tl_model,
        "tl_generate_args": {
            "max_new_tokens": 10,
            "temperature": 0.0,  # Deterministic for testing
            "do_sample": False,  # Greedy decoding for deterministic output
        },
    }

    # Create the model using Inspect
    model = get_model(
        "transformer_lens/test-model",  # Model name (not used by TransformerLens)
        config=GenerateConfig(max_tokens=10),
        **model_args,
    )

    # Test basic generation
    message = ChatMessageUser(content="Hello")
    response = await model.generate(input=[message])

    # Verify basic response structure
    assert len(response.completion) >= 1
    assert response.model == "test-model"  # Model name without provider prefix
    assert response.choices[0].message.content is not None
    assert len(response.choices[0].message.content) > 0


@pytest.mark.anyio
@skip_if_no_transformer_lens
async def test_transformer_lens_missing_tl_model() -> None:
    """Test that TransformerLens provider raises error when tl_model is missing."""
    model_args = {
        "tl_generate_args": {
            "max_new_tokens": 10,
        },
    }

    with pytest.raises(AssertionError, match="tl_model is required in model_args"):
        get_model("transformer_lens/test-model", **model_args)  # type: ignore


@pytest.mark.anyio
@skip_if_no_transformer_lens
async def test_transformer_lens_missing_tl_generate_args() -> None:
    """Test that TransformerLens provider raises error when tl_generate_args is missing."""
    from transformer_lens import HookedTransformer

    tl_model = HookedTransformer.from_pretrained("gpt2", device="cpu")
    model_args = {
        "tl_model": tl_model,
    }

    with pytest.raises(
        AssertionError, match="tl_generate_args is required in model_args"
    ):
        get_model("transformer_lens/test-model", **model_args)


@pytest.mark.anyio
@skip_if_no_transformer_lens
async def test_transformer_lens_invalid_tl_model_type() -> None:
    """Test that TransformerLens provider raises error when tl_model is not a HookedTransformer."""
    model_args = {
        "tl_model": "not-a-hooked-transformer",
        "tl_generate_args": {
            "max_new_tokens": 10,
        },
    }

    with pytest.raises(
        AssertionError, match="tl_model must be a transformer_lens.HookedTransformer"
    ):
        get_model("transformer_lens/test-model", **model_args)  # type: ignore


@pytest.mark.anyio
@skip_if_no_transformer_lens
async def test_transformer_lens_multiple_messages() -> None:
    """Test TransformerLens provider with multiple chat messages."""
    from transformer_lens import HookedTransformer

    tl_model = HookedTransformer.from_pretrained("gpt2", device="cpu")
    model_args = {
        "tl_model": tl_model,
        "tl_generate_args": {
            "max_new_tokens": 5,
            "temperature": 0.0,
            "do_sample": False,
        },
    }

    model = get_model("transformer_lens/test-model", **model_args)

    # Test with multiple messages
    from inspect_ai.model import ChatMessageSystem

    messages = [
        ChatMessageSystem(content="You are a helpful assistant."),
        ChatMessageUser(content="Hello"),
    ]

    response = await model.generate(input=messages)  # type: ignore
    assert len(response.completion) >= 1
    assert response.choices[0].message.content is not None


@pytest.mark.anyio
@skip_if_no_transformer_lens
async def test_transformer_lens_with_eval_model_args_parameter() -> None:
    """Test TransformerLens provider using eval() with model_args parameter instead of keyword expansion."""
    # Import here to avoid import errors if transformer_lens is not installed
    from transformer_lens import HookedTransformer

    from inspect_ai import Task, eval_async
    from inspect_ai.dataset import Sample
    from inspect_ai.scorer import includes
    from inspect_ai.solver import generate

    # Create a small HookedTransformer model for testing
    tl_model = HookedTransformer.from_pretrained(
        "gpt2",  # Using small GPT-2 for testing
        device="cpu",  # Use CPU for testing to avoid GPU requirements
    )

    # Set up model args for the TransformerLens provider
    model_args = {
        "tl_model": tl_model,
        "tl_generate_args": {
            "max_new_tokens": 5,
            "temperature": 0.0,  # Deterministic for testing
            "do_sample": False,  # Greedy decoding for deterministic output
        },
    }

    # Create a simple task for testing
    task = Task(
        dataset=[Sample(input="Say hello", target="hello")],
        solver=generate(),
        scorer=includes(),
    )

    # Test eval() with model_args parameter instead of keyword expansion
    logs = await eval_async(
        tasks=task,
        model="transformer_lens/test-model",  # Model name (not used by TransformerLens)
        model_args=model_args,  # Using model_args parameter instead of keyword expansion
        limit=1,
    )

    # Verify the evaluation completed successfully
    assert len(logs) == 1
    log = logs[0]
    assert log.status == "success"
    assert log.samples is not None
    assert len(log.samples) == 1

    # Verify the sample was processed
    sample = log.samples[0]
    assert sample.output is not None
    assert sample.output.completion is not None
    assert len(sample.output.completion) > 0
