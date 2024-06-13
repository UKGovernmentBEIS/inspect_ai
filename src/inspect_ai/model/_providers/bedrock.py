import abc
import asyncio
import json
from typing import Any, cast

from typing_extensions import override

from inspect_ai._util.constants import (
    DEFAULT_MAX_RETRIES,
    DEFAULT_MAX_TOKENS,
    DEFAULT_TIMEOUT,
)
from inspect_ai._util.error import pip_dependency_error
from inspect_ai._util.version import verify_required_version

from .._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
)
from .._generate_config import GenerateConfig
from .._model import ModelAPI, simple_input_messages
from .._model_output import ChatCompletionChoice, ModelOutput, ModelUsage
from .._tool import ToolChoice, ToolInfo
from .util import as_stop_reason, model_base_url


class BedrockAPI(ModelAPI):
    def __init__(
        self,
        model_name: str,
        base_url: str | None,
        config: GenerateConfig = GenerateConfig(),
        **model_args: Any,
    ):
        super().__init__(model_name=model_name, base_url=base_url, config=config)

        # we can optionally proxy to another ModelAPI
        self.model_api: ModelAPI | None = None

        base_url = model_base_url(base_url, "BEDROCK_BASE_URL")

        # delegate to AnthropicAPI for anthropic models
        if is_anthropic(model_name):
            from .anthropic import AnthropicAPI

            self.model_api = AnthropicAPI(
                model_name=model_name,
                base_url=base_url,
                config=config,
                bedrock=True,
                **model_args,
            )
        elif is_mistral(model_name):
            self.handler: BedrockChatHandler = MistralChatHandler(
                model_name, base_url, config
            )
        elif is_llama(model_name):
            self.handler = Llama2ChatHandler(model_name, base_url, config)
        else:
            raise ValueError(f"Unsupported Bedrock model: {model_name}")

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput:
        if self.model_api:
            return await self.model_api.generate(input, tools, tool_choice, config)
        else:
            return await self.handler.generate(input, config)

    @override
    def max_tokens(self) -> int | None:
        if self.model_api:
            return self.model_api.max_tokens()
        else:
            return self.handler.max_tokens()

    @override
    def connection_key(self) -> str:
        return self.model_name

    @override
    def is_rate_limit(self, ex: BaseException) -> bool:
        if self.model_api:
            return self.model_api.is_rate_limit(ex)
        else:
            return self.handler.is_rate_limit(ex)

    @override
    def collapse_user_messages(self) -> bool:
        if self.model_api:
            return self.model_api.collapse_user_messages()
        else:
            return super().collapse_user_messages()


# https://docs.aws.amazon.com/bedrock/latest/userguide/inference-invoke.html
class BedrockChatHandler(abc.ABC):
    def __init__(
        self, model_name: str, base_url: str | None, config: GenerateConfig
    ) -> None:
        # import boto3 on demand
        try:
            import boto3
            from botocore.config import Config

            verify_required_version("Bedrock API", "boto3", "1.34.0")

            self.model_name = model_name
            self.client = boto3.client(
                service_name="bedrock-runtime",
                endpoint_url=base_url,
                config=Config(
                    connect_timeout=(
                        config.timeout if config.timeout else DEFAULT_TIMEOUT
                    ),
                    read_timeout=config.timeout if config.timeout else DEFAULT_TIMEOUT,
                    retries=dict(
                        max_attempts=(
                            config.max_retries
                            if config.max_retries
                            else DEFAULT_MAX_RETRIES
                        ),
                        mode="adaptive",
                    ),
                ),
            )
        except ImportError:
            raise pip_dependency_error("Bedrock API", ["boto3"])

    async def generate(
        self, input: list[ChatMessage], config: GenerateConfig
    ) -> ModelOutput:
        # convert to compatible message list (no system, no consec user, etc.)
        input = simple_input_messages(input, self.fold_system_message)

        # create the body
        body = self.request_body(input, config)
        if config.temperature is not None:
            body["temperature"] = config.temperature
        if config.top_p is not None:
            body["top_p"] = config.top_p

        # run this in a background thread
        async def invoke_model() -> Any:
            return self.client.invoke_model(
                body=json.dumps(body),
                modelId=self.model_name,
                accept="application/json",
                contentType="application/json",
            )

        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(None, invoke_model)
        response_body = json.loads((await response).get("body").read())

        choice = self.completion_choice(response_body)

        return ModelOutput(
            model=self.model_name,
            choices=[choice],
            usage=self.model_usage(response_body),
        )

    def is_rate_limit(self, ex: BaseException) -> bool:
        from boto3.exceptions import RetriesExceededError
        from botocore.exceptions import ClientError

        if isinstance(ex, ClientError):
            if ex.response["Error"]["Code"] == "LimitExceededException":
                return True
        elif isinstance(ex, RetriesExceededError):
            return True

        return False

    @abc.abstractmethod
    def request_body(
        self,
        input: list[ChatMessage],
        config: GenerateConfig,
    ) -> dict[str, Any]: ...

    @abc.abstractmethod
    def completion_choice(self, response: dict[str, Any]) -> ChatCompletionChoice: ...

    # optional hook to provide a system message folding template
    def fold_system_message(self, user: str, system: str) -> str:
        return f"{system}\n\n{user}"

    # optional hook to extract model usage
    def model_usage(self, response: dict[str, Any]) -> ModelUsage | None:
        return None

    # optional hook to set max_tokens
    def max_tokens(self) -> int | None:
        return DEFAULT_MAX_TOKENS


# https://docs.aws.amazon.com/bedrock/latest/userguide/model-parameters-mistral.html
class MistralChatHandler(BedrockChatHandler):
    @override
    def request_body(
        self,
        input: list[ChatMessage],
        config: GenerateConfig,
    ) -> dict[str, Any]:
        # https://docs.mistral.ai/models/#chat-template
        # https://community.aws/content/2dFNOnLVQRhyrOrMsloofnW0ckZ/how-to-prompt-mistral-ai-models-and-why

        # build prompt
        prompt = "<s>" + " ".join([self.chat_message_str(message) for message in input])

        body: dict[str, Any] = dict(prompt=remove_end_token(prompt))
        if config.stop_seqs is not None:
            body["stop"] = config.stop_seqs
        if config.max_tokens is not None:
            body["max_tokens"] = config.max_tokens
        if config.top_k is not None:
            body["top_k"] = config.top_k

        return body

    @override
    def completion_choice(self, response: dict[str, Any]) -> ChatCompletionChoice:
        outputs: list[dict[str, str]] = response.get("outputs", [])
        return ChatCompletionChoice(
            message=ChatMessageAssistant(
                content="\n".join([output.get("text", "") for output in outputs]),
                source="generate",
            ),
            stop_reason=as_stop_reason(response.get("stop_reason")),
        )

    def chat_message_str(self, message: ChatMessage) -> str:
        if isinstance(message, ChatMessageUser | ChatMessageSystem):
            return f"[INST] {message.text} [/INST] "
        elif isinstance(message, ChatMessageAssistant):
            return f"{message.text}</s>"
        elif isinstance(message, ChatMessageTool):
            return ""


# https://docs.aws.amazon.com/bedrock/latest/userguide/model-parameters-meta.html
class Llama2ChatHandler(BedrockChatHandler):
    @override
    def request_body(
        self,
        input: list[ChatMessage],
        config: GenerateConfig,
    ) -> dict[str, Any]:
        # https://huggingface.co/blog/llama2#how-to-prompt-llama-2

        prompt = " ".join([self.chat_message_str(message) for message in input])
        body: dict[str, Any] = dict(prompt=remove_end_token(prompt))
        if config.max_tokens:
            body["max_gen_len"] = config.max_tokens
        return body

    @override
    def completion_choice(self, response: dict[str, Any]) -> ChatCompletionChoice:
        return ChatCompletionChoice(
            message=ChatMessageAssistant(
                content=response.get("generation", ""),
                source="generate",
            ),
            stop_reason=as_stop_reason(response.get("stop_reason")),
        )

    @override
    def fold_system_message(self, user: str, system: str) -> str:
        return f"<SYS>\n{system}\n<</SYS>\n\n{user}"

    @override
    def model_usage(self, response: dict[str, Any]) -> ModelUsage | None:
        input_tokens = cast(int, response.get("prompt_token_count", 0))
        output_tokens = cast(int, response.get("generation_token_count", 0))
        if input_tokens or output_tokens:
            return ModelUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
            )
        else:
            return None

    def chat_message_str(self, message: ChatMessage) -> str:
        if isinstance(message, ChatMessageUser | ChatMessageSystem):
            return f"<s>[INST] {message.text} [/INST] "
        elif isinstance(message, ChatMessageAssistant):
            return f"{message.text} </s>"
        elif isinstance(message, ChatMessageTool):
            return ""


def is_anthropic(model_name: str) -> bool:
    return model_name.startswith("anthropic.")


def is_mistral(model_name: str) -> bool:
    return model_name.startswith("mistral.")


def is_llama(model_name: str) -> bool:
    return model_name.startswith("meta.llama")


def remove_end_token(prompt: str) -> str:
    # pull off </s> at end so putting words in mouth is supported
    end_token = "</s>"
    if prompt.endswith(end_token):
        index = prompt.rfind(end_token)
        prompt = prompt[:index]
    return prompt
