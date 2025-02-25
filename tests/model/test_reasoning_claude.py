import pytest
from test_helpers.utils import skip_if_no_anthropic

from .test_reasoning_content import check_reasoning_content


@pytest.mark.asyncio
@skip_if_no_anthropic
async def test_reasoning_claude():
    await check_reasoning_content("anthropic/claude-3-7-sonnet-20250219")
