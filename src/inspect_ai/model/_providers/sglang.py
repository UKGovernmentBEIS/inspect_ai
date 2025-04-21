import atexit
import os
from logging import getLogger
from subprocess import Popen
from typing import Any

from typing_extensions import override

from inspect_ai._util.error import PrerequisiteError, pip_dependency_error
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._providers.util.local_server_utils import (
    merge_env_server_args,
    configure_devices,
    start_local_server,
    terminate_process,
)

from .openai import OpenAIAPI

# Environment variable names
# SGLANG_BASE_URL = "SGLANG_BASE_URL"
# SGLANG_API_KEY = "SGLANG_API_KEY"
SGLANG_DEFAULT_SERVER_ARGS = "SGLANG_DEFAULT_SERVER_ARGS"

logger = getLogger(__name__)


class SGLangAPI(OpenAIAPI):
    """
    Provider for using SGLang models.

    This provider can either:
    1. Connect to an existing SGLang server (if base_url or port is provided)
    2. Start a new SGLang server for the specified model

    Additional server_args:
        host (str): Host to bind the server to (default: "0.0.0.0")
        device (str): Devices to run the server on. Can be a single device or a list of devices as used in CUDA_VISIBLE_DEVICES. If tp is not provided, the server will use the number of devices as the tensor parallel size.

    Environment variables:
        SGLANG_BASE_URL: Base URL for an existing SGLang server
        SGLANG_API_KEY: API key for the SGLang server
        SGLANG_DEFAULT_SERVER_ARGS: JSON string of default server args, e.g. '{"tp": 4, "max_model_len": 8192}'
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
            SGLANG_DEFAULT_SERVER_ARGS, server_args, logger
        )

        try:
            # Try to initialize with existing server
            super().__init__(
                model_name=model_name,
                base_url=base_url,
                api_key=api_key,
                config=config,
                service="SGLang",
                service_base_url=base_url,
            )
            logger.info(f"Using existing SGLang server at {self.base_url}")
        except PrerequisiteError:
            # No existing server found, start a new one
            logger.warning(
                f"Existing SGLang server not found. Starting new server for {model_name}."
            )

            # Start the server
            host = self.server_args.pop("host", "0.0.0.0")
            base_url = self._start_server(model_name, host, port=None)
            atexit.register(self._cleanup_server)
            logger.warning(f"SGLang server started at {base_url}")

            # Initialize with new server
            super().__init__(
                model_name=model_name,
                base_url=base_url,
                api_key=api_key,
                config=config,
                service="SGLang",
                service_base_url=base_url,
            )
        # # Load and merge server args from environment
        # self.server_args = merge_env_server_args(
        #     SGLANG_DEFAULT_SERVER_ARGS, server_args, logger
        # )

        # # Get base_url from environment or argument
        # if not base_url and port:  # if port is provided assume there is a local server
        #     base_url = f"http://localhost:{port}/v1"
        # else:
        #     base_url = model_base_url(base_url, SGLANG_BASE_URL)

        # self.server_process: Popen[str] | None = None
        # self.port: int | None = port

        # # Default API key if not provided
        # if api_key is not None:
        #     self.api_key: str = api_key
        # else:
        #     self.api_key = str(os.environ.get(SGLANG_API_KEY, "local"))

        # # If no base_url is provided, start a new server
        # if not base_url:
        #     logger.warning(
        #         f"Existing SGLang server not found. Starting new server for {model_name}."
        #     )
        #     host = self.server_args.pop("host", "0.0.0.0")
        #     base_url = self._start_server(model_name, host, port=None)
        #     atexit.register(self._cleanup_server)

        #     logger.warning(f"SGLang server started at {base_url}")
        # else:
        #     logger.info(f"Using existing SGLang server at {base_url}")

        # # Initialize OpenAI API with our SGLang server
        # super().__init__(
        #     model_name=model_name,
        #     base_url=base_url,
        #     api_key=api_key,
        #     config=config,
        # )

    def _start_server(self, model_path: str, host: str, port: int | None = None) -> str:
        """Start a new SGLang server and return the base URL.

        Args:
            model_path: Path to the model to use
            host: Host to bind the server to
            port: Port to bind the server to
        Returns:
            str: The base URL for the server
        """
        # Verify sglang package is installed since we're starting a server
        try:
            import sglang  # type: ignore  # noqa: F401
        except ImportError:
            raise pip_dependency_error("SGLang Server", ["sglang"])

        # Handle device configuration
        self.server_args = configure_devices(self.server_args, parallel_size_param="tp")

        # Create server command as a list instead of a string
        cmd = [
            "python", "-m", "sglang.launch_server",
            "--model-path", model_path,
            "--host", host,
            "--api-key", self.api_key,
            # while the default backend is supposed to be xgrammar, for some reason leaving this
            # unspecified causes the server to fail when using ebnf grammars
            "--grammar-backend", self.server_args.pop("grammar_backend", "xgrammar"),
        ]  # fmt: skip

        # Add additional arguments
        for key, value in self.server_args.items():
            cmd.extend([f"--{key}", str(value)])

        base_url, self.server_process, self.port = start_local_server(
            cmd, host=host, port=port, api_key=self.api_key, server_type="SGLang"
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
            logger.info("Cleaning up SGLang server")
            terminate_process(self.server_process)
            self.server_process, self.port = None, None

    async def aclose(self) -> None:
        """Close the client and terminate the server if we started it."""
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

        # if config.response_schema is not None and config.guided_decoding is not None:
        #     raise ValueError(
        #         "response_schema and guided_decoding cannot both be set. Please set only one of them."
        #     )

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
        # elif config.guided_decoding:
        #     if config.guided_decoding.json_schema:
        #         params["response_format"] = dict(
        #             type="json_schema",
        #             json_schema=dict(
        #                 name=config.guided_decoding.json_schema.name,
        #                 schema=config.guided_decoding.json_schema.json_schema.model_dump(
        #                     exclude_none=True
        #                 ),
        #                 description=config.guided_decoding.json_schema.description,
        #                 strict=config.guided_decoding.json_schema.strict,
        #             ),
        #         )
        #     elif config.guided_decoding.structural_tags:
        #         params["response_format"] = dict(
        #             type="structural_tag",
        #             structures=[
        #                 dict(
        #                     begin=structure.begin,
        #                     schema=structure.json_schema.model_dump(exclude_none=True),
        #                     end=structure.end,
        #                 )
        #                 for structure in config.guided_decoding.structural_tags.structures
        #             ],
        #             triggers=config.guided_decoding.structural_tags.triggers,
        #         )
        #     elif config.guided_decoding.grammar:
        #         extra_body["ebnf"] = config.guided_decoding.grammar
        #     elif config.guided_decoding.regex:
        #         extra_body["regex"] = config.guided_decoding.regex
        #     elif config.guided_decoding.choice:
        #         # choice is not natively supported by SGLang, so we need to convert it to a regex format
        #         regex = "|".join(config.guided_decoding.choice)
        #         extra_body["regex"] = regex

        # Add extra_body to params if it has content
        if extra_body:
            params["extra_body"] = extra_body

        return params
