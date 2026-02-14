"""LoRA adapter support for vLLM provider.

This module provides utilities for:
- Parsing vLLM model names with LoRA adapter syntax (base:adapter)
- Tracking vLLM servers by base model to enable server reuse
- Dynamically loading LoRA adapters via vLLM's API
"""

from __future__ import annotations

import asyncio
import atexit
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from subprocess import Popen
from typing import Any

import httpx

logger = logging.getLogger(__name__)


@dataclass
class VLLMServerInfo:
    """Information about a running vLLM server."""

    base_url: str
    api_key: str
    port: int | None = None
    process: Popen[str] | None = None
    lora_enabled: bool = False
    is_external: bool = False
    loaded_adapters: set[str] = field(default_factory=set)
    _adapter_locks: dict[str, asyncio.Lock] = field(default_factory=dict)

    def get_adapter_lock(self, adapter_path: str) -> asyncio.Lock:
        """Get or create a lock for the given adapter path."""
        if adapter_path not in self._adapter_locks:
            self._adapter_locks[adapter_path] = asyncio.Lock()
        return self._adapter_locks[adapter_path]


# Global tracking for vLLM servers by base model
# Key: (base_model, external_base_url or None)
# Value: VLLMServerInfo
_vllm_servers: dict[tuple[str, str | None], VLLMServerInfo] = {}


def parse_vllm_model(model_name: str) -> tuple[str, str | None, str | None]:
    """Parse vLLM model name into base model and optional LoRA adapter.

    Supports syntax: "base-model" or "base-model:adapter-path"

    Args:
        model_name: Model name, optionally with :adapter suffix

    Returns:
        Tuple of (base_model, adapter_path, adapter_name) where:
        - base_model: The base model identifier
        - adapter_path: HuggingFace repo or local path (None if no adapter)
        - adapter_name: Sanitized name for vLLM API (None if no adapter)

    Examples:
        >>> parse_vllm_model("meta-llama/Llama-3-8B")
        ("meta-llama/Llama-3-8B", None, None)
        >>> parse_vllm_model("meta-llama/Llama-3-8B:org/my-adapter")
        ("meta-llama/Llama-3-8B", "org/my-adapter", "org_my-adapter")
        >>> parse_vllm_model("llama:./local/path/adapter")
        ("llama", "./local/path/adapter", "._local_path_adapter")
    """
    if ":" not in model_name:
        return (model_name, None, None)

    # Split on first colon only (adapter path may contain colons for URLs)
    base, adapter_path = model_name.split(":", 1)

    # Sanitize adapter path to create valid vLLM adapter name
    # Replace / with _ to create a flat identifier
    adapter_name = adapter_path.replace("/", "_")

    return (base, adapter_path, adapter_name)


def get_adapter_rank(adapter_path: str) -> int | None:
    """Get the LoRA rank from an adapter's configuration.

    Supports both local paths and HuggingFace repo IDs. Returns None if
    the rank cannot be determined (missing config, missing field, etc.).

    Args:
        adapter_path: Local path or HuggingFace repo ID for the adapter.

    Returns:
        The LoRA rank (r) value from adapter_config.json, or None on failure.
    """
    local_path = Path(adapter_path) / "adapter_config.json"
    if local_path.exists():
        config_path: Path = local_path
    else:
        downloaded = _download_adapter_config(adapter_path)
        if downloaded is None:
            return None
        config_path = downloaded

    with open(config_path) as f:
        adapter_config = json.load(f)

    if "r" not in adapter_config:
        logger.warning(
            f"adapter_config.json for {adapter_path} has no 'r' field. "
            f"Skipping max_lora_rank auto-detection."
        )
        return None

    rank: int = adapter_config["r"]
    logger.info(f"Detected LoRA rank {rank} for adapter {adapter_path}")
    return rank


def _download_adapter_config(adapter_path: str) -> Path | None:
    """Download adapter_config.json from HuggingFace Hub.

    Returns:
        Path to downloaded config, or None if not found.
    """
    from huggingface_hub import hf_hub_download
    from huggingface_hub.errors import EntryNotFoundError

    try:
        return Path(hf_hub_download(adapter_path, "adapter_config.json"))
    except EntryNotFoundError:
        logger.warning(
            f"Could not fetch adapter_config.json for {adapter_path}. "
            f"Skipping max_lora_rank auto-detection."
        )
        return None


# Pre-computed LoRA config from model list scanning.
# Key: base_model, Value: {"enable_lora": bool, "max_lora_rank": int}
_precomputed_lora_config: dict[str, dict[str, Any]] = {}


def precompute_vllm_lora_config(model_names: list[str]) -> None:
    """Pre-scan vLLM model names to compute LoRA server config.

    Scans all vLLM model names for adapter syntax and computes the
    max LoRA rank across all adapters sharing the same base model.
    Results are stored in a module-level dict for VLLMProvider to read.

    Args:
        model_names: List of model name strings (may include non-vLLM models).
    """
    _precomputed_lora_config.clear()

    for name in model_names:
        if not name.startswith("vllm/"):
            continue
        # Strip the "vllm/" prefix before parsing
        base_model, adapter_path, _ = parse_vllm_model(name[len("vllm/") :])
        if adapter_path is None:
            continue

        rank = get_adapter_rank(adapter_path)

        if base_model not in _precomputed_lora_config:
            _precomputed_lora_config[base_model] = {"enable_lora": True}
        if rank is not None:
            prev = _precomputed_lora_config[base_model].get("max_lora_rank")
            _precomputed_lora_config[base_model]["max_lora_rank"] = (
                max(prev, rank) if prev is not None else rank
            )

    for base_model, config in _precomputed_lora_config.items():
        logger.info(f"Pre-computed vLLM LoRA config for {base_model}: {config}")


def get_precomputed_lora_config(base_model: str) -> dict[str, Any] | None:
    """Get pre-computed LoRA config for a base model, if available."""
    return _precomputed_lora_config.get(base_model)


def get_server_for_model(
    base_model: str, external_base_url: str | None = None
) -> VLLMServerInfo | None:
    """Get existing server info for a base model if available.

    Args:
        base_model: The base model identifier
        external_base_url: External server URL if using VLLM_BASE_URL

    Returns:
        VLLMServerInfo if server exists, None otherwise
    """
    return _vllm_servers.get((base_model, external_base_url))


def register_server(
    base_model: str,
    server_info: VLLMServerInfo,
    external_base_url: str | None = None,
) -> None:
    """Register a vLLM server for a base model.

    Args:
        base_model: The base model identifier
        server_info: Server information to register
        external_base_url: External server URL if using VLLM_BASE_URL
    """
    _vllm_servers[(base_model, external_base_url)] = server_info


async def check_adapter_available(
    base_url: str, adapter_name: str, api_key: str
) -> bool:
    """Check if a LoRA adapter is available on the vLLM server.

    Args:
        base_url: vLLM server base URL (with /v1 suffix)
        adapter_name: Name of the adapter to check
        api_key: API key for authentication

    Returns:
        True if adapter is listed in /v1/models, False otherwise
    """
    # Normalize URL - remove trailing /v1 if present for consistent handling
    api_base = base_url.rstrip("/")
    if api_base.endswith("/v1"):
        api_base = api_base[:-3]

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{api_base}/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10.0,
        )
        response.raise_for_status()
        data = response.json()

        model_ids = [m.get("id") for m in data.get("data", [])]
        return adapter_name in model_ids


async def load_adapter(
    base_url: str,
    adapter_name: str,
    adapter_path: str,
    api_key: str,
) -> None:
    """Load a LoRA adapter on the vLLM server.

    Args:
        base_url: vLLM server base URL (with /v1 suffix)
        adapter_name: Name to register the adapter under
        adapter_path: HuggingFace repo or local path to adapter
        api_key: API key for authentication

    Raises:
        RuntimeError: If adapter loading fails with actionable error message
    """
    # Normalize URL
    api_base = base_url.rstrip("/")
    if api_base.endswith("/v1"):
        api_base = api_base[:-3]

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{api_base}/v1/load_lora_adapter",
            json={"lora_name": adapter_name, "lora_path": adapter_path},
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=120.0,  # Loading can take time for large adapters
        )

        if response.status_code == 404:
            raise RuntimeError(
                "LoRA adapter endpoint not found. The vLLM server may not have been "
                "started with --enable-lora flag. If using external server "
                "(VLLM_BASE_URL), restart with: vllm serve MODEL --enable-lora"
            )

        if response.status_code == 400:
            error_text = response.text
            raise RuntimeError(
                f"Failed to load LoRA adapter '{adapter_path}': {error_text}\n"
                f"Common causes:\n"
                f"  - Adapter not found (check HuggingFace repo or local path)\n"
                f"  - Adapter incompatible with base model\n"
                f"  - Adapter configuration issues"
            )

        response.raise_for_status()
        logger.info(f"Successfully loaded LoRA adapter: {adapter_name}")


async def ensure_adapter_loaded(
    server_info: VLLMServerInfo,
    adapter_path: str,
    adapter_name: str,
) -> None:
    """Ensure a LoRA adapter is loaded on the vLLM server.

    This function is idempotent and thread-safe. It checks if the adapter
    is already loaded before attempting to load it.

    Args:
        server_info: Server information including URL and loaded adapters
        adapter_path: HuggingFace repo or local path to adapter
        adapter_name: Name to register/use the adapter under

    Raises:
        RuntimeError: If adapter loading fails
    """
    # Fast path: already loaded in our tracking
    if adapter_path in server_info.loaded_adapters:
        return

    # Acquire per-adapter lock to prevent duplicate loading
    lock = server_info.get_adapter_lock(adapter_path)
    async with lock:
        # Double-check after acquiring lock
        if adapter_path in server_info.loaded_adapters:
            return

        # Check if adapter is already available on server
        # (may have been loaded externally or in previous session)
        try:
            if await check_adapter_available(
                server_info.base_url, adapter_name, server_info.api_key
            ):
                logger.info(
                    f"LoRA adapter '{adapter_name}' already available on server"
                )
                server_info.loaded_adapters.add(adapter_path)
                return
        except httpx.HTTPStatusError as e:
            logger.warning(f"Failed to check adapter availability: {e}")
            # Continue to try loading

        # Load the adapter
        logger.info(f"Loading LoRA adapter: {adapter_path} as {adapter_name}")
        await load_adapter(
            server_info.base_url,
            adapter_name,
            adapter_path,
            server_info.api_key,
        )
        server_info.loaded_adapters.add(adapter_path)


def cleanup_servers() -> None:
    """Cleanup all tracked vLLM servers.

    Called during process exit to terminate spawned servers.
    """
    from inspect_ai._util.local_server import terminate_process

    for key, server_info in list(_vllm_servers.items()):
        if server_info.process is not None and not server_info.is_external:
            logger.info(f"Cleaning up vLLM server for {key[0]}")
            terminate_process(server_info.process)
    _vllm_servers.clear()


# Register cleanup handler for process exit
atexit.register(cleanup_servers)
