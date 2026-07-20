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

# Sampling parameters that Moonshot says to omit for Kimi K3 (the model uses
# fixed sampling and the API rejects attempts to override it).
# https://platform.kimi.ai/docs/guide/use-thinking-effort
K3_FIXED_SAMPLING_PARAMS = (
    "temperature",
    "top_p",
    "frequency_penalty",
    "presence_penalty",
)

K3_FIXED_SAMPLING_WARNING = (
    "The {parameter} parameter is not supported by {model} (Kimi K3 uses "
    "fixed sampling) and will be ignored."
)

K3_TOOL_CHOICE_WARNING = (
    "Forcing use of the {name!r} tool is not supported by {model} (Kimi K3 "
    "thinking is always on, which is incompatible with a named tool_choice) "
    'and will be submitted as "required".'
)


class MoonshotAPI(OpenAICompatibleAPI):
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
            service="Moonshot",
            service_base_url="https://api.moonshot.ai/v1",
            emulate_tools=emulate_tools,
            **model_args,
        )

    def is_kimi_k3(self) -> bool:
        return self.service_model_name().lower().startswith("kimi-k3")

    @override
    def canonical_name(self) -> str:
        """Canonical model name for model info database lookup.

        Kimi models are keyed under the `moonshotai` organization in the
        model info database (matching OpenRouter/HuggingFace naming).
        """
        return f"moonshotai/{self.service_model_name()}"

    @override
    def resolve_tools(
        self, tools: list[ToolInfo], tool_choice: ToolChoice, config: GenerateConfig
    ) -> tuple[list[ToolInfo], ToolChoice, GenerateConfig]:
        tools, tool_choice, config = super().resolve_tools(tools, tool_choice, config)
        if self.is_kimi_k3() and isinstance(tool_choice, ToolFunction):
            warn_once(
                logger,
                K3_TOOL_CHOICE_WARNING.format(
                    name=tool_choice.name, model=self.service_model_name()
                ),
            )
            tool_choice = "any"
        return tools, tool_choice, config

    @override
    def handle_bad_request(self, ex: APIStatusError) -> ModelOutput | Exception:
        # Moonshot signals context window overflow with a plain
        # invalid_request_error (no code field), e.g. "Invalid request: Your
        # request exceeded model token limit: 262144 (requested: 425573)"
        if ex.status_code == 400 and "exceeded model token limit" in ex.message:
            return ModelOutput.from_content(
                model=self.model_name, content=ex.message, stop_reason="model_length"
            )
        return super().handle_bad_request(ex)

    @override
    def completion_params(self, config: GenerateConfig, tools: bool) -> dict[str, Any]:
        params = super().completion_params(config, tools)
        if self.is_kimi_k3():
            for param in K3_FIXED_SAMPLING_PARAMS:
                if param in params:
                    del params[param]
                    warn_once(
                        logger,
                        K3_FIXED_SAMPLING_WARNING.format(
                            parameter=param, model=self.service_model_name()
                        ),
                    )
            effort = params.get("reasoning_effort")
            if effort is not None and effort != "max":
                params["reasoning_effort"] = "max"
        return params
