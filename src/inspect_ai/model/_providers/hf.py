import asyncio
import functools
import os
from dataclasses import dataclass
from queue import Empty, Queue
from threading import Thread
from typing import Any, Literal, Protocol, cast

import numpy as np
import torch
from torch import Tensor
from transformers import AutoModelForCausalLM, AutoTokenizer, set_seed  # type: ignore
from typing_extensions import override

from inspect_ai._util.constants import DEFAULT_MAX_TOKENS

from .._model import (
    ChatCompletionChoice,
    ChatMessage,
    ChatMessageAssistant,
    GenerateConfig,
    ModelAPI,
    ModelOutput,
    ModelUsage,
    simple_input_messages,
)
from .._tool import ToolChoice, ToolInfo
from .._util import chat_api_input


class HuggingFaceAPI(ModelAPI):
    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        config: GenerateConfig = GenerateConfig(),
        **model_args: Any,
    ):
        super().__init__(model_name=model_name, base_url=base_url, config=config)

        # set random seeds
        if config.seed is not None:
            set_random_seeds(config.seed)

        # collect known model_args (then delete them so we can pass the rest on)
        def collect_model_arg(name: str) -> Any | None:
            nonlocal model_args
            value = model_args.get(name, None)
            if value:
                model_args.pop(name)
            return value

        device = collect_model_arg("device")
        tokenizer = collect_model_arg("tokenizer")
        model_path = collect_model_arg("model_path")
        tokenizer_path = collect_model_arg("tokenizer_path")
        self.batch_size = collect_model_arg("batch_size")

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
                model_path, device_map=self.device, **model_args
            )
        else:
            self.model = AutoModelForCausalLM.from_pretrained(
                model_name, device_map=self.device, **model_args
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

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput:
        # create chat
        chat = self.hf_chat(input)

        # prepare tokenizer
        tokenizer = functools.partial(self.tokenizer, return_tensors="pt", padding=True)

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
                device=self.device,
                tokenizer=tokenizer,
                generator=generator,
                decoder=decoder,
            )
        )

        # construct choice
        choice = ChatCompletionChoice(
            message=ChatMessageAssistant(content=response.output, source="generate")
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
        )

    @override
    def max_tokens(self) -> int | None:
        """Default is 16, bump it up to a value suitable for evals."""
        return DEFAULT_MAX_TOKENS

    @override
    def max_connections(self) -> int:
        """Effectively the batch size."""
        return 32

    def hf_chat(self, messages: list[ChatMessage]) -> str:
        # handle system message and consecutive user messages
        messages = simple_input_messages(messages)
        # convert to hf format
        hf_messages = chat_api_input(messages)
        # apply chat template
        chat = self.tokenizer.apply_chat_template(
            hf_messages, add_generation_prompt=True, tokenize=False
        )

        # return
        return cast(str, chat)


def set_random_seeds(seed: int | None = None) -> None:
    if seed is None:
        seed = np.random.default_rng().integers(2**32 - 1)
    # python hash seed
    os.environ["PYTHONHASHSEED"] = str(seed)
    # transformers seed
    set_seed(seed)


class Tokenizer(Protocol):
    def __call__(self, input: list[str]) -> dict[Literal["input_ids"], Tensor]:
        ...


class Generator(Protocol):
    def __call__(self, input_ids: Tensor) -> Tensor:
        ...


class Decoder(Protocol):
    def __call__(self, sequences: Tensor) -> list[str]:
        ...


@dataclass
class GenerateInput:
    input: str
    device: str
    tokenizer: Tokenizer
    generator: Generator
    decoder: Decoder


@dataclass
class GenerateOutput:
    output: str
    input_tokens: int
    output_tokens: int
    total_tokens: int


batch_thread: Thread | None = None

batch_queue: "Queue[tuple[GenerateInput, asyncio.Future[GenerateOutput]]]" = Queue()


async def batched_generate(input: GenerateInput) -> GenerateOutput:
    # start the background thread if necessary
    global batch_thread
    if batch_thread is None:
        batch_thread = Thread(target=process_batches, daemon=True)
        batch_thread.start()

    # enque the job
    loop = asyncio.get_event_loop()
    future: asyncio.Future[GenerateOutput] = loop.create_future()
    batch_queue.put((input, future))

    # await the job
    await future

    # return it
    return future.result()


def process_batches() -> None:
    while True:
        # drain the queue (wait until no new messages have shown up for 2 secones)
        inputs: list[tuple[GenerateInput, asyncio.Future[GenerateOutput]]] = []
        while True:
            try:
                input = batch_queue.get(timeout=2)
                inputs.append(input)
            except Empty:
                break

        # see if we have any work to do
        if len(inputs) == 0:
            continue

        try:
            # capture the generator and decoder functions
            first_input = inputs[0][0]
            device = first_input.device
            tokenizer = first_input.tokenizer
            generator = first_input.generator
            decoder = first_input.decoder

            # tokenize and move to device
            input_ids = tokenizer([item[0].input for item in inputs])["input_ids"]
            input_ids = input_ids.to(device)

            # generate
            with torch.inference_mode():
                generate_ids = generator(input_ids=input_ids)

            # decode
            outputs = decoder(sequences=generate_ids[:, input_ids.size(dim=1) :])

            # call back futures
            for i, output in enumerate(outputs):
                future = inputs[i][1]
                input_tokens = input_ids.size(dim=1)
                output_tokens = generate_ids.size(dim=1) - input_ids.size(dim=1)
                future.set_result(
                    GenerateOutput(
                        output=output,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        total_tokens=input_tokens + output_tokens,
                    )
                )
        except Exception as ex:
            for input in inputs:
                future = input[1]
                future.set_exception(ex)
