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
        if not base_url and port:
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
            base_url = self._start_server(model_name, host, port=None)

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

        # Create server command using vllm serve CLI
        cmd = f"vllm serve {model_path} --host {host} --api-key {self.api_key}"

        # Add additional arguments
        for key, value in self.server_args.items():
            # Convert Python style args (underscore) to CLI style (dash)
            cli_key = key.replace("_", "-")
            cmd += f" --{cli_key} {value}"

        try:
            # Launch server
            self.server_process, self.port = launch_server_cmd(cmd, port=port)
            base_url = f"http://localhost:{self.port}/v1"
            wait_for_server(f"http://localhost:{self.port}", api_key=self.api_key)
        except Exception as e:
            # Cleanup any partially started server
            if self.server_process:
                try:
                    terminate_process(self.server_process)
                except Exception:
                    if hasattr(self.server_process, "terminate"):
                        self.server_process.terminate()

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
            # Only set these config values if both are currently None
            if (
                config.add_generation_prompt is None
                and config.continue_final_message is None
            ):
                config.add_generation_prompt = False
                config.continue_final_message = True

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
                        exclude_none=True
                    ),
                    description=config.response_schema.description,
                    strict=config.response_schema.strict,
                ),
            )

        # Handle extra_body
        extra_body = {}
        if config.extra_body:
            extra_body.update(config.extra_body)

        # Add generation prompt configuration to extra_body if present
        if config.add_generation_prompt is not None:
            extra_body["add_generation_prompt"] = config.add_generation_prompt
        if config.continue_final_message is not None:
            extra_body["continue_final_message"] = config.continue_final_message

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


# Global dictionary to keep track of process and port mappings
process_socket_map = {}


def reserve_port(host, start=30000, end=40000):
    """
    Reserve an available port by trying to bind a socket.

    Returns a tuple (port, lock_socket) where `lock_socket` is kept open to hold the lock.
    """
    candidates = list(range(start, end))
    random.shuffle(candidates)

    for port in candidates:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            # Attempt to bind to the port on localhost
            sock.bind((host, port))
            return port, sock
        except socket.error:
            sock.close()  # Failed to bind, try next port
            continue
    raise RuntimeError("No free port available.")


def release_port(lock_socket):
    """Release the reserved port by closing the lock socket."""
    try:
        lock_socket.close()
    except Exception as e:
        print(f"Error closing socket: {e}")


def execute_shell_command(command: str) -> subprocess.Popen:
    """Execute a shell command and return its process handle."""
    command = command.replace("\\\n", " ").replace("\\", " ")
    parts = command.split()

    # Create a process that redirects output to pipes so we can capture it
    process = subprocess.Popen(
        parts,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=1,  # Line buffered
    )

    # Set up background thread to read and log stdout
    def log_output():
        for line in iter(process.stdout.readline, ""):
            if line:
                logger.info(line.strip())
        process.stdout.close()

    # Set up background thread to read and log stderr
    def log_error():
        for line in iter(process.stderr.readline, ""):
            if line:
                logger.warning(line.strip())
        process.stderr.close()

    # Start background threads to handle output
    import threading

    threading.Thread(target=log_output, daemon=True).start()
    threading.Thread(target=log_error, daemon=True).start()

    logger.info(f"Started VLLM server with command: {command}")
    return process


def kill_process_tree(pid):
    """Kill a process and all its children."""
    try:
        # Send SIGTERM
        subprocess.run(["pkill", "-TERM", "-P", str(pid)], check=False)
        subprocess.run(["kill", "-TERM", str(pid)], check=False)
        time.sleep(0.5)

        # If process still exists, send SIGKILL
        try:
            os.kill(pid, 0)  # Check if process exists
            subprocess.run(["pkill", "-KILL", "-P", str(pid)], check=False)
            subprocess.run(["kill", "-KILL", str(pid)], check=False)
        except OSError:
            pass  # Process already terminated
    except Exception as e:
        print(f"Error killing process tree: {e}")


def launch_server_cmd(command: str, host: str = "0.0.0.0", port: int | None = None):
    """
    Launch the server using the given command.

    If no port is specified, a free port is reserved.
    """
    if port is None:
        port, lock_socket = reserve_port(host)
    else:
        lock_socket = None

    full_command = f"{command} --port {port}"
    logger.info(f"Launching VLLM server on port {port}")
    process = execute_shell_command(full_command)

    if lock_socket is not None:
        process_socket_map[process] = lock_socket

    return process, port


def terminate_process(process):
    """Terminate the process and automatically release the reserved port."""
    kill_process_tree(process.pid)

    lock_socket = process_socket_map.pop(process, None)
    if lock_socket is not None:
        release_port(lock_socket)


def wait_for_server(base_url: str, timeout: int = None, api_key: str = None) -> None:
    """Wait for the server to be ready by polling the /v1/models endpoint.

    Args:
        base_url: The base URL of the server
        timeout: Maximum time to wait in seconds. None means wait forever.
        api_key: The API key to use for the request
    """
    logger.info(f"Waiting for VLLM server at {base_url} to become ready...")
    start_time = time.time()
    while True:
        try:
            response = requests.get(
                f"{base_url}/v1/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            if response.status_code == 200:
                logger.info("VLLM server is ready.")
                break

            if timeout and time.time() - start_time > timeout:
                error_msg = "Server did not become ready within timeout period"
                logger.error(error_msg)
                raise TimeoutError(error_msg)
        except requests.exceptions.RequestException as e:
            logger.debug(f"Server not ready yet: {str(e)}")
            time.sleep(1)
