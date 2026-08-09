"""vLLM provider using ``/v1/completions`` instead of ``/v1/chat/completions``.

This provider bypasses the chat template entirely, sending a raw prompt to the
completions endpoint.  It is intended for perplexity benchmarks and any other
use case that requires the ``/v1/completions`` API (echo mode,
fill-in-the-middle, etc.).

The provider subclasses :class:`VLLMAPI` and inherits server lifecycle,
tokenization, retry logic, and error handling.  Only ``generate()`` is
overridden, delegating the request/response handling to the shared
implementation in :mod:`.openai_compatible_completions` (also used by the
``openai-api-completions`` provider).
"""

from __future__ import annotations

import logging

from typing_extensions import override

from inspect_ai.model._chat_message import ChatMessage
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model_call import ModelCall
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.tool._tool_choice import ToolChoice
from inspect_ai.tool._tool_info import ToolInfo

from .openai_compatible_completions import (
    generate_raw_completions,
    resolve_completions_prompt,
)
from .vllm import VLLMAPI

logger = logging.getLogger(__name__)


class VLLMCompletionsAPI(VLLMAPI):
    """vLLM provider that routes through ``/v1/completions``.

    Inherits server lifecycle, tokenize(), retries, and error handling
    from :class:`VLLMAPI`.  Overrides ``generate()`` to call the
    completions endpoint with a raw prompt instead of chat messages.

    Usage::

        model = get_model("vllm-completions/EleutherAI/pythia-70m", device=0)
        response = await model.generate(input=[ChatMessageUser(content="Hello")])

    Pre-tokenized prompts (skip the round-trip through string)::

        token_ids = my_custom_tokenizer.encode("Hello")
        response = await model.generate(
            input=[ChatMessageUser(content="", metadata={"prompt_token_ids": token_ids})]
        )

    vLLM's ``/v1/completions`` uses ``list[int]`` prompts verbatim — special
    tokens are not added regardless of the ``add_special_tokens`` flag, so
    pre-tokenized prompts pass through exactly as supplied.
    """

    @override
    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput | tuple[ModelOutput | Exception, ModelCall]:
        # resolve before server startup so bad input fails without GPU work
        prompt = resolve_completions_prompt(input, "vllm-completions")
        await self._ensure_server_started()
        return await generate_raw_completions(self, prompt, config)
