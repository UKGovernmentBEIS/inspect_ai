"""LoRA adapter support for vLLM provider.

Provides:
- Parsing vLLM model names with LoRA adapter syntax (base:adapter)
- Shared server state tracking to enable server reuse across models
- Dynamic LoRA adapter loading via vLLM's HTTP API
"""

from __future__ import annotations

import atexit
import json
import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from subprocess import Popen

import anyio
import httpx

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LoRAAdapter:
    """A LoRA adapter reference: HF repo or local path, plus optional revision.

    Frozen so it can be used as a ``set`` / ``dict`` key.

    ``is_preloaded`` distinguishes adapters that should be loaded by this
    process (HF repo or on-disk path) from bare names that name an
    adapter already registered on an external vLLM server (used with
    ``VLLM_BASE_URL``). For the latter we skip the HF rank-detection
    and load-on-startup paths.
    """

    path: str
    revision: str | None = None
    is_preloaded: bool = False

    @property
    def name(self) -> str:
        """vLLM-side ``lora_name`` for this adapter.

        Format: ``"<path>"`` or ``"<path>@<revision>"``. Encoding the
        revision in the name disambiguates same-path-different-revision
        loads on one server, and makes ``/v1/models`` self-describing.
        """
        return f"{self.path}@{self.revision}" if self.revision else self.path

    @classmethod
    def from_suffix(cls, suffix: str) -> "LoRAAdapter":
        """Parse the post-colon suffix of a vLLM model name.

        Accepts a local path that exists on disk, a HuggingFace repo
        (``org/name``), or either with an ``@revision`` suffix. A bare
        name (no ``/`` and not a local path) is treated as the
        ``lora_name`` of an adapter already loaded on an external
        server.
        """
        if Path(suffix).exists():
            return cls(path=suffix)
        path, _, revision = suffix.partition("@")
        if "/" not in path:
            return cls(path=suffix, is_preloaded=True)
        if "@" in suffix and not revision:
            raise ValueError(
                "Empty revision after '@'. Use 'org/my-adapter@<branch|tag|commit>'."
            )
        return cls(path=path, revision=revision or None)


@dataclass
class VLLMServer:
    """Shared state for a vLLM server serving a given base model.

    Created during __init__ (synchronous). LoRA fields are incrementally
    updated as each VLLMAPI instance registers its adapter. Connection
    fields are set once on first generate() when the server is resolved
    or started.
    """

    # LoRA config — incrementally updated during __init__
    enable_lora: bool = False
    max_lora_rank: int | None = None

    # Connection — set when server is resolved/started
    base_url: str | None = None
    api_key: str | None = None
    port: int | None = None
    process: Popen[str] | None = None

    # Set of adapters registered on the server (vLLM name is ``adapter.name``).
    loaded_adapters: set[LoRAAdapter] = field(default_factory=set)

    # Lifecycle epoch — bumped by close() so all instances know to re-resolve
    _epoch: int = 0

    # Lock for server startup (protects base_url check → start → assign)
    _init_lock: anyio.Lock = field(default_factory=anyio.Lock)
    # Lock for adapter loading (protects loaded check → HTTP load → add)
    _load_lock: threading.Lock = field(default_factory=threading.Lock)


# base_model → server state
_vllm_servers: dict[str, VLLMServer] = {}


def parse_vllm_model(model_name: str) -> tuple[str, LoRAAdapter | None]:
    """Parse vLLM model name into base model and optional LoRA adapter.

    Supports syntax: ``"base-model"``, ``"base-model:adapter-name"``,
    or ``"base-model:adapter/path[@revision]"``. Splits on the first
    colon only (the adapter path may itself contain colons, e.g. for
    URLs).

    Args:
        model_name: Model name, optionally with ``:adapter[@revision]`` suffix.

    Returns:
        Tuple of (base_model, adapter). The adapter is ``None`` if no
        LoRA suffix was provided.

    Examples:
        >>> parse_vllm_model("meta-llama/Llama-3-8B")
        ('meta-llama/Llama-3-8B', None)
        >>> parse_vllm_model("meta-llama/Llama-3-8B:org/my-adapter")
        ('meta-llama/Llama-3-8B', LoRAAdapter(path='org/my-adapter', revision=None))
        >>> parse_vllm_model("meta-llama/Llama-3-8B:org/my-adapter@v2")
        ('meta-llama/Llama-3-8B', LoRAAdapter(path='org/my-adapter', revision='v2'))
    """
    if ":" not in model_name:
        return (model_name, None)
    # Split on first colon only (adapter path may contain colons for URLs)
    base, suffix = model_name.split(":", 1)
    return (base, LoRAAdapter.from_suffix(suffix))


def get_adapter_rank(adapter: LoRAAdapter) -> int | None:
    """Get the LoRA rank from an adapter's configuration.

    Reads the ``r`` field from ``adapter_config.json``, looking first
    for a local file and falling back to downloading from HuggingFace
    (at ``adapter.revision`` if specified). Returns ``None`` for
    pre-loaded external adapters (their config isn't reachable from
    this process) and when the field can't be read.

    Args:
        adapter: The adapter to inspect.

    Returns:
        The LoRA rank (``r``) value, or ``None`` if it cannot be determined.
    """
    if adapter.is_preloaded:
        return None

    local_path = Path(adapter.path) / "adapter_config.json"
    if local_path.exists():
        config_path: Path = local_path
    else:
        downloaded = _download_adapter_config(adapter)
        if downloaded is None:
            return None
        config_path = downloaded

    with open(config_path) as f:
        adapter_config = json.load(f)

    if "r" not in adapter_config:
        logger.warning(
            f"adapter_config.json for {adapter.name} has no 'r' field. "
            f"Skipping max_lora_rank auto-detection."
        )
        return None

    rank: int = adapter_config["r"]
    logger.info(f"Detected LoRA rank {rank} for adapter {adapter.name}")
    return rank


def _download_adapter_config(adapter: LoRAAdapter) -> Path | None:
    """Download adapter_config.json from HuggingFace Hub.

    Returns:
        Path to the downloaded config file, or ``None`` if not found.
    """
    from huggingface_hub import hf_hub_download
    from huggingface_hub.errors import EntryNotFoundError

    try:
        return Path(
            hf_hub_download(
                adapter.path, "adapter_config.json", revision=adapter.revision
            )
        )
    except EntryNotFoundError:
        logger.warning(
            f"Could not fetch adapter_config.json for {adapter.name}. "
            f"Skipping max_lora_rank auto-detection."
        )
        return None


def _normalize_api_base(base_url: str) -> str:
    """Strip trailing ``/v1`` and slash to get the root server URL."""
    url = base_url.rstrip("/")
    if url.endswith("/v1"):
        url = url[:-3]
    return url


def _load_adapter(base_url: str, adapter: LoRAAdapter, api_key: str) -> None:
    """Load a LoRA adapter on the vLLM server via its HTTP API.

    Args:
        base_url: vLLM server base URL (may include ``/v1`` suffix).
        adapter: The adapter to load.
        api_key: API key for authentication.

    Raises:
        RuntimeError: If the adapter endpoint is missing (404) or the
            adapter fails to load (400).
    """
    api_base = _normalize_api_base(base_url)
    lora_path = adapter.path
    if adapter.revision is not None:
        from huggingface_hub import snapshot_download

        lora_path = snapshot_download(adapter.path, revision=adapter.revision)

    with httpx.Client() as client:
        response = client.post(
            f"{api_base}/v1/load_lora_adapter",
            json={"lora_name": adapter.name, "lora_path": lora_path},
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=120.0,
        )

        if response.status_code == 404:
            raise RuntimeError(
                "LoRA adapter endpoint not found. The vLLM server may not have "
                "been started with --enable-lora. If using an external server "
                "(VLLM_BASE_URL), restart with: vllm serve MODEL --enable-lora"
            )

        if response.status_code == 400:
            raise RuntimeError(
                f"Failed to load LoRA adapter '{adapter.name}': {response.text}\n"
                f"Common causes:\n"
                f"  - Adapter not found (check HuggingFace repo or local path)\n"
                f"  - Adapter incompatible with base model\n"
                f"  - Adapter rank exceeds server's max_lora_rank"
            )

        response.raise_for_status()
        logger.info(f"Loaded LoRA adapter: {adapter.name}")


def _adapter_on_server(base_url: str, adapter_name: str, api_key: str) -> bool:
    """Check whether the vLLM server already lists *adapter_name*."""
    api_base = _normalize_api_base(base_url)
    with httpx.Client() as client:
        response = client.get(
            f"{api_base}/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10.0,
        )
        response.raise_for_status()
        model_ids = [m.get("id") for m in response.json().get("data", [])]
        return adapter_name in model_ids


def ensure_adapter_loaded(server: VLLMServer, adapter: LoRAAdapter) -> None:
    """Ensure a LoRA adapter is loaded on the server.

    Idempotent and thread-safe. Checks the local ``loaded_adapters``
    set first, then queries the server's ``/v1/models`` endpoint (the
    adapter may have been loaded externally), and finally loads via
    ``/v1/load_lora_adapter`` if needed.

    Called from ``_resolve_server`` (sync). In the async path this runs
    inside ``anyio.to_thread.run_sync``, matching the existing pattern
    for ``_resolve_server`` / ``_ensure_server_started``.

    Args:
        server: Shared server state (must have ``base_url`` set).
        adapter: The adapter to register.

    Raises:
        RuntimeError: If adapter loading fails.
    """
    if adapter in server.loaded_adapters:
        return

    with server._load_lock:
        if adapter in server.loaded_adapters:
            return

        if server.base_url is None or server.api_key is None:
            raise RuntimeError("Server must be resolved before loading adapters")

        try:
            if _adapter_on_server(server.base_url, adapter.name, server.api_key):
                logger.info(
                    f"LoRA adapter '{adapter.name}' already available on server"
                )
                server.loaded_adapters.add(adapter)
                return
        except httpx.HTTPStatusError as e:
            logger.warning(f"Failed to check adapter availability: {e}")
            raise

        if adapter.is_preloaded:
            raise RuntimeError(
                f"LoRA adapter '{adapter.name}' is not registered on the vLLM "
                f"server, and as a bare name (no '/') it cannot be loaded as a "
                f"HuggingFace repo or local path. Either pre-load it on the "
                f"server before connecting, or use 'org/name[@revision]' or "
                f"'/local/path' syntax."
            )

        logger.info(f"Loading LoRA adapter: {adapter.name}")
        _load_adapter(server.base_url, adapter, server.api_key)
        server.loaded_adapters.add(adapter)


def cleanup_servers() -> None:
    """Terminate all spawned vLLM servers. Called at process exit."""
    from inspect_ai._util.local_server import terminate_process

    for base_model, server in list(_vllm_servers.items()):
        if server.process is not None:
            logger.info(f"Cleaning up vLLM server for {base_model}")
            terminate_process(server.process)
            server.process = None
    _vllm_servers.clear()


atexit.register(cleanup_servers)
