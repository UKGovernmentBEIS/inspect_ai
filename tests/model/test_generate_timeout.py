import pytest
from test_helpers.utils import skip_if_no_anthropic

from inspect_ai.model import GenerateConfig, get_model


@skip_if_no_anthropic
@pytest.mark.asyncio
async def test_generate_timeout() -> None:
    m = get_model("anthropic/claude-sonnet-4-20250514")

    with pytest.raises(RuntimeError):
        await m.generate(
            "I need to test your timeouts. Write a very long essay about anything you want, but make sure it is at least 20 lines long.",
            config=GenerateConfig(timeout=1, max_retries=1),
        )
