# HuggingFace Dataset: Lazy Memory-Mapped Access

## Context

The `hf_dataset()` loader currently calls `dataset.to_list()` on the HuggingFace `datasets.Dataset` object, converting it to a list of Python dicts, then converts those to `Sample` objects and wraps them in a `MemoryDataset`. This defeats HuggingFace's built-in memory-mapped Arrow storage — the entire dataset is materialized into Python objects in memory.

For large HF datasets (100K+ samples, image-heavy benchmarks), this is the dominant memory consumer. The HF `datasets` library already supports lazy, memory-mapped row access via `dataset[i]` which returns a single dict on demand. We can leverage this by creating a new `Dataset` subclass that wraps the HF dataset and converts rows to `Sample` on access.

## Design

### New class: `HuggingFaceDataset(Dataset)`

A `Dataset` subclass that holds a reference to the HuggingFace `datasets.Dataset` object and a `RecordToSample` converter. Rows are converted to `Sample` on `__getitem__` access rather than all at once.

**Key design decisions:**

1. **Shuffle via index permutation** — Instead of shuffling the underlying HF dataset (which creates a copy), maintain a `list[int]` index mapping. `shuffle()` shuffles this list (tiny — just integers). `__getitem__(i)` translates through the mapping.

2. **`RecordToSample` can return multiple samples** — The `RecordToSample` protocol allows one record to produce multiple `Sample` objects. This means we can't assume a 1:1 mapping between HF row indices and our sample indices. We need to handle this during construction by doing a single pass to build the index.

3. **Fallback to `MemoryDataset` for multi-sample records** — If the `RecordToSample` function produces multiple samples from a single record, fall back to eager `MemoryDataset` (current behavior). This is rare in practice and keeps the lazy path simple.

4. **`filter()` returns a `MemoryDataset`** — Filtering requires evaluating the predicate on every sample, so it materializes. This matches the current behavior and `filter()` is only used for `sample_id` selection (small result sets).

5. **`sort()` without materializing** — Sort the `_indices` array by evaluating the key function on each sample lazily. Each sample is accessed once for the key but not kept in memory simultaneously.

6. **`shuffle_choices()` materializes** — Modifies sample content in place, requires all samples. This is relatively rare and the whole point is saving memory on large datasets.

### Files to modify

#### `src/inspect_ai/dataset/_sources/hf.py`
- Create `HuggingFaceDataset(Dataset)` class
- Modify `hf_dataset()` to return `HuggingFaceDataset` when possible, fall back to `MemoryDataset` when `RecordToSample` produces multiple samples per record

#### `src/inspect_ai/dataset/_dataset.py`
- No changes needed — `HuggingFaceDataset` is an implementation detail, not part of the public API

#### `src/inspect_ai/dataset/__init__.py`
- No changes needed

### `HuggingFaceDataset` implementation sketch

```python
class HuggingFaceDataset(Dataset):
    def __init__(
        self,
        hf_dataset: Any,  # datasets.Dataset
        data_to_sample: RecordToSample,
        name: str | None = None,
        location: str | None = None,
        shuffled: bool = False,
        indices: list[int] | None = None,
        auto_id: bool = False,
    ) -> None:
        self._hf_dataset = hf_dataset
        self._data_to_sample = data_to_sample
        self._name = name
        self._location = location
        self._shuffled = shuffled
        self._auto_id = auto_id
        # Index mapping: our index -> HF row index
        self._indices = indices if indices is not None else list(range(len(hf_dataset)))
        # Overlay for shuffle_choices — when populated, overrides lazy access
        self._materialized: list[Sample] | None = None

    def _get_sample(self, index: int) -> Sample:
        """Get a sample by our logical index."""
        if self._materialized is not None:
            return self._materialized[index]
        hf_index = self._indices[index]
        record = self._hf_dataset[hf_index]  # lazy Arrow read
        sample = as_sample_list(self._data_to_sample(record))[0]
        if self._auto_id:
            sample.id = index + 1
        return sample

    def __len__(self) -> int:
        if self._materialized is not None:
            return len(self._materialized)
        return len(self._indices)

    def __getitem__(self, index: int | slice) -> Sample | Dataset:
        if isinstance(index, int):
            return self._get_sample(index)
        else:
            if self._materialized is not None:
                return MemoryDataset(
                    samples=self._materialized[index],
                    name=self._name,
                    location=self._location,
                    shuffled=self._shuffled,
                )
            return HuggingFaceDataset(
                hf_dataset=self._hf_dataset,
                data_to_sample=self._data_to_sample,
                name=self._name,
                location=self._location,
                shuffled=self._shuffled,
                indices=self._indices[index],
                auto_id=self._auto_id,
            )

    def shuffle(self, seed: int | None = None) -> None:
        if self._materialized is not None:
            if seed is not None:
                random.Random(seed).shuffle(self._materialized)
            else:
                random.shuffle(self._materialized)
        else:
            if seed is not None:
                random.Random(seed).shuffle(self._indices)
            else:
                random.shuffle(self._indices)
        self._shuffled = True

    def filter(self, predicate, name=None) -> MemoryDataset:
        # Materializes — filter is used for sample_id selection (small results)
        return MemoryDataset(
            samples=[s for s in self if predicate(s)],
            name=name or self._name,
            location=self._location,
            shuffled=self._shuffled,
        )

    def sort(self, reverse=False, key=sample_input_len) -> None:
        if self._materialized is not None:
            self._materialized.sort(reverse=reverse, key=key)
        else:
            # Sort indices by evaluating key lazily — each sample accessed
            # once for the key but not kept in memory simultaneously
            self._indices.sort(
                reverse=reverse,
                key=lambda idx: key(
                    as_sample_list(self._data_to_sample(self._hf_dataset[idx]))[0]
                ),
            )

    def shuffle_choices(self, seed=None) -> None:
        # Materialize all samples, then shuffle choices in place
        if self._materialized is None:
            self._materialized = [self._get_sample(i) for i in range(len(self))]
            self._indices = []  # free the index list
        # Apply choice shuffling (same logic as MemoryDataset)
        rand = random.Random(seed)
        for sample in self._materialized:
            if not sample.choices:
                continue
            positions = list(range(len(sample.choices)))
            rand.shuffle(positions)
            sample.choices = [sample.choices[i] for i in positions]
            # ... remap target ...
```

### Multi-sample `RecordToSample` detection

In `hf_dataset()`, probe the first record to check if `data_to_sample` returns multiple samples:

```python
first_record = hf_ds[0]
probe_result = as_sample_list(data_to_sample(first_record))
if len(probe_result) > 1:
    # Fall back to MemoryDataset (current behavior)
    return MemoryDataset(
        samples=data_to_samples(hf_ds.to_list(), data_to_sample, auto_id),
        ...
    )
else:
    return HuggingFaceDataset(hf_ds, data_to_sample, ...)
```

### `auto_id` handling

When `auto_id=True`, IDs are assigned sequentially. The `HuggingFaceDataset` computes `id = index + 1` in `_get_sample()` rather than pre-assigning.

### `shuffle_choices` handling

When `shuffle_choices()` is called, the dataset materializes all samples into an internal `_materialized` list and switches to list-backed access (essentially becoming a `MemoryDataset` internally without changing the type). This is acceptable because `shuffle_choices` is relatively rare and users who use it are likely okay with the memory cost.

## Access patterns during eval (confirming compatibility)

1. **`dataset[sample_index].id`** (run.py:383) — single item access, works with lazy `__getitem__`
2. **`deepcopy(dataset[sample_index])`** (run.py:412) — single item access + deepcopy, works
3. **`len(dataset)`** (run.py:470) — works via `len(self._indices)`
4. **`dataset.name`** (run.py:266) — property, works
5. **`for s in dataset`** (run.py:296, early stopping) — iteration via `__getitem__`, works
6. **`dataset.shuffle(seed)`** (loader.py) — shuffles index array, works
7. **`slice_dataset()` uses `dataset.filter()` and `dataset[slice]`** — both handled

## What this does NOT help with

- CSV/JSON datasets — those parse the entire file anyway
- Datasets where `RecordToSample` returns multiple samples per record
- Very small datasets (overhead isn't meaningful)

## Verification

```bash
# Unit tests
pytest tests/test_eval_set.py tests/test_eval.py -x -v

# HF-specific dataset tests (if any exist)
pytest tests/ -k "hf" -v

# Type checking
mypy --exclude tests/test_package src tests
```

Manual verification: load a HF dataset and confirm memory usage is lower by checking process RSS before/after.
