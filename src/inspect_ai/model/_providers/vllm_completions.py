"""vLLM provider using ``/v1/completions`` instead of ``/v1/chat/completions``.

This provider bypasses the chat template entirely, sending raw text to the
completions endpoint.  It is intended for perplexity benchmarks and any other
use case that requires the ``/v1/completions`` API (echo mode,
fill-in-the-middle, etc.).

The provider subclasses :class:`VLLMAPI` and inherits server lifecycle,
tokenization, retry logic, and error handling.  Only ``generate()`` is
overridden.
"""

from __future__ import annotations

import logging
from typing import Any

from openai import NotFoundError
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

from .vllm import VLLMAPI

logger = logging.getLogger(__name__)


class VLLMCompletionsAPI(VLLMAPI):
    """vLLM provider that routes through ``/v1/completions``.

    Inherits server lifecycle, tokenize(), retries, and error handling
    from :class:`VLLMAPI`.  Overrides ``generate()`` to call the
    completions endpoint with raw text instead of chat messages.

    Usage::

        model = get_model("vllm-completions/EleutherAI/pythia-70m", device=0)
        response = await model.generate(input=[ChatMessageUser(content="Hello")])
    """

    @override
    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput | tuple[ModelOutput | Exception, ModelCall]:
        await self._ensure_server_started()

        # Extract raw text from input messages.
        # /v1/completions takes a string prompt — validate that the input
        # is a single user message (the normal case for perplexity evals
        # where Sample.input is a plain string).
        if len(input) != 1 or input[0].role != "user":
            raise TypeError(
                "vllm-completions requires a single user message as input. "
                "The /v1/completions endpoint sends raw text — multi-message "
                "or multi-role inputs are not supported. Use Sample(input='text')."
            )
        prompt = input[0].text
        if not prompt:
            raise ValueError("vllm-completions: input message has no text content.")

        # Build request parameters. Same precedence as the chat completions
        # path (openai_chat_completion_params in _openai.py): user extra_body
        # goes first, then dedicated config fields override.
        extra_body: dict[str, Any] = {}
        if config.extra_body:
            extra_body.update(config.extra_body)
        if config.prompt_logprobs is not None:
            extra_body["prompt_logprobs"] = config.prompt_logprobs

        request_kwargs: dict[str, Any] = dict(
            model=self.service_model_name(),
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
        if config.logprobs is True:
            request_kwargs["logprobs"] = config.top_logprobs or 1
        if extra_body:
            request_kwargs["extra_body"] = extra_body

        # Register ModelCall for eval log visibility.
        request_id = self._http_hooks.start_request()
        model_call = set_active_model_event_call(request_kwargs)

        try:
            response = await self.client.completions.create(**request_kwargs)
        except NotFoundError:
            model_call.set_error(
                as_error_response("NotFoundError: /v1/completions not supported"),
                self._http_hooks.end_request(request_id),
            )
            raise RuntimeError(
                f"Server at {self.base_url} does not support /v1/completions. "
                f"Ensure you are using a vLLM-compatible server."
            ) from None

        model_call.set_response(
            response.model_dump(), self._http_hooks.end_request(request_id)
        )

        # Parse response
        if not response.choices:
            return ModelOutput(model=response.model, choices=[]), model_call

        choice = response.choices[0]

        # prompt_logprobs: vLLM extension, lives inside the choice for
        # /v1/completions (unlike chat completions where it's top-level).
        raw_plps = (
            choice.model_extra.get("prompt_logprobs") if choice.model_extra else None
        )
        parsed_prompt_lps = (
            parse_vllm_prompt_logprobs_raw(raw_plps) if raw_plps else None
        )

        # Completion token logprobs (standard completions format)
        parsed_completion_lps = parse_completion_logprobs(choice.logprobs)

        model_output = ModelOutput(
            model=response.model,
            choices=[
                ChatCompletionChoice(
                    message=ChatMessageAssistant(content=choice.text),
                    stop_reason=as_stop_reason(choice.finish_reason),
                    logprobs=parsed_completion_lps,
                    prompt_logprobs=parsed_prompt_lps,
                )
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
