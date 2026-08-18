from test_helpers.utils import skip_if_no_fireworks

from inspect_ai.model import (
    ChatMessageUser,
    GenerateConfig,
    get_model,
)


@skip_if_no_fireworks
async def test_fireworks_compatible() -> None:
    model = get_model(
        # Fireworks retires models from serverless over time; this must be one
        # of the ids listed by GET /inference/v1/models
        "fireworks/accounts/fireworks/models/kimi-k3",
        config=GenerateConfig(
            frequency_penalty=0.0,
            stop_seqs=None,
            max_tokens=50,
            presence_penalty=0.0,
            logit_bias=dict([(42, 10), (43, -10)]),
            seed=None,
            temperature=0.0,
            top_p=1.0,
        ),
    )
    message = ChatMessageUser(content="Hello Fireworks!")
    res = await model.generate(input=[message])
    assert len(res.completion) >= 1
