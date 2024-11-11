import logging
import os
import pickle
from contextvars import ContextVar
from datetime import datetime, timezone
from hashlib import md5
from pathlib import Path
from shutil import rmtree

from dateutil.relativedelta import relativedelta

from inspect_ai._util.appdirs import inspect_cache_dir
from inspect_ai.tool import ToolChoice, ToolInfo

from ._chat_message import ChatMessage
from ._generate_config import GenerateConfig
from ._model_output import ModelOutput

logger = logging.getLogger(__name__)


def _path_is_in_cache(path: Path | str) -> bool:
    """This ensures the path is in our cache directory, just in case the `model` is ../../../home/ubuntu/maliciousness"""
    if isinstance(path, str):
        path = Path(path)

    return cache_path() in Path(os.path.normpath(path)).parents


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


class CachePolicy:
    """The `CachePolicy` is used to define various criteria that impact how model calls are cached.

    Attributes:
        expiry(str | None): Default "24h". The expiry time for the cache entry.
          This is a string of the format "12h" for 12 hours or "1W" for a week,
          etc. This is how long we will keep the cache entry, if we access it
          after this point we'll clear it. Setting to `None` will cache
          indefinitely.
        per_epoch(bool): Default True. By default we cache responses separately
          for different epochs. The general use case is that if there are
          multiple epochs, we should cache each response separately because
          scorers will aggregate across epochs. However, sometimes a response
          can be cached regardless of epoch if the call being made isn't under
          test as part of the evaluation. If False, this option allows you to
          bypass that and cache independently of the epoch.
        scopes(dict[str, str]): A dictionary of additional metadata that should
          be included in the cache key. This allows for more fine-grained
          control over the cache key generation.
    """

    def __init__(
        self,
        expiry: str | None = "1W",
        per_epoch: bool = True,
        scopes: dict[str, str] = {},
    ) -> None:
        self.per_epoch = per_epoch
        self.scopes = scopes

        if expiry is None:
            self.expiry = None
        else:
            self.expiry = _parse_expiry(expiry)


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
        config: GenerateConfig,
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


def _cache_key(entry: CacheEntry) -> str:
    components = [
        (
            entry.config.model_dump(
                # Exclude fields that don't affect the model output
                exclude=set(["max_retries", "timeout", "max_connections"])
            )
        ),
        ",".join([str(message.model_dump()) for message in entry.input]),
        entry.base_url,
        entry.tool_choice,
        entry.tools,
        entry.policy.expiry,
        entry.policy.scopes,
    ]

    if entry.policy.per_epoch:
        components.append(epoch.get(None))

    base_string = "|".join([str(component) for component in components])

    logger.debug(_cache_key_debug_string([str(component) for component in components]))

    return md5(base_string.encode("utf-8")).hexdigest()


def _cache_key_debug_string(components: list[str]) -> str:
    components_str = "\n".join(f"  - {component}" for component in components)
    return f"Computed cache key from components:\n{components_str}"


def _cache_expiry(policy: CachePolicy) -> datetime | None:
    if policy.expiry is None:
        return None

    expiry_time: datetime = datetime.now(timezone.utc) + relativedelta(
        seconds=policy.expiry
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
    """Cache a value in the cache directory."""
    filename = cache_path(model=entry.model) / _cache_key(entry)

    try:
        filename.parent.mkdir(parents=True, exist_ok=True)

        with open(filename, "wb") as f:
            expiry = _cache_expiry(entry.policy)
            logger.debug("Storing in cache: %s (expires: %s)", filename, expiry)
            pickle.dump((expiry, output), f)
        return True
    except Exception as e:
        logger.debug(f"Failed to cache {filename}: {e}")
        return False


def cache_fetch(entry: CacheEntry) -> ModelOutput | None:
    """Fetch a value from the cache directory."""
    filename = cache_path(model=entry.model) / _cache_key(entry)
    try:
        logger.debug("Fetching from cache: %s", filename)

        with open(filename, "rb") as f:
            expiry, output = pickle.load(f)
            if not isinstance(output, ModelOutput):
                logger.debug(
                    "Unexpected cached type, can only fetch ModelOutput: %s (%s)",
                    type(output),
                    filename,
                )
                return None

            if _is_expired(expiry):
                logger.debug("Cache expired for %s (%s)", filename, expiry)
                # If it's expired, no point keeping it as we'll never access it
                # successfully again.
                filename.unlink(missing_ok=True)
                return None

            return output
    except Exception as e:
        logger.debug(f"Failed to fetch from cache {filename}: {e}")
        return None


def cache_clear(model: str = "") -> bool:
    """Clear the cache directory."""
    try:
        path = cache_path(model)

        if (model == "" or _path_is_in_cache(path)) and path.exists():
            logger.debug("Clearing cache: %s", path)
            rmtree(path)
            return True

        return False
    except Exception as e:
        logger.error(f"Failed to clear cache: {e}")
        return False


def cache_path(model: str = "") -> Path:
    env_cache_dir = os.environ.get("INSPECT_CACHE_DIR", None)
    if env_cache_dir:
        generate_cache = Path(env_cache_dir) / "generate"
        generate_cache.mkdir(parents=True, exist_ok=True)
    else:
        generate_cache = inspect_cache_dir("generate")
    if model:
        return generate_cache / model
    else:
        return generate_cache


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
        subdirs(list[str]): List of folders to filter by, which are generally
            model names. Empty directories will be ignored.
        files(list[str]): List of files to filter by explicitly. Note that
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
        filter_by(list[str]): Default []. List of model names to filter by. If
            an empty list, this will search the entire cache.
    """
    expired_cache_entries = []
    filter_by_paths = [
        cache_path(model) for model in filter_by if _path_is_in_cache(cache_path(model))
    ]

    if filter_by and not filter_by_paths:
        # An edge case where all the paths we get are invalid ones (e.g.
        # "../../foo/bar") but we don't want to search the entire cache
        return []

    logger.debug("Filtering by paths: %s", filter_by_paths)
    for dirpath, _dirnames, filenames in os.walk(cache_path()):
        if filter_by_paths and Path(dirpath) not in filter_by_paths:
            logger.debug("Skipping path %s", dirpath)
            continue

        logger.debug("Checking dirpath %s", dirpath)
        for filename in filenames:
            path = Path(dirpath) / filename
            logger.debug("Checking path %s", path)
            try:
                with open(path, "rb") as f:
                    expiry, _cache_entry = pickle.load(f)
                    if _is_expired(expiry):
                        logger.debug("Expired cache entry found: %s (%s)", path, expiry)
                        expired_cache_entries.append(path)
            except Exception as e:
                logger.debug("Failed to load cached item %s: %s", path, e)
                continue

    return expired_cache_entries


def cache_prune(files: list[Path] = []) -> None:
    """Delete all expired cache entries.

    Args:
        files(list[Path]): Default []. List of files to prune. If empty, this
            will search the entire cache.
    """
    if not files:
        files = cache_list_expired()

    for file in files:
        try:
            with open(file, "rb") as f:
                expiry, _cache_entry = pickle.load(f)
                if _is_expired(expiry):
                    logger.debug("Pruning expired cache: %s", file)
                    file.unlink(missing_ok=True)
        except Exception as e:
            logger.debug("Failed to prune cache %s: %s", file, e)
            continue
