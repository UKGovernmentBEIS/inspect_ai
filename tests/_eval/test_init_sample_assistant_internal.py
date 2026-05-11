"""Tests for `init_sample_assistant_internal` find_spec caching.

The function is called once per sample. `importlib.util.find_spec` walks
importer paths and is expensive (~3 ms per call). The package availability
is invariant for the process lifetime, so we cache the find_spec result
at module load. These tests guard the cache.
"""

from __future__ import annotations

import importlib
import time
from unittest.mock import patch

from inspect_ai._eval.task import run as _run_mod


def test_init_sample_assistant_internal_does_not_call_find_spec() -> None:
    """Calling `init_sample_assistant_internal` must not invoke `find_spec`.

    The check happens at module load. Each per-sample invocation should be
    a cheap boolean check + (potentially) cached imports — no path walking.
    """
    call_count = 0
    original_find_spec = importlib.util.find_spec

    def tracking_find_spec(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return original_find_spec(*args, **kwargs)

    with patch("importlib.util.find_spec", tracking_find_spec):
        for _ in range(50):
            _run_mod.init_sample_assistant_internal()

    assert call_count == 0, (
        f"`init_sample_assistant_internal` called find_spec {call_count} times; "
        f"package availability should be cached at module load"
    )


def test_init_sample_assistant_internal_is_fast() -> None:
    """100 calls must be effectively free.

    Without caching, each call costs ~3 ms × 2 lookups = ~6 ms, so 100
    calls would be ~600 ms. With caching, each call is a couple of bool
    checks + sys.modules lookups for the imports — sub-millisecond per call.
    """
    # Warm up sys.modules for the imports (matches steady-state behavior).
    _run_mod.init_sample_assistant_internal()

    t0 = time.perf_counter()
    for _ in range(100):
        _run_mod.init_sample_assistant_internal()
    elapsed = time.perf_counter() - t0

    assert elapsed < 0.05, (
        f"100 calls to init_sample_assistant_internal took {elapsed * 1000:.0f}ms — "
        f"find_spec cache may not be active"
    )
