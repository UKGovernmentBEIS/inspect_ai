import logging
import os
import random
import socket
import subprocess
import time
from typing import Any

import requests
from typing_extensions import override

from inspect_ai.model._chat_message import ChatMessage
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model_call import ModelCall
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.model._providers.util import model_base_url
from inspect_ai.model._providers.util.server_utils import (
    launch_server_cmd,
    terminate_process,
    wait_for_server,
)
from inspect_ai.tool._tool_choice import ToolChoice
from inspect_ai.tool._tool_info import ToolInfo

from .openai import OpenAIAPI

# Environment variable names
VLLM_BASE_URL = "VLLM_BASE_URL"
VLLM_API_KEY = "VLLM_API_KEY"

# Set up logger for this module
logger = logging.getLogger(__name__)


class VLLMAPI(OpenAIAPI):
    """
    Provider for using VLLM models.

    This provider can either:
    1. Connect to an existing VLLM server (if base_url is provided)
    2. Start a new VLLM server for the specified model

    Additional server_args:
        tensor_parallel_size (int): The tensor parallel size to use
        host (str): Host to bind the server to (default: "0.0.0.0")
        dtype (str): Data type for model weights (default: "auto")
        quantization (str): Quantization method
        max_model_len (int): Maximum sequence length
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
        host = server_args.pop("host", "0.0.0.0")
        self.server_args = server_args

        # Get base_url from environment or argument
        if not base_url and port:  # if port is provided assume there is a local server
            base_url = f"http://localhost:{port}/v1"
        else:
            base_url = model_base_url(base_url, VLLM_BASE_URL)

        self.server_process = None
        self.port = port
        self.model_name = model_name

        # Default API key if not provided
        if not api_key:
            api_key = os.environ.get(VLLM_API_KEY, "local")
        self.api_key = api_key

        # Start server if needed
        if not base_url:
            logger.info("Starting new VLLM server...")
            if "model_path" in self.server_args:
                model_name = self.server_args.pop("model_path")
            base_url = self._start_server(model_name, host, port=None)
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
        # Verify we have a model path
        if not model_path:
            raise ValueError(
                "No model_name provided for VLLM. Please specify a model_name argument."
            )

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

        try:
            # Launch server
            self.server_process, self.port = launch_server_cmd(
                cmd, host=host, port=port
            )
            base_url = f"http://localhost:{self.port}/v1"
            wait_for_server(f"http://localhost:{self.port}", api_key=self.api_key)
        except Exception as e:
            # Cleanup any partially started server
            if self.server_process:
                terminate_process(self.server_process)

            # Re-raise with more context
            raise RuntimeError(f"Failed to start VLLM server: {str(e)}") from e

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

    async def close(self) -> None:
        """Close the client and terminate the server if we started it."""
        # Close the OpenAI client
        await super().close()

        # Terminate the server if we started it
        if self.server_is_running:
            terminate_process(self.server_process)

            # Clear references
            self.server_process = None
            self.port = None

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput | tuple[ModelOutput | Exception, ModelCall]:
        # check if last message is an assistant message, in this case we want to
        # continue the final message
        if input[-1].role == "assistant":
            # Create a copy of the config to avoid modifying the original
            config = config.model_copy()

            # Set these parameters in extra_body
            if config.extra_body is None:
                config.extra_body = {}

            # Only set these values if they're not already present in extra_body
            if "add_generation_prompt" not in config.extra_body:
                config.extra_body["add_generation_prompt"] = False
            if "continue_final_message" not in config.extra_body:
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
