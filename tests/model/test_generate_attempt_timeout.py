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


class BriefAPI(SlowAPI):
    """A provider whose generate outlasts the override but finishes quickly."""

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput:
        BriefAPI.attempts += 1
        await anyio.sleep(2)
        return ModelOutput.from_content(model=self.model_name, content="done")


class StallingStreamAPI(SlowAPI):
    """A provider that streams one chunk, then stalls."""

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput:
        from inspect_ai.model._stream import (
            StreamTextEvent,
            report_model_stream_delta,
            report_model_stream_start,
        )

        StallingStreamAPI.attempts += 1
        report_model_stream_start()
        await report_model_stream_delta(StreamTextEvent(text="chunk"))
        await anyio.sleep(60)
        return ModelOutput.from_content(model=self.model_name, content="too late")


async def test_stream_idle_timeout_detects_stall_before_attempt_timeout() -> None:
    """A stall is detected in O(idle timeout), not O(attempt timeout).

    With a 60s attempt_timeout and 1s stream_idle_timeout, the stalled
    stream fails as StreamIdleTimeoutError after ~1s (the inner scope), not
    the coarse whole-attempt backstop.
    """
    from inspect_ai.model._model import StreamIdleTimeoutError

    @modelapi(name="mockstall")
    def mockstall() -> type[ModelAPI]:
        return StallingStreamAPI

    try:
        model = get_model("mockstall/test")
        StallingStreamAPI.attempts = 0
        with pytest.raises(tenacity.RetryError) as excinfo:
            await model.generate(
                "hello",
                config=GenerateConfig(
                    attempt_timeout=60, stream_idle_timeout=1, max_retries=0
                ),
            )
        assert isinstance(
            excinfo.value.last_attempt.exception(), StreamIdleTimeoutError
        )
        assert StallingStreamAPI.attempts == 1
    finally:
        del _registry["modelapi:mockstall"]


async def test_attempt_timeout_wins_when_idle_timeout_is_larger() -> None:
    """The coarse backstop still fires when the stall clock is slack.

    The attempt scope (outer) absorbs its own cancellation without marking
    the inner idle scope, so the failure is attributed to attempt_timeout.
    """
    from inspect_ai.model._model import AttemptTimeoutError

    @modelapi(name="mockstall2")
    def mockstall2() -> type[ModelAPI]:
        return StallingStreamAPI

    try:
        model = get_model("mockstall2/test")
        StallingStreamAPI.attempts = 0
        with pytest.raises(tenacity.RetryError) as excinfo:
            await model.generate(
                "hello",
                config=GenerateConfig(
                    attempt_timeout=1, stream_idle_timeout=60, max_retries=0
                ),
            )
        assert isinstance(excinfo.value.last_attempt.exception(), AttemptTimeoutError)
        assert StallingStreamAPI.attempts == 1
    finally:
        del _registry["modelapi:mockstall2"]


async def test_stream_idle_timeout_live_override() -> None:
    """The `inspect ctl config` override applies without any launch config."""

    @modelapi(name="mockstallslow")
    def mockstallslow() -> type[ModelAPI]:
        return StallingStreamAPI

    try:
        model = get_model("mockstallslow/test")
        StallingStreamAPI.attempts = 0
        set_generate_config_override("stream_idle_timeout", 1)
        set_generate_config_override("max_retries", 0)
        with pytest.raises(tenacity.RetryError):
            await model.generate("hello")
        assert StallingStreamAPI.attempts == 1
    finally:
        reset_generate_config_overrides()
        del _registry["modelapi:mockstallslow"]


class BriefStreamAPI(SlowAPI):
    """A provider that streams a chunk and finishes shortly after."""

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput:
        from inspect_ai.model._stream import (
            StreamTextEvent,
            report_model_stream_delta,
            report_model_stream_start,
        )

        BriefStreamAPI.attempts += 1
        report_model_stream_start()
        await report_model_stream_delta(StreamTextEvent(text="chunk"))
        await anyio.sleep(1.5)
        return ModelOutput.from_content(model=self.model_name, content="done")


async def test_stream_idle_timeout_override_exempts_batched_calls() -> None:
    """A batched call keeps its launch stream_idle_timeout despite an override.

    Batched calls never stream, but the carve-out also keeps the override
    from resubmitting an entire batch (same rationale as attempt_timeout).
    """

    @modelapi(name="mockbriefstream")
    def mockbriefstream() -> type[ModelAPI]:
        return BriefStreamAPI

    try:
        model = get_model("mockbriefstream/test", config=GenerateConfig(batch=True))
        BriefStreamAPI.attempts = 0
        set_generate_config_override("stream_idle_timeout", 1)
        set_generate_config_override("max_retries", 0)
        output = await model.generate("hello")
        assert BriefStreamAPI.attempts == 1
        assert output.completion == "done"
    finally:
        reset_generate_config_overrides()
        del _registry["modelapi:mockbriefstream"]


async def test_generate_attempt_timeout_override_exempts_batched_calls() -> None:
    """A batched call keeps its launch attempt_timeout despite a live override.

    An attempt in batch mode awaits an entire provider batch; an override
    cancelling that wait would resubmit the request into a new batch
    (duplicated provider work), so the override deliberately does not reach
    batched calls. The max_retries=0 override keeps a regression cheap: if
    the attempt_timeout override were applied, the single 2s attempt would
    time out at 1s and the call would fail fast rather than hang.
    """

    @modelapi(name="mockbrief")
    def mockbrief() -> type[ModelAPI]:
        return BriefAPI

    try:
        model = get_model("mockbrief/test", config=GenerateConfig(batch=True))
        BriefAPI.attempts = 0
        set_generate_config_override("attempt_timeout", 1)
        set_generate_config_override("max_retries", 0)
        output = await model.generate("hello")
        assert BriefAPI.attempts == 1
        assert output.completion == "done"
    finally:
        reset_generate_config_overrides()
        del _registry["modelapi:mockbrief"]
