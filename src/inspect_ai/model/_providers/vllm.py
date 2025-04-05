import atexit
import logging
import os
from subprocess import Popen
from typing import Any

from typing_extensions import override

from inspect_ai._util.error import pip_dependency_error
from inspect_ai.model._chat_message import ChatMessage
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model_call import ModelCall
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.model._providers.util import model_base_url
from inspect_ai.model._providers.util.local_server_utils import (
    load_server_args_from_env,
    start_local_server,
    terminate_process,
)
from inspect_ai.tool._tool_choice import ToolChoice
from inspect_ai.tool._tool_info import ToolInfo

from .openai import OpenAIAPI

# Environment variable names
VLLM_BASE_URL = "VLLM_BASE_URL"
VLLM_API_KEY = "VLLM_API_KEY"
VLLM_DEFAULT_SERVER_ARGS = "VLLM_DEFAULT_SERVER_ARGS"
VLLM_CONFIGURE_LOGGING = "VLLM_CONFIGURE_LOGGING"

# Set up logger for this module
logger = logging.getLogger(__name__)


class VLLMAPI(OpenAIAPI):
    """
    Provider for using VLLM models.

    This provider can either:
    1. Connect to an existing VLLM server (if base_url or port is provided)
    2. Start a new VLLM server for the specified model

    Additional server_args:
        host (str): Host to bind the server to (default: "0.0.0.0")
        configure_logging (bool): Enable fine-grained VLLM logging (default: False)
        device (str): Devices to run the server on. Can be a single device or a list of devices as used in CUDA_VISIBLE_DEVICES. If tensor_parallel_size is not provided, the server will use the number of devices as the tensor parallel size.

    Environment variables:
        VLLM_BASE_URL: Base URL for an existing vLLM server
        VLLM_API_KEY: API key for the vLLM server
        VLLM_DEFAULT_SERVER_ARGS: JSON string of default server args, e.g. '{"tensor_parallel_size": 4, "max_model_len": 8192}'
        VLLM_CONFIGURE_LOGGING: Enable fine-grained VLLM logging
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
        # Load and merge server args from environment
        self.server_args = load_server_args_from_env(
            VLLM_DEFAULT_SERVER_ARGS, server_args, logger
        )

        # Extract and handle the configure_logging parameter
        configure_logging = self.server_args.pop("configure_logging", False)
        os.environ[VLLM_CONFIGURE_LOGGING] = "1" if configure_logging else "0"

        # Get base_url from environment or argument
        if not base_url and port:  # if port is provided assume there is a local server
            base_url = f"http://localhost:{port}/v1"
        else:
            base_url = model_base_url(base_url, VLLM_BASE_URL)

        self.server_process: Popen[str] | None = None
        self.port: int | None = port

        # Default API key if not provided
        if api_key is not None:
            self.api_key: str = api_key
        else:
            self.api_key = str(os.environ.get(VLLM_API_KEY, "local"))

        # If no base_url is provided, start a new server
        if not base_url:
            logger.warning(
                f"Existing vLLM server not found. Starting new server for {model_name}."
            )
            host = self.server_args.pop("host", "0.0.0.0")
            base_url = self._start_server(model_name, host, port=None)
            atexit.register(self._cleanup_server)

            logger.warning(f"VLLM server started at {base_url}")
        else:
            logger.info(f"Using existing VLLM server at {base_url}")

        # Initialize OpenAI API with our VLLM server
        super().__init__(
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            config=config,
        )

    def _start_server(self, model_path: str, host: str, port: int | None = None) -> str:
        """Start a new VLLM server and return the base URL.

        Args:
            model_path: Path to the model to use
            host: Host to bind the server to
            port: Port to bind the server to
        Returns:
            str: The base URL for the server
        """
        # Verify vllm package is installed since we're starting a server
        try:
            import vllm  # type: ignore  # noqa: F401
        except ImportError:
            raise pip_dependency_error("vLLM Server", ["vllm"])

        # Handle device configuration
        if "device" in self.server_args:
            if isinstance(self.server_args["device"], list):
                self.server_args["device"] = ",".join(
                    map(str, self.server_args["device"])
                )
            os.environ["CUDA_VISIBLE_DEVICES"] = str(self.server_args["device"])
            if "tensor_parallel_size" not in self.server_args:
                devices = os.environ.get("CUDA_VISIBLE_DEVICES", "").split(",")
                self.server_args["tensor_parallel_size"] = len(devices)

            self.server_args.pop("device")

        # Build command as a list
        cmd = ["vllm", "serve", model_path, "--host", host, "--api-key", self.api_key]

        # Add additional arguments
        for key, value in self.server_args.items():
            # Convert Python style args (underscore) to CLI style (dash)
            cli_key = key.replace("_", "-")
            cmd.extend([f"--{cli_key}", str(value)])

        base_url, self.server_process, self.port = start_local_server(
            cmd, host=host, port=port, api_key=self.api_key, server_type="vLLM"
        )

        return base_url

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
            logger.info("Cleaning up VLLM server")
            terminate_process(self.server_process)
            self.server_process, self.port = None, None

    async def aclose(self) -> None:
        """Close the client and terminate the server if we started it."""
        logger.info("Closing VLLM server")

        # Close the OpenAI client
        await super().aclose()

        self._cleanup_server()

        # Deregister the atexit handler since we've manually cleaned up
        atexit.unregister(self._cleanup_server)

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

    def completion_params(self, config: GenerateConfig, tools: bool) -> dict[str, Any]:
        params: dict[str, Any] = dict(
            model=self.model_name,
        )
        if config.max_tokens is not None:
            params["max_tokens"] = config.max_tokens
        if config.frequency_penalty is not None:
            params["frequency_penalty"] = config.frequency_penalty
        if config.stop_seqs is not None:
            params["stop"] = config.stop_seqs
        if config.presence_penalty is not None:
            params["presence_penalty"] = config.presence_penalty
        if config.logit_bias is not None:
            params["logit_bias"] = config.logit_bias
        if config.seed is not None:
            params["seed"] = config.seed
        if config.temperature is not None:
            params["temperature"] = config.temperature
        if config.top_p is not None:
            params["top_p"] = config.top_p
        if config.num_choices is not None:
            params["n"] = config.num_choices
        if config.logprobs is not None:
            params["logprobs"] = config.logprobs
        if config.top_logprobs is not None:
            params["top_logprobs"] = config.top_logprobs

        if config.response_schema is not None and config.guided_decoding is not None:
            raise ValueError(
                "response_schema and guided_decoding cannot both be set. Please set only one of them."
            )

        if config.response_schema is not None:
            params["response_format"] = dict(
                type="json_schema",
                json_schema=dict(
                    name=config.response_schema.name,
                    schema=config.response_schema.json_schema.model_dump(
                        exclude_none=True,
                        by_alias=True,
                    ),
                    description=config.response_schema.description,
                    strict=config.response_schema.strict,
                ),
            )

        # Handle extra_body
        extra_body = {}
        if config.extra_body:
            extra_body.update(config.extra_body)

        # Add guided decoding configuration to extra_body if present
        if config.guided_decoding:
            guided_config = config.guided_decoding.model_dump(
                exclude_none=True,
                by_alias=True,
            )
            if guided_config:
                extra_body.update(guided_config)

        # Add extra_body to params if it has content
        if extra_body:
            params["extra_body"] = extra_body

        return params
