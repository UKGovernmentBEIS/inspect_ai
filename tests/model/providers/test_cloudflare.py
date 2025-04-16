import pytest
from test_helpers.utils import skip_if_no_cloudflare

from inspect_ai.model import get_model


@pytest.mark.anyio
@skip_if_no_cloudflare
async def test_cloudflare_api() -> None:
    async with get_model("cf/meta/llama-3.1-8b-instruct-awq") as model:
        message = "This is a test string. What are you?"
        response = await model.generate(input=message)
        assert len(response.completion) >= 1
