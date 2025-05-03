from __future__ import annotations

import concurrent
import concurrent.futures
import copy
import functools
import gc
import json
import os
import time
from concurrent.futures import Future
from dataclasses import dataclass
from logging import getLogger
from queue import Empty, Queue
from threading import Thread
from typing import Any, Literal, Protocol, cast

import anyio
import numpy as np
import torch  # type: ignore
from torch import Tensor  # type: ignore
from transformers import (  # type: ignore
    AutoModelForCausalLM,
    AutoTokenizer,
    PreTrainedTokenizerBase,
    set_seed,
)
from typing_extensions import override

from inspect_ai._util.constants import DEFAULT_MAX_TOKENS
from inspect_ai._util.content import (
    ContentAudio,
    ContentImage,
    ContentText,
    ContentVideo,
)
from inspect_ai._util.trace import trace_action
from inspect_ai.tool import ToolChoice, ToolInfo

from .._chat_message import ChatMessage, ChatMessageAssistant
from .._generate_config import GenerateConfig
from .._model import ModelAPI
from .._model_output import (
    ChatCompletionChoice,
    Logprob,
    Logprobs,
    ModelOutput,
    ModelUsage,
    TopLogprob,
)
from .util import ChatAPIHandler, HFHandler

logger = getLogger(__name__)


HF_TOKEN = "HF_TOKEN"


class HuggingFaceAPI(ModelAPI):
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
            api_key_vars=[HF_TOKEN],
            config=config,
        )

        # set random seeds
        if config.seed is not None:
            set_random_seeds(config.seed)

        # collect known model_args (then delete them so we can pass the rest on)
        def collect_model_arg(name: str) -> Any | None:
            nonlocal model_args
            value = model_args.get(name, None)
            if value is not None:
                model_args.pop(name)
            return value

        device = collect_model_arg("device")
        tokenizer = collect_model_arg("tokenizer")
        model_path = collect_model_arg("model_path")
        tokenizer_path = collect_model_arg("tokenizer_path")
        self.batch_size = collect_model_arg("batch_size")
        self.chat_template = collect_model_arg("chat_template")
        self.tokenizer_call_args = collect_model_arg("tokenizer_call_args")
        self.enable_thinking = collect_model_arg("enable_thinking")
        if self.tokenizer_call_args is None:
            self.tokenizer_call_args = {}

        # device
        if device:
            self.device = device
        elif torch.backends.mps.is_available():
            self.device = "mps"
        elif torch.cuda.is_available():
            self.device = "cuda:0"
        else:
            self.device = "cpu"

        # model
        if model_path:
            self.model = AutoModelForCausalLM.from_pretrained(
                model_path, device_map=self.device, token=self.api_key, **model_args
            )
        else:
            self.model = AutoModelForCausalLM.from_pretrained(
                model_name, device_map=self.device, token=self.api_key, **model_args
            )

        # tokenizer
        if tokenizer:
            self.tokenizer = AutoTokenizer.from_pretrained(tokenizer)
        elif model_path:
            if tokenizer_path:
                self.tokenizer = AutoTokenizer.from_pretrained(tokenizer_path)
            else:
                self.tokenizer = AutoTokenizer.from_pretrained(model_path)
        else:
            self.tokenizer = AutoTokenizer.from_pretrained(model_name)
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
        # create handler
        handler: ChatAPIHandler | None = (
            HFHandler(self.model_name) if len(tools) > 0 else None
        )

        # create chat
        chat = self.hf_chat(input, tools)

        assert isinstance(self.tokenizer_call_args, dict)
        # prepare tokenizer
        tokenizer = functools.partial(
            self.tokenizer,
            return_tensors="pt",
            padding=True,
            **self.tokenizer_call_args,
        )

        # prepare generator
        kwargs: dict[str, Any] = dict(do_sample=True)
        if config.max_tokens is not None:
            kwargs["max_new_tokens"] = config.max_tokens
        if config.temperature is not None:
            kwargs["temperature"] = config.temperature
        if config.top_p is not None:
            kwargs["top_p"] = config.top_p
        if config.top_k is not None:
            kwargs["top_k"] = config.top_k
        if config.logprobs is not None:
            kwargs["output_logits"] = config.logprobs
        if "return_dict_in_generate" in kwargs:
            assert kwargs["return_dict_in_generate"]
        if config.stop_seqs is not None:
            from transformers.generation import StopStringCriteria  # type: ignore

            stopping_criteria = [StopStringCriteria(self.tokenizer, config.stop_seqs)]
            kwargs["stopping_criteria"] = stopping_criteria

        kwargs["return_dict_in_generate"] = True
        generator = functools.partial(self.model.generate, **kwargs)

        # prepare decoder
        decoder = functools.partial(
            self.tokenizer.batch_decode,
            skip_special_tokens=True,
            clean_up_tokenization_spaces=False,
        )

        # generate (uses a queue to batch so we await)
        response = await batched_generate(
            GenerateInput(
                input=chat,
                device=self.model.device,
                tokenizer=tokenizer,
                generator=generator,
                decoder=decoder,
                batch_size=config.max_connections or self.max_connections(),
            )
        )

        # gather logprobs
        final_logprobs = None
        if config.logprobs is not None:
            final_logprobs = extract_logprobs(
                response=response,
                top=config.top_logprobs,
                tokenizer=self.tokenizer,
            )

        # construct choice
        choice = ChatCompletionChoice(
            message=ChatMessageAssistant(
                content=response.output, model=self.model_name, source="generate"
            ),
            logprobs=(
                Logprobs(content=final_logprobs) if final_logprobs is not None else None
            ),
        )

        choice = ChatCompletionChoice(
            message=chat_completion_assistant_message(
                response, tools, handler, self.model_name
            ),
            logprobs=(
                Logprobs(content=final_logprobs) if final_logprobs is not None else None
            ),
        )

        # return output
        return ModelOutput(
            model=self.model_name,
            choices=[choice],
            usage=ModelUsage(
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                total_tokens=response.total_tokens,
            ),
            time=response.time,
        )

    @override
    def max_tokens(self) -> int | None:
        """Default is 16, bump it up to a value suitable for evals."""
        return DEFAULT_MAX_TOKENS

    @override
    def max_connections(self) -> int:
        """Effectively the batch size."""
        return 32

    @override
    def collapse_user_messages(self) -> bool:
        return True

    def hf_chat(self, messages: list[ChatMessage], tools: list[ToolInfo]) -> str:
        # convert to hf format
        tools_list = []
        hf_messages = copy.deepcopy(messages)
        if len(tools) > 0:
            tools_list = [
                json.loads(tool.model_dump_json(exclude_none=True, indent=2))
                for tool in tools
            ]
            if "mistral" in self.model_name.lower():
                hf_messages = shorten_tool_id(hf_messages)
                tools_list = tools_to_mistral_format(tools_list)
            elif "qwen" in self.model_name.lower():
                hf_messages = inspect_tools_to_string(hf_messages)

        hf_messages = message_content_to_string(hf_messages)
        # apply chat template
        if self.tokenizer.chat_template is not None:
            chat = self.tokenizer.apply_chat_template(
                hf_messages,
                add_generation_prompt=True,
                tokenize=False,
                tools=tools_list if len(tools_list) > 0 else None,
                enable_thinking=self.enable_thinking,  # not all models use this, check if it is supported
            )
        else:
            chat = ""
            for message in hf_messages:
                chat += f"{message.role}: {message.content}\n"
        # return
        return cast(str, chat)


def message_content_to_string(messages: list[ChatMessage]) -> list[ChatMessage]:
    """Convert list of content in `ChatMessageAssistant`, `ChatMessageUser` or `ChatMessageSystem` to a string."""
    for message in messages:
        if isinstance(message.content, list):
            is_multimodal = any(
                isinstance(item, ContentAudio | ContentImage | ContentVideo)
                for item in message.content
            )
            if is_multimodal:
                raise NotImplementedError(
                    "HuggingFace provider does not support multimodal content, please provide text inputs only."
                )
            message.content = message.text
    return messages


def shorten_tool_id(messages: list[ChatMessage]) -> list[ChatMessage]:
    """Shorten the tool_call_id in the messages to the last 9 characters for Mistral."""
    for i, message in enumerate(messages):
        if message.role == "tool":
            # Trim tool_call_id in tool messages
            if message.tool_call_id is not None:
                message.tool_call_id = message.tool_call_id[-9:]
        elif message.role == "assistant" and hasattr(message, "tool_calls"):
            # Trim tool_call IDs inside tool_calls for assistant messages
            for tool_call in message.tool_calls or []:
                tool_call.id = tool_call.id[-9:]
    return messages


def tools_to_mistral_format(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert tools to the format required for Mistral."""
    mistral_tools = []
    for tool in tools:
        mistral_tools.append(
            {
                "function": {
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": {
                        "type": tool["parameters"]["type"],
                        "properties": tool["parameters"]["properties"],
                        "required": tool["parameters"]["required"],
                    },
                }
            }
        )
    return mistral_tools


def inspect_tools_to_string(messages: list[ChatMessage]) -> list[ChatMessage]:
    """Convert tools to a string for Qwen."""
    for message in messages:
        if message.role == "assistant":
            # check if the message contains a tool call
            tool_content = ""
            if message.tool_calls:
                for tool_call in message.tool_calls:
                    tool_content += f'\n```json\n{{"name": "{tool_call.function}", "arguments": {json.dumps(tool_call.arguments)}}}\n```'
            # remove the tool call from the message
            message.tool_calls = None
            if isinstance(message.content, str):
                message.content += tool_content
            else:
                message.content.append(ContentText(text=tool_content))
    return messages


def chat_completion_assistant_message(
    response: Any,
    tools: list[ToolInfo],
    handler: ChatAPIHandler | None,
    model_name: str,
) -> ChatMessageAssistant:
    if handler:
        return handler.parse_assistant_response(response.output, tools)
    else:
        return ChatMessageAssistant(
            content=response.output, model=model_name, source="generate"
        )


def set_random_seeds(seed: int | None = None) -> None:
    if seed is None:
        seed = np.random.default_rng().integers(2**32 - 1)  # type: ignore
    # python hash seed
    os.environ["PYTHONHASHSEED"] = str(seed)
    # transformers seed
    set_seed(seed)


# return value from generate as a result of specifying return_dict_in_generate
class ModelGenerateOutput:
    sequences: Tensor
    logits: tuple[Tensor]


class Tokenizer(Protocol):
    def __call__(
        self, input: list[str]
    ) -> dict[Literal["input_ids", "attention_mask"], Tensor]: ...


class Generator(Protocol):
    def __call__(self, input_ids: Tensor, attention_mask: Tensor) -> Tensor: ...


class Decoder(Protocol):
    def __call__(self, sequences: Tensor) -> list[str]: ...


@dataclass
class GenerateInput:
    input: str
    device: str
    tokenizer: Tokenizer
    generator: Generator
    decoder: Decoder
    batch_size: int


@dataclass
class GenerateOutput:
    output: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    logprobs: torch.Tensor | None
    time: float


@dataclass
class _QueueItem:
    input: GenerateInput
    future: Future[GenerateOutput]


batch_thread: Thread | None = None

batch_queue: "Queue[_QueueItem]" = Queue()


async def batched_generate(input: GenerateInput) -> GenerateOutput:
    # start the background thread if necessary
    global batch_thread
    if batch_thread is None:
        batch_thread = Thread(target=process_batches, daemon=True)
        batch_thread.start()

    # enqueue the job
    future = Future[GenerateOutput]()
    batch_queue.put(_QueueItem(input=input, future=future))

    # await the future
    with trace_action(logger, "HF Batched Generate", "HF Batched Generate"):
        while True:
            try:
                return future.result(timeout=0.01)
            except concurrent.futures.TimeoutError:
                pass
            await anyio.sleep(1)


def process_batches() -> None:
    while True:
        # drain the queue (wait until no new messages have shown up for 2 seconds)
        inputs: list[tuple[GenerateInput, Future[GenerateOutput]]] = []
        while True:
            try:
                input = batch_queue.get(timeout=2)
                inputs.append((input.input, input.future))
                if len(inputs) == input.input.batch_size:
                    # max batch size reached
                    break
            except Empty:
                # we have exhausted the queue
                break

        # see if we have any work to do
        if len(inputs) == 0:
            continue

        try:
            # capture the generator and decoder functions
            start_time = time.monotonic()
            first_input = inputs[0][0]
            device = first_input.device
            tokenizer = first_input.tokenizer
            generator = first_input.generator
            decoder = first_input.decoder

            # tokenize and move to device
            tokenized_inputs = tokenizer([item[0].input for item in inputs])
            input_ids = tokenized_inputs["input_ids"]
            attention_mask = tokenized_inputs["attention_mask"]
            input_ids = input_ids.to(device)
            attention_mask = attention_mask.to(device)

            # generate
            with torch.inference_mode():
                generation_outputs = cast(
                    ModelGenerateOutput,
                    generator(input_ids=input_ids, attention_mask=attention_mask),
                )
                generate_ids = generation_outputs.sequences
                logits = generation_outputs.logits

            # get logprobs from logits
            logprobs = None
            if logits is not None:
                stacked_logits = torch.stack(logits).transpose(0, 1)
                logprobs = torch.nn.functional.log_softmax(stacked_logits, dim=-1)

            # decode
            generated_tokens = generate_ids[:, input_ids.size(dim=1) :]
            if logprobs is not None:
                assert logprobs.shape[1] == generated_tokens.shape[1]
            outputs = decoder(sequences=generated_tokens)

            # call back futures
            total_time = time.monotonic() - start_time
            for i, output in enumerate(outputs):
                future = inputs[i][1]
                input_tokens = input_ids.size(dim=1)
                output_tokens = generate_ids.size(dim=1) - input_ids.size(dim=1)

                # asyncio futures are not thread safe, so we need to pass the event loop
                # down to this point, so we can mark the future as done in a thread safe manner.
                # see: https://docs.python.org/3/library/asyncio-dev.html#concurrency-and-multithreading
                future.set_result(
                    GenerateOutput(
                        output=output,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        total_tokens=input_tokens + output_tokens,
                        logprobs=logprobs[i] if logprobs is not None else None,
                        time=total_time,
                    )
                )

        except Exception as ex:
            for inp in inputs:
                future = inp[1]
                future.set_exception(ex)


def extract_logprobs(
    response: GenerateOutput,
    top: int | None,
    tokenizer: PreTrainedTokenizerBase,
) -> list[Logprob]:
    assert response.logprobs is not None
    k = top or 1
    topk_values, topk_inds = response.logprobs.topk(k=k, dim=-1)
    final_logprobs = []
    for toks, vals in zip(topk_inds, topk_values):
        top_logprobs: list[TopLogprob] = []
        for tok, val in zip(toks, vals):
            # TODO: you get byte artifacts converting single ids to tokens like this...
            # but `tokenizer.decode` strips spaces. There must be a better way to do this.
            token_str = tokenizer.convert_ids_to_tokens(tok.item())
            top_logprobs.append(
                TopLogprob(
                    token=token_str,
                    logprob=val,
                    bytes=list(map(ord, token_str)),
                )
            )
        final_logprobs.append(
            Logprob(
                token=top_logprobs[0].token,
                logprob=top_logprobs[0].logprob,
                bytes=top_logprobs[0].bytes,
                top_logprobs=top_logprobs,
            )
        )
    return final_logprobs
