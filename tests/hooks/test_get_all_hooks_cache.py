"""Tests for the `get_all_hooks` cache.

`get_all_hooks` is on the hot path of every hook emission. It used to walk
the entire process-wide registry on every call. The cache keys on
``(registry_version, len(registry))`` so that:

    1. Late-registered hooks (e.g. via `@hooks` decorators in task files
       loaded by `load_file_tasks`) are still returned.
    2. Direct deletions from `_registry` (used by some test fixtures)
       also invalidate the cache.
    3. Repeated calls with no registry change are O(1) instead of
       O(registry_size).
"""

from __future__ import annotations

import time

from inspect_ai._util import registry as _registry_mod
from inspect_ai.hooks._hooks import Hooks, get_all_hooks, hooks


def test_get_all_hooks_returns_late_registered_hook() -> None:
    """A hook registered after the cache is populated must be returned."""
    # Prime the cache with whatever's currently registered.
    initial = list(get_all_hooks())

    @hooks(name="late_test_hook", description="registered after first cache populate")
    class LateHook(Hooks):
        pass

    try:
        after = list(get_all_hooks())
    finally:
        # Clean up so we don't pollute other tests.
        _registry_mod._registry.pop("hooks:late_test_hook", None)

    assert any(type(h).__name__ == "LateHook" for h in after), (
        "cache failed to invalidate when a new hook was registered"
    )
    # Original hooks still present.
    initial_ids = {id(h) for h in initial}
    after_ids = {id(h) for h in after}
    assert initial_ids.issubset(after_ids)


def test_get_all_hooks_invalidates_on_direct_deletion() -> None:
    """A hook removed via `del _registry[...]` must not appear on the next call.

    Some test fixtures clean up by deleting from `_registry` directly,
    bypassing `registry_add`. The cache must invalidate in that case too —
    the (version, length) state captures the deletion via the length change.
    """

    @hooks(name="cache_del_test_hook", description="for deletion test")
    class DelTestHook(Hooks):
        pass

    after_add = [type(h).__name__ for h in get_all_hooks()]
    assert "DelTestHook" in after_add

    # Direct deletion (does not go through registry_add)
    del _registry_mod._registry["hooks:cache_del_test_hook"]

    after_del = [type(h).__name__ for h in get_all_hooks()]
    assert "DelTestHook" not in after_del, (
        "cache returned a hook that had been deleted from the registry"
    )


def test_get_all_hooks_cache_avoids_full_registry_scan() -> None:
    """Repeated calls with no registry change must be fast (O(1)).

    Without caching, every call iterates `_registry`; with caching it's a
    couple of attribute reads and a tuple comparison. 100k cached calls
    should comfortably finish in well under 200ms even on slow CI; without
    the cache, this would balloon to seconds for typical registry sizes.
    """
    # Prime the cache and capture state.
    get_all_hooks()
    state_before = (
        _registry_mod._registry_version,
        len(_registry_mod._registry),
    )

    t0 = time.perf_counter()
    for _ in range(100_000):
        get_all_hooks()
    elapsed = time.perf_counter() - t0

    state_after = (
        _registry_mod._registry_version,
        len(_registry_mod._registry),
    )
    assert state_before == state_after, (
        "registry was mutated unexpectedly during the cache hot-path test"
    )
    assert elapsed < 0.4, (
        f"100k cached get_all_hooks() calls took {elapsed:.3f}s — "
        f"cache may not be active"
    )


def test_registry_version_bumps_on_add() -> None:
    """Sanity: every `registry_add` increments `_registry_version`."""
    before = _registry_mod._registry_version

    @hooks(name="version_bump_test_hook", description="")
    class VersionHook(Hooks):
        pass

    try:
        after = _registry_mod._registry_version
        assert after > before, "registry_add did not bump _registry_version"
    finally:
        _registry_mod._registry.pop("hooks:version_bump_test_hook", None)
