import atexit
import logging
import os
from subprocess import Popen
from typing import Any

from openai import APIStatusError
from typing_extensions import override

from inspect_ai._util.error import PrerequisiteError, pip_dependency_error
from inspect_ai._util.local_server import (
    configure_devices,
    merge_env_server_args,
    start_local_server,
    terminate_process,
)
from inspect_ai.model._chat_message import ChatMessage
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model_call import ModelCall
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.tool._tool_choice import ToolChoice
from inspect_ai.tool._tool_info import ToolInfo

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
    Provider for using vLLM models.

    This provider can either:
    1. Connect to an existing vLLM server (if base_url or port is provided)
    2. Start a new vLLM server for the specified model

    Additional server_args:
        timeout (int): Timeout for the server (default: 10 minutes)
        host (str): Host to bind the server to (default: "0.0.0.0")
        configure_logging (bool): Enable fine-grained vLLM logging (default: False)
        device (str): Devices to run the server on. Can be a single device or a list of devices as used in CUDA_VISIBLE_DEVICES. If tensor_parallel_size is not provided, the server will use the number of devices as the tensor parallel size.

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
        **server_args: Any,
    ) -> None:
        # Validate inputs
        if base_url and port:
            raise ValueError("base_url and port cannot both be provided.")
        if port:
            base_url = f"http://localhost:{port}/v1"

        # Initialize server process and port variables
        self.server_process: Popen[str] | None = None
        self.port: int | None = port
        self.server_args = merge_env_server_args(
            VLLM_DEFAULT_SERVER_ARGS, server_args, logger
        )

        self.server_found = True
        try:
            # Try to initialize with existing server
            super().__init__(
                model_name=model_name,
                base_url=base_url,
                api_key=api_key,
                config=config,
                service="vLLM",
                service_base_url=base_url,
            )
            logger.info(f"Using existing vLLM server at {self.base_url}")
        except PrerequisiteError:
            self.server_found = False

        if not self.server_found:
            logger.warning(
                f"Existing vLLM server not found. Starting new server for {model_name}."
            )

            # Extract and handle the configure_logging parameter
            configure_logging = self.server_args.pop("configure_logging", False)
            os.environ[VLLM_CONFIGURE_LOGGING] = "1" if configure_logging else "0"

            # Start the server
            base_url, api_key = self._start_server(model_name, api_key=api_key)
            logger.warning(f"vLLM server started at {base_url}")

            # Initialize with new server
            super().__init__(
                model_name=model_name,
                base_url=base_url,
                api_key=api_key,
                config=config,
                service="vLLM",
                service_base_url=base_url,
            )

    def _start_server(
        self,
        model_path: str,
        api_key: str | None = None,
    ) -> tuple[str, str]:
        """Start a new vLLM server and return the base URL and API key.

        Args:
            model_path: Path to the model to use
            api_key: API key for the server
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
            port=None,  # find a free port
            api_key=api_key,
            server_type="vLLM",
            timeout=timeout,
            server_args=self.server_args,
            env=env_vars,
        )

        # Register cleanup function to run when Python exits
        atexit.register(self._cleanup_server)

        return base_url, api_key

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

        return await super().generate(input, tools, tool_choice, config)

    @override
    def handle_bad_request(self, ex: APIStatusError) -> ModelOutput | Exception:
        if ex.status_code == 400:
            # Extract message safely
            if isinstance(ex.body, dict) and "message" in ex.body:
                content = str(ex.body.get("message"))
            else:
                content = ex.message

            if "maximum context length" in content:
                return ModelOutput.from_content(
                    self.model_name, content=content, stop_reason="model_length"
                )
        return ex
