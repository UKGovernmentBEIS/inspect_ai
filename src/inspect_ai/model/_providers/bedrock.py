import abc
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
from inspect_ai.tool import ToolChoice, ToolInfo

from .._chat_message import (
    ChatMessage,
)
from .._generate_config import GenerateConfig
from .._model import ModelAPI
from .._model_call import ModelCall
from .._model_output import ChatCompletionChoice, ModelOutput, ModelUsage
from .util import (
    ChatAPIHandler,
    ChatAPIMessage,
    Llama31Handler,
    as_stop_reason,
    chat_api_input,
    model_base_url,
)

ANTHROPIC_API_KEY = "ANTHROPIC_API_KEY"


class BedrockAPI(ModelAPI):
    def __init__(
        self,
        model_name: str,
        base_url: str | None,
        config: GenerateConfig = GenerateConfig(),
        **model_args: Any,
    ):
        super().__init__(
            model_name=model_name,
            base_url=base_url,
            api_key_vars=[ANTHROPIC_API_KEY],
            config=config,
        )

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
        elif is_llama2(model_name):
            self.handler = Llama2ChatHandler(model_name, base_url, config)
        elif is_llama3(model_name):
            self.handler = Llama3ChatHandler(model_name, base_url, config)
        else:
            raise ValueError(f"Unsupported Bedrock model: {model_name}")

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput | tuple[ModelOutput, ModelCall]:
        if self.model_api:
            return await self.model_api.generate(input, tools, tool_choice, config)
        else:
            return await self.handler.generate(input, tools, tool_choice, config)

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
        # import aioboto3 on demand
        try:
            import aioboto3

            verify_required_version("Bedrock API", "aioboto3", "13.0.0")

            # properties for the client
            self.model_name = model_name
            self.base_url = base_url
            self.config = config

            # Create a shared session to be used by the handler
            self.session = aioboto3.Session()

        except ImportError:
            raise pip_dependency_error("Bedrock API", ["aioboto3"])

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput | tuple[ModelOutput, ModelCall]:
        from botocore.config import Config

        formatted_input_with_tools: list[ChatAPIMessage] = chat_api_input(
            input, tools, self.chat_api_handler()
        )
        body = self.request_body(formatted_input_with_tools, config)

        if config.temperature is not None:
            body["temperature"] = config.temperature
        if config.top_p is not None:
            body["top_p"] = config.top_p

        # Use the session to create the client
        async with self.session.client(
            service_name="bedrock-runtime",
            endpoint_url=self.base_url,
            config=Config(
                connect_timeout=config.timeout if config.timeout else DEFAULT_TIMEOUT,
                read_timeout=config.timeout if config.timeout else DEFAULT_TIMEOUT,
                retries=dict(
                    max_attempts=config.max_retries
                    if config.max_retries
                    else DEFAULT_MAX_RETRIES,
                    mode="adaptive",
                ),
            ),
        ) as client:
            try:
                response = await client.invoke_model(
                    body=json.dumps(body),
                    modelId=self.model_name,
                    accept="application/json",
                    contentType="application/json",
                )
            except Exception as ex:
                return self.handle_generate_exception(ex)

            response_body = json.loads(await response["body"].read())

        choice = self.completion_choice(response_body, tools, self.chat_api_handler())
        output = ModelOutput(
            model=self.model_name,
            choices=[choice],
            usage=self.model_usage(response_body),
        )

        # record call
        call = ModelCall.create(
            request=dict(modelId=self.model_name, **body), response=response_body
        )

        # return
        return output, call

    def is_rate_limit(self, ex: BaseException) -> bool:
        from boto3.exceptions import RetriesExceededError
        from botocore.exceptions import ClientError

        if isinstance(ex, ClientError):
            if ex.response["Error"]["Code"] == "LimitExceededException":
                return True
        elif isinstance(ex, RetriesExceededError):
            return True

        return False

    def handle_generate_exception(self, ex: Exception) -> ModelOutput:
        error = str(ex)
        if "maximum context length" in error:
            # see if we can narrow down to just the error message
            content = error
            response = getattr(ex, "response", None)
            if isinstance(response, dict) and "Error" in response:
                error_dict = cast(dict[str, Any], response.get("Error"))
                content = error_dict["Message"]
            return ModelOutput.from_content(
                model=self.model_name,
                content=content,
                stop_reason="model_length",
            )
        else:
            raise ex

    @abc.abstractmethod
    def request_body(
        self,
        input: list[ChatAPIMessage],
        config: GenerateConfig,
    ) -> dict[str, Any]: ...

    @abc.abstractmethod
    def completion_choice(
        self,
        response: dict[str, Any],
        tools: list[ToolInfo],
        handler: ChatAPIHandler,
    ) -> ChatCompletionChoice: ...

    def chat_api_handler(self) -> ChatAPIHandler:
        if "llama" in self.model_name.lower():
            return Llama31Handler()
        else:
            return ChatAPIHandler()

    # optional hook to provide a system message folding template
    def fold_system_message(self, user: str, system: str) -> str:
        return f"{system}\n\n{user}"

    # optional hook to extract model usage
    def model_usage(self, response: dict[str, Any]) -> ModelUsage | None:
        return None

    # optional hook to set max_tokens
    def max_tokens(self) -> int | None:
        return DEFAULT_MAX_TOKENS

    def custom_remove_end_token(self, prompt: str) -> str:
        return remove_end_token(prompt)

    @abc.abstractmethod
    def chat_message_str(self, message: ChatAPIMessage) -> str:
        pass


# https://docs.aws.amazon.com/bedrock/latest/userguide/model-parameters-mistral.html
class MistralChatHandler(BedrockChatHandler):
    @override
    def request_body(
        self,
        input: list[ChatAPIMessage],
        config: GenerateConfig,
    ) -> dict[str, Any]:
        # https://docs.mistral.ai/models/#chat-template
        # https://community.aws/content/2dFNOnLVQRhyrOrMsloofnW0ckZ/how-to-prompt-mistral-ai-models-and-why

        # build prompt
        prompt = "<s>" + " ".join([self.chat_message_str(message) for message in input])

        body: dict[str, Any] = dict(prompt=self.custom_remove_end_token(prompt))
        if config.stop_seqs is not None:
            body["stop"] = config.stop_seqs
        if config.max_tokens is not None:
            body["max_tokens"] = config.max_tokens
        if config.top_k is not None:
            body["top_k"] = config.top_k

        return body

    @override
    def completion_choice(
        self,
        response: dict[str, Any],
        tools: list[ToolInfo],
        handler: ChatAPIHandler,
    ) -> ChatCompletionChoice:
        outputs: list[dict[str, str]] = response.get("outputs", [])
        return ChatCompletionChoice(
            message=handler.parse_assistant_response(
                response="\n".join([output.get("text", "") for output in outputs]),
                tools=tools,
            ),
            stop_reason=as_stop_reason(response.get("stop_reason")),
        )

    def chat_message_str(self, message: ChatAPIMessage) -> str:
        role = message["role"]
        content = message["content"]
        if role in ("user", "system"):
            return f"[INST] {content} [/INST] "
        elif role == "assistant":
            return f"{content}</s>"
        elif role == "tool":
            return ""
        return f"{content}"


class BaseLlamaChatHandler(BedrockChatHandler):
    @override
    def request_body(
        self,
        input: list[ChatAPIMessage],
        config: GenerateConfig,
    ) -> dict[str, Any]:
        prompt = " ".join([self.chat_message_str(message) for message in input])
        body: dict[str, Any] = dict(prompt=self.custom_remove_end_token(prompt))
        if config.max_tokens:
            body["max_gen_len"] = config.max_tokens
        return body

    @override
    def completion_choice(
        self, response: dict[str, Any], tools: list[ToolInfo], handler: ChatAPIHandler
    ) -> ChatCompletionChoice:
        return ChatCompletionChoice(
            message=handler.parse_assistant_response(
                response.get("generation", ""), tools
            ),
            stop_reason=as_stop_reason(response.get("stop_reason")),
        )

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


# https://docs.aws.amazon.com/bedrock/latest/userguide/model-parameters-meta.html
class Llama2ChatHandler(BaseLlamaChatHandler):
    @override
    def fold_system_message(self, user: str, system: str) -> str:
        return f"<SYS>\n{system}\n<</SYS>\n\n{user}"

    def chat_message_str(self, message: ChatAPIMessage) -> str:
        role = message["role"]
        content = message["content"]
        if role in ("user", "system"):
            return f"<s>[INST] {content} [/INST] "
        elif role == "assistant":
            return f"{content} </s>"
        elif role == "tool":
            return ""
        return f"{content}"


class Llama3ChatHandler(BaseLlamaChatHandler):
    @override
    def custom_remove_end_token(self, prompt: str) -> str:
        return remove_end_token(prompt, end_token="<|end_of_text|>")

    @override
    def fold_system_message(self, user: str, system: str) -> str:
        return f"<|start_header_id|>system<|end_header_id|>\n{system}\n<|eot_id|>\n<|start_header_id|>user<|end_header_id|>\n\n{user}<|eot_id|>"

    def chat_message_str(self, message: ChatAPIMessage) -> str:
        role = message["role"]
        content = message["content"]
        if role == "user":
            return f"<|start_header_id|>user<|end_header_id|>{content}<|eot_id|>"
        if role == "system":
            return f"<|start_header_id|>system<|end_header_id|>{content}<|eot_id|>"
        if role == "assistant":
            return f"<|start_header_id|>assistant<|end_header_id|>{content}<|eot_id|>"

        elif role == "tool":
            return f"<|start_header_id|>assistant<|end_header_id|>Tool Response: {content}<|eot_id|>"
        return f"{content}"


def is_anthropic(model_name: str) -> bool:
    return model_name.startswith("anthropic.")


def is_mistral(model_name: str) -> bool:
    return model_name.startswith("mistral.")


def is_llama2(model_name: str) -> bool:
    return model_name.startswith("meta.llama2")


def is_llama3(model_name: str) -> bool:
    return model_name.startswith("meta.llama3")


def remove_end_token(prompt: str, end_token: str = "</s>") -> str:
    # pull off </s> at end so putting words in mouth is supported
    if prompt.endswith(end_token):
        index = prompt.rfind(end_token)
        prompt = prompt[:index]
    return prompt
