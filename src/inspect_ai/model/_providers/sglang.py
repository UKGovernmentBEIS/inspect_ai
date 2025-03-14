import os
from typing import Any

from sglang.utils import launch_server_cmd, terminate_process, wait_for_server
from typing_extensions import override

from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._providers.util import model_base_url

from .openai import OpenAIAPI

# Environment variable names
SGLANG_BASE_URL = "SGLANG_BASE_URL"
SGLANG_API_KEY = "SGLANG_API_KEY"
SGLANG_MODEL_PATH = "SGLANG_MODEL_PATH"


class SGLangAPI(OpenAIAPI):
    """
    Provider for using SGLang models.

    This provider can either:
    1. Connect to an existing SGLang server (if base_url is provided)
    2. Start a new SGLang server for the specified model

    Additional model_args:
        model_path (str): The model path to use with SGLang (e.g., "meta-llama/Meta-Llama-3.1-8B-Instruct")
        host (str): Host to bind the server to (default: "0.0.0.0")
        grammar_backend (str): Grammar backend to use (default: "xgrammar")
        server_args (dict): Additional arguments to pass to the SGLang server
    """

    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        config: GenerateConfig = GenerateConfig(),
        **server_args: Any,
    ) -> None:
        host = server_args.pop("host", "0.0.0.0")
        # grammar_backend = model_args.pop("grammar_backend", "xgrammar")
        self.server_args = server_args  # model_args.pop("server_args", {})

        # Get base_url from environment or argument
        base_url = model_base_url(base_url, SGLANG_BASE_URL)
        self.server_process = None
        self.port = None
        self.model_name = model_name

        # Start server if needed
        if not base_url:
            if "model_path" in self.server_args:
                model_name = self.server_args.pop("model_path")
            base_url = self._start_server(model_name, host, port=None)

        # Default API key if not provided
        if not api_key:
            api_key = os.environ.get(SGLANG_API_KEY, "local")

        # Initialize OpenAI API with our SGLang server
        super().__init__(
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            config=config,
            # **server_args,
        )

    def _start_server(self, model_path: str, host: str, port: int | None = None) -> str:
        """Start a new SGLang server and return the base URL.

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
                "No model_path provided for SGLang. Please specify a model_path argument or set the SGLANG_MODEL_PATH environment variable."
            )

        if "device" in self.server_args:
            if isinstance(self.server_args["device"], list):
                self.server_args["device"] = ",".join(
                    map(str, self.server_args["device"])
                )
            os.environ["CUDA_VISIBLE_DEVICES"] = str(self.server_args["device"])
            if "tp" not in self.server_args:
                devices = os.environ.get("CUDA_VISIBLE_DEVICES", "").split(",")
                self.server_args["tp"] = len(devices)

            self.server_args.pop("device")

        # Create server command
        cmd = f"python -m sglang.launch_server --model-path {model_path} --host {host}"

        # Add additional arguments
        for key, value in self.server_args.items():
            cmd += f" --{key} {value}"

        try:
            # Launch server
            self.server_process, self.port = launch_server_cmd(cmd, port=port)
            base_url = f"http://localhost:{self.port}/v1"
            wait_for_server(f"http://localhost:{self.port}")
        except Exception as e:
            # Cleanup any partially started server
            if self.server_process:
                try:
                    terminate_process(self.server_process)
                except Exception:
                    if hasattr(self.server_process, "terminate"):
                        self.server_process.terminate()

            # Re-raise with more context
            raise RuntimeError(f"Failed to start SGLang server: {str(e)}") from e

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
