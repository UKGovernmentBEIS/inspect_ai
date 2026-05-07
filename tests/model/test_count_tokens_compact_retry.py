"""count_tokens and compact: eventless contract plus resolved retry config."""

# pyright: reportImplicitRelativeImport=false

from _helpers.event_assertions import model_events
from _helpers.retry_provider import RetryableModelError
from tenacity import wait_fixed
from tenacity.wait import WaitBaseT

from inspect_ai._util.registry import REGISTRY_INFO, RegistryInfo
from inspect_ai.log._transcript import Transcript, init_transcript
from inspect_ai.model import GenerateConfig, get_model
from inspect_ai.model._chat_message import ChatMessage
from inspect_ai.model._model import ModelAPI
from inspect_ai.model._model_call import ModelCall
from inspect_ai.model._model_output import ModelOutput, ModelUsage
from inspect_ai.tool import ToolChoice, ToolInfo


class _CountingAPI(ModelAPI):
    def __init__(self, *, count_failures: int = 0, compact_failures: int = 0) -> None:
        super().__init__(
            model_name="fake",
            base_url=None,
            api_key=None,
            api_key_vars=[],
            config=GenerateConfig(),
        )
        setattr(
            self,
            REGISTRY_INFO,
            RegistryInfo(type="modelapi", name="inspect_ai/mockllm"),
        )
        self.count_attempts = 0
        self.compact_attempts = 0
        self._count_failures = count_failures
        self._compact_failures = compact_failures

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput | tuple[ModelOutput, ModelCall]:
        return ModelOutput.from_content("fake", "ok")

    async def count_tokens(
        self, input: str | list[ChatMessage], config: GenerateConfig | None = None
    ) -> int:
        self.count_attempts += 1
        if self.count_attempts <= self._count_failures:
            raise RetryableModelError("transient")
        return 42

    async def compact(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        config: GenerateConfig,
        instructions: str | None = None,
    ) -> tuple[list[ChatMessage], ModelUsage | None]:
        self.compact_attempts += 1
        if self.compact_attempts <= self._compact_failures:
            raise RetryableModelError("transient")
        return input, ModelUsage(input_tokens=1, output_tokens=1, total_tokens=2)

    def should_retry(self, ex: Exception) -> bool:
        return isinstance(ex, RetryableModelError)

    def retry_wait(self) -> WaitBaseT:
        return wait_fixed(0)


async def test_count_tokens_emits_no_model_events() -> None:
    transcript = Transcript()
    init_transcript(transcript)
    model = get_model("mockllm/test", memoize=False)
    model.api = _CountingAPI(count_failures=2)

    result = await model.count_tokens("hi", GenerateConfig(max_retries=5))

    assert result == 42
    assert model_events(transcript) == []


async def test_count_tokens_honors_local_config_max_retries() -> None:
    model = get_model("mockllm/test", memoize=False)
    api = _CountingAPI(count_failures=2)
    model.api = api
    model.config = GenerateConfig(max_retries=1)

    result = await model.count_tokens("hi", GenerateConfig(max_retries=5))

    assert result == 42
    assert api.count_attempts == 3


async def test_compact_emits_no_model_events() -> None:
    transcript = Transcript()
    init_transcript(transcript)
    model = get_model("mockllm/test", memoize=False)
    model.api = _CountingAPI(compact_failures=1)
    model.config = GenerateConfig(max_retries=3)

    _, usage = await model.compact([], tools=[])

    assert usage is not None
    assert model_events(transcript) == []


async def test_compact_uses_resolved_config_retry_settings() -> None:
    model = get_model("mockllm/test", memoize=False)
    api = _CountingAPI(compact_failures=2)
    model.api = api
    model.config = GenerateConfig(max_retries=5)

    _, usage = await model.compact([], tools=[])

    assert usage is not None
    assert api.compact_attempts == 3
