import asyncio
import atexit
import functools
import logging
import os
from subprocess import Popen
from typing import Any

from openai import APIStatusError
from tenacity.wait import WaitBaseT, wait_fixed
from typing_extensions import override

from inspect_ai._util.content import (
    Content,
    ContentImage,
    ContentReasoning,
    ContentText,
)
from inspect_ai._util.error import PrerequisiteError, pip_dependency_error
from inspect_ai._util.local_server import (
    DEFAULT_RETRY_DELAY,
    configure_devices,
    merge_env_server_args,
    start_local_server,
    terminate_process,
)
from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageTool,
    ChatMessageUser,
)
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model_call import ModelCall
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.tool._tool_choice import ToolChoice
from inspect_ai.tool._tool_info import ToolInfo

from ._vllm_lora import (
    VLLMServerInfo,
    compute_lora_config_from_registry,
    ensure_adapter_loaded,
    get_server_for_model,
    get_server_init_lock,
    parse_vllm_model,
    register_server,
    register_vllm_model,
)
from .openai_compatible import OpenAICompatibleAPI

# Environment variable names
# VLLM_BASE_URL = "VLLM_BASE_URL"
# VLLM_API_KEY = "VLLM_API_KEY"
VLLM_DEFAULT_SERVER_ARGS = "VLLM_DEFAULT_SERVER_ARGS"
VLLM_CONFIGURE_LOGGING = "VLLM_CONFIGURE_LOGGING"

# Set up logger for this module
logger = logging.getLogger(__name__)


class VLLMAPI(OpenAICompatibleAPI):
    """
    Provider for using vLLM models with optional LoRA adapter support.

    This provider can either:
    1. Connect to an existing vLLM server (if base_url or port is provided)
    2. Start a new vLLM server for the specified model

    LoRA Adapter Support:
        Use the syntax "base-model:adapter" to specify a LoRA adapter.
        Example: "meta-llama/Llama-3-8B:myorg/my-lora-adapter"

        When an adapter is specified:
        - The server is automatically started with --enable-lora
        - The adapter is dynamically loaded on first request
        - Multiple models can share the same server if they use the same base model

    Args:
        model_name (str): Name or path of the model to use. Optionally include
            ":adapter" suffix to specify a LoRA adapter from HuggingFace or local path.
        base_url (str | None): Base URL of the vLLM server. If not provided, will use localhost.
        port (int | None): Port of the vLLM server. If not provided, will use a free port on localhost.
        api_key (str | None): API key for the vLLM server. If not provided, will use "inspectai" as default.
        config (GenerateConfig): Configuration for generation. Defaults to GenerateConfig().
        is_mistral (bool): Whether the model is a Mistral model. If True, it will handle folding user messages into tool messages as Mistral does not support a user message immediately after a tool message. Defaults to False.

    Additional server_args:
        timeout (int): Timeout for the server (default: 10 minutes)
        host (str): Host to bind the server to (default: "0.0.0.0")
        configure_logging (bool): Enable fine-grained vLLM logging (default: False)
        device (str): Devices to run the server on. Can be a single device or a list of devices as used in CUDA_VISIBLE_DEVICES. If tensor_parallel_size is not provided, the server will use the number of devices as the tensor parallel size.
        enable_lora (bool): Force LoRA mode even without :adapter syntax (default: auto-detected)

    Environment variables:
        VLLM_BASE_URL: Base URL for an existing vLLM server
        VLLM_API_KEY: API key for the vLLM server
        VLLM_DEFAULT_SERVER_ARGS: JSON string of default server args, e.g. '{"tensor_parallel_size": 4, "max_model_len": 8192}'
        VLLM_CONFIGURE_LOGGING: Enable fine-grained vLLM logging
    """

    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        port: int | None = None,
        api_key: str | None = None,
        config: GenerateConfig = GenerateConfig(),
        is_mistral: bool = False,
        retry_delay: int | None = None,
        **server_args: Any,
    ) -> None:
        # Parse model name for LoRA adapter support
        # Syntax: "base-model" or "base-model:adapter-path"
        self.base_model, self.adapter_path, self.adapter_name = parse_vllm_model(
            model_name
        )

        # Register in global model registry so that by the time generate()
        # runs, we have full visibility of all adapters for this base model.
        register_vllm_model(self.base_model, self.adapter_path, self.adapter_name)

        # Validate inputs
        if base_url and port:
            raise ValueError("base_url and port cannot both be provided.")
        if port:
            base_url = f"http://localhost:{port}/v1"

        # save retry delay
        self.retry_delay = retry_delay or DEFAULT_RETRY_DELAY

        # Initialize server process and port variables
        self.is_mistral = is_mistral
        self.server_process: Popen[str] | None = None
        self.port: int | None = port
        self.server_args = merge_env_server_args(
            VLLM_DEFAULT_SERVER_ARGS, server_args, logger
        )

        # Track external base URL for server lookup
        external_base_url = base_url
        self._external_base_url = external_base_url
        self._lazy_init_needed = False

        # Check for existing server for this base model
        existing_server = get_server_for_model(self.base_model, external_base_url)
        if existing_server is not None:
            logger.info(
                f"Reusing vLLM server for {self.base_model} at {existing_server.base_url}"
            )
            self.server_info = existing_server
            super().__init__(
                model_name=self.base_model,
                base_url=existing_server.base_url,
                api_key=existing_server.api_key,
                config=config,
                service="vLLM",
                service_base_url=existing_server.base_url,
            )
            return

        self.server_found = True
        try:
            # Try to initialize with existing server
            resolved_api_key = api_key or os.environ.get("VLLM_API_KEY", "dummy")
            super().__init__(
                model_name=self.base_model,
                base_url=base_url,
                api_key=resolved_api_key,
                config=config,
                service="vLLM",
                service_base_url=base_url,
            )
            logger.info(f"Using existing vLLM server at {self.base_url}")

            # Register external server for reuse
            assert self.base_url is not None
            self.server_info = VLLMServerInfo(
                base_url=self.base_url,
                api_key=resolved_api_key,
                lora_enabled=self.server_args.get("enable_lora", False),
                is_external=True,
            )
            register_server(self.base_model, self.server_info, external_base_url)
        except PrerequisiteError:
            self.server_found = False

        if not self.server_found:
            # No server found — defer startup to first generate() call.
            # By then, all model __init__ calls will have completed and
            # the registry will have full visibility of all adapters.
            self._lazy_init_needed = True
            self._deferred_api_key = api_key
            self._deferred_config = config

            # Call super().__init__ with placeholder URL so the object
            # is in a valid state (model_name, config, etc. are set).
            resolved_api_key = api_key or os.environ.get("VLLM_API_KEY", "inspectai")
            super().__init__(
                model_name=self.base_model,
                base_url="http://placeholder:0/v1",
                api_key=resolved_api_key,
                config=config,
                service="vLLM",
                service_base_url="http://placeholder:0/v1",
            )

    def _start_server(
        self,
        model_path: str,
        api_key: str | None = None,
        port: int | None = None,
    ) -> tuple[str, str]:
        """Start a new vLLM server and return the base URL and API key.

        Args:
            model_path: Path to the model to use
            api_key: API key for the server
            port: Port for the server. If None, will find a free port.

        Returns:
            tuple[str, str]: The base URL for the server and the API key
        """
        # Verify vllm package is installed since we're starting a server
        try:
            import vllm  # type: ignore  # noqa: F401
        except ImportError:
            raise pip_dependency_error("vLLM Server", ["vllm"])

        # Handle device configuration
        self.server_args, env_vars = configure_devices(
            self.server_args, parallel_size_param="tensor_parallel_size"
        )

        if not api_key:
            api_key = "inspectai"  # Create a default API key if not provided

        timeout = self.server_args.pop("timeout", None)
        host = self.server_args.pop("host", "0.0.0.0")

        # Build command as a list
        cmd = ["vllm", "serve", model_path, "--host", host, "--api-key", api_key]

        base_url, self.server_process, self.port = start_local_server(
            cmd,
            host=host,
            port=port,  # If None, find a free port
            api_key=api_key,
            server_type="vLLM",
            timeout=timeout,
            server_args=self.server_args,
            env=env_vars,
        )

        # Register cleanup function to run when Python exits
        atexit.register(self._cleanup_server)

        return base_url, api_key

    async def _ensure_server_started(self) -> None:
        """Start vLLM server on first generate() call, with full adapter visibility.

        By the time generate() is called, all model __init__ calls have completed
        and the global registry contains every adapter for this base model.
        This lets us compute the correct LoRA config (enable_lora, max_lora_rank)
        across all adapters before starting the server.
        """
        if not self._lazy_init_needed:
            return

        lock = get_server_init_lock(self.base_model)
        async with lock:
            if not self._lazy_init_needed:
                return

            # Check if another instance already started the server
            existing = get_server_for_model(self.base_model, self._external_base_url)
            if existing is not None:
                # If yes, we can use the existing server
                self.server_info = existing
            else:
                # Compute LoRA config from registry (all models registered by now)
                lora_config = compute_lora_config_from_registry(self.base_model)
                for key, value in lora_config.items():
                    self.server_args.setdefault(key, value)

                # Extract and handle the configure_logging parameter
                configure_logging = self.server_args.pop("configure_logging", False)
                os.environ[VLLM_CONFIGURE_LOGGING] = "1" if configure_logging else "0"

                # Set env var for runtime LoRA updating if LoRA is enabled
                if self.server_args.get("enable_lora"):
                    os.environ["VLLM_ALLOW_RUNTIME_LORA_UPDATING"] = "True"

                # Start server in thread to avoid blocking the event loop
                base_url, resolved_api_key = await asyncio.to_thread(
                    self._start_server,
                    self.base_model,
                    api_key=self._deferred_api_key,
                    port=self.port,
                )
                logger.warning(f"vLLM server started at {base_url}")

                # Register spawned server for reuse by other instances
                self.server_info = VLLMServerInfo(
                    base_url=base_url,
                    api_key=resolved_api_key,
                    port=self.port,
                    process=self.server_process,
                    lora_enabled=self.server_args.get("enable_lora", False),
                    is_external=False,
                )
                register_server(
                    self.base_model, self.server_info, self._external_base_url
                )

            # Update connection to actual server and recreate OpenAI client
            self.base_url = self.server_info.base_url
            self.api_key = self.server_info.api_key
            self.initialize()
            self._lazy_init_needed = False

    @property
    def server_is_running(self) -> bool:
        """Check if the server is running."""
        if self.server_process is None:
            return False

        # Check if process is still alive
        return self.server_process.poll() is None

    @override
    def collapse_user_messages(self) -> bool:
        return True

    @override
    def collapse_assistant_messages(self) -> bool:
        return True

    @override
    def retry_wait(self) -> WaitBaseT | None:
        return wait_fixed(self.retry_delay)

    @override
    def service_model_name(self) -> str:
        """Return the model name to use in API requests.

        vLLM's OpenAI-compatible API routes LoRA requests by the model field,
        so we must send the adapter name instead of the base model.
        """
        if self.adapter_name:
            return self.adapter_name
        return self.base_model

    def _cleanup_server(self) -> None:
        """Cleanup method to terminate server process when Python exits."""
        if self.server_is_running and self.server_process is not None:
            logger.info("Cleaning up vLLM server")
            terminate_process(self.server_process)
            self.server_process, self.port = None, None

    async def aclose(self) -> None:
        """Close the client and terminate the server if we started it."""
        logger.info("Closing vLLM server")

        # Close the OpenAI client
        await super().aclose()

        self.close()

    def close(self) -> None:
        """
        Terminate the server if we started it.

        Note that this does not close the OpenAI client as we are not in an async context.
        """
        self._cleanup_server()

        # Deregister the atexit handler since we've manually cleaned up
        atexit.unregister(self._cleanup_server)

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput | tuple[ModelOutput | Exception, ModelCall]:
        # Lazy server startup: by now all models have been initialized and
        # the registry has full visibility of all adapters for this base model.
        await self._ensure_server_started()

        # Ensure LoRA adapter is loaded if needed (idempotent, async-safe)
        if self.adapter_path:
            # adapter_name is always set when adapter_path is set (from parse_vllm_model)
            assert self.adapter_name is not None
            await ensure_adapter_loaded(
                self.server_info,
                self.adapter_path,
                self.adapter_name,
            )

        # check if last message is an assistant message, in this case we want to
        # continue the final message instead of generating a new one
        if input[-1].role == "assistant":
            # Create a copy of the config to avoid modifying the original
            config = config.model_copy()

            # Set these parameters in extra_body
            if config.extra_body is None:
                config.extra_body = {}

            # Only set these values if they're not already present in extra_body
            if (
                "add_generation_prompt" not in config.extra_body
                and "continue_final_message" not in config.extra_body
            ):
                config.extra_body["add_generation_prompt"] = False
                config.extra_body["continue_final_message"] = True
        # if model is mistral, we need to fold user messages into tool messages, as mistral does not support a user message immediately after a tool message
        if self.is_mistral:
            input = functools.reduce(mistral_message_reducer, input, [])
        return await super().generate(input, tools, tool_choice, config)

    @override
    def handle_bad_request(self, ex: APIStatusError) -> ModelOutput | Exception:
        if ex.status_code == 400:
            # Extract message safely
            if isinstance(ex.body, dict) and "message" in ex.body:
                content = str(ex.body.get("message"))
            else:
                content = ex.message

            if (
                "maximum context length" in content
                or "max_tokens must be at least 1" in content
            ):
                return ModelOutput.from_content(
                    self.model_name, content=content, stop_reason="model_length"
                )
        return ex


def mistral_message_reducer(
    messages: list[ChatMessage],
    message: ChatMessage,
) -> list[ChatMessage]:
    """Fold any user messages found immediately after tool messages into the last tool message."""
    if (
        len(messages) > 0
        and isinstance(messages[-1], ChatMessageTool)
        and isinstance(message, ChatMessageUser)
    ):
        messages[-1] = fold_user_message_into_tool_message(messages[-1], message)
    else:
        messages.append(message)

    return messages


def fold_user_message_into_tool_message(
    tool_message: ChatMessageTool,
    user_message: ChatMessageUser,
) -> ChatMessageTool:
    def convert_content_items_to_string(list_content: list[Content]) -> str:
        if not all(
            isinstance(item, (ContentText | ContentReasoning | ContentImage))
            for item in list_content
        ):
            raise TypeError("Expected all items to be ContentText or ContentReasoning")

        parts = []
        for item in list_content:
            if isinstance(item, ContentText):
                parts.append(item.text)
            elif isinstance(item, ContentReasoning):
                parts.append(item.reasoning)
            elif isinstance(item, ContentImage):
                parts.append(f"[Image: {item.image}]")
            else:
                raise ValueError("Unexpected content item type")
        return "".join(parts)

    def normalise_content(
        content: str | list[Content] | None,
    ) -> str | None:
        return (
            None
            if content is None
            else convert_content_items_to_string(content)
            if isinstance(content, list)
            else content
        )

    tool_content = normalise_content(tool_message.content)
    user_content = normalise_content(user_message.content)

    return ChatMessageTool(
        content=(tool_content or "") + (user_content or ""),
        tool_call_id=tool_message.tool_call_id,
    )
