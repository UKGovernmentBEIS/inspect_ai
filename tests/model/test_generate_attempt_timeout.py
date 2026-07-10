import anyio
import pytest
import tenacity
from test_helpers.utils import skip_if_no_anthropic

from inspect_ai._util.registry import _registry
from inspect_ai.model import (
    ChatMessage,
    GenerateConfig,
    ModelAPI,
    ModelOutput,
    get_model,
)
from inspect_ai.model._generate_overrides import (
    reset_generate_config_overrides,
    set_generate_config_override,
)
from inspect_ai.model._registry import modelapi
from inspect_ai.tool import ToolChoice, ToolInfo


@skip_if_no_anthropic
async def test_generate_attempt_timeout() -> None:
    m = get_model("anthropic/claude-sonnet-4-5")

    with pytest.raises(tenacity.RetryError):
        await m.generate(
            "I need to test your timeouts. Write a very long essay about anything you want, but make sure it is at least 20 lines long.",
            config=GenerateConfig(attempt_timeout=1, max_retries=1),
        )


class SlowAPI(ModelAPI):
    """A provider whose generate outlasts any reasonable attempt timeout."""

    attempts: int = 0

    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        config: GenerateConfig = GenerateConfig(),
        **model_args: object,
    ):
        super().__init__(
            model_name=model_name,
            base_url=base_url,
            api_key="slow-api-key",
            api_key_vars=[],
            config=config,
        )

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput:
        SlowAPI.attempts += 1
        await anyio.sleep(60)
        return ModelOutput.from_content(model=self.model_name, content="too late")


async def test_generate_attempt_timeout_live_override() -> None:
    """The `inspect ctl config` overrides apply without any launch config.

    The launch config sets neither attempt_timeout nor max_retries (retry
    forever, no per-attempt limit); the live overrides alone must time the
    attempt out and stop the retry loop. max_retries counts retries, so the
    0 override means exactly one attempt (the fail-fast incident value).
    """

    @modelapi(name="mockslow")
    def mockslow() -> type[ModelAPI]:
        return SlowAPI

    try:
        model = get_model("mockslow/test")
        SlowAPI.attempts = 0
        set_generate_config_override("attempt_timeout", 1)
        set_generate_config_override("max_retries", 0)
        with pytest.raises(tenacity.RetryError):
            await model.generate("hello")
        assert SlowAPI.attempts == 1
    finally:
        reset_generate_config_overrides()
        del _registry["modelapi:mockslow"]
