import logging
import os
import pickle
from hashlib import md5
from pathlib import Path
from shutil import rmtree
from typing import Any

from inspect_ai._util.appdirs import inspect_cache_dir

from ._chat_message import ChatMessage
from ._generate_config import GenerateConfig
from ._tool import ToolChoice, ToolInfo

logger = logging.getLogger(__name__)


def cache_store(
    base_url: str | None,
    config: GenerateConfig,
    input: list[ChatMessage],
    model: str,
    tool_choice: ToolChoice | None,
    tools: list[ToolInfo],
    value: Any,
) -> bool:
    """Cache a value in the cache directory."""
    filename = cache_path(model=model) / build_cache_key(
        base_url, config, input, tool_choice, tools
    )
    try:
        logger.debug("Storing in cache: %s", filename)
        filename.parent.mkdir(parents=True, exist_ok=True)
        with open(filename, "wb") as f:
            pickle.dump(value, f)
        return True
    except Exception as e:
        logger.debug(f"Failed to cache {filename}: {e}")
        return False


def cache_fetch(
    base_url: str | None,
    config: GenerateConfig,
    input: list[ChatMessage],
    model: str,
    tool_choice: ToolChoice | None,
    tools: list[ToolInfo],
) -> Any:
    """Fetch a value from the cache directory."""
    filename = cache_path(model=model) / build_cache_key(
        base_url, config, input, tool_choice, tools
    )
    try:
        logger.debug("Fetching from cache: %s", filename)
        with open(filename, "rb") as f:
            return pickle.load(f)
    except Exception as e:
        logger.debug(f"Failed to fetch from cache {filename}: {e}")
        return None


def cache_clear(model: str = "") -> bool:
    """Clear the cache directory."""
    try:
        path = cache_path(model)

        # This ensures the path is in our cache directory, just in case the
        # `model` is ../../../home/ubuntu/maliciousness
        if cache_path() in Path(os.path.normpath(path)).parents and path.exists():
            logger.warning("Clearing cache: %s", path)
            rmtree(path)

        return True
    except Exception as e:
        logger.error(f"Failed to clear cache: {e}")
        return False


def cache_path(model: str = "") -> Path:
    return inspect_cache_dir(model)


def build_cache_key(
    base_url: str | None,
    config: GenerateConfig,
    input: list[ChatMessage],
    tool_choice: ToolChoice | None,
    tools: list[ToolInfo],
) -> str:
    base_string = "|".join(
        [
            str(cache_item)
            for cache_item in [
                (
                    config.model_dump(
                        exclude=set(["max_retries", "timeout", "max_connections"])
                    )
                ),
                ",".join([str(message.model_dump()) for message in input]),
                base_url,
                tool_choice,
                tools,
            ]
        ]
    )
    key = md5(base_string.encode("utf-8")).hexdigest()
    return key
