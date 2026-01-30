import gc
import time
from typing import Any, override

import torch
from nnterp import StandardizedTransformer  # type: ignore

from inspect_ai._util.content import (
    ContentAudio,
    ContentDocument,
    ContentImage,
    ContentVideo,
)
from inspect_ai.model import (
    ChatCompletionChoice,
    ChatMessage,
    ChatMessageAssistant,
    GenerateConfig,
    ModelAPI,
    ModelOutput,
    ModelUsage,
)
from inspect_ai.model._model_output import Logprob, Logprobs, TopLogprob
from inspect_ai.model._reasoning import emulate_reasoning_history
from inspect_ai.tool import (
    ToolChoice,
    ToolInfo,
)


class NNterpAPI(ModelAPI):
    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        config: GenerateConfig = GenerateConfig(),
        **model_args: Any,
    ):
        super().__init__(
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            api_key_vars=["HF_TOKEN"],
            config=config,
        )

        # collect known model_args (then delete them so we can pass the rest on)
        def collect_model_arg(name: str, default: Any = None) -> Any:
            nonlocal model_args
            value = model_args.pop(name, default)
            return value

        dispatch = collect_model_arg("dispatch", True)
        device_map = collect_model_arg("device_map", "auto")
        dtype = collect_model_arg("dtype", torch.float16)
        self.hidden_states = collect_model_arg("hidden_states", False)

        self.model = StandardizedTransformer(
            model_name,
            dispatch=dispatch,
            device_map=device_map,
            dtype=dtype,
            **model_args,
        )

        self.tokenizer = self.model.tokenizer
        # LLMs generally don't have a pad token and we need one for batching
        self.tokenizer.pad_token = self.tokenizer.eos_token
        self.tokenizer.padding_side = "left"

    @override
    def close(self) -> None:
        self.model = None
        self.tokenizer = None
        gc.collect()

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput:
        start_time = time.monotonic()

        # apply chat template to format messages
        chat = self._apply_chat_template(input)

        # tokenize input
        tokenized = self.tokenizer(
            chat,
            return_tensors="pt",
            padding=True,
        )
        input_ids = tokenized["input_ids"]
        attention_mask = tokenized["attention_mask"]

        # prepare generator kwargs
        kwargs: dict[str, Any] = dict(do_sample=True)
        if config.max_tokens is not None:
            kwargs["max_new_tokens"] = config.max_tokens
        if config.temperature is not None:
            kwargs["temperature"] = config.temperature
        if config.top_p is not None:
            kwargs["top_p"] = config.top_p
        if config.top_k is not None:
            kwargs["top_k"] = config.top_k

        if config.stop_seqs is not None:
            from transformers.generation import StopStringCriteria  # type: ignore

            stopping_criteria = [StopStringCriteria(self.tokenizer, config.stop_seqs)]
            kwargs["stopping_criteria"] = stopping_criteria

        # determine what to extract
        output_logits = config.logprobs is True
        output_hidden_states = self.hidden_states is True

        logits_list: list[Any] = []
        hidden_states_list: list[list[Any]] = []

        # generate with nnterp model
        with torch.inference_mode():
            with self.model.generate(
                **kwargs,
            ) as tracer:
                with tracer.invoke(input_ids=input_ids, attention_mask=attention_mask):
                    output_ids = tracer.result.save()

                if output_logits or output_hidden_states:
                    with tracer.invoke():
                        with tracer.iter[:]:
                            _hidden_states: list[Any] = []

                            if output_hidden_states:
                                for layer in range(self.model.num_layers):
                                    _hidden_states.append(
                                        self.model.layers_output[layer].cpu()
                                    )

                            if output_logits:
                                logits_list.append(self.model.logits.cpu())

                            if output_hidden_states:
                                hidden_states_list.append(_hidden_states)

        # decode only the new tokens (exclude input tokens)
        generated_ids = output_ids[:, input_ids.size(1) :]
        output_text = self.tokenizer.decode(
            generated_ids[0],
            skip_special_tokens=True,
            clean_up_tokenization_spaces=False,
        )

        # process logprobs if requested
        final_logprobs = None
        if output_logits and len(logits_list) > 0:
            # Stack logits from each generation step
            # Each logit tensor may be [batch, seq_len, vocab] or [batch, vocab]
            stacked_logits = torch.stack(logits_list, dim=0)
            # Reshape to [num_tokens, vocab] - squeeze out batch and any extra dims
            # Shape after stack: [num_tokens, batch, ...maybe seq..., vocab]
            if stacked_logits.dim() == 4:
                # [num_tokens, batch, seq, vocab] -> take last token of seq, first batch
                stacked_logits = stacked_logits[:, 0, -1, :]  # [num_tokens, vocab]
            elif stacked_logits.dim() == 3:
                # [num_tokens, batch, vocab] -> take first batch
                stacked_logits = stacked_logits[:, 0, :]  # [num_tokens, vocab]

            # Apply log_softmax to get log probabilities
            logprobs_tensor = torch.nn.functional.log_softmax(stacked_logits, dim=-1)
            # Extract formatted logprobs
            final_logprobs = extract_logprobs(
                logprobs=logprobs_tensor,
                top=config.top_logprobs,
                tokenizer=self.tokenizer,
            )

        # process hidden states if requested
        processed_hidden_states = None
        if output_hidden_states and len(hidden_states_list) > 0:
            # hidden_states_list is: list[list[Tensor]] where outer is per-token, inner is per-layer
            # Convert to: tuple[tuple[Tensor]] - (num_tokens, num_layers, ...)
            processed_hidden_states = tuple(
                tuple(hs for hs in token_hidden_states)
                for token_hidden_states in hidden_states_list
            )

        # calculate token counts
        input_tokens = input_ids.size(1)
        output_tokens = generated_ids.size(1)
        total_tokens = input_tokens + output_tokens
        elapsed_time = time.monotonic() - start_time

        # construct choice
        choice = ChatCompletionChoice(
            message=ChatMessageAssistant(
                content=output_text, model=self.model_name, source="generate"
            ),
            logprobs=(
                Logprobs(content=final_logprobs) if final_logprobs is not None else None
            ),
        )

        # build metadata
        metadata = None
        if processed_hidden_states is not None:
            metadata = {"hidden_states": processed_hidden_states}

        # return output
        return ModelOutput(
            model=self.model_name,
            choices=[choice],
            usage=ModelUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
            ),
            time=elapsed_time,
            metadata=metadata,
        )

    def _apply_chat_template(self, messages: list[ChatMessage]) -> str:
        """Apply chat template to format messages for the model."""
        # convert messages to format expected by tokenizer
        formatted_messages = message_content_to_list(messages)

        # apply chat template if available
        if self.tokenizer.chat_template is not None:
            chat = self.tokenizer.apply_chat_template(
                formatted_messages,
                add_generation_prompt=True,
                tokenize=False,
            )
        else:
            # fallback: simple concatenation
            chat = ""
            for message in formatted_messages:
                chat += f"{message['role']}: {message['content']}\n"

        return str(chat)


def message_content_to_list(messages: list[ChatMessage]) -> list[dict[str, str]]:
    """Convert list of ChatMessage to list of dicts for apply_chat_template.

    Modified from the HuggingFace provider.
    """
    result = []
    for message in emulate_reasoning_history(messages):
        if isinstance(message.content, list):
            is_multimodal = any(
                isinstance(
                    item, ContentAudio | ContentImage | ContentVideo | ContentDocument
                )
                for item in message.content
            )
            if is_multimodal:
                raise NotImplementedError(
                    "NNterp provider does not support multimodal content, please provide text inputs only."
                )
            content = message.text
        else:
            content = message.content

        result.append({"role": message.role, "content": content})

    return result


def extract_logprobs(
    logprobs: torch.Tensor,
    top: int | None,
    tokenizer: Any,
) -> list[Logprob]:
    """Extract formatted logprobs from a logprobs tensor.

    Args:
        logprobs: Tensor of shape [num_tokens, vocab_size] containing log probabilities
        top: Number of top logprobs to return per token
        tokenizer: Tokenizer for converting token ids to strings

    Returns:
        List of Logprob objects, one per generated token
    """
    k = top or 1
    topk_values, topk_inds = logprobs.topk(k=k, dim=-1)
    final_logprobs = []

    for toks, vals in zip(topk_inds, topk_values):
        top_logprobs_list: list[TopLogprob] = []
        for tok, val in zip(toks, vals):
            token_str = tokenizer.convert_ids_to_tokens(tok.item())
            top_logprobs_list.append(
                TopLogprob(
                    token=token_str,
                    logprob=float(val),
                    bytes=list(map(ord, token_str)),
                )
            )
        final_logprobs.append(
            Logprob(
                token=top_logprobs_list[0].token,
                logprob=top_logprobs_list[0].logprob,
                bytes=top_logprobs_list[0].bytes,
                top_logprobs=top_logprobs_list,
            )
        )
    return final_logprobs
