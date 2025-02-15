import asyncio

import pytest

from inspect_ai.model import GenerateConfig, get_model


@pytest.mark.asyncio
async def test_model_caching_enabled():
    """Test that identical model requests return the same cached instance."""
    # Get the same model twice
    model1 = get_model("mockllm/model")
    model2 = get_model("mockllm/model")

    # Verify we got the same instance
    assert model1 is model2


@pytest.mark.asyncio
async def test_model_caching_disabled():
    """Test that caching can be disabled."""
    # Get the same model twice with caching disabled
    model1 = get_model("mockllm/model", use_cache=False)
    model2 = get_model("mockllm/model", use_cache=False)

    # Verify we got different instances
    assert model1 is not model2


@pytest.mark.asyncio
async def test_different_configs_different_cache():
    """Test that different configs result in different cached instances."""
    config1 = GenerateConfig(temperature=0.7)
    config2 = GenerateConfig(temperature=0.9)

    model1 = get_model("mockllm/model", config=config1)
    model2 = get_model("mockllm/model", config=config2)

    # Verify we got different instances
    assert model1 is not model2


@pytest.mark.asyncio
async def test_different_provider_params_different_cache():
    """Test that different provider params result in different cached instances."""
    model1 = get_model("mockllm/model", param1="value1")
    model2 = get_model("mockllm/model", param1="value2")

    # Verify we got different instances
    assert model1 is not model2


@pytest.mark.asyncio
async def test_context_manager():
    """Test the async context manager functionality."""
    async with get_model("mockllm/model") as model:
        await model.generate("Say hello")

    # Verify the model was closed
    assert hasattr(model, "_closed") and model._closed


@pytest.mark.asyncio
async def test_context_manager_exception_handling():
    """Test that the context manager properly handles exceptions."""
    with pytest.raises(ValueError):
        async with get_model("mockllm/model") as model:
            raise ValueError("Test error")

    # Verify the model was closed despite the exception
    assert hasattr(model, "_closed") and model._closed


@pytest.mark.asyncio
async def test_cache_consistency():
    """Test that cached models maintain consistent state."""
    model1 = get_model("mockllm/model")

    # Set some attribute on the first instance
    model1._test_attr = "test_value"

    # Get the same model again
    model2 = get_model("mockllm/model")

    # Verify the attribute is present on the cached instance
    assert hasattr(model2, "_test_attr")
    assert model2._test_attr == "test_value"


if __name__ == "__main__":

    async def main():
        await test_different_configs_different_cache()

    asyncio.run(main())
