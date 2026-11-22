from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from inspect_ai.util._checkpoint import checkpointer_impl

CACHE_DIR_ENV = "INSPECT_TEST_CHECKPOINT_CACHE_DIR"


def _cache_dir_from_env(subdir: str) -> Path:
    d = Path(os.environ[CACHE_DIR_ENV]) / subdir
    d.mkdir(exist_ok=True)
    return d


@contextmanager
def redirect_transcript_store_cache_dir() -> Iterator[None]:
    with patch.object(checkpointer_impl, "inspect_cache_dir", _cache_dir_from_env):
        yield
