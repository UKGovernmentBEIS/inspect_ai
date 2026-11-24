import json
import logging
import math
import os
import re
from contextvars import ContextVar
from datetime import datetime, timezone
from hashlib import md5, sha256
from io import BytesIO
from pathlib import Path, PurePosixPath, PureWindowsPath
from shutil import rmtree
from typing import Any, BinaryIO, Optional

from dateutil.relativedelta import relativedelta
from pydantic import (
    AwareDatetime,
    BaseModel,
    Field,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)
from pydantic_core import to_json

from inspect_ai._util.appdirs import inspect_cache_dir
from inspect_ai._util.atomic_write import atomic_write_bytes
from inspect_ai._util.constants import DESERIALIZING
from inspect_ai._util.logger import warn_once
from inspect_ai._util.trace import trace_message
from inspect_ai.tool import ToolChoice, ToolInfo

from ._chat_message import ChatMessage
from ._model_output import ModelOutput

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
        filename = cache_path(model=entry.model) / f"{entry.key}{_ENTRY_SUFFIX}"
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


def _parse_expiry(period: str) -> int:
    """Returns the number of seconds in the period where period is a string of the format "12h" or "1W" etc."""
    factor = period[-1]
    match factor:
        case "s":
            return int(period[:-1])
        case "m":
            return int(period[:-1]) * 60
        case "h":
            return int(period[:-1]) * 60 * 60
        case "D":
            return int(period[:-1]) * 60 * 60 * 24
        case "W":
            return int(period[:-1]) * 60 * 60 * 24 * 7
        case "M":
            return int(period[:-1]) * 60 * 60 * 24 * 30
        case "Y":
            return int(period[:-1]) * 60 * 60 * 24 * 365
        case _:
            raise ValueError(f"Invalid expiry: {period}")


class CachePolicy(BaseModel):
    """Caching options for model generation."""

    expiry: str | None = Field(default="1W")
    """The expiry time for cache entries (Default "1W").
    This is a string of the format "12h" for 12 hours or "1W" for a week,
    etc. This is how long we will keep the cache entry, if we access it
    after this point we'll clear it. Setting to `None` will cache
    indefinitely."""

    per_epoch: bool = Field(default=True)
    """Default True. By default we cache responses separately
    for different epochs. The general use case is that if there are
    multiple epochs, we should cache each response separately because
    scorers will aggregate across epochs. However, sometimes a response
    can be cached regardless of epoch if the call being made isn't under
    test as part of the evaluation. If False, this option allows you to
    bypass that and cache independently of the epoch."""

    scopes: dict[str, str] = Field(default_factory=dict)
    """A dictionary of additional metadata that should
    be included in the cache key. This allows for more fine-grained
    control over the cache key generation."""

    @model_validator(mode="before")
    @classmethod
    def _missing_expiry_is_none(cls, data: Any, info: ValidationInfo) -> Any:
        """Read an ``expiry`` missing from a persisted policy as None, not "1W".

        Logs are written with ``exclude_none``, which drops a None ``expiry``,
        while the "1W" default is always written out. So when deserializing a
        log, a missing ``expiry`` can only have been None (never expire).
        """
        if (
            isinstance(data, dict)
            and isinstance(info.context, dict)
            and info.context.get(DESERIALIZING, False)
        ):
            return {"expiry": None} | data
        return data

    @staticmethod
    def from_string(expiry: str) -> Optional["CachePolicy"]:
        try:
            _parse_expiry(expiry)  # confirm this is a legit expiry
            return CachePolicy(expiry=expiry)
        except ValueError:
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
        model_args_key(str | None): Fingerprint of the model constructor arguments.
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
        model_args_key: str | None = None,
    ):
        self.base_url = base_url
        self.config = config
        self.input = input
        self.model = model
        self.tool_choice = tool_choice
        self.tools = tools
        self.policy = policy
        self.model_args_key = model_args_key
        self.key = _cache_key(self)


def cache_model_args_key(
    model_args: dict[str, Any], *, instance_key: str | None = None
) -> str | None:
    """Fingerprint model args, scoping opaque values to an optional instance key.

    Opaque objects (including clients, callables, and redacted secrets) cannot
    be given a reliable persistent identity. With an instance key, they can
    still share responses within that model's lifetime, while the JSON portions
    of the arguments continue to distinguish request defaults.

    Dictionary order is kept: providers can resolve keys that overlap (header
    names that differ in case, Google harm-category aliases) by order.
    """
    if not model_args:
        return ""
    try:
        if not _is_json_value(model_args):
            raise ValueError("Opaque model args")
        serialized = json.dumps(model_args, allow_nan=False)
    except (ValueError, RecursionError):
        if instance_key is None:
            return None
        return cache_instance_model_args_key(model_args, instance_key)
    return sha256(serialized.encode("utf-8")).hexdigest()


def cache_instance_model_args_key(model_args: dict[str, Any], instance_key: str) -> str:
    """Fingerprint model args for one model instance.

    The JSON portions of the arguments still distinguish request defaults, and
    the encoding cannot match an instance-independent fingerprint.
    """
    serialized = json.dumps([instance_key, _model_args_tree(model_args, set())])
    return sha256(serialized.encode("utf-8")).hexdigest()


def _model_args_tree(value: Any, ancestors: set[int]) -> Any:
    """Tag each node so an opaque placeholder cannot collide with user JSON."""
    if type(value) in (str, int, bool, type(None)) or (
        type(value) is float and math.isfinite(value)
    ):
        return ["value", value]
    if id(value) in ancestors:
        return ["opaque"]
    if type(value) is list or (
        type(value) is dict and all(type(key) is str for key in value)
    ):
        ancestors.add(id(value))
        try:
            if isinstance(value, list):
                return ["list", [_model_args_tree(item, ancestors) for item in value]]
            return [
                "dict",
                {key: _model_args_tree(item, ancestors) for key, item in value.items()},
            ]
        finally:
            ancestors.remove(id(value))
    return ["opaque"]


def _is_json_value(value: Any) -> bool:
    if type(value) in (str, int, float, bool, type(None)):
        return True
    if type(value) is list:
        return all(_is_json_value(item) for item in value)
    if type(value) is dict:
        return all(
            type(key) is str and _is_json_value(item) for key, item in value.items()
        )
    return False


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

    # Preserve existing keys for models with no constructor arguments.
    if entry.model_args_key:
        components.append(f"model_args:{entry.model_args_key}")

    base_string = "|".join([str(component) for component in components])

    return md5(base_string.encode("utf-8")).hexdigest()


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


# Cache entry files (format version 1) are UTF-8 JSON Lines with two lines: a
# header (`_CacheHeader`) and the `ModelOutput`. They are only ever parsed with
# the stdlib `json` module and validated with Pydantic, so reading a cache file
# cannot execute code. Entries written by earlier versions of Inspect are
# pickles named by the bare key; they are never read, only recognized by their
# first two bytes so that `cache_prune` can delete them.
_ENTRY_VERSION = 1
_ENTRY_SUFFIX = ".jsonl"
_MAX_HEADER_BYTES = 4096
_KEY_PATTERN = re.compile(r"[0-9a-f]{32}")
_PICKLE_PROTOCOLS = range(2, 6)


class _CacheHeader(BaseModel):
    """First line of a cache entry file."""

    version: int = Field(strict=True)
    key: str = Field(strict=True)
    expiry: AwareDatetime | None

    @field_validator("expiry", mode="before")
    @classmethod
    def _expiry_is_iso_string(cls, value: Any) -> Any:
        if value is not None and not isinstance(value, (str, datetime)):
            raise ValueError("expiry must be an ISO 8601 string or null")
        return value


class _InvalidEntry(ValueError):
    """A cache entry file that cannot be read."""


class _OutputNotCacheable(ValueError):
    """A model output that the cache cannot store and return unchanged."""


def _read_header(f: BinaryIO, key: str) -> _CacheHeader:
    """Read and validate the header line of a cache entry file.

    Raises:
       _InvalidEntry: If the header is missing, too long, does not validate,
          has another format version or names another key.
    """
    line = f.readline(_MAX_HEADER_BYTES)
    if not line.endswith(b"\n"):
        raise _InvalidEntry("header line is missing or too long")
    try:
        data = json.loads(line)
    except (ValueError, RecursionError) as ex:
        raise _InvalidEntry(f"header is not JSON: {ex}") from ex
    if not isinstance(data, dict):
        raise _InvalidEntry("header is not a JSON object")
    try:
        header = _CacheHeader.model_validate(data)
    except ValidationError as ex:
        raise _InvalidEntry(f"invalid header: {ex}") from ex
    if header.version != _ENTRY_VERSION:
        raise _InvalidEntry(f"unsupported format version {header.version}")
    if header.key != key:
        raise _InvalidEntry("header key does not match the file name")
    return header


def _read_body(f: BinaryIO) -> ModelOutput:
    """Read and validate the `ModelOutput` line that follows the header.

    Validation runs without the log deserialization context, so stored
    message IDs are kept as written.
    """
    body = f.read()
    if not body.endswith(b"\n"):
        raise _InvalidEntry("body is missing or truncated")
    return ModelOutput.model_validate(json.loads(body))


def _entry_bytes(key: str, expiry: datetime | None, output: ModelOutput) -> bytes:
    """Serialize a cache entry, checking that lookup will return `output` unchanged.

    The body is written with non-finite floats as `NaN`/`Infinity` constants
    (as eval logs write them) and strings as UTF-8. It is then read back with
    the lookup's reader and compared with `output`, leaving out `metadata`
    values (which may come back in their JSON form) and treating an empty
    `completion` as the first choice's text (as validation fills it in).

    Raises:
       _OutputNotCacheable: If the output does not serialize or does not
          read back equal.
    """
    header = _CacheHeader(version=_ENTRY_VERSION, key=key, expiry=expiry)
    try:
        body = to_json(output.model_dump(), inf_nan_mode="constants") + b"\n"
    except Exception as ex:
        raise _OutputNotCacheable("they cannot be serialized to JSON") from ex
    try:
        read_back = _read_body(BytesIO(body))
    except Exception as ex:
        raise _OutputNotCacheable("they do not read back unchanged from JSON") from ex
    if _comparable(read_back) != _comparable(output):
        raise _OutputNotCacheable("they do not read back unchanged from JSON")
    return header.model_dump_json().encode("utf-8") + b"\n" + body


def _comparable(output: ModelOutput) -> ModelOutput:
    """`output` without `metadata` and with `completion` filled as validation fills it."""
    return output.model_copy(
        update={
            "completion": output.completion
            or (output.choices[0].message.text if output.choices else ""),
            "metadata": None,
            "fallback": output.fallback.model_copy(update={"metadata": None})
            if output.fallback
            else None,
            "choices": [
                choice.model_copy(
                    update={
                        "message": choice.message.model_copy(update={"metadata": None})
                    }
                )
                for choice in output.choices
            ],
        }
    )


def _entry_name_key(name: str) -> str | None:
    """The cache key of a current-format entry file name, or None."""
    if name.endswith(_ENTRY_SUFFIX):
        key = name[: -len(_ENTRY_SUFFIX)]
        if _KEY_PATTERN.fullmatch(key):
            return key
    return None


def _is_pruneable(path: Path) -> bool:
    """Whether `path` is an expired current-format entry or a legacy entry.

    Only regular files named like an entry are opened. A current-format
    entry is judged by its header alone; a legacy (pickle) entry by its name
    and its first two bytes, without deserializing it.

    Raises:
       _InvalidEntry: If a current-format entry's header is invalid.
       OSError: If the file cannot be read.
    """
    if not path.is_file():
        return False
    key = _entry_name_key(path.name)
    if key is not None:
        with open(path, "rb") as f:
            header = _read_header(f, key)
        if _is_expired(header.expiry):
            trace("Expired cache entry found: %s (%s)", path, header.expiry)
            return True
        return False
    if _KEY_PATTERN.fullmatch(path.name):
        with open(path, "rb") as f:
            magic = f.read(2)
        if len(magic) == 2 and magic[0] == 0x80 and magic[1] in _PICKLE_PROTOCOLS:
            trace("Cache entry from an earlier version found: %s", path)
            return True
    return False


def cache_store(
    entry: CacheEntry,
    output: ModelOutput,
) -> bool:
    """Cache a value in the cache directory.

    Outputs stopped by a provider content filter are never cached: refusal
    retry loops (e.g. `react()`'s `retry_refusals`) re-call generate with
    identical inputs, so a cached refusal would be replayed on every retry
    instead of giving the model a fresh attempt.

    Outputs that would not read back unchanged (see `_entry_bytes`) are not
    cached, with a warning. The entry is written to a temporary file and
    renamed into place, so readers never see a partly written entry.
    """
    if any(choice.stop_reason == "content_filter" for choice in output.choices):
        trace("Not caching content_filter output: %s", entry.key)
        return False

    filename: Path | None = None
    try:
        filename = _cache_entry_path(entry)
        if filename is None:
            return False
        expiry = _cache_expiry(entry.policy)
        data = _entry_bytes(entry.key, expiry, output)
        trace("Storing in cache: %s (expires: %s)", filename, expiry)
        atomic_write_bytes(str(filename), data, fsync=False)
        return True
    except _OutputNotCacheable as e:
        trace(f"Not caching {filename}: {e} ({e.__cause__})")
        warn_once(
            logger,
            f"Some outputs of model {entry.model!r} are not cached because {e}.",
        )
        return False
    except Exception as e:
        trace(f"Failed to cache {filename}: {e}")
        return False


def cache_fetch(entry: CacheEntry) -> ModelOutput | None:
    """Fetch a value from the cache directory.

    A missing, invalid or expired entry is a miss (an expired entry is also
    deleted).
    """
    filename: Path | None = None
    try:
        filename = _cache_entry_path(entry)
        if filename is None:
            return None

        trace("Fetching from cache: %s", filename)
        with open(filename, "rb") as f:
            header = _read_header(f, entry.key)
            if not _is_expired(header.expiry):
                return _read_body(f)

        trace("Cache expired for %s (%s)", filename, header.expiry)
        # If it's expired, no point keeping it as we'll never access it
        # successfully again.
        filename.unlink(missing_ok=True)
        return None
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
    """Returns a list of all the cache entries that can be pruned.

    These are entries that have passed their expiry time, and entries written
    by an earlier version of Inspect (which are never used). Entries are
    judged by their header alone, and other files are ignored.

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
                if _is_pruneable(path):
                    expired_cache_entries.append(path)
            except (_InvalidEntry, OSError) as e:
                trace("Skipping cache file %s: %s", path, e)
                continue

    return expired_cache_entries


def cache_prune(files: list[Path] = []) -> None:
    """Delete all expired cache entries.

    Entries written by an earlier version of Inspect are also deleted, since
    they are never used. Files that are not cache entries are left alone.

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
            if _is_pruneable(file):
                trace("Pruning cache entry: %s", file)
                file.unlink(missing_ok=True)
        except (_InvalidEntry, OSError) as e:
            trace("Failed to prune cache %s: %s", file, e)
            continue
