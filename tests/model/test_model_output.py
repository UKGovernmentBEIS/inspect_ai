from inspect_ai.model._model_output import ModelUsage


def test_model_usage_addition() -> None:
    usage1 = ModelUsage(
        input_tokens=1,
        output_tokens=2,
        total_tokens=3,
        input_tokens_cache_write=4,
        input_tokens_cache_read=5,
        reasoning_tokens=6,
    )
    usage2 = ModelUsage(
        input_tokens=10,
        output_tokens=20,
        total_tokens=30,
        input_tokens_cache_write=40,
        input_tokens_cache_read=50,
        reasoning_tokens=60,
    )

    result = usage1 + usage2

    assert result.input_tokens == 11
    assert result.output_tokens == 22
    assert result.total_tokens == 33
    assert result.input_tokens_cache_write == 44
    assert result.input_tokens_cache_read == 55
    assert result.reasoning_tokens == 66


def test_model_usage_addition_with_none_fields() -> None:
    usage1 = ModelUsage(
        input_tokens_cache_write=None,
        input_tokens_cache_read=2,
        reasoning_tokens=None,
    )
    usage2 = ModelUsage(
        input_tokens_cache_write=1,
        input_tokens_cache_read=None,
        reasoning_tokens=None,
    )

    result = usage1 + usage2

    assert result.input_tokens_cache_write == 1
    assert result.input_tokens_cache_read == 2
    assert result.reasoning_tokens is None
