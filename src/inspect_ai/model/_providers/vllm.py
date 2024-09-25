import asyncio
import functools
import os
from dataclasses import dataclass
from queue import Empty, Queue
from threading import Thread
from typing import Any, cast

from typing_extensions import override
from vllm import LLM, CompletionOutput, RequestOutput, SamplingParams  # type: ignore

from inspect_ai._util.constants import DEFAULT_MAX_TOKENS
from inspect_ai.tool import ToolChoice, ToolInfo

from .._chat_message import ChatMessage, ChatMessageAssistant
from .._generate_config import GenerateConfig
from .._model import ModelAPI, simple_input_messages
from .._model_output import (
    ChatCompletionChoice,
    Logprob,
    Logprobs,
    ModelOutput,
    ModelUsage,
    StopReason,
    TopLogprob,
)
from .util import chat_api_input

DEFAULT_START_TOKEN = "<|im_start|>"
DEFAULT_END_TOKEN = "<|im_end|>"

HF_TOKEN = "HF_TOKEN"


@dataclass
class GenerateInput:
    input: str
    generator: Any
    batch_size: int
    num_top_logprobs: int | None = None


@dataclass
class GenerateOutput:
    output: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    stop_reason: StopReason
    logprobs: Logprobs | None = None


class VLLMAPI(ModelAPI):
    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        config: GenerateConfig = GenerateConfig(),
        **model_args: Any,
    ) -> None:
        super().__init__(
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            api_key_vars=[HF_TOKEN],
            config=config,
        )

        self.seed = None
        if config.seed is not None:
            self.seed = config.seed

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
        self.chat_template = collect_model_arg("chat_template")

        # if user provides model_path, use that instead of model_name
        if model_path:
            model_name = model_path

        # load tokenizer
        if not tokenizer:
            if tokenizer_path:
                tokenizer = tokenizer_path
            else:
                tokenizer = model_name

        # set which GPUs are available to use
        if device is not None:
            os.environ["CUDA_VISIBLE_DEVICES"] = str(device)

        # tell vllm how many GPUs to use
        if "tensor_parallel_size" not in model_args:
            devices = os.environ.get("CUDA_VISIBLE_DEVICES", "").split(",")
            num_devices = len(devices)
            if num_devices > 1:
                model_args["tensor_parallel_size"] = num_devices
            else:
                model_args["tensor_parallel_size"] = 1

        # https://github.com/vllm-project/vllm/pull/6051
        # Gemma 2 models require FlashInfer backend for softcap logits
        if "google/gemma-2" in model_name:
            os.environ["VLLM_ATTENTION_BACKEND"] = "FLASHINFER"
            try:
                import importlib

                # check if flashinfer is installed
                importlib.import_module("flashinfer")
            except ImportError:
                raise ImportError(
                    "To use the 'google/gemma-2' model, you must install the 'flashinfer' package. "
                    "See https://docs.flashinfer.ai/installation.html"
                )

        # load model
        self.model = LLM(model_name, tokenizer=tokenizer, **model_args)

        # we get the tokenizer so we can use it to apply the model's chat template later
        self.tokenizer = self.model.get_tokenizer()

    def apply_chat_template(
        self, messages: list[ChatMessage], tools: list[ToolInfo]
    ) -> str:
        # handle system message and consecutive user messages
        messages = simple_input_messages(messages)
        # convert to chat template input format
        chat_messages = chat_api_input(messages, tools)
        # apply chat template
        chat = self.tokenizer.apply_chat_template(
            chat_messages,
            add_generation_prompt=True,
            tokenize=False,
            chat_template=self.chat_template,
        )
        return cast(str, chat)

    @override
    def max_connections(self) -> int:
        """Effectively the batch size."""
        return 32

    def get_sampling_params(self, config: GenerateConfig, chat: str) -> SamplingParams:
        kwargs: dict[str, Any] = dict()
        if config.max_tokens is not None:
            kwargs["max_tokens"] = config.max_tokens
        else:
            kwargs["max_tokens"] = DEFAULT_MAX_TOKENS

        if config.temperature is not None:
            # for some reason vllm doesn't generate anything for 0 < temperature < 0.02
            if 0 < config.temperature < 0.02:
                config.temperature = 0.02
            kwargs["temperature"] = config.temperature
        if config.top_p is not None:
            kwargs["top_p"] = config.top_p
        if config.top_k is not None:
            kwargs["top_k"] = config.top_k
        # if config.min_p is not None:
        #     kwargs["min_p"] = config.min_p
        if config.seed is not None:
            kwargs["seed"] = config.seed
        elif self.seed is not None:
            kwargs["seed"] = self.seed

        if config.frequency_penalty is not None:
            kwargs["frequency_penalty"] = config.frequency_penalty
        if config.presence_penalty is not None:
            kwargs["presence_penalty"] = config.presence_penalty

        if config.num_choices is not None:
            kwargs["n"] = config.num_choices
        if config.best_of is not None:
            kwargs["best_of"] = config.best_of

        if config.logprobs is not None:
            kwargs["logprobs"] = 0
        if config.top_logprobs is not None:
            kwargs["logprobs"] = config.top_logprobs

        if config.stop_seqs is not None:
            kwargs["stop"] = config.stop_seqs

        # some models don't stop at <|im_end|> token
        # perhaps there is a better solution than this (modify tokenizer?)
        # TODO: what model needs this?
        if chat.startswith(DEFAULT_START_TOKEN):
            if "stop" not in kwargs:
                kwargs["stop"] = [DEFAULT_END_TOKEN]
            else:
                kwargs["stop"].append(DEFAULT_END_TOKEN)

        sampling_params = SamplingParams(
            **kwargs,
            stop_token_ids=self.tokenizer.all_special_ids,  # We default to stopping at all special tokens
            include_stop_str_in_output=False,
        )
        return sampling_params

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput:
        chat = self.apply_chat_template(input, tools)

        # prepare generator
        sampling_params = self.get_sampling_params(config, chat)
        generator = functools.partial(
            self.model.generate, sampling_params=sampling_params, use_tqdm=False
        )

        # generate
        responses = await batched_generate(
            GenerateInput(
                input=chat,
                generator=generator,
                batch_size=config.max_connections or self.max_connections(),
                num_top_logprobs=config.top_logprobs,
            )
        )

        return self.process_responses(responses, tools)

    def process_responses(
        self, responses: list[GenerateOutput], tools: list[ToolInfo]
    ) -> ModelOutput:
        choices = [
            ChatCompletionChoice(
                message=ChatMessageAssistant(
                    content=response.output, source="generate"
                ),
                stop_reason=response.stop_reason,
                logprobs=response.logprobs,
            )
            for response in responses
        ]

        # TODO: what's the best way to calculate token usage for num_choices > 1
        input_tokens = responses[0].input_tokens
        output_tokens = sum(response.output_tokens for response in responses)
        total_tokens = input_tokens + output_tokens

        return ModelOutput(
            model=self.model_name,
            choices=choices,
            usage=ModelUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
            ),
        )


@dataclass
class _QueueItem:
    input: GenerateInput
    future: asyncio.Future[list[GenerateOutput]]
    loop: asyncio.AbstractEventLoop


batch_thread: Thread | None = None

batch_queue: "Queue[_QueueItem]" = Queue()


async def batched_generate(input: GenerateInput) -> list[GenerateOutput]:
    # start the background thread if necessary
    global batch_thread
    if batch_thread is None:
        batch_thread = Thread(target=process_batches, daemon=True)
        batch_thread.start()

    # enqueue the job
    loop = asyncio.get_event_loop()
    future: asyncio.Future[list[GenerateOutput]] = loop.create_future()
    batch_queue.put(_QueueItem(input=input, future=future, loop=loop))

    # await the job
    await future

    # return it
    return future.result()


def string_to_bytes(string: str) -> list[int]:
    return list(map(ord, string))


def extract_logprobs(
    completion: CompletionOutput, num_top_logprobs: int | None
) -> Logprobs | None:
    if completion.logprobs is None or not completion.logprobs:
        return None

    # if config.logprobs = True, we want to get the selected tokens logprob
    # but if config.top_logprobs is not set, we don't want to return the top logprobs
    if num_top_logprobs is None:
        num_top_logprobs = 0

    logprobs = []
    for token_id, logprob in zip(completion.token_ids, completion.logprobs):
        top_logprobs = [
            TopLogprob(
                token=cast(str, token.decoded_token),
                logprob=token.logprob,
                bytes=string_to_bytes(cast(str, token.decoded_token)),
            )
            # exclude the chosen token if it's not in the top logprobs
            for token in logprob.values()
            if cast(int, token.rank) - 1 < num_top_logprobs
        ]
        selected_token = logprob[token_id]
        logprobs.append(
            Logprob(
                token=cast(str, selected_token.decoded_token),
                logprob=selected_token.logprob,
                bytes=string_to_bytes(cast(str, selected_token.decoded_token)),
                top_logprobs=top_logprobs,
            )
        )

    return Logprobs(content=logprobs)


def get_stop_reason(finish_reason: str | None) -> StopReason:
    if finish_reason == "stop":
        return "stop"
    elif finish_reason == "length":
        return "max_tokens"
    elif finish_reason == "abort":
        return "unknown"
    else:
        return "unknown"


def post_process_output(
    output: RequestOutput, i: int, num_top_logprobs: int | None
) -> GenerateOutput:
    completion = output.outputs[i]
    output_text: str = completion.text

    # # remove end token if it's there (byproduct of default chat template)
    # TODO: Remove
    # if output_text.endswith(DEFAULT_END_TOKEN):
    #     output_text = output_text[:len(DEFAULT_END_TOKEN)]

    input_tokens = len(output.prompt_token_ids)
    output_tokens = len(completion.token_ids)
    total_tokens = input_tokens + output_tokens

    return GenerateOutput(
        output=output_text,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        stop_reason=get_stop_reason(completion.finish_reason),
        logprobs=extract_logprobs(completion, num_top_logprobs),
    )


def post_process_outputs(
    output: RequestOutput, num_top_logprobs: int | None
) -> list[GenerateOutput]:
    return [
        post_process_output(output, i, num_top_logprobs)
        for i in range(len(output.outputs))
    ]


def process_batches() -> None:
    while True:
        # drain the queue (wait until no new messages have shown up for 2 seconds)
        inputs: list[tuple[GenerateInput, asyncio.Future[list[GenerateOutput]]]] = []
        while True:
            try:
                input = batch_queue.get(
                    timeout=2
                )  # wait 2 seconds max TODO: what's optimal wait time?
                loop = input.loop
                inputs.append((input.input, input.future))
                if len(inputs) >= input.input.batch_size:
                    # max batch size reached
                    break
            except Empty:
                # we have exhausted the queue
                break

        # see if we have any work to do
        if len(inputs) == 0:
            continue

        try:
            first_input = inputs[0][0]
            generator = first_input.generator
            num_top_logprobs = first_input.num_top_logprobs

            # generate
            outputs = generator([input[0].input for input in inputs])

            for i, output in enumerate(outputs):
                future = inputs[i][1]

                # asyncio futures are not thread safe, so we need to pass the event loop
                # down to this point, so we can mark the future as done in a thread safe manner.
                # see: https://docs.python.org/3/library/asyncio-dev.html#concurrency-and-multithreading
                loop.call_soon_threadsafe(
                    future.set_result, post_process_outputs(output, num_top_logprobs)
                )

        except Exception as e:
            for _, future in inputs:
                loop.call_soon_threadsafe(future.set_exception, e)
