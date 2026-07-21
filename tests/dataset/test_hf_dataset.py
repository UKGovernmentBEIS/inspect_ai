from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from test_helpers.utils import skip_if_no_package

from inspect_ai.dataset._sources.hf import (
    _call_with_hf_retry,
    _should_retry_hf_error,
)


def _make_hf_http_error(status_code: int):
    from huggingface_hub.errors import HfHubHTTPError

    response = SimpleNamespace(headers={}, request=None, status_code=status_code)
    return HfHubHTTPError("err", response=response)  # type: ignore[arg-type]


@skip_if_no_package("huggingface_hub")
def test_retry_hf_429():
    assert _should_retry_hf_error(_make_hf_http_error(429)) is True


@skip_if_no_package("huggingface_hub")
def test_retry_hf_502():
    assert _should_retry_hf_error(_make_hf_http_error(502)) is True


@skip_if_no_package("huggingface_hub")
def test_no_retry_hf_401():
    assert _should_retry_hf_error(_make_hf_http_error(401)) is False


@skip_if_no_package("huggingface_hub")
def test_no_retry_hf_404():
    assert _should_retry_hf_error(_make_hf_http_error(404)) is False


@skip_if_no_package("huggingface_hub")
def test_retry_local_entry_not_found():
    from huggingface_hub.errors import LocalEntryNotFoundError

    assert _should_retry_hf_error(LocalEntryNotFoundError("missing")) is True


@skip_if_no_package("datasets")
def test_retry_dataset_generation_error():
    from datasets.exceptions import DatasetGenerationError  # type: ignore

    assert _should_retry_hf_error(DatasetGenerationError("oops")) is True


def test_retry_filenotfound_hub_unreachable():
    err = FileNotFoundError(
        "An error happened while trying to locate the file on the Hub "
        "and we cannot find the requested files in the local cache."
    )
    assert _should_retry_hf_error(err) is True


def test_retry_filenotfound_hub_either():
    err = FileNotFoundError("file is not present on the Hugging Face Hub either")
    assert _should_retry_hf_error(err) is True


def test_no_retry_filenotfound_unrelated():
    assert _should_retry_hf_error(FileNotFoundError("/tmp/foo not found")) is False


def test_retry_valueerror_cache_message():
    assert _should_retry_hf_error(ValueError("Couldn't find cache for foo")) is True


def test_no_retry_valueerror_unrelated():
    assert _should_retry_hf_error(ValueError("bad arg")) is False


@skip_if_no_package("requests")
def test_retry_readtimeout_huggingface():
    from requests.exceptions import ReadTimeout

    assert _should_retry_hf_error(ReadTimeout("timed out: huggingface.co")) is True


@skip_if_no_package("requests")
def test_no_retry_readtimeout_other_host():
    from requests.exceptions import ReadTimeout

    assert _should_retry_hf_error(ReadTimeout("timed out: example.com")) is False


def test_no_retry_unrelated_exception():
    assert _should_retry_hf_error(RuntimeError("boom")) is False


@pytest.fixture
def fast_retry(monkeypatch):
    import tenacity.nap

    monkeypatch.setattr(tenacity.nap, "sleep", lambda _s: None)


@skip_if_no_package("huggingface_hub")
def test_retry_succeeds_after_transient(fast_retry):
    transient = _make_hf_http_error(429)

    fn = MagicMock(side_effect=[transient, "ok"])
    assert _call_with_hf_retry(fn) == "ok"
    assert fn.call_count == 2


@skip_if_no_package("huggingface_hub")
def test_retry_gives_up_after_max_tries(fast_retry, monkeypatch):
    from huggingface_hub.errors import HfHubHTTPError

    # force a known max-tries regardless of CI env
    monkeypatch.setattr("inspect_ai.dataset._sources.hf._hf_max_tries", lambda: 3)

    transient = _make_hf_http_error(429)

    fn = MagicMock(side_effect=transient)
    with pytest.raises(HfHubHTTPError):
        _call_with_hf_retry(fn)
    assert fn.call_count == 3


def test_retry_does_not_retry_non_transient(fast_retry):
    fn = MagicMock(side_effect=RuntimeError("boom"))
    with pytest.raises(RuntimeError):
        _call_with_hf_retry(fn)
    assert fn.call_count == 1


def test_max_tries_uses_ci_env(monkeypatch):
    from inspect_ai.dataset._sources.hf import (
        _MAX_TRIES_CI,
        _MAX_TRIES_DEFAULT,
        _hf_max_tries,
    )

    monkeypatch.delenv("CI", raising=False)
    assert _hf_max_tries() == _MAX_TRIES_DEFAULT

    monkeypatch.setenv("CI", "1")
    assert _hf_max_tries() == _MAX_TRIES_CI


def _install_fake_datasets(monkeypatch, load_dataset):
    # `verify_required_version` queries importlib.metadata, not sys.modules,
    # so it has to be patched separately from the module stub.
    import sys
    import types

    fake = types.ModuleType("datasets")
    fake.load_dataset = load_dataset
    fake.load_from_disk = lambda *_a, **_k: None
    monkeypatch.setitem(sys.modules, "datasets", fake)
    monkeypatch.setattr(
        "inspect_ai.dataset._sources.hf.verify_required_version",
        lambda *_a, **_k: None,
    )


@skip_if_no_package("huggingface_hub")
def test_hf_dataset_retry_false_disables_retry(monkeypatch):
    from huggingface_hub.errors import HfHubHTTPError

    transient = _make_hf_http_error(429)
    call_count = 0

    def fake_load_dataset(*_a, **_k):
        nonlocal call_count
        call_count += 1
        raise transient

    _install_fake_datasets(monkeypatch, fake_load_dataset)

    from inspect_ai.dataset import hf_dataset

    with pytest.raises(HfHubHTTPError):
        hf_dataset(
            path="inspect-ai-test/nonexistent-dataset",
            split="test",
            cached=False,
            retry=False,
        )
    assert call_count == 1


@skip_if_no_package("huggingface_hub")
def test_hf_dataset_default_retries_transient_errors(fast_retry, monkeypatch):
    from huggingface_hub.errors import HfHubHTTPError

    # pin max-tries so CI=true doesn't push it to 5
    monkeypatch.setattr("inspect_ai.dataset._sources.hf._hf_max_tries", lambda: 3)

    transient = _make_hf_http_error(429)
    call_count = 0

    def fake_load_dataset(*_a, **_k):
        nonlocal call_count
        call_count += 1
        raise transient

    _install_fake_datasets(monkeypatch, fake_load_dataset)

    from inspect_ai.dataset import hf_dataset

    with pytest.raises(HfHubHTTPError):
        hf_dataset(
            path="inspect-ai-test/nonexistent-dataset",
            split="test",
            cached=False,
        )
    assert call_count == 3


class _FakeHFDataset:
    """Minimal stand-in for a datasets.Dataset object."""

    def __init__(self, records) -> None:
        self._records = list(records)
        self.saved_to: str | None = None

    def shuffle(self, seed=None):
        import random

        rng = random.Random(seed)
        shuffled = list(self._records)
        rng.shuffle(shuffled)
        return _FakeHFDataset(shuffled)

    def select(self, indices):
        return _FakeHFDataset([self._records[i] for i in indices])

    def to_list(self):
        return list(self._records)

    def save_to_disk(self, path):
        import os

        os.makedirs(path, exist_ok=True)
        self.saved_to = path


def _install_fake_datasets_full(monkeypatch, tmp_path, load_dataset, load_from_disk):
    import sys
    import types

    fake = types.ModuleType("datasets")
    fake.load_dataset = load_dataset
    fake.load_from_disk = load_from_disk
    monkeypatch.setitem(sys.modules, "datasets", fake)
    monkeypatch.setattr(
        "inspect_ai.dataset._sources.hf.verify_required_version",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "inspect_ai.dataset._sources.hf.inspect_cache_dir",
        lambda *_a, **_k: str(tmp_path),
    )


@pytest.mark.parametrize("limit,expected", [(None, 2), (0, 0), (1, 1)])
def test_hf_dataset_limit(limit, expected, tmp_path, monkeypatch) -> None:
    records = [{"input": "a", "target": "1"}, {"input": "b", "target": "2"}]

    def fake_load_dataset(*_a, **_k):
        return _FakeHFDataset(records)

    _install_fake_datasets_full(
        monkeypatch, tmp_path, fake_load_dataset, lambda *_a, **_k: None
    )

    from inspect_ai.dataset import hf_dataset

    dataset = hf_dataset(
        path="org/ds", split="test", limit=limit, cached=False, retry=False
    )

    assert len(dataset) == expected


def test_hf_dataset_shuffle_sets_shuffled_flag(tmp_path, monkeypatch):
    # Regression: hf_dataset(..., shuffle=True) must report dataset.shuffled
    # as True so the eval log header records the shuffle correctly.
    records = [{"input": "a", "target": "1"}, {"input": "b", "target": "2"}]

    def fake_load_dataset(*_a, **_k):
        return _FakeHFDataset(records)

    _install_fake_datasets_full(
        monkeypatch, tmp_path, fake_load_dataset, lambda *_a, **_k: None
    )

    from inspect_ai.dataset import hf_dataset

    ds = hf_dataset(path="org/ds", split="test", shuffle=True, cached=False)
    assert ds.shuffled is True

    ds_unshuffled = hf_dataset(path="org/ds", split="test", shuffle=False, cached=False)
    assert ds_unshuffled.shuffled is False


def test_hf_dataset_cache_key_includes_revision(tmp_path, monkeypatch) -> None:
    # Regression: loading with revision="X" must not poison the cache for a
    # subsequent default (revision=None) load of the same dataset.
    saved_dirs: dict[str, list] = {}

    def fake_load_dataset(*_a, revision=None, **_k):
        target = revision or "default"
        ds = _FakeHFDataset([{"input": "q", "target": target}])
        # capture where each revision gets cached
        orig_save = ds.save_to_disk

        def save(path):
            orig_save(path)
            saved_dirs.setdefault(path, []).append(target)

        ds.save_to_disk = save
        return ds

    def fake_load_from_disk(path):
        # return whatever was last saved at this path
        target = saved_dirs[path][-1]
        return _FakeHFDataset([{"input": "q", "target": target}])

    _install_fake_datasets_full(
        monkeypatch, tmp_path, fake_load_dataset, fake_load_from_disk
    )

    from inspect_ai.dataset import hf_dataset

    # first load pins a specific revision
    ds_pinned = hf_dataset(path="org/ds", split="test", revision="abc123")
    assert ds_pinned[0].target == "abc123"

    # second load asks for the default branch; must NOT serve the pinned
    # revision from cache
    ds_default = hf_dataset(path="org/ds", split="test")
    assert ds_default[0].target == "default", (
        "default-revision load returned data cached from revision='abc123'"
    )


def test_hf_dataset_cache_hit_does_not_invoke_retry(tmp_path, monkeypatch):
    # Regression guard: cache-hit must skip the retry wrapper, otherwise a
    # corrupted local cache would stall behind the 5-minute backoff window.
    import sys
    import types

    from inspect_ai._util.file import safe_filename
    from inspect_ai._util.hash import mm3_hash

    monkeypatch.setattr(
        "inspect_ai.dataset._sources.hf.inspect_cache_dir",
        lambda *_a, **_k: str(tmp_path),
    )

    path = "test/cache-hit-dataset"
    split = "test"
    # must match the hash formula in hf_dataset
    dataset_hash = mm3_hash(f"{path}{None}{None}{split}{None}{{}}")
    cache_dir = tmp_path / f"{safe_filename(path)}-{dataset_hash}"
    cache_dir.mkdir()

    fake_dataset = SimpleNamespace(
        to_list=lambda: [{"input": "x", "target": "y"}],
    )

    def must_not_call_load_dataset(*_a, **_k):
        pytest.fail("datasets.load_dataset must not be called on cache hit")

    fake = types.ModuleType("datasets")
    fake.load_dataset = must_not_call_load_dataset
    fake.load_from_disk = lambda *_a, **_k: fake_dataset
    monkeypatch.setitem(sys.modules, "datasets", fake)
    monkeypatch.setattr(
        "inspect_ai.dataset._sources.hf.verify_required_version",
        lambda *_a, **_k: None,
    )

    def must_not_call_retry(_fn):
        pytest.fail("_call_with_hf_retry must not wrap the cache-hit branch")

    monkeypatch.setattr(
        "inspect_ai.dataset._sources.hf._call_with_hf_retry", must_not_call_retry
    )

    from inspect_ai.dataset import hf_dataset

    result = hf_dataset(path=path, split=split)
    assert len(result) == 1
