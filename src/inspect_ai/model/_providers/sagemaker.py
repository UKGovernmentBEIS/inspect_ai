import json
from logging import getLogger
from typing import Any

from botocore.config import Config  # type: ignore[import-untyped]
from botocore.exceptions import ClientError  # type: ignore[import-untyped]
from openai.types.chat import ChatCompletion
from typing_extensions import override

from inspect_ai._util.constants import DEFAULT_MAX_TOKENS
from inspect_ai._util.content import Content, ContentText
from inspect_ai._util.error import pip_dependency_error
from inspect_ai._util.images import file_as_data_uri
from inspect_ai._util.url import is_http_url
from inspect_ai._util.version import verify_required_version
from inspect_ai.model._openai import chat_choices_from_openai, model_output_from_openai
from inspect_ai.tool import ToolChoice, ToolInfo
from inspect_ai.tool._tool_choice import ToolFunction

from .._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
)
from .._generate_config import GenerateConfig
from .._model import ModelAPI
from .._model_call import ModelCall
from .._model_output import ModelOutput

logger = getLogger(__name__)

SAGEMAKER_DEFAULTS = {
    "region_name": "us-east-1",
    "read_timeout": 600,
    "connect_timeout": 60,
}

SAGEMAKER_RETRY_ERROR_CODES = {
    # commented codes typically don't warrant retry
    0,  # Container timeout (SageMaker-specific)
    # 408, # Request timeout
    # 500, # Internal server error
    # 502, # Bad gateway
    503,  # Service unavailable
    504,  # Gateway timeout
    # 507, # Insufficient storage
}

# https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/sagemaker-runtime/client/invoke_endpoint.html


class SagemakerAPI(ModelAPI):
    def __init__(
        self,
        model_name: str,
        config: GenerateConfig = GenerateConfig(),
        **model_args: Any,
    ):
        super().__init__(
            model_name=model_name,
            base_url=None,
            api_key=None,
            api_key_vars=[],
            config=config,
        )

        self.endpoint_name = model_name

        # save model_args (coerce numeric values from CLI strings)
        merged_args: dict[str, Any] = SAGEMAKER_DEFAULTS | model_args
        for key in ("read_timeout", "connect_timeout"):
            if key in merged_args:
                merged_args[key] = int(str(merged_args[key]))
        self.model_args = merged_args

        # import aioboto3 on demand
        try:
            import aioboto3  # type: ignore[import-untyped]

            verify_required_version("Sagemaker API", "aioboto3", "13.0.0")

            # Create a shared session to be used when generating
            self.session = aioboto3.Session()

        except ImportError:
            raise pip_dependency_error("Sagemaker API", ["aioboto3"])

        self.request_content_type = "application/json"
        self.request_accept_type = "application/json"

        # Extract streaming configuration (handle string "True"/"False" from CLI)
        stream_val = model_args.get("stream", False)
        self.stream = (
            stream_val
            if isinstance(stream_val, bool)
            else str(stream_val).lower() == "true"
        )

    @override
    def connection_key(self) -> str:
        return self.endpoint_name

    @override
    def max_tokens(self) -> int | None:
        return DEFAULT_MAX_TOKENS

    @override
    def should_retry(self, ex: Exception) -> bool:
        if isinstance(ex, ClientError):
            error_code = ex.response.get("Error", {}).get("Code", "")
            status_code = ex.response.get("OriginalStatusCode", -1)

            should_retry_ = (
                error_code == "ModelError"
                and status_code in SAGEMAKER_RETRY_ERROR_CODES
            )

            return should_retry_
        else:
            return False

    @override
    def collapse_user_messages(self) -> bool:
        return True

    @override
    def collapse_assistant_messages(self) -> bool:
        return True

    @override
    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput | tuple[ModelOutput | Exception, ModelCall]:
        # Prepare request components
        config = self._prepare_vllm_config(input, config)
        tools_config = self._prepare_tools_config(tools)
        processed_messages = await self._prepare_messages(input)

        # Build request body
        request_body = self._build_request_body(
            config, processed_messages, tools_config, tool_choice
        )

        # Add stream parameter to request body
        request_body["stream"] = self.stream

        # Make request
        async with self._create_client() as client:
            if self.stream:
                body_bytes, output = await self._invoke_endpoint_streaming(
                    client, request_body
                )
            else:
                body_bytes = await self._invoke_endpoint(client, request_body)
                output = json.loads(body_bytes.decode("utf-8"))

        # Process response
        model_output = model_output_from_response(output, tools)
        model_call = ModelCall.create(request=request_body, response=output, time=0)

        return model_output, model_call

    def _prepare_vllm_config(
        self, input: list[ChatMessage], config: GenerateConfig
    ) -> GenerateConfig:
        """Prepare vLLM-specific configuration for message continuation."""
        if not (input and isinstance(input[-1], ChatMessageAssistant)):
            return config

        config = config.model_copy()
        if config.extra_body is None:
            config.extra_body = {}
        config.extra_body.setdefault("add_generation_prompt", False)
        config.extra_body.setdefault("continue_final_message", True)
        return config

    def _prepare_tools_config(
        self, tools: list[ToolInfo]
    ) -> list[dict[str, Any]] | None:
        """Convert tools to OpenAI format for vLLM."""
        if not tools:
            return None
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters.model_dump(exclude_none=True),
                },
            }
            for tool in tools
        ]

    async def _prepare_messages(self, input: list[ChatMessage]) -> list[dict[str, Any]]:
        """Process and collapse input messages."""
        collapsed = collapse_consecutive_messages(
            input, self.collapse_user_messages(), self.collapse_assistant_messages()
        )
        return [await process_chat_message(message) for message in collapsed]

    def _create_client(self) -> Any:
        """Create SageMaker runtime client with proper configuration."""
        return self.session.client(  # type: ignore[call-overload]
            service_name="sagemaker-runtime",
            region_name=str(self.model_args["region_name"]),
            endpoint_url=self.model_args.get("endpoint_url"),
            config=Config(
                read_timeout=int(str(self.model_args["read_timeout"])),
                connect_timeout=int(str(self.model_args["connect_timeout"])),
                retries={"total_max_attempts": 1, "mode": "standard"},
            ),
        )

    def _build_request_body(
        self,
        config: GenerateConfig,
        messages: list[dict[str, Any]],
        tools_config: list[dict[str, Any]] | None,
        tool_choice: ToolChoice,
    ) -> dict[str, Any]:
        """Build OpenAI-compatible request body for vLLM."""
        request_body: dict[str, Any] = {
            "messages": messages,
            "max_tokens": config.max_tokens,
            "temperature": config.temperature,
            "top_p": config.top_p,
        }

        # Add optional parameters
        self._add_optional_params(request_body, config)

        # Add tools and tool choice
        if tools_config:
            request_body["tools"] = tools_config
            self._add_tool_choice(request_body, tool_choice)
            if config.parallel_tool_calls is not None:
                request_body["parallel_tool_calls"] = config.parallel_tool_calls

        # Add response schema
        if config.response_schema is not None:
            request_body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": config.response_schema.name,
                    "schema": config.response_schema.json_schema.model_dump(
                        exclude_none=True
                    ),
                    "description": config.response_schema.description,
                    "strict": config.response_schema.strict,
                },
            }

        # Add extra body parameters
        if config.extra_body:
            request_body.update(config.extra_body)

        return request_body

    def _add_optional_params(
        self, request_body: dict[str, Any], config: GenerateConfig
    ) -> None:
        """Add optional parameters to request body."""
        optional_params = [
            ("top_k", config.top_k),
            ("stop", config.stop_seqs),
            ("frequency_penalty", config.frequency_penalty),
            ("presence_penalty", config.presence_penalty),
            ("logit_bias", config.logit_bias),
            ("seed", config.seed),
            ("n", config.num_choices),
            ("logprobs", config.logprobs),
            ("top_logprobs", config.top_logprobs),
            ("best_of", config.best_of),
            ("reasoning_effort", config.reasoning_effort),
        ]

        for param_name, param_value in optional_params:
            if param_value is not None:
                request_body[param_name] = param_value

    def _add_tool_choice(
        self, request_body: dict[str, Any], tool_choice: ToolChoice
    ) -> None:
        """Add tool choice to request body in OpenAI format."""
        if isinstance(tool_choice, ToolFunction):
            request_body["tool_choice"] = {
                "type": "function",
                "function": {"name": tool_choice.name},
            }
        elif tool_choice == "any":
            request_body["tool_choice"] = "required"
        elif tool_choice == "none":
            request_body["tool_choice"] = "none"
        else:  # "auto" or any other value defaults to auto
            request_body["tool_choice"] = "auto"

    async def _invoke_endpoint(
        self, client: Any, request_body: dict[str, Any]
    ) -> bytes:
        """Invoke SageMaker endpoint and return response body bytes."""
        response = await client.invoke_endpoint(
            EndpointName=self.endpoint_name,
            ContentType=self.request_content_type,
            Accept=self.request_accept_type,
            Body=json.dumps(request_body),
        )
        body: bytes = await response["Body"].read()
        return body

    async def _invoke_endpoint_streaming(
        self, client: Any, request_body: dict[str, Any]
    ) -> tuple[bytes, dict[str, Any]]:
        """Invoke SageMaker endpoint with streaming and return assembled response.

        https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/sagemaker-runtime/client/invoke_endpoint_with_response_stream.html
        """
        response = await client.invoke_endpoint_with_response_stream(
            EndpointName=self.endpoint_name,
            ContentType=self.request_content_type,
            Accept=self.request_accept_type,
            Body=json.dumps(request_body),
        )

        # Process streaming response
        event_stream = response["Body"]

        # Accumulate text and chunks
        accumulated_text = ""
        accumulated_chunks = []
        partial_content = ""  # Buffer for incomplete JSON

        async for event in event_stream:
            # Check for error events first
            if "ModelStreamError" in event:
                error_info = event["ModelStreamError"]
                error_code = error_info.get("ErrorCode", "Unknown")
                error_message = error_info.get("Message", "Model stream error occurred")
                logger.error(f"ModelStreamError: {error_code} - {error_message}")
                raise RuntimeError(f"ModelStreamError [{error_code}]: {error_message}")

            if "InternalStreamFailure" in event:
                error_message = event["InternalStreamFailure"].get(
                    "Message", "Internal stream failure occurred"
                )
                logger.error(f"InternalStreamFailure: {error_message}")
                raise RuntimeError(f"InternalStreamFailure: {error_message}")

            # Process payload chunks
            if "PayloadPart" in event:
                chunk = event["PayloadPart"]["Bytes"].decode("utf-8")

                # Strip "data: " prefix if present
                partial_content += chunk[6:] if chunk.startswith("data: ") else chunk

                try:
                    chunk_data = json.loads(partial_content)

                    partial_content = ""
                    accumulated_chunks.append(chunk_data)

                    if "choices" in chunk_data and len(chunk_data["choices"]) > 0:
                        choice = chunk_data["choices"][0]
                        delta = choice.get("delta", {})

                        if "content" in delta and delta["content"]:
                            accumulated_text += delta["content"]

                except json.JSONDecodeError:
                    # Continue accumulating content until we have valid JSON
                    continue

        # Build final response from accumulated chunks
        if accumulated_chunks:
            # Use the last chunk as base (contains final metadata)
            final_chunk = accumulated_chunks[-1]

            # Debug logging
            logger.info(
                f"Streaming complete: {len(accumulated_chunks)} chunks, accumulated text length: {len(accumulated_text)}"
            )

            # Construct complete response in OpenAI format
            final_response = {
                "id": final_chunk.get("id", ""),
                "object": "chat.completion",
                "created": final_chunk.get("created", 0),
                "model": final_chunk.get("model", self.endpoint_name),
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": accumulated_text},
                        "finish_reason": final_chunk.get("choices", [{}])[0].get(
                            "finish_reason", "stop"
                        )
                        if final_chunk.get("choices")
                        else "stop",
                    }
                ],
                "usage": final_chunk.get(
                    "usage",
                    {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                ),
            }
        else:
            # Fallback if no chunks received
            logger.warning("No chunks received from streaming endpoint")
            final_response = {
                "id": "",
                "object": "chat.completion",
                "created": 0,
                "model": self.endpoint_name,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": ""},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                },
            }

        # Return both raw bytes (for logging) and parsed response
        response_bytes = json.dumps(final_response).encode("utf-8")
        return response_bytes, final_response


async def process_chat_message(message: ChatMessage) -> dict[str, Any]:
    if isinstance(message, (ChatMessageSystem, ChatMessageUser)):
        content = await process_content(message.content)
        return {"role": message.role, "content": content}
    if isinstance(message, ChatMessageAssistant):
        content = await process_content(message.content)
        result: dict[str, Any] = {"role": message.role, "content": content}

        # Add tool calls for assistant messages
        if message.tool_calls:
            result["tool_calls"] = [
                dict(
                    id=tool_call.id,
                    type="function",
                    function={
                        "name": tool_call.function,
                        "arguments": json.dumps(tool_call.arguments),
                    },
                )
                for tool_call in message.tool_calls
            ]

        return result
    if isinstance(message, ChatMessageTool):
        # Handle tool message content with error support
        content = f"Error: {message.error.message}" if message.error else message.text
        return {
            "role": "tool",
            "tool_call_id": str(message.tool_call_id),
            "content": content,
        }
    else:
        raise ValueError(f"Unexpected message type: {type(message)}")


async def process_content(content: list[Content] | str) -> str | list[dict[str, Any]]:
    if isinstance(content, str):
        return content

    processed_content = []
    for item in content:
        if item.type == "text":
            processed_content.append({"type": "text", "text": item.text})
        elif item.type == "image":
            image_url = item.image
            if not is_http_url(image_url):
                image_url = await file_as_data_uri(image_url)

            processed_content.append(
                {
                    "type": "image_url",
                    "image_url": {  # type: ignore[dict-item]
                        "url": image_url,
                        "detail": getattr(item, "detail", "auto"),
                    },
                }
            )
        elif item.type == "reasoning":
            processed_content.append({"type": "reasoning", "reasoning": item.reasoning})

    # Return string if single text item, otherwise return list
    if len(processed_content) == 1 and processed_content[0]["type"] == "text":
        return processed_content[0]["text"]
    return processed_content


def collapse_consecutive_messages(
    messages: list[ChatMessage],
    collapse_user_messages: bool,
    collapse_assistant_messages: bool,
) -> list[ChatMessage]:
    if not messages:
        return []

    collapsed_messages = [messages[0]]

    for message in messages[1:]:
        last_message = collapsed_messages[-1]
        if message.role == last_message.role and (
            (isinstance(message, ChatMessageUser) and collapse_user_messages)
            or (
                isinstance(message, ChatMessageAssistant)
                and collapse_assistant_messages
            )
        ):
            # Merge content handling both str and list types
            a, b = last_message.content, message.content
            if isinstance(a, str) and isinstance(b, str):
                last_message.content = f"{a}\n{b}"
            elif isinstance(a, list) and isinstance(b, list):
                last_message.content = a + b
            elif isinstance(a, str) and isinstance(b, list):
                last_message.content = [ContentText(text=a)] + b
            elif isinstance(a, list) and isinstance(b, str):
                last_message.content = a + [ContentText(text=b)]
        else:
            collapsed_messages.append(message)

    return collapsed_messages


def model_output_from_response(
    output: dict[str, Any], tools: list[ToolInfo]
) -> ModelOutput:
    # Convert dict response to ChatCompletion object for reuse of OpenAI logic
    completion = ChatCompletion.model_validate(output)

    # Use OpenAI's proven response processing logic
    choices = chat_choices_from_openai(completion, tools)
    return model_output_from_openai(completion, choices)
