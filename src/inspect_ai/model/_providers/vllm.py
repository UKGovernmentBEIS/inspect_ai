import functools
import logging
import os
import socket
from subprocess import Popen
from typing import Any
from urllib.parse import urlparse

import anyio
from openai import APIConnectionError, APIStatusError
from tenacity.wait import WaitBaseT, wait_fixed
from typing_extensions import override

from inspect_ai._util.content import (
    Content,
    ContentImage,
    ContentReasoning,
    ContentText,
)
from inspect_ai._util.error import pip_dependency_error
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
    VLLMServer,
    _vllm_servers,
    ensure_adapter_loaded,
    get_adapter_rank,
    parse_vllm_model,
)
from .openai_compatible import OpenAICompatibleAPI

VLLM_DEFAULT_SERVER_ARGS = "VLLM_DEFAULT_SERVER_ARGS"
VLLM_CONFIGURE_LOGGING = "VLLM_CONFIGURE_LOGGING"

logger = logging.getLogger(__name__)


class VLLMAPI(OpenAICompatibleAPI):
    """Provider for using vLLM models with optional LoRA adapter support.

    This provider can either:
    1. Connect to an existing vLLM server (if base_url or port is provided)
    2. Start a new vLLM server for the specified model

    LoRA adapters are specified with ``"base-model:adapter"`` syntax::

        get_model("vllm/meta-llama/Llama-3-8B:myorg/my-lora-adapter")

    Multiple models sharing the same base reuse a single server.  The
    server is started lazily on the first ``generate()`` call, after all
    model ``__init__`` calls have completed so that ``enable_lora`` and
    ``max_lora_rank`` are computed correctly across all adapters.

    Args:
        model_name (str): Name or path of the model to use. Optionally
            include ``:adapter`` suffix to specify a LoRA adapter from
            HuggingFace or a local path.
        base_url (str | None): Base URL of an existing vLLM server. If
            not provided, a new server will be started on localhost.
        port (int | None): Port of an existing vLLM server on localhost.
            If not provided, a free port is chosen automatically.
        api_key (str | None): API key for the vLLM server. Defaults to
            the ``VLLM_API_KEY`` env var, or ``"inspectai"`` if unset.
        config (GenerateConfig): Configuration for generation. Defaults
            to ``GenerateConfig()``.
        is_mistral (bool): Whether the model is a Mistral model. If
            ``True``, user messages immediately following tool messages
            are folded together (Mistral does not support this sequence).
            Defaults to ``False``.
        retry_delay (int | None): Seconds to wait between retries
            (default 5).
        lazy_init (bool): If ``True`` (default), defer server startup to
            the first ``generate()`` call.  This ensures ``enable_lora``
            and ``max_lora_rank`` are computed correctly when multiple
            models share a base.  Set to ``False`` to start the server
            immediately in ``__init__`` (useful for single-model setups
            where you want fast failure on misconfiguration).
        **server_args: Additional arguments forwarded to the ``vllm
            serve`` command.  Notable keys:

            - ``timeout`` (int): Server startup timeout in seconds
              (default: 10 minutes).
            - ``host`` (str): Host to bind the server to (default:
              ``"0.0.0.0"``).
            - ``configure_logging`` (bool): Enable fine-grained vLLM
              logging (default: ``False``).
            - ``device`` / ``devices`` (str): GPU device(s) to run the
              server on, as used in ``CUDA_VISIBLE_DEVICES``. If
              ``tensor_parallel_size`` is not provided, it is set to the
              number of devices automatically.
            - ``enable_lora`` (bool): Force LoRA mode even without
              ``:adapter`` syntax (default: auto-detected from model
              name).

    Environment variables:
        VLLM_BASE_URL: Base URL for an existing vLLM server.
        VLLM_API_KEY: API key for the vLLM server.
        VLLM_DEFAULT_SERVER_ARGS: JSON string of default server args,
            e.g. ``'{"tensor_parallel_size": 4, "max_model_len": 8192}'``.
        VLLM_CONFIGURE_LOGGING: Enable fine-grained vLLM logging.
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
        lazy_init: bool = True,
        **server_args: Any,
    ) -> None:
        # Parse "base-model" or "base-model:adapter-path"
        self.base_model, self.adapter_path, self.adapter_name = parse_vllm_model(
            model_name
        )

        if base_url and port:
            raise ValueError("base_url and port cannot both be provided.")

        self.api_key = api_key or os.environ.get("VLLM_API_KEY", "inspectai")
        self.model_name = self.base_model
        self.base_url: str | None = None

        # Store for deferred OpenAICompatibleAPI.__init__()
        self._init_config = config
        self._init_base_url = f"http://localhost:{port}/v1" if port else base_url
        self._server_resolved = False

        self.is_mistral = is_mistral
        self.retry_delay = retry_delay or DEFAULT_RETRY_DELAY
        self.port = port
        self.server_args = merge_env_server_args(
            VLLM_DEFAULT_SERVER_ARGS, server_args, logger
        )

        # Get or create the shared server entry for this base model
        # and incrementally update LoRA config.
        self._server = _vllm_servers.setdefault(self.base_model, VLLMServer())
        if self.adapter_path:
            self._server.enable_lora = True
            rank = get_adapter_rank(self.adapter_path)
            if rank is not None:
                self._server.max_lora_rank = max(self._server.max_lora_rank or 0, rank)

        if not lazy_init:
            self._resolve_server()

    # -- server lifecycle ----------------------------------------------------

    def _resolve_server(self) -> None:
        """Resolve or start the vLLM server, then call ``super().__init__``."""
        if self._server_resolved:
            return

        server = self._server

        if server.base_url is None:
            external_url = self._init_base_url or os.environ.get("VLLM_BASE_URL")
            server.api_key = self.api_key
            if external_url:
                server.base_url = external_url
            else:
                base_url, process, port = self._start_server(self.base_model, self.port)
                logger.info(f"vLLM server started at {base_url}")

                server.base_url = base_url
                server.process = process
                server.port = port

        super().__init__(
            model_name=self.base_model,
            base_url=server.base_url,
            api_key=self.api_key,
            config=self._init_config,
            service="vLLM",
            service_base_url=server.base_url,
        )
        self._server_resolved = True

        if self.adapter_path and self.adapter_name:
            ensure_adapter_loaded(self._server, self.adapter_path, self.adapter_name)

    async def _ensure_server_started(self) -> None:
        """Lazy version of ``_resolve_server`` — thread-safe for concurrent ``generate()`` calls."""
        if self._server_resolved:
            return
        async with self._server._init_lock:
            await anyio.to_thread.run_sync(self._resolve_server)

    def _start_server(
        self,
        model_path: str,
        port: int | None = None,
    ) -> tuple[str, Popen[str], int]:
        """Start a new vLLM server subprocess.

        Args:
            model_path: HuggingFace model ID or local path.
            port: Port to bind to. If ``None``, a free port is chosen.

        Returns:
            Tuple of (base_url, process, port).
        """
        try:
            import vllm  # type: ignore  # noqa: F401
        except ImportError:
            raise pip_dependency_error("vLLM Server", ["vllm"])

        server = self._server
        if server.enable_lora:
            self.server_args.setdefault("enable_lora", True)
            if server.max_lora_rank is not None:
                self.server_args.setdefault("max_lora_rank", server.max_lora_rank)
            os.environ["VLLM_ALLOW_RUNTIME_LORA_UPDATING"] = "True"

        configure_logging = self.server_args.pop("configure_logging", False)
        os.environ[VLLM_CONFIGURE_LOGGING] = "1" if configure_logging else "0"

        self.server_args, env_vars = configure_devices(
            self.server_args, parallel_size_param="tensor_parallel_size"
        )

        timeout = self.server_args.pop("timeout", None)
        host = self.server_args.pop("host", "0.0.0.0")

        cmd = [
            "vllm",
            "serve",
            model_path,
            "--host",
            host,
            "--api-key",
            self.api_key,
        ]

        base_url, process, found_port = start_local_server(
            cmd,
            host=host,
            port=port,
            api_key=self.api_key,
            server_type="vLLM",
            timeout=timeout,
            server_args=self.server_args,
            env=env_vars,
        )
        return base_url, process, found_port

    @property
    def server_is_running(self) -> bool:
        """Check if the server process is still alive."""
        if self._server.process is None:
            return False
        return self._server.process.poll() is None

    async def aclose(self) -> None:
        """Close the OpenAI client and terminate the server if we started it."""
        if self._server_resolved:
            await super().aclose()
        self.close()

    def close(self) -> None:
        """Terminate the server if we spawned it.

        Does not close the OpenAI client (use ``aclose`` for that).
        """
        if self._server.process is not None and self._server.process.poll() is None:
            logger.info("Cleaning up vLLM server")
            terminate_process(self._server.process)
            self._server.process = None

    # -- ModelAPI overrides --------------------------------------------------

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
        """Return adapter name for LoRA requests, else the base model.

        vLLM's OpenAI-compatible API routes LoRA requests by the ``model``
        field, so we send the adapter name instead of the base model when
        a LoRA adapter is in use.
        """
        if self.adapter_name:
            return self.adapter_name
        return self.base_model

    @override
    def should_retry(self, ex: BaseException) -> bool:
        if _is_fatal_vllm_error(ex):
            logger.error(
                "Detected fatal vLLM error (OOM/illegal CUDA state); not retrying."
            )
            return False

        if _is_dead_local_vllm_endpoint(ex, self.base_url):
            logger.error(
                "vLLM endpoint %s is unreachable. Failing fast.",
                self.base_url,
            )
            return False

        if self._server.process is not None and not self.server_is_running:
            logger.error("Inspect-managed vLLM server process exited; not retrying.")
            return False

        return super().should_retry(ex)

    # -- generation ----------------------------------------------------------

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput | tuple[ModelOutput | Exception, ModelCall]:
        await self._ensure_server_started()

        # If the last message is from the assistant, continue it rather
        # than starting a new generation turn.
        if input[-1].role == "assistant":
            config = config.model_copy()
            if config.extra_body is None:
                config.extra_body = {}
            if (
                "add_generation_prompt" not in config.extra_body
                and "continue_final_message" not in config.extra_body
            ):
                config.extra_body["add_generation_prompt"] = False
                config.extra_body["continue_final_message"] = True

        # Mistral does not support a user message immediately after a tool
        # message, so fold them together.
        if self.is_mistral:
            input = functools.reduce(mistral_message_reducer, input, [])

        return await super().generate(input, tools, tool_choice, config)

    @override
    def handle_bad_request(self, ex: APIStatusError) -> ModelOutput | Exception:
        if ex.status_code == 400:
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_fatal_vllm_error(ex: BaseException) -> bool:
    """Match vLLM startup OOM and CUDA OOM variants that are not transient."""
    fatal_markers = (
        "free memory on device",
        "less than desired gpu memory utilization",
        "cuda out of memory",
        "torch.outofmemoryerror",
        "cuda error: an illegal memory access was encountered",
        "cudaerrorillegaladdress",
        "torch.acceleratorerror",
    )

    seen: set[int] = set()
    current: BaseException | None = ex
    messages: list[str] = []

    while current is not None and id(current) not in seen:
        seen.add(id(current))
        messages.append(str(current))
        current = current.__cause__ or current.__context__

    error_text = " ".join(messages).lower()
    return any(marker in error_text for marker in fatal_markers)


def _is_dead_local_vllm_endpoint(ex: BaseException, base_url: str | None) -> bool:
    """Short-circuit connection failures for localhost endpoints only."""
    if not isinstance(ex, APIConnectionError):
        return False
    if not base_url:
        return False

    parsed = urlparse(base_url)
    host = (parsed.hostname or "").lower()
    if host not in {"localhost", "127.0.0.1", "::1"}:
        return False

    port = parsed.port
    if port is None:
        port = 443 if parsed.scheme == "https" else 80

    try:
        with socket.create_connection((host, port), timeout=0.2):
            return False
    except OSError:
        return True


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
