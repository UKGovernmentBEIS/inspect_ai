import os
from typing import Any

from inspect_ai.model._providers.util import model_base_url
from inspect_ai.model._providers.util.server_utils import (
    launch_server_cmd,
    terminate_process,
    wait_for_server,
)
from typing_extensions import override

from inspect_ai.model._generate_config import GenerateConfig

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
        port (int): Port to bind the server to (default: None)
        grammar_backend (str): Grammar backend to use (default: "xgrammar")
        server_args (dict): Additional arguments to pass to the SGLang server
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
        # grammar_backend = model_args.pop("grammar_backend", "xgrammar")
        self.server_args = server_args  # model_args.pop("server_args", {})

        # Get base_url from environment or argument
        if not base_url and port:  # if port is provided assume there is a local server
            base_url = f"http://localhost:{port}/v1"
        else:
            base_url = model_base_url(base_url, SGLANG_BASE_URL)

        self.server_process = None
        self.port = port
        self.model_name = model_name

        # Default API key if not provided
        if not api_key:
            api_key = os.environ.get(SGLANG_API_KEY, "local")
        self.api_key = api_key

        # Start server if needed
        if not base_url:
            if "model_path" in self.server_args:
                model_name = self.server_args.pop("model_path")
            base_url = self._start_server(model_name, host, port=None)

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

        # Create server command as a list instead of a string
        cmd = [
            "python", "-m", "sglang.launch_server",
            "--model-path", model_path,
            "--host", host,
            "--api-key", self.api_key,
        ]  # fmt: skip

        # Add additional arguments
        for key, value in self.server_args.items():
            cmd.extend([f"--{key}", str(value)])

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

        # Handle extra_body
        extra_body = {}
        if config.extra_body:
            extra_body.update(config.extra_body)

        if config.response_schema:
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
        elif config.guided_decoding:
            if config.guided_decoding.json_schema:
                params["response_format"] = dict(
                    type="json_schema",
                    json_schema=dict(
                        name=config.guided_decoding.json_schema.name,
                        schema=config.guided_decoding.json_schema.json_schema.model_dump(
                            exclude_none=True
                        ),
                        description=config.guided_decoding.json_schema.description,
                        strict=config.guided_decoding.json_schema.strict,
                    ),
                )
            elif config.guided_decoding.structural_tags:
                params["response_format"] = dict(
                    type="structural_tag",
                    structures=[
                        dict(
                            begin=structure.begin,
                            schema=structure.json_schema.model_dump(exclude_none=True),
                            end=structure.end,
                        )
                        for structure in config.guided_decoding.structural_tags.structures
                    ],
                    triggers=config.guided_decoding.structural_tags.triggers,
                )
            elif config.guided_decoding.grammar:
                extra_body["ebnf"] = config.guided_decoding.grammar
            elif config.guided_decoding.regex:
                extra_body["regex"] = config.guided_decoding.regex

        # Add extra_body to params if it has content
        if extra_body:
            params["extra_body"] = extra_body

        return params
