import pytest
from test_helpers.utils import skip_if_no_sambanova

from inspect_ai.model import (
    ChatMessageUser,
    GenerateConfig,
    get_model,
)


@pytest.mark.asyncio
@skip_if_no_sambanova
async def test_sambanova_compatible() -> None:
    model = get_model(
        "sambanova/DeepSeek-V3-0324",
        config=GenerateConfig(
            stop_seqs=None,
            max_tokens=50,
            temperature=0.0,
            top_p=1.0,
            top_k=None,
        ),
    )
    message = ChatMessageUser(content="What is an LLM")
    res = await model.generate(input=[message])
    assert len(res.completion) >= 1
