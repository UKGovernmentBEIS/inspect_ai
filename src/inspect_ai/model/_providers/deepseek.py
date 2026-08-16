from logging import getLogger
from typing import Any

from openai import APIStatusError
from typing_extensions import override

from inspect_ai._util.logger import warn_once
from inspect_ai.tool import ToolChoice, ToolFunction, ToolInfo

from .._generate_config import GenerateConfig
from .._model_output import ModelOutput
from .openai_compatible import OpenAICompatibleAPI

logger = getLogger(__name__)

DEEPSEEK_TOOL_CHOICE_WARNING = (
    "Forcing tool use ({choice}) is not supported by {model} while thinking "
    'is enabled (the default) and will be submitted as "auto". Set '
    'reasoning_effort="none" to disable thinking and force tool use.'
)

# DeepSeek's documented effort scale is low/high/max. The API currently
# accepts other values but only these are contractual, so intermediate
# values map to the nearest documented value.
# https://api-docs.deepseek.com/guides/thinking_mode
DEEPSEEK_EFFORT_MAP = {
    "minimal": "low",
    "medium": "high",
    "xhigh": "max",
}


class DeepSeekAPI(OpenAICompatibleAPI):
    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        config: GenerateConfig = GenerateConfig(),
        emulate_tools: bool = False,
        **model_args: Any,
    ) -> None:
        super().__init__(
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            config=config,
            service="DeepSeek",
            service_base_url="https://api.deepseek.com",
            emulate_tools=emulate_tools,
            **model_args,
        )

    @staticmethod
    def thinking_disabled(config: GenerateConfig) -> bool:
        """Whether the request explicitly disables thinking.

        DeepSeek V4 models think by default; thinking is disabled via
        `reasoning_effort="none"` or by passing `thinking: {"type": "disabled"}`
        in extra_body, which also lifts the forced-tool_choice restriction.
        """
        if config.reasoning_effort == "none":
            return True
        thinking = (config.extra_body or {}).get("thinking")
        return isinstance(thinking, dict) and thinking.get("type") == "disabled"

    @override
    def resolve_tools(
        self, tools: list[ToolInfo], tool_choice: ToolChoice, config: GenerateConfig
    ) -> tuple[list[ToolInfo], ToolChoice, GenerateConfig]:
        tools, tool_choice, config = super().resolve_tools(tools, tool_choice, config)
        # thinking mode rejects any forced tool_choice ("required" or a named
        # function) with a 400; only "auto" and "none" are accepted
        if not self.thinking_disabled(config) and (
            isinstance(tool_choice, ToolFunction) or tool_choice == "any"
        ):
            choice = (
                f'"{tool_choice.name}"'
                if isinstance(tool_choice, ToolFunction)
                else '"any"'
            )
            warn_once(
                logger,
                DEEPSEEK_TOOL_CHOICE_WARNING.format(
                    choice=choice, model=self.service_model_name()
                ),
            )
            tool_choice = "auto"
        return tools, tool_choice, config

    @override
    def canonical_name(self) -> str:
        """Canonical model name for model info database lookup.

        DeepSeek models are keyed under the `deepseek` organization in the
        model info database.
        """
        return f"deepseek/{self.service_model_name()}"

    @override
    def handle_bad_request(self, ex: APIStatusError) -> ModelOutput | Exception:
        # DeepSeek signals context window overflow with a generic
        # invalid_request_error code (not context_length_exceeded), e.g.
        # "This model's maximum context length is 1048576 tokens. However,
        # you requested 1283793 tokens ..."
        if ex.status_code == 400 and "maximum context length" in ex.message:
            return ModelOutput.from_content(
                model=self.model_name, content=ex.message, stop_reason="model_length"
            )
        return super().handle_bad_request(ex)

    @override
    def completion_params(self, config: GenerateConfig, tools: bool) -> dict[str, Any]:
        params = super().completion_params(config, tools)
        effort = params.get("reasoning_effort")
        if effort == "none":
            # thinking is disabled via the documented thinking parameter
            # rather than an effort value
            del params["reasoning_effort"]
            extra_body: dict[str, Any] = dict(params.get("extra_body") or {})
            extra_body.setdefault("thinking", {"type": "disabled"})
            params["extra_body"] = extra_body
        elif effort in DEEPSEEK_EFFORT_MAP:
            params["reasoning_effort"] = DEEPSEEK_EFFORT_MAP[effort]
        return params
