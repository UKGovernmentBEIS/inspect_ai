import os
import re
from logging import getLogger
from typing import Any

from typing_extensions import override

from inspect_ai._util.content import ContentText
from inspect_ai._util.logger import warn_once
from inspect_ai.tool import ToolChoice, ToolFunction, ToolInfo

from .._chat_message import ChatMessage
from .._generate_config import GenerateConfig
from .._model_call import ModelCall
from .._model_output import ModelOutput, StopDetails
from .openai_compatible import OpenAICompatibleAPI
from .util import environment_prerequisite_error

logger = getLogger(__name__)

META_BASE_URL = "https://api.meta.ai/v1"

# `MODEL_API_KEY` is the variable Meta's own SDK quickstarts use; `META_API_KEY`
# follows inspect's provider naming convention. Either works.
META_API_KEY_VARS = ("META_API_KEY", "MODEL_API_KEY")

META_TOOL_CHOICE_WARNING = (
    "Forcing tool use ({choice}) is not supported by {model} (the Meta Model "
    'API only accepts tool_choice="auto") and will be submitted as "auto".'
)

META_TOOL_CHOICE_NONE_WARNING = (
    'tool_choice="none" is not supported by {model} (the Meta Model API only '
    'accepts tool_choice="auto"); tools will be omitted from the request instead.'
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
    "The {parameter} parameter is not supported by {model} (Muse Spark is a "
    "reasoning model) and will be ignored."
)

# Chat Completions params the API rejects with a 400 (the Responses path
# already omits these with a warning of its own).
META_CHAT_UNSUPPORTED_PARAMS = ("stop", "logit_bias", "n")

# Refusal detection. The API surfaces no structured refusal signal (no
# `refusal` content part, no `content_filter` incomplete reason): a refusal is
# an ordinary assistant message such as "I can't provide information or
# guidance on that." or "I can't help with that — ... If you're interested in
# X, I'm happy to help with that instead." We flag short replies that open
# with a first-person refusal so agent loops and scorers see a
# `content_filter` stop rather than a normal completion. Longer replies are
# left alone: a message that declines one thing and then continues at length
# is partial compliance, not a refusal.
REFUSAL_MAX_CHARS = 1000

_I_CANNOT = (
    r"(?:i\s+(?:can(?:'|no|\s+no)?t|won't|will not|am (?:not able|unable) to)"
    r"|i'm (?:not able|unable) to)"
)
_REFUSAL_VERBS = (
    r"(?:help|assist|provide|create|write|generate|produce|do|comply|support|"
    r"share|give|continue|proceed|fulfil|engage|participate)"
)
REFUSAL_PATTERNS = (
    # "I'm sorry, but I can't help with that" / "Sorry, I can't ..."
    re.compile(
        rf"^(?:i'm sorry|i am sorry|sorry|i apologi[sz]e|unfortunately)[,.!]?\s*(?:but\s+)?{_I_CANNOT}\b",
        re.IGNORECASE,
    ),
    # "I can't help with that" / "I won't provide ..." / "I'm unable to assist"
    re.compile(rf"^{_I_CANNOT}\s+{_REFUSAL_VERBS}\b", re.IGNORECASE),
)
_CONTRASTIVE = re.compile(r"\b(?:but|however|though|although)\b", re.IGNORECASE)
_SENTENCE_END = re.compile(r"[.!?\n]")


def meta_refusal_stop_details(text: str) -> StopDetails | None:
    """Detect a first-person refusal in a short assistant reply.

    Returns refusal `StopDetails` when `text` is short and opens with a
    refusal, otherwise None. The heuristic deliberately errs toward missing a
    refusal over mislabelling a real answer.
    """
    stripped = text.strip()
    if not stripped or len(stripped) > REFUSAL_MAX_CHARS:
        return None
    # normalize typographic apostrophes and leading markdown emphasis
    normalized = stripped.replace("’", "'").lstrip("*_# ")
    for pattern in REFUSAL_PATTERNS:
        match = pattern.match(normalized)
        if match is None:
            continue
        # a contrastive clause in the same sentence ("I can't X, but Y" /
        # "can't help but notice") means the reply goes on to answer; a later
        # sentence offering alternatives is still a refusal
        rest = normalized[match.end() :]
        end = _SENTENCE_END.search(rest)
        sentence = rest if end is None else rest[: end.start()]
        if not _CONTRASTIVE.search(sentence):
            return StopDetails(type="refusal", explanation=stripped)
    return None


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
        responses_api: bool | None = None,
        strict_tools: bool = False,
        detect_refusals: bool = True,
        **model_args: Any,
    ) -> None:
        api_key_var = META_API_KEY_VARS[0]
        if not api_key:
            for var in META_API_KEY_VARS:
                value = os.environ.get(var)
                if value:
                    api_key, api_key_var = value, var
                    break
            else:
                raise environment_prerequisite_error("Meta", list(META_API_KEY_VARS))

        super().__init__(
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            config=config,
            service="Meta",
            service_base_url=META_BASE_URL,
            api_key_var=api_key_var,
            responses_api=True if responses_api is None else responses_api,
            strict_tools=strict_tools,
            **model_args,
        )
        self.detect_refusals = detect_refusals

    @override
    def canonical_name(self) -> str:
        """Muse models are keyed under the `meta` organization in the model info database."""
        return f"meta/{self.service_model_name()}"

    @override
    def should_stream(self, config: GenerateConfig) -> bool:
        return True

    @override
    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput | tuple[ModelOutput | Exception, ModelCall]:
        result = await super().generate(
            input, tools, tool_choice, self.resolve_config(config)
        )
        if not self.detect_refusals:
            return result
        if isinstance(result, tuple):
            output, call = result
            if isinstance(output, ModelOutput):
                output = self.flag_refusal(output)
            return output, call
        return self.flag_refusal(result)

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
        model = self.service_model_name()
        if tool_choice == "none":
            if tools:
                warn_once(logger, META_TOOL_CHOICE_NONE_WARNING.format(model=model))
                tools = []
        elif tool_choice == "any" or isinstance(tool_choice, ToolFunction):
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

    def flag_refusal(self, output: ModelOutput) -> ModelOutput:
        """Convert a text refusal into a `content_filter` stop (see `meta_refusal_stop_details`)."""
        if output.empty or output.stop_reason != "stop":
            return output
        choice = output.choices[0]
        message = choice.message
        if message.tool_calls:
            return output
        details = meta_refusal_stop_details(message.text)
        if details is None:
            return output
        choice.stop_reason = "content_filter"
        choice.stop_details = details
        if isinstance(message.content, str):
            message.content = [ContentText(text=message.content, refusal=True)]
        else:
            for content in message.content:
                if isinstance(content, ContentText):
                    content.refusal = True
        return output
