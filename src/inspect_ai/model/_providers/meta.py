import os
from logging import getLogger
from typing import Any

from typing_extensions import override

from inspect_ai._util.logger import warn_once
from inspect_ai.tool import ToolChoice, ToolFunction, ToolInfo

from .._chat_message import ChatMessage
from .._generate_config import GenerateConfig
from .._model_call import ModelCall
from .._model_output import ModelOutput
from .openai_compatible import OpenAICompatibleAPI
from .util import (
    environment_prerequisite_error,
    forced_tool_choice_degraded_metadata,
    is_forced_tool_choice,
)

logger = getLogger(__name__)

META_BASE_URL = "https://api.meta.ai/v1"

# `MODEL_API_KEY` is the variable Meta's own SDK quickstarts use; `META_API_KEY`
# follows inspect's provider naming convention. Either works.
META_API_KEY_VARS = ("META_API_KEY", "MODEL_API_KEY")

META_TOOL_CHOICE_WARNING = (
    "Forcing tool use ({choice}) is not supported by {model} (the Meta Model "
    'API only accepts tool_choice="auto") and will be submitted as "auto".'
)

META_REASONING_NONE_WARNING = (
    "Reasoning cannot be disabled for {model} (the Meta Model API rejects "
    'reasoning_effort="none"); the model default will be used instead.'
)

META_REASONING_MAX_WARNING = (
    'reasoning_effort="max" is not yet available for {model} and will be '
    'submitted as "xhigh".'
)

META_UNSUPPORTED_PARAM_WARNING = (
    "The {parameter} parameter is not supported by {model} and will be ignored."
)

# Chat Completions params the API rejects with a 400 (the Responses path
# already omits these with a warning of its own).
META_CHAT_UNSUPPORTED_PARAMS = ("stop", "logit_bias", "n")


def _flag_refusal_stop(output: ModelOutput) -> None:
    """Report a structurally-signalled refusal as a content_filter stop.

    A policy block reaches us three ways depending on protocol and streaming:
    a 400 with `content_policy_violation`, a `content_filter` finish reason,
    or (streamed Responses) a completed response whose only content is a
    `refusal` part. The first two already stop as `content_filter`; the last
    arrives as an ordinary `stop` that agent loops would treat as compliance,
    so promote it. Keyed on the API's own refusal field, never on message text.
    """
    for choice in output.choices:
        details = choice.stop_details
        if (
            choice.stop_reason == "stop"
            and details is not None
            and details.type == "refusal"
        ):
            choice.stop_reason = "content_filter"


class MetaAPI(OpenAICompatibleAPI):
    """Provider for Muse Spark models on the Meta Model API.

    Uses the Responses API by default (Chat Completions redacts reasoning and
    cannot carry it across turns) with streaming enabled (the model reasons
    before emitting any visible output). Pass `responses_api=False` or
    `stream=False` as model args to override.
    """

    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        config: GenerateConfig = GenerateConfig(),
        responses_api: bool = True,
        strict_tools: bool = False,
        **model_args: Any,
    ) -> None:
        from inspect_ai.hooks._hooks import has_api_key_override

        # name the env var the key came from; with neither set, defer to the
        # base class only if an api_key hook may still supply one
        api_key_var = next(
            (var for var in META_API_KEY_VARS if os.environ.get(var)), None
        )
        if not api_key and api_key_var is None and not has_api_key_override():
            raise environment_prerequisite_error("Meta", list(META_API_KEY_VARS))

        super().__init__(
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            config=config,
            service="Meta",
            service_base_url=META_BASE_URL,
            api_key_var=api_key_var or META_API_KEY_VARS[0],
            responses_api=responses_api,
            strict_tools=strict_tools,
            **model_args,
        )

    @override
    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput | tuple[ModelOutput | Exception, ModelCall]:
        result = await super().generate(input, tools, tool_choice, config)
        output = result[0] if isinstance(result, tuple) else result
        if isinstance(output, ModelOutput):
            _flag_refusal_stop(output)
            if tools and is_forced_tool_choice(tool_choice):
                output.metadata = (
                    output.metadata or {}
                ) | forced_tool_choice_degraded_metadata(tool_choice)
        return result

    @override
    def canonical_name(self) -> str:
        """Muse models are keyed under the `meta` organization in the model info database."""
        return f"meta/{self.service_model_name()}"

    @override
    def should_stream(self, config: GenerateConfig) -> bool:
        return True

    def resolve_config(self, config: GenerateConfig) -> GenerateConfig:
        """Drop or remap generation options the API rejects with a 400."""
        model = self.service_model_name()
        updates: dict[str, Any] = {}
        if config.reasoning_effort == "none":
            warn_once(logger, META_REASONING_NONE_WARNING.format(model=model))
            updates["reasoning_effort"] = None
        elif config.reasoning_effort == "max":
            warn_once(logger, META_REASONING_MAX_WARNING.format(model=model))
            updates["reasoning_effort"] = "xhigh"
        for parameter in ("logprobs", "top_logprobs"):
            if getattr(config, parameter) is not None:
                warn_once(
                    logger,
                    META_UNSUPPORTED_PARAM_WARNING.format(
                        parameter=parameter, model=model
                    ),
                )
                updates[parameter] = None
        return config.model_copy(update=updates) if updates else config

    @override
    def resolve_tools(
        self, tools: list[ToolInfo], tool_choice: ToolChoice, config: GenerateConfig
    ) -> tuple[list[ToolInfo], ToolChoice, GenerateConfig]:
        tools, tool_choice, config = super().resolve_tools(tools, tool_choice, config)
        config = self.resolve_config(config)
        model = self.service_model_name()
        if is_forced_tool_choice(tool_choice):
            choice = (
                f'"{tool_choice.name}"'
                if isinstance(tool_choice, ToolFunction)
                else '"any"'
            )
            warn_once(
                logger, META_TOOL_CHOICE_WARNING.format(choice=choice, model=model)
            )
            tool_choice = "auto"
        return tools, tool_choice, config

    @override
    def completion_params(self, config: GenerateConfig, tools: bool) -> dict[str, Any]:
        params = super().completion_params(config, tools)
        # the API documents max_completion_tokens (not the legacy max_tokens)
        if "max_tokens" in params:
            params["max_completion_tokens"] = params.pop("max_tokens")
        for parameter in META_CHAT_UNSUPPORTED_PARAMS:
            if parameter in params:
                del params[parameter]
                warn_once(
                    logger,
                    META_UNSUPPORTED_PARAM_WARNING.format(
                        parameter=parameter, model=self.service_model_name()
                    ),
                )
        return params
