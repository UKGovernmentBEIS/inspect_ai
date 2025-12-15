from contextvars import ContextVar
from copy import deepcopy
from typing import Any, Literal, Union

from pydantic import BaseModel, Field, model_validator
from typing_extensions import TypedDict

from inspect_ai._util.constants import DEFAULT_BATCH_SIZE
from inspect_ai.model._cache import CachePolicy
from inspect_ai.util._json import JSONSchema


class ResponseSchema(BaseModel):
    """Schema for model response when using Structured Output."""

    name: str
    """The name of the response schema. Must be a-z, A-Z, 0-9, or contain underscores and dashes, with a maximum length of 64."""

    json_schema: JSONSchema
    """The schema for the response format, described as a JSON Schema object."""

    description: str | None = Field(default=None)
    """A description of what the response format is for, used by the model to determine how to respond in the format."""

    strict: bool | None = Field(default=None)
    """Whether to enable strict schema adherence when generating the output. If set to true, the model will always follow the exact schema defined in the schema field.
    OpenAI and Mistral only."""


class BatchConfig(BaseModel):
    """Batch processing configuration."""

    size: int | None = Field(default=None)
    """Target minimum number of requests to include in each batch. If not specified, uses default of 100. Batches may be smaller if the timeout is reached or if requests don’t fit within size limits."""

    max_size: int | None = Field(default=None)
    """Maximum number of requests to include in each batch. If not specified, falls back to the provider-specific maximum batch size."""

    send_delay: float | None = Field(default=None)
    """Maximum time (in seconds) to wait before sending a partially filled batch. If not specified, uses a default of 15 seconds. This prevents indefinite waiting when request volume is low.
    """

    tick: float | None = Field(default=None)
    """Time interval (in seconds) between checking for new batch requests and batch completion status. If not specified, uses a default of 15 seconds.

    When expecting a very large number of concurrent batches, consider increasing this value to reduce overhead from continuous polling since an http request must be made for each batch on each tick.
    """

    max_batches: int | None = Field(default=None)
    """Maximum number of batches to have in flight at once for a provider (defaults to 100)."""

    max_consecutive_check_failures: int | None = Field(default=None)
    """Maximum number of consecutive check failures before failing a batch (defaults to 1000)."""


class GenerateConfigArgs(TypedDict, total=False):
    """Type for kwargs that selectively override GenerateConfig."""

    max_retries: int | None
    """Maximum number of times to retry request (defaults to unlimited)."""

    timeout: int | None
    """Request timeout (in seconds)."""

    attempt_timeout: int | None
    """Timeout (in seconds) for any given attempt (if exceeded, will abandon attempt and retry according to max_retries)."""

    max_connections: int | None
    """Maximum number of concurrent connections to Model API (default is model specific)."""

    system_message: str | None
    """Override the default system message."""

    max_tokens: int | None
    """The maximum number of tokens that can be generated in the completion (default is model specific)."""

    top_p: float | None
    """An alternative to sampling with temperature, called nucleus sampling, where the model considers the results of the tokens with top_p probability mass."""

    temperature: float | None
    """What sampling temperature to use, between 0 and 2. Higher values like 0.8 will make the output more random, while lower values like 0.2 will make it more focused and deterministic."""

    stop_seqs: list[str] | None
    """Sequences where the API will stop generating further tokens. The returned text will not contain the stop sequence."""

    best_of: int | None
    """Generates best_of completions server-side and returns the 'best' (the one with the highest log probability per token). vLLM only."""

    frequency_penalty: float | None
    """Number between -2.0 and 2.0. Positive values penalize new tokens based on their existing frequency in the text so far, decreasing the model's likelihood to repeat the same line verbatim. OpenAI, Google, Grok, Groq, and vLLM only."""

    presence_penalty: float | None
    """Number between -2.0 and 2.0. Positive values penalize new tokens based on whether they appear in the text so far, increasing the model's likelihood to talk about new topics. OpenAI, Google, Grok, Groq, and vLLM only."""

    logit_bias: dict[int, float] | None
    """Map token Ids to an associated bias value from -100 to 100 (e.g. "42=10,43=-10"). OpenAI and Grok only."""

    seed: int | None
    """Random seed. OpenAI, Google, Mistral, Groq, HuggingFace, and vLLM only."""

    top_k: int | None
    """Randomly sample the next word from the top_k most likely next words. Anthropic, Google, and HuggingFace only."""

    num_choices: int | None
    """How many chat completion choices to generate for each input message. OpenAI, Grok, Google, and TogetherAI only."""

    logprobs: bool | None
    """Return log probabilities of the output tokens. OpenAI, Google, Grok, TogetherAI, Huggingface, llama-cpp-python, and vLLM only."""

    top_logprobs: int | None
    """Number of most likely tokens (0-20) to return at each token position, each with an associated log probability. OpenAI, Google, Grok, and Huggingface only."""

    parallel_tool_calls: bool | None
    """Whether to enable parallel function calling during tool use (defaults to True). OpenAI and Groq only."""

    internal_tools: bool | None
    """Whether to automatically map tools to model internal implementations (e.g. 'computer' for anthropic)."""

    max_tool_output: int | None
    """Maximum tool output (in bytes). Defaults to 16 * 1024."""

    cache_prompt: Literal["auto"] | bool | None
    """Whether to cache the prompt prefix. Defaults to "auto", which will enable caching for requests with tools. Anthropic only."""

    verbosity: Literal["low", "medium", "high"] | None
    """Constrains the verbosity of the model's response. Lower values will result in more concise responses, while higher values will result in more verbose responses. GPT 5.x models only (defaults to "medium" for OpenAI models)."""

    effort: Literal["low", "medium", "high"] | None
    """Control how many tokens are used for a response, trading off between response thoroughness and token efficiency. Anthropic Claude 4.5 Opus only."""

    reasoning_effort: (
        Literal["none", "minimal", "low", "medium", "high", "xhigh"] | None
    )
    """Constrains effort on reasoning. Defaults vary by provider and model and not all models support all values (please consult provider documentation for details)."""

    reasoning_tokens: int | None
    """Maximum number of tokens to use for reasoning. Anthropic Claude models only."""

    reasoning_summary: Literal["none", "concise", "detailed", "auto"] | None
    """Provide summary of reasoning steps (OpenAI reasoning models only). Use 'auto' to access the most detailed summarizer available for the current model (defaults to 'auto' if your organization is verified by OpenAI)."""

    reasoning_history: Literal["none", "all", "last", "auto"] | None
    """Include reasoning in chat message history sent to generate."""

    response_schema: ResponseSchema | None
    """Request a response format as JSONSchema (output should still be validated). OpenAI, Google, and Mistral only."""

    extra_body: dict[str, Any] | None
    """Extra body to be sent with requests to OpenAI compatible servers. OpenAI, vLLM, and SGLang only."""

    cache: bool | CachePolicy | None
    """Policy for caching of model generations."""

    batch: bool | int | BatchConfig | None
    """Use batching API when available. True to enable batching with default configuration, False to disable batching, a number to enable batching of the specified batch size, or a BatchConfig object specifying the batching configuration."""


class GenerateConfig(BaseModel):
    """Model generation options."""

    max_retries: int | None = Field(default=None)
    """Maximum number of times to retry request (defaults to unlimited)."""

    timeout: int | None = Field(default=None)
    """Timeout (in seconds) for an entire request (including retries)."""

    attempt_timeout: int | None = Field(default=None)
    """Timeout (in seconds) for any given attempt (if exceeded, will abandon attempt and retry according to max_retries)."""

    max_connections: int | None = Field(default=None)
    """Maximum number of concurrent connections to Model API (default is model specific)."""

    system_message: str | None = Field(default=None)
    """Override the default system message."""

    max_tokens: int | None = Field(default=None)
    """The maximum number of tokens that can be generated in the completion (default is model specific)."""

    top_p: float | None = Field(default=None)
    """An alternative to sampling with temperature, called nucleus sampling, where the model considers the results of the tokens with top_p probability mass."""

    temperature: float | None = Field(default=None)
    """What sampling temperature to use, between 0 and 2. Higher values like 0.8 will make the output more random, while lower values like 0.2 will make it more focused and deterministic."""

    stop_seqs: list[str] | None = Field(default=None)
    """Sequences where the API will stop generating further tokens. The returned text will not contain the stop sequence."""

    best_of: int | None = Field(default=None)
    """Generates best_of completions server-side and returns the 'best' (the one with the highest log probability per token). vLLM only."""

    frequency_penalty: float | None = Field(default=None)
    """Number between -2.0 and 2.0. Positive values penalize new tokens based on their existing frequency in the text so far, decreasing the model's likelihood to repeat the same line verbatim. OpenAI, Google, Grok, Groq, vLLM, and SGLang only."""

    presence_penalty: float | None = Field(default=None)
    """Number between -2.0 and 2.0. Positive values penalize new tokens based on whether they appear in the text so far, increasing the model's likelihood to talk about new topics. OpenAI, Google, Grok, Groq, vLLM, and SGLang only."""

    logit_bias: dict[int, float] | None = Field(default=None)
    """Map token Ids to an associated bias value from -100 to 100 (e.g. "42=10,43=-10"). OpenAI, Grok, Grok, and vLLM only."""

    seed: int | None = Field(default=None)
    """Random seed. OpenAI, Google, Mistral, Groq, HuggingFace, and vLLM only."""

    top_k: int | None = Field(default=None)
    """Randomly sample the next word from the top_k most likely next words. Anthropic, Google, HuggingFace, vLLM, and SGLang only."""

    num_choices: int | None = Field(default=None)
    """How many chat completion choices to generate for each input message. OpenAI, Grok, Google, TogetherAI, vLLM, and SGLang only."""

    logprobs: bool | None = Field(default=None)
    """Return log probabilities of the output tokens. OpenAI, Grok, TogetherAI, Huggingface, llama-cpp-python, vLLM, and SGLang only."""

    top_logprobs: int | None = Field(default=None)
    """Number of most likely tokens (0-20) to return at each token position, each with an associated log probability. OpenAI, Grok, Huggingface, vLLM, and SGLang only."""

    parallel_tool_calls: bool | None = Field(default=None)
    """Whether to enable parallel function calling during tool use (defaults to True). OpenAI and Groq only."""

    internal_tools: bool | None = Field(default=None)
    """Whether to automatically map tools to model internal implementations (e.g. 'computer' for anthropic)."""

    max_tool_output: int | None = Field(default=None)
    """Maximum tool output (in bytes). Defaults to 16 * 1024."""

    cache_prompt: Literal["auto"] | bool | None = Field(default=None)
    """Whether to cache the prompt prefix. Defaults to "auto", which will enable caching for requests with tools. Anthropic only."""

    verbosity: Literal["low", "medium", "high"] | None = Field(default=None)
    """Constrains the verbosity of the model's response. Lower values will result in more concise responses, while higher values will result in more verbose responses. GPT 5.x models only (defaults to "medium" for OpenAI models)."""

    effort: Literal["low", "medium", "high"] | None = Field(default=None)
    """Control how many tokens are used for a response, trading off between response thoroughness and token efficiency. Anthropic Claude 4.5 Opus only."""

    reasoning_effort: (
        Literal["none", "minimal", "low", "medium", "high", "xhigh"] | None
    ) = Field(default=None)
    """Constrains effort on reasoning. Defaults vary by provider and model and not all models support all values (please consult provider documentation for details)."""

    reasoning_tokens: int | None = Field(default=None)
    """Maximum number of tokens to use for reasoning. Anthropic Claude models only."""

    reasoning_summary: Literal["none", "concise", "detailed", "auto"] | None = Field(
        default=None
    )
    """Provide summary of reasoning steps (OpenAI reasoning models only). Use 'auto' to access the most detailed summarizer available for the current model (defaults to 'auto' if your organization is verified by OpenAI)."""

    reasoning_history: Literal["none", "all", "last", "auto"] | None = Field(
        default=None
    )
    """Include reasoning in chat message history sent to generate."""

    response_schema: ResponseSchema | None = Field(default=None)
    """Request a response format as JSONSchema (output should still be validated). OpenAI, Google, Mistral, vLLM, and SGLang only."""

    extra_body: dict[str, Any] | None = Field(default=None)
    """Extra body to be sent with requests to OpenAI compatible servers. OpenAI, vLLM, and SGLang only."""

    cache: bool | CachePolicy | None = Field(default=None)
    """Policy for caching of model generate output."""

    batch: bool | int | BatchConfig | None = Field(default=None)
    """Use batching API when available. True to enable batching with default configuration, False to disable batching, a number to enable batching of the specified batch size, or a BatchConfig object specifying the batching configuration."""

    # migrate reasoning_history as a bool
    @model_validator(mode="before")
    @classmethod
    def migrate_reasoning(cls, data: Any) -> Any:
        if isinstance(data, dict):
            reasoning_history = data.get("reasoning_history", None)
            if reasoning_history is True:
                data["reasoning_history"] = "all"
            elif reasoning_history is False:
                data["reasoning_history"] = "none"

        return data

    def merge(
        self, other: Union["GenerateConfig", GenerateConfigArgs]
    ) -> "GenerateConfig":
        """Merge another model configuration into this one.

        Args:
           other (Union[GenerateConfig, GenerateConfigArgs]):
              Configuration to merge.

        Returns:
           Merged configuration.
        """
        if not isinstance(other, GenerateConfig):
            other = GenerateConfig(**other)
        config_keys = list(GenerateConfigArgs.__mutable_keys__)  # type: ignore
        config = deepcopy(self)
        for key in config_keys:
            value = getattr(other, key, None)
            if value is not None:
                setattr(config, key, value)
        return config


def active_generate_config() -> GenerateConfig:
    return active_generate_config_context_var.get()


def set_active_generate_config(config: GenerateConfig) -> None:
    active_generate_config_context_var.set(config)


active_generate_config_context_var: ContextVar[GenerateConfig] = ContextVar(
    "generate_config", default=GenerateConfig()
)


def normalized_batch_config(
    batch: bool | int | BatchConfig | None,
) -> BatchConfig | None:
    return (
        batch
        if isinstance(batch, BatchConfig)
        else None
        if not batch
        else BatchConfig(size=DEFAULT_BATCH_SIZE if batch is True else batch)
    )
