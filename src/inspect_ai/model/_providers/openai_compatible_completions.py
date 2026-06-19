"""OpenAI-compatible provider using ``/v1/completions`` instead of ``/v1/chat/completions``.

This provider bypasses the chat template entirely, sending a raw prompt to the
legacy completions endpoint. It is intended for perplexity benchmarks, base
model evaluation, and any other use case that requires the ``/v1/completions``
API (echo mode, fill-in-the-middle, pre-tokenized prompts, etc.).

The module also hosts the shared completions-endpoint implementation
(:func:`resolve_completions_prompt` and :func:`generate_raw_completions`)
consumed by both :class:`OpenAICompatibleCompletionsAPI` and the
``vllm-completions`` provider.
"""

from __future__ import annotations

import logging
from typing import Any

from openai import NotFoundError
from openai.types.completion_choice import CompletionChoice
from typing_extensions import override

from inspect_ai.log._samples import set_active_model_event_call
from inspect_ai.model._chat_message import ChatMessage, ChatMessageAssistant
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model_call import ModelCall, as_error_response
from inspect_ai.model._model_output import (
    ChatCompletionChoice,
    ModelOutput,
    ModelUsage,
    as_stop_reason,
)
from inspect_ai.model._openai import (
    parse_completion_logprobs,
    parse_vllm_prompt_logprobs_raw,
)
from inspect_ai.tool._tool_choice import ToolChoice
from inspect_ai.tool._tool_info import ToolInfo

from .openai_compatible import OpenAICompatibleAPI

logger = logging.getLogger(__name__)


def resolve_completions_prompt(
    input: list[ChatMessage], provider: str
) -> str | list[int]:
    """Validate input shape and resolve the ``/v1/completions`` prompt.

    The completions endpoint takes a single prompt, so the input must be a
    single user message (the normal case for perplexity evals where
    ``Sample.input`` is a plain string). Pre-tokenized IDs in
    ``metadata["prompt_token_ids"]`` take precedence over message text —
    the endpoint accepts both ``str`` and ``list[int]`` prompts.

    Validation is deliberately separate from the request itself so providers
    with deferred startup (e.g. ``vllm-completions``) can reject bad input
    before doing any server work.

    Args:
        input: Chat messages passed to ``generate()``.
        provider: Provider name used in error messages.

    Returns:
        The prompt to send: message text, or token IDs if supplied.
    """
    if len(input) != 1 or input[0].role != "user":
        raise TypeError(
            f"{provider} requires a single user message as input. "
            "The /v1/completions endpoint sends a raw prompt — multi-message "
            "or multi-role inputs are not supported. Use Sample(input='text')."
        )

    metadata = input[0].metadata or {}
    prompt_token_ids = metadata.get("prompt_token_ids")
    if prompt_token_ids is not None:
        if not isinstance(prompt_token_ids, list) or not all(
            isinstance(t, int) for t in prompt_token_ids
        ):
            raise TypeError(
                f"{provider}: metadata['prompt_token_ids'] must be a list[int]."
            )
        if not prompt_token_ids:
            raise ValueError(f"{provider}: metadata['prompt_token_ids'] is empty.")
        return prompt_token_ids

    prompt = input[0].text
    if not prompt:
        raise ValueError(
            f"{provider}: input message has no text content "
            "and no metadata['prompt_token_ids']."
        )
    return prompt


async def generate_raw_completions(
    api: OpenAICompatibleAPI,
    prompt: str | list[int],
    config: GenerateConfig,
) -> ModelOutput | tuple[ModelOutput | Exception, ModelCall]:
    """Generate via the ``/v1/completions`` endpoint of an OpenAI-compatible server.

    Shared implementation behind ``openai-api-completions`` and
    ``vllm-completions``. Handles request construction from
    :class:`GenerateConfig`, ``ModelCall`` registration, and parsing of the
    response (including completions-format logprobs and, when the server
    returns them, vLLM-style per-choice ``prompt_logprobs``).
    """
    # Build request parameters. Same precedence as the chat completions
    # path (openai_chat_completion_params in _openai.py): user extra_body
    # goes first, then dedicated config fields override.
    extra_body: dict[str, Any] = {}
    if config.extra_body:
        extra_body.update(config.extra_body)
    if config.prompt_logprobs is not None:
        extra_body["prompt_logprobs"] = config.prompt_logprobs

    request_kwargs: dict[str, Any] = dict(
        model=api.service_model_name(),
        prompt=prompt,
        # Default temperature=0.0 for deterministic scoring (perplexity evals).
        max_tokens=config.max_tokens if config.max_tokens is not None else 1,
        temperature=config.temperature if config.temperature is not None else 0.0,
    )

    if config.top_p is not None:
        request_kwargs["top_p"] = config.top_p
    if config.frequency_penalty is not None:
        request_kwargs["frequency_penalty"] = config.frequency_penalty
    if config.presence_penalty is not None:
        request_kwargs["presence_penalty"] = config.presence_penalty
    if config.seed is not None:
        request_kwargs["seed"] = config.seed
    if config.stop_seqs is not None:
        request_kwargs["stop"] = config.stop_seqs
    if config.num_choices is not None:
        # /v1/completions `n`: sample multiple completions per prompt in one
        # request — prompt tokens are billed once, not per sample.
        request_kwargs["n"] = config.num_choices
    if config.logprobs is True:
        request_kwargs["logprobs"] = config.top_logprobs or 1
    if extra_body:
        request_kwargs["extra_body"] = extra_body

    # Register ModelCall for eval log visibility.
    request_id = api._http_hooks.start_request()
    model_call = set_active_model_event_call(request_kwargs)

    try:
        response = await api.client.completions.create(**request_kwargs)
    except NotFoundError:
        model_call.set_error(
            as_error_response("NotFoundError: /v1/completions not supported"),
            api._http_hooks.end_request(request_id),
        )
        raise RuntimeError(
            f"Server at {api.base_url} does not support /v1/completions. "
            f"Ensure the server exposes the legacy completions endpoint."
        ) from None

    model_call.set_response(
        response.model_dump(), api._http_hooks.end_request(request_id)
    )

    # Parse response
    if not response.choices:
        return ModelOutput(model=response.model, choices=[]), model_call

    def parse_choice(choice: CompletionChoice) -> ChatCompletionChoice:
        # prompt_logprobs: vLLM extension (also implemented by SGLang), lives
        # inside the choice for /v1/completions (unlike chat completions where
        # it's top-level). Parsed when present, ignored otherwise.
        raw_plps = (
            choice.model_extra.get("prompt_logprobs") if choice.model_extra else None
        )
        return ChatCompletionChoice(
            message=ChatMessageAssistant(content=choice.text),
            stop_reason=as_stop_reason(choice.finish_reason),
            # Completion token logprobs (standard completions format)
            logprobs=parse_completion_logprobs(choice.logprobs),
            prompt_logprobs=parse_vllm_prompt_logprobs_raw(raw_plps)
            if raw_plps
            else None,
        )

    model_output = ModelOutput(
        model=response.model,
        choices=[
            parse_choice(c)
            for c in sorted(response.choices, key=lambda c: c.index or 0)
        ],
        usage=(
            ModelUsage(
                input_tokens=response.usage.prompt_tokens,
                output_tokens=response.usage.completion_tokens,
                total_tokens=response.usage.total_tokens,
            )
            if response.usage
            else None
        ),
    )

    return model_output, model_call


class OpenAICompatibleCompletionsAPI(OpenAICompatibleAPI):
    """OpenAI-compatible provider that routes through ``/v1/completions``.

    Inherits service/credential resolution (``<SERVICE>_API_KEY`` /
    ``<SERVICE>_BASE_URL`` environment variables), retries, and error
    handling from :class:`OpenAICompatibleAPI`. Overrides ``generate()``
    to call the completions endpoint with a raw prompt instead of chat
    messages.

    Usage::

        model = get_model("openai-api-completions/together/meta-llama/Llama-3-8B")
        response = await model.generate(input=[ChatMessageUser(content="Hello")])

    Pre-tokenized prompts (skip the round-trip through string)::

        token_ids = my_custom_tokenizer.encode("Hello")
        response = await model.generate(
            input=[ChatMessageUser(content="", metadata={"prompt_token_ids": token_ids})]
        )

    Token IDs are passed through verbatim. Whether the server adds special
    tokens to pre-tokenized prompts is server-dependent (vLLM does not).
    """

    @override
    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput | tuple[ModelOutput | Exception, ModelCall]:
        prompt = resolve_completions_prompt(input, "openai-api-completions")
        return await generate_raw_completions(self, prompt, config)
