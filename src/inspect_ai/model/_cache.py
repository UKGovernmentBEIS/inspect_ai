import logging
import os
import pickle
import re
from contextvars import ContextVar
from datetime import datetime, timezone
from hashlib import md5
from pathlib import Path, PurePosixPath, PureWindowsPath
from shutil import rmtree
from typing import Any

from dateutil.relativedelta import relativedelta
from pydantic import BaseModel

from inspect_ai._util.appdirs import inspect_cache_dir
from inspect_ai._util.logger import warn_once
from inspect_ai._util.trace import trace_message
from inspect_ai.tool._tool_choice import ToolChoice
from inspect_ai.tool._tool_info import ToolInfo

from ._cache_policy import _parse_expiry
from ._chat_message import ChatMessage
from ._model_output import ModelOutput

# isort: split
# Backward-compatible re-exports of names that moved to inspect_ai.core.
from inspect_ai.core._cache_policy import CachePolicy as CachePolicy

# End of backward-compatible re-exports.

logger = logging.getLogger(__name__)


def trace(msg: str, *args: Any) -> None:
    trace_message(logger, "Cache", msg, *args)


def _path_is_in_cache(path: Path | str, root: Path | None = None) -> bool:
    """Whether `path` is strictly inside the cache directory.

    Both paths are resolved first, so a symlink that leads out of the cache
    directory fails the check.
    """
    try:
        resolved_root = (root or _cache_root()).resolve()
        return resolved_root in Path(path).resolve().parents
    except (OSError, RuntimeError, ValueError):
        # unresolvable (e.g. a symlink loop or an embedded NUL): not provably
        # in the cache
        return False


def _is_safe_model_name(model: str) -> bool:
    """Whether `model` is a relative path with no `.` or `..` segments.

    Both `/` and backslash count as separators, and a segment of only dots and
    spaces is refused (Windows trims trailing dots and spaces), so a name is
    judged the same way on every platform.
    """
    if "\0" in model or PurePosixPath(model).anchor or PureWindowsPath(model).anchor:
        return False
    return all(
        segment == "" or segment.strip(". ") != ""
        for segment in re.split(r"[/\\]", model)
    )


def _cache_entry_path(entry: "CacheEntry") -> Path | None:
    """Path of the cache file for `entry`, or None (with a warning) if it is outside the cache directory."""
    try:
        filename = cache_path(model=entry.model) / entry.key
        if _path_is_in_cache(filename):
            return filename
    except ValueError:
        pass
    warn_once(
        logger,
        f"Model output caching is disabled for model {entry.model!r}: "
        "its cache entries would be outside the cache directory.",
    )
    return None


# The `epoch` is an essential part of the cache key for `generate` call. When
# calling with multiple epochs we are essentially making *exactly the same call*
# multiple times, so all other fields will be the same.
#
# Abstracting this to a ContextVar allows us to set it at the execution stage
# and access it safely where we're fetching/storing from the cache without
# adding more noise to the call stack.
epoch: ContextVar[int] = ContextVar("epoch")


class CacheEntry:
    """
    This is used to orchestrate the caching of ModelOutput from the model.

    All the attributes are used to generate a unique key for each cache entry.

    Attributes:
        base_url(str | None): The base URL of the model API, if any.
        config(GenerateConfig): The configuration used to generate the output.
        input(list[ChatMessage]): The messages exchanged with the model.
        model(str): The model name.
        policy(CachePolicy): The `CachePolicy` defining things like additional
          metadata for the cache key, expiry time, and other settings which
          affect all individual cached entries.
        tool_choice(ToolChoice | None): The tool choice, if any.
        tools(list[ToolInfo]): The tools provided to the model.
    """

    def __init__(
        self,
        base_url: str | None,
        config: BaseModel,
        input: list[ChatMessage],
        model: str,
        policy: CachePolicy,
        tool_choice: ToolChoice | None,
        tools: list[ToolInfo],
    ):
        self.base_url = base_url
        self.config = config
        self.input = input
        self.model = model
        self.tool_choice = tool_choice
        self.tools = tools
        self.policy = policy
        self.key = _cache_key(self)


# Runtime/transport GenerateConfig knobs that cannot change what the provider
# returns, and so must not affect the cache key. Their union must equal
# GENERATE_CONFIG_FIELDS_TO_EXCLUDE (the task-identity partition in
# inspect_ai._eval.evalset) — both answer the same question, and
# test_cache_key_neutral_fields_match_task_identity fails when they diverge.
#
# Which bucket a field goes in decides whether existing caches survive
# classifying it:
#
#  - Dropped fields are absent from the serialized config. Right for a field
#    classified when it is added to GenerateConfig: keys written before the
#    field existed were already computed without it, so they still match.
#  - Neutralized fields are serialized as their default instead. Right for a
#    field that has been part of the key already — dropping one rewrites every
#    key in every existing cache, whereas a config that leaves it unset
#    serializes exactly as it did before.
_CACHE_KEY_DROPPED_FIELDS = {
    "max_connections",
    "adaptive_connections",
    "max_retries",
    "timeout",
    "stream_idle_timeout",
    "cache",
    "batch",
    # never reaches the provider request (it decides what generate() does with
    # a refusal, and refusals are never cached), so a cache hit can't depend on
    # it. Unlike the fields above it *does* change sample outcomes, so it stays
    # in eval-set task identity (GENERATE_CONFIG_FIELDS_TO_EXCLUDE).
    "fail_on_refusal",
}

_CACHE_KEY_NEUTRALIZED_FIELDS = {
    "attempt_timeout",
    "cache_prompt",
}


def _cache_key_config(config: BaseModel) -> dict[str, Any]:
    """The generate config as the cache key sees it, with runtime knobs made inert."""
    values = config.model_dump(exclude=_CACHE_KEY_DROPPED_FIELDS)
    fields = type(config).model_fields
    for field in _CACHE_KEY_NEUTRALIZED_FIELDS & values.keys():
        values[field] = fields[field].get_default()
    return values


def _cache_key(entry: CacheEntry) -> str:
    components = [
        _cache_key_config(entry.config),
        ",".join(
            [
                str(
                    message.model_dump(
                        exclude={
                            "id": True,
                            "content": {"__all__": {"cache_breakpoint"}},
                        }
                    )
                )
                for message in entry.input
            ]
        ),
        entry.base_url,
        entry.tool_choice,
        entry.tools,
        _parse_expiry(entry.policy.expiry) if entry.policy.expiry is not None else None,
        entry.policy.scopes,
    ]

    if entry.policy.per_epoch:
        components.append(epoch.get(None))

    base_string = "|".join([str(component) for component in components])

    trace(_cache_key_debug_string([str(component) for component in components]))

    return md5(base_string.encode("utf-8")).hexdigest()


def _cache_key_debug_string(components: list[str]) -> str:
    components_str = "\n".join(f"  - {component}" for component in components)
    return f"Computed cache key from components:\n{components_str}"


def _cache_expiry(policy: CachePolicy) -> datetime | None:
    if policy.expiry is None:
        return None

    expiry_time: datetime = datetime.now(timezone.utc) + relativedelta(
        seconds=_parse_expiry(policy.expiry)
    )
    return expiry_time


def _is_expired(expiry: datetime | None) -> bool:
    if expiry is None:
        return False

    return datetime.now(timezone.utc) > expiry


def cache_store(
    entry: CacheEntry,
    output: ModelOutput,
) -> bool:
    """Cache a value in the cache directory.

    Outputs stopped by a provider content filter are never cached: refusal
    retry loops (e.g. `react()`'s `retry_refusals`) re-call generate with
    identical inputs, so a cached refusal would be replayed on every retry
    instead of giving the model a fresh attempt.
    """
    if any(choice.stop_reason == "content_filter" for choice in output.choices):
        trace("Not caching content_filter output: %s", entry.key)
        return False

    filename = _cache_entry_path(entry)
    if filename is None:
        return False

    try:
        filename.parent.mkdir(parents=True, exist_ok=True)

        with open(filename, "wb") as f:
            expiry = _cache_expiry(entry.policy)
            trace("Storing in cache: %s (expires: %s)", filename, expiry)
            pickle.dump((expiry, output), f)
        return True
    except Exception as e:
        trace(f"Failed to cache {filename}: {e}")
        return False


def cache_fetch(entry: CacheEntry) -> ModelOutput | None:
    """Fetch a value from the cache directory."""
    filename = _cache_entry_path(entry)
    if filename is None:
        return None
    try:
        trace("Fetching from cache: %s", filename)

        with open(filename, "rb") as f:
            expiry, output = pickle.load(f)
            if not isinstance(output, ModelOutput):
                trace(
                    "Unexpected cached type, can only fetch ModelOutput: %s (%s)",
                    type(output),
                    filename,
                )
                return None

            if _is_expired(expiry):
                trace("Cache expired for %s (%s)", filename, expiry)
                # If it's expired, no point keeping it as we'll never access it
                # successfully again.
                filename.unlink(missing_ok=True)
                return None

            return output
    except Exception as e:
        trace(f"Failed to fetch from cache {filename}: {e}")
        return None


def cache_clear(model: str = "") -> bool:
    """Clear the cache directory.

    Args:
       model: Model to clear cache for.
    """
    try:
        path = cache_path(model)

        if path.exists():
            trace("Clearing cache: %s", path)
            rmtree(path)
            return True

        return False
    except Exception as e:
        logger.error(f"Failed to clear cache: {e}")
        return False


def cache_path(model: str = "") -> Path:
    """Path to cache directory.

    Args:
       model: Path to cache directory for specific model.

    Raises:
       ValueError: If the directory for `model` would not be inside the
          cache directory (e.g. the name has `..` segments). Nothing is
          created in that case.
    """
    generate_cache = _cache_root()
    path = generate_cache / model if model else generate_cache
    if model and (
        not _is_safe_model_name(model) or not _path_is_in_cache(path, generate_cache)
    ):
        raise ValueError(
            f"The cache directory for model {model!r} would be outside {generate_cache}."
        )
    generate_cache.mkdir(parents=True, exist_ok=True)
    return path


def _cache_root() -> Path:
    """The cache directory, without creating it."""
    env_cache_dir = os.environ.get("INSPECT_CACHE_DIR", None)
    if env_cache_dir:
        return Path(env_cache_dir) / "generate"
    else:
        return inspect_cache_dir("generate", create=False)


def _cache_size_directories_only(filter_by: list[str]) -> list[tuple[str, int]]:
    root = cache_path()
    non_empty_directories = []
    for dirpath, _dirnames, filenames in os.walk(root):
        if not filenames:
            # Empty directory or just directories, carry on searching
            continue

        if not filter_by:
            # No filtering, so we want all directories
            non_empty_directories.append(dirpath)
            continue

        filtered_path = any(model in str(dirpath) for model in filter_by)
        if filtered_path:
            non_empty_directories.append(dirpath)

    models_with_sizes = []

    for directory in non_empty_directories:
        model_name = directory.replace(f"{root}/", "")
        size = sum(
            f.stat().st_size for f in Path(directory).glob("**/*") if f.is_file()
        )
        models_with_sizes.append((model_name, size))

    return models_with_sizes


def _cache_size_files_only(files: list[Path]) -> list[tuple[str, int]]:
    if not files:
        return []

    directories: dict[str, int] = {}
    root = str(cache_path())

    for file in files:
        if root in str(file) and file.exists():
            model = str(file.parent).replace(f"{root}/", "")
            if directories.get(model):
                directories[model] += file.stat().st_size
            else:
                directories[model] = file.stat().st_size

    return [(path, size) for path, size in directories.items()]


def cache_size(
    subdirs: list[str] = [], files: list[Path] = []
) -> list[tuple[str, int]]:
    """Calculate the size of various cached directories and files

    If neither  `subdirs` nor `files` are provided, the entire cache directory
    will be calculated.

    Args:
        subdirs: List of folders to filter by, which are generally
            model names. Empty directories will be ignored.
        files: List of files to filter by explicitly. Note that
            return value group these up by their parent directory

    Returns:
        list[tuple[str, int]]: List of tuples containing the model name and the
            size of the cache in bytes
    """
    if files and not subdirs:
        # This prevents us accidentally working out the cache for all paths when
        # we've just been given a list of files
        subdir_sizes = []
    else:
        subdir_sizes = _cache_size_directories_only(filter_by=subdirs)

    file_sizes = _cache_size_files_only(files=files)
    return sorted(subdir_sizes + file_sizes, key=lambda size: size[0])


def cache_list_expired(filter_by: list[str] = []) -> list[Path]:
    """Returns a list of all the cached files that have passed their expiry time.

    Args:
        filter_by: Default []. List of model names to filter by. If
            an empty list, this will search the entire cache.
    """
    expired_cache_entries = []
    filter_by_paths = []
    for model in filter_by:
        try:
            filter_by_paths.append(cache_path(model))
        except ValueError as ex:
            warn_once(logger, str(ex))

    if filter_by and not filter_by_paths:
        # An edge case where all the paths we get are invalid ones (e.g.
        # "../../foo/bar") but we don't want to search the entire cache
        return []

    trace("Filtering by paths: %s", filter_by_paths)
    root = cache_path()
    for dirpath, _dirnames, filenames in os.walk(root):
        if filter_by_paths and Path(dirpath) not in filter_by_paths:
            trace("Skipping path %s", dirpath)
            continue

        trace("Checking dirpath %s", dirpath)
        for filename in filenames:
            path = Path(dirpath) / filename
            trace("Checking path %s", path)
            if not _path_is_in_cache(path, root):
                trace("Skipping path outside the cache: %s", path)
                continue
            try:
                with open(path, "rb") as f:
                    expiry, _cache_entry = pickle.load(f)
                    if _is_expired(expiry):
                        trace("Expired cache entry found: %s (%s)", path, expiry)
                        expired_cache_entries.append(path)
            except Exception as e:
                trace("Failed to load cached item %s: %s", path, e)
                continue

    return expired_cache_entries


def cache_prune(files: list[Path] = []) -> None:
    """Delete all expired cache entries.

    Args:
        files: List of files to prune. If empty, this
            will search the entire cache. Files outside the
            cache directory are skipped.
    """
    if not files:
        files = cache_list_expired()

    root = _cache_root()
    for file in files:
        if not _path_is_in_cache(file, root):
            logger.warning(f"Not pruning {file}: it is outside the cache directory.")
            continue
        try:
            with open(file, "rb") as f:
                expiry, _cache_entry = pickle.load(f)
                if _is_expired(expiry):
                    trace("Pruning expired cache: %s", file)
                    file.unlink(missing_ok=True)
        except Exception as e:
            trace("Failed to prune cache %s: %s", file, e)
            continue
