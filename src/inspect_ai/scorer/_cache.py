"""Score output caching.

Caches Score objects to avoid re-running scorers when the same scorer
is applied to the same sample with the same output. Follows the same
patterns as model/_cache.py for generate() caching.
"""

import logging
import os
import pickle
import tempfile
from datetime import datetime, timezone
from hashlib import md5
from pathlib import Path
from shutil import rmtree
from typing import Any

from inspect_ai._util.appdirs import inspect_cache_dir
from inspect_ai._util.trace import trace_message
from inspect_ai.model._cache import CachePolicy, _is_expired, _parse_expiry

from ._metric import Score

logger = logging.getLogger(__name__)


def trace(msg: str, *args: Any) -> None:
    trace_message(logger, "ScoreCache", msg, *args)


class ScoreCacheEntry:
    """Cache key components for a score cache entry.

    All attributes are used to generate a unique cache key.

    Attributes:
        scorer_name: Unqualified registry name of the scorer.
        scorer_args: Init params for the scorer (template, model, etc.).
        eval_model: The model used for evaluation.
        model_roles: Model role config mappings (e.g., grader -> ModelConfig).
        input: Original sample input.
        messages: Chat messages (model_dump with id excluded).
        output: Full ModelOutput.
        target: Expected answer.
        choices: Multiple-choice options (may be None).
        metadata: Sample metadata dict.
        policy: CachePolicy defining expiry, scopes, etc.
        epoch: Sample epoch (if per_epoch is True).
    """

    def __init__(
        self,
        scorer_name: str,
        scorer_args: dict[str, Any],
        eval_model: str,
        model_roles: dict[str, Any] | None,
        input: Any,
        messages: list[Any],
        output: Any,
        target: str | list[str],
        choices: list[str] | None,
        metadata: dict[str, Any] | None,
        policy: CachePolicy,
        epoch: int | None = None,
    ) -> None:
        self.scorer_name = scorer_name
        self.scorer_args = scorer_args
        self.eval_model = eval_model
        self.model_roles = model_roles
        self.input = input
        self.messages = messages
        self.output = output
        self.target = target
        self.choices = choices
        self.metadata = metadata
        self.policy = policy
        self.epoch = epoch


def _score_cache_key(entry: ScoreCacheEntry) -> str:
    """Compute MD5 cache key from all entry components."""
    components: list[Any] = [
        entry.scorer_name,
        str(entry.scorer_args),
        entry.eval_model,
        str(entry.model_roles),
        str(entry.input),
        ",".join(str(m) for m in entry.messages),
        str(entry.output),
        str(entry.target),
        str(entry.choices),
        str(entry.metadata),
        _parse_expiry(entry.policy.expiry) if entry.policy.expiry is not None else None,
        entry.policy.scopes,
    ]

    if entry.policy.per_epoch and entry.epoch is not None:
        components.append(entry.epoch)

    base_string = "|".join(str(c) for c in components)
    trace(_score_cache_key_debug_string([str(c) for c in components]))
    return md5(base_string.encode("utf-8")).hexdigest()


def _score_cache_key_debug_string(components: list[str]) -> str:
    components_str = "\n".join(f"  - {component}" for component in components)
    return f"Computed score cache key from components:\n{components_str}"


def _cache_expiry(policy: CachePolicy) -> datetime | None:
    if policy.expiry is None:
        return None
    from dateutil.relativedelta import relativedelta

    return datetime.now(timezone.utc) + relativedelta(
        seconds=_parse_expiry(policy.expiry)
    )


def score_cache_path(scorer_name: str = "") -> Path:
    """Path to score cache directory.

    Args:
        scorer_name: Optional scorer name for subdirectory.
    """
    env_cache_dir = os.environ.get("INSPECT_CACHE_DIR", None)
    if env_cache_dir:
        scores_cache = Path(env_cache_dir) / "scores"
        scores_cache.mkdir(parents=True, exist_ok=True)
    else:
        scores_cache = inspect_cache_dir("scores")
    if scorer_name:
        return scores_cache / scorer_name
    else:
        return scores_cache


def _path_is_in_score_cache(path: Path | str) -> bool:
    if isinstance(path, str):
        path = Path(path)
    return score_cache_path() in Path(os.path.normpath(path)).parents


def score_cache_store(entry: ScoreCacheEntry, score: Score) -> bool:
    """Cache a Score in the cache directory using atomic writes.

    Returns True on success, False on failure (e.g. non-serializable metadata).
    """
    cache_dir = score_cache_path(scorer_name=entry.scorer_name)
    filename = cache_dir / _score_cache_key(entry)

    try:
        cache_dir.mkdir(parents=True, exist_ok=True)

        # Atomic write: write to temp file then rename
        fd, tmp_path = tempfile.mkstemp(dir=cache_dir)
        try:
            expiry = _cache_expiry(entry.policy)
            trace("Storing score in cache: %s (expires: %s)", filename, expiry)
            with os.fdopen(fd, "wb") as f:
                pickle.dump((expiry, score), f)
            os.rename(tmp_path, filename)
        except Exception:
            # Clean up temp file on failure
            with open(os.devnull, "w"):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
            raise

        return True
    except (pickle.PicklingError, TypeError) as e:
        trace("Failed to cache score (non-serializable): %s", e)
        return False
    except Exception as e:
        trace("Failed to cache score %s: %s", filename, e)
        return False


def score_cache_fetch(entry: ScoreCacheEntry) -> Score | None:
    """Fetch a Score from the cache directory.

    Returns the cached Score if found and not expired, None otherwise.
    """
    filename = score_cache_path(scorer_name=entry.scorer_name) / _score_cache_key(entry)
    try:
        trace("Fetching score from cache: %s", filename)
        with open(filename, "rb") as f:
            expiry, score = pickle.load(f)
            if not isinstance(score, Score):
                trace(
                    "Unexpected cached type, can only fetch Score: %s (%s)",
                    type(score),
                    filename,
                )
                return None

            if _is_expired(expiry):
                trace("Score cache expired for %s (%s)", filename, expiry)
                filename.unlink(missing_ok=True)
                return None

            return score
    except FileNotFoundError:
        trace("Score cache miss: %s", filename)
        return None
    except Exception as e:
        trace("Failed to fetch from score cache %s: %s", filename, e)
        return None


def score_cache_clear(scorer_name: str = "") -> bool:
    """Clear the score cache directory.

    Args:
        scorer_name: Scorer to clear cache for. Empty string clears all.
    """
    try:
        path = score_cache_path(scorer_name)
        if (scorer_name == "" or _path_is_in_score_cache(path)) and path.exists():
            trace("Clearing score cache: %s", path)
            rmtree(path)
            return True
        return False
    except Exception as e:
        logger.error(f"Failed to clear score cache: {e}")
        return False


def score_cache_size(
    subdirs: list[str] | None = None, files: list[Path] | None = None
) -> list[tuple[str, int]]:
    """Calculate the size of score cache directories.

    Args:
        subdirs: List of scorer names to filter by.
        files: List of files to filter by.

    Returns:
        List of (name, size_bytes) tuples.
    """
    subdirs = subdirs or []
    files = files or []
    root = score_cache_path()

    if files and not subdirs:
        subdir_sizes: list[tuple[str, int]] = []
    else:
        subdir_sizes = []
        for dirpath, _dirnames, filenames in os.walk(root):
            if not filenames:
                continue
            if subdirs and not any(s in str(dirpath) for s in subdirs):
                continue
            name = str(dirpath).replace(f"{root}/", "")
            size = sum(
                f.stat().st_size for f in Path(dirpath).glob("**/*") if f.is_file()
            )
            subdir_sizes.append((name, size))

    file_sizes: list[tuple[str, int]] = []
    if files:
        directories: dict[str, int] = {}
        root_str = str(root)
        for file in files:
            if root_str in str(file) and file.exists():
                name = str(file.parent).replace(f"{root_str}/", "")
                directories[name] = directories.get(name, 0) + file.stat().st_size
        file_sizes = list(directories.items())

    return sorted(subdir_sizes + file_sizes, key=lambda x: x[0])


def score_cache_list_expired(filter_by: list[str] | None = None) -> list[Path]:
    """Returns a list of expired score cache files.

    Args:
        filter_by: List of scorer names to filter by.
    """
    filter_by = filter_by or []
    expired: list[Path] = []
    filter_by_paths = [
        score_cache_path(name)
        for name in filter_by
        if _path_is_in_score_cache(score_cache_path(name))
    ]

    if filter_by and not filter_by_paths:
        return []

    for dirpath, _dirnames, filenames in os.walk(score_cache_path()):
        if filter_by_paths and Path(dirpath) not in filter_by_paths:
            continue
        for filename in filenames:
            path = Path(dirpath) / filename
            try:
                with open(path, "rb") as f:
                    expiry, _score = pickle.load(f)
                    if _is_expired(expiry):
                        expired.append(path)
            except Exception:
                continue

    return expired


def score_cache_prune(files: list[Path] | None = None) -> None:
    """Delete all expired score cache entries.

    Args:
        files: List of files to prune. If None, searches entire cache.
    """
    if files is None:
        files = score_cache_list_expired()

    for file in files:
        try:
            with open(file, "rb") as f:
                expiry, _score = pickle.load(f)
                if _is_expired(expiry):
                    trace("Pruning expired score cache: %s", file)
                    file.unlink(missing_ok=True)
        except Exception as e:
            trace("Failed to prune score cache %s: %s", file, e)
            continue
