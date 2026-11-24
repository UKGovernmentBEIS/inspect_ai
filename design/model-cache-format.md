# Model cache format

## Overview

The model output cache stores each cached generation as a small JSON Lines
file, so that reading the cache only ever parses data. Each entry file has
two lines: a header with the format version, the cache key and the expiry
time, and then the `ModelOutput` as JSON. A lookup reads the header, checks
the version, key and expiry, and validates the output with the same Pydantic
models that read eval logs; anything that does not parse or validate is a
cache miss. `inspect cache list --pruneable` and `inspect cache prune` read
only the header line and judge an entry by it alone. Before storing an
output, the cache reads the serialized entry back with the lookup's own
reader and stores it only if the result equals the original (leaving
`metadata` out of the comparison), so a cache hit returns what was stored.
Each entry is written to a temporary file in its directory and renamed into
place, so a reader sees either a whole entry or none.

Entries written by earlier versions of Inspect are pickles under a different
file name. They are never loaded: an upgraded Inspect misses on them and
regenerates the output, and `inspect cache prune` deletes them, recognizing
them by name and by their first two bytes without deserializing them.

## Why

Loading a cache file must never execute code, whatever bytes the file holds.
`pickle.load()` can execute code while it reads, before the caller sees a
value, so no check made after loading can give that guarantee; the format
itself has to be one whose reader only parses data. The cached value is
already a Pydantic model that eval logs serialize to JSON
(`ModelEvent.output`), so JSON reuses existing serialization and validation
rather than adding new ones.

## How it works

User documentation: "Management", "Cache Directory" and "Cache Entries" in
[Caching](../docs/caching.qmd). All code is in
`src/inspect_ai/model/_cache.py` and all tests in `tests/model/test_cache.py`
unless noted; the tests use `mockllm` and a cache directory under `tmp_path`,
and need no network, Docker or provider.

### Layout and file name

The cache root and model directories are those `cache_path` returns, with
its path-safety checks (`_path_is_in_cache`, `_is_safe_model_name`). An entry
lives at `cache_path(model) / "<key>.jsonl"` (`_cache_entry_path`), where
`<key>` is the cache key `_cache_key` computes. The format did not change the
key or the directory layout (`test_cache_layout_unchanged_for_normal_model_names`).

### Entry file (format version 1)

A UTF-8 file of exactly two lines, each ending in `\n`:

1. **Header**, a JSON object validated by `_CacheHeader`: the integer format
   `version`, the entry's `key` (which must equal the key in the file name),
   and `expiry`, a timestamp with a UTC offset or `null` for an entry that
   never expires.
2. **Body**, the `ModelOutput` as one line of JSON.

Both lines use the JSON dialect eval logs use, with non-finite floats as
`NaN`/`Infinity` constants (see [NaN score serialization](nan-serialization.md)),
and strings are written as UTF-8 rather than `\u` escapes, which keeps text
in non-Latin scripts at half the size (`_entry_bytes`). Unknown header fields
are ignored, so an additive change old readers can ignore needs no new
version; `version` changes only when an old reader would misread the file.

The header is a separate line so that list and prune can read an entry's
expiry with one bounded `readline`, without parsing the output.

### Reading

One header reader (`_read_header`) serves lookup, list and prune. It reads a
single line up to a fixed bound and rejects a header that is missing,
over-long, not a JSON object, invalid, of another version, or names another
key. Only lookup reads the body (`_read_body`). All parsing is the stdlib
`json` module followed by validation against fixed Pydantic models.

- **Lookup** (`cache_fetch`) reads only `<key>.jsonl`. A missing file, an
  invalid header or a body that does not validate is a miss: traced, never
  raised. The body is parsed only under a valid, unexpired header. An expired
  entry is a miss and is deleted. Validation runs without the log
  deserialization context, so stored message IDs come back as written. A miss
  leads to a normal generation whose store replaces the file.
- **List** (`cache_list_expired`) walks the cache tree (or the model
  directories asked for) and opens only regular files whose names match an
  entry pattern, never the body. It returns current-format entries whose
  header is valid and expired, whatever their body holds (an expired entry
  can no longer be served either way), and legacy entries. A file with an
  invalid header is skipped, since it may be damaged or of another format
  version.
- **Prune** (`cache_prune`) re-classifies each file it is given the same way
  (`_is_pruneable`), after the inside-the-cache check, and deletes only files
  it classifies as list would. The classification and the deletion are
  separate steps on a path, so a store that replaces the entry between them
  can be deleted (see Guarantees and limits).

Tests: `test_cache_invalid_headers`, `test_cache_invalid_bodies_are_judged_by_header`,
`test_cache_expiry`, `test_cache_round_trip`, `test_cache_round_trip_non_ascii`.

### Legacy entries

A **legacy entry** is a file named by a bare key (no suffix) whose first two
bytes are a pickle protocol header (`_is_pruneable`). Reading those two bytes
is the only access.

- Lookup never reads them, so after upgrading every earlier entry is a miss
  and is regenerated on first use.
- List reports them as pruneable whatever their expiry, because this version
  can never serve them, and prune deletes them; `inspect cache clear` removes
  them with everything else. The CLI help and the pruneable table title say
  so (`src/inspect_ai/_cli/cache.py`).
- A key-named file without a pickle header, and any file matching neither
  pattern, is left alone by list and prune.

Test: `test_cache_legacy_entries`.

### Store and the round-trip check

`cache_store` never caches content-filter outputs. Otherwise it serializes
the entry and, before writing, reads the body back with the lookup's own
reader and compares the result with the original output (`_entry_bytes`,
`_comparable`). The comparison leaves out the `metadata` fields of the
output, its fallback and its messages, and treats an empty `completion` on
the original as the first choice's message text, which is what validation
fills in on reading (Anthropic's merged `pause_turn` outputs have this
shape). The same bytes are written only if the two are equal. If
serialization or the read-back fails, or the result differs, the output is
not cached: `generate()` returns it normally, the store is traced, and a
warning is logged once per model and reason.

The check makes the hit guarantee hold whatever an output holds, without a
list of the types JSON cannot carry. Outputs it refuses include tool-call
arguments with values JSON returns in another form (dates and colliding
integer and string keys that the YAML fallback of `parse_tool_call` produces
from model text, dataclass and Pydantic objects), strings with surrogate code
points, some outputs holding NaN, and `metadata` that does not serialize.
Infinite floats round-trip and are cached.

Tests: `test_cache_lossy_outputs_are_not_cached`,
`test_cache_nan_output_is_not_stored`, `test_cache_normalized_outputs_are_cached`,
`test_cache_skips_content_filter`.

### Writing, concurrency and failure

`cache_store` writes with `atomic_write_bytes` without `fsync`
(`src/inspect_ai/_util/atomic_write.py`, the writer eval logs use): a
temporary file in the entry's directory renamed into place. Its trade-offs
(space for a second copy during the write, refused renames on Windows while
a reader holds the entry open, permissions of the temporary copy) are
documented there and accepted for the cache as for eval logs. List and prune
never match temporary files, so they never list or delete a write in
progress; `cache_size` counts and `cache_clear` removes any left by a killed
process.

`cache_fetch` and `cache_store` resolve the entry path and create directories
inside their exception handlers, so a failure there (for example a regular
file where the cache root should be) is a miss or a skipped store, like a
failure while reading or writing. The outside-the-cache refusal keeps its
warning. The CLI commands keep their own error behaviour.

Tests: `test_cache_concurrent_writers_and_reader` (skipped on Windows, where
the rename is refused while the reader holds the file),
`test_cache_failed_write_is_skipped`, `test_cache_temporary_files_are_not_entries`,
`test_cache_path_setup_failures_are_misses`.

## Guarantees and limits

- **Reading never executes code.** No cache path (lookup, list, prune,
  clear, size) deserializes with pickle or any other mechanism that
  constructs objects the input chooses. `_cache.py` does not import `pickle`
  (`test_cache_module_does_not_import_pickle`), and a crafted pickle with a
  side effect, placed at a key's legacy path, at `<key>.jsonl` and under an
  unrelated name, never runs through lookup, list, prune or the CLI
  (`test_cache_never_deserializes_pickle`).
- **Invalid files are misses.** A file whose header or body does not parse or
  validate never raises into `generate()`.
- **A hit returns what was stored.** It never changes content, tool calls or
  their arguments. The only differences a hit can show are `metadata` values
  of non-JSON types in their JSON form (a `datetime` as its ISO string, as the
  eval log records it) and an empty `completion` filled from the message
  text. The guarantee is `==` equality, not type identity: a value equal to
  its JSON form, such as an `IntEnum` in tool-call arguments, comes back as
  the plain JSON type.
- **Whole entries only.** A reader sees the previous whole entry, the new one
  or none, and concurrent writers of one key leave one writer's whole file.
  There is no `fsync`, so after a system crash an entry may be empty or
  partial, which readers treat as invalid. There is no locking.
- **List and prune judge by the header alone**, reading a bounded header and
  never the output.
- **Cache I/O failures do not raise into `generate()`.** Errors inside
  `cache_fetch` and `cache_store` become misses or skipped stores. Building
  the cache key happens before them, in `Model._generate`, and its errors
  still propagate: model arguments that cannot be fingerprinted fail a cached
  generation (`test_cache_defers_unserializable_model_args_to_caching`).
- **Cleanup can discard a fresh entry.** Prune, and lookup's deletion of an
  expired entry, judge a file and then delete its path, without a lock. A
  store that renames a new entry into place between those steps loses it,
  and the next identical call generates again. Entries stay whole either
  way.
- **Limits.** Outputs the round-trip check refuses reach the provider on
  every call. The check costs one extra parse, validation and comparison per
  store, tens of microseconds per entry against model calls of seconds.
  Entries are about the size of the pickles they replace for mostly-English
  outputs and larger for text in other scripts, since a pickle stores a
  repeated string once. Lookup reads the whole entry file; a very large file
  costs memory, not execution.

## Decisions

- **No migration of pickle entries.** No command or option converts them,
  because converting means unpickling; existing entries are regenerated
  instead (decision: Ransom, 2026-11-20).
- **A store-time round-trip check, not a type-by-type rule**, decides which
  outputs are cached (decision: Ransom, 2026-11-20).
- **Atomic writes, not a body hash checked on lookup**, keep partial and
  mixed files from being read (decision: Ransom, 2026-11-23).
- **A new file name**, so two Inspect versions sharing a cache directory
  coexist and legacy files are recognizable by name.
- **Prune is the single cleanup path** for legacy entries; storing a new
  entry leaves a key's legacy file in place.

## Alternatives considered

- **Validate after `pickle.load()`, or a restricted unpickler.** Code runs
  during the load, so validating afterwards cannot work. A
  `find_class` allow-list still runs the reduce and `__setstate__` machinery
  of every allowed class and must track every class reachable from
  `ModelOutput`; it is hardening, not a guarantee.
- **An opt-in migration command** using `pickle.load()`. It would keep
  long-lived caches but keeps a pickle-loading path in Inspect.
- **The same file name with new content.** Two Inspect versions sharing the
  default user cache directory would overwrite each other's entries on every
  shared key, and legacy files could be told apart only by their bytes.
- **One JSON object with the header fields first.** Reading only the
  metadata would need a streaming parser, and ijson does not accept the
  `NaN`/`Infinity` constants.
- **Expiry in the file name or mtime.** Lookup would have to search for a
  name by key, and mtime does not survive copies.
- **A metadata index (SQLite).** A second source of truth to keep consistent
  under concurrent writers; header reads are already cheaper than the full
  loads they replaced.
- **A compressed body.** About three times smaller, but unreadable with
  ordinary tools and a codec in the format; a later version can add it.
- **A type-by-type rule for cacheable outputs.** It must name every type JSON
  changes and inspect values before a model dump erases their types, and each
  missed type is a hit that returns changed data.
- **A body hash in the header.** Readers would still see partial and mixed
  files, every lookup would hash the body, and header-only list and prune
  could not use it.
- **Deleting a key's legacy file when its new entry is stored.** It deletes
  entries an older Inspect sharing the directory still uses, and adds a
  side effect to the write path.

## Compatibility

- **Existing caches.** Entries written by earlier versions are not reused,
  including caches set never to expire: each previously cached call reaches
  the provider once more and is stored in the new format. The old files stay
  on disk until `inspect cache prune` or `inspect cache clear` removes them,
  so a cache can hold both formats for one key until then. The user docs
  ("Cache Entries") say so.
- **Older and newer Inspect sharing a cache directory.** Each reads only its
  own files. An older Inspect's prune fails to unpickle the JSON files (`{`
  is not a pickle opcode) and skips them; a newer Inspect's prune deletes the
  older version's entries.
- **Public API and CLI.** `cache_clear`, `cache_list_expired`, `cache_path`,
  `cache_prune`, `cache_size` and `CachePolicy` keep their signatures.
  `cache_list_expired` and `cache_prune` also return and delete legacy
  entries; their docstrings and the CLI help say so.
- **Eval logs, schemas and viewer types.** Unchanged, as are `ModelEvent.cache`
  and the cache key.
- **Test helper.** `tests/test_helpers/output_cache.py`, used by the live
  provider cache tests, checks for the `<key>.jsonl` entry.

## Security

Untrusted input reaching the cache code: the bytes of any file under the
cache root, the file names in it, and symlinks.

- Content is parsed only by the stdlib `json` module and validated against
  fixed Pydantic models. Validation imports nothing, constructs no object the
  input chooses and opens no path the input names; its one file access is
  `mimetypes.guess_type` in `ContentDocument` validation
  (`src/inspect_ai/_util/content.py`), which loads the system MIME database
  the first time it runs. Eval-log reading already validates the same models
  from files written by others.
- Lookup reads one path derived from the key. List and prune open only files
  named like an entry, after the inside-the-cache check, which resolves
  symlinks (`test_cache_store_and_fetch_stay_in_cache_dir`,
  `test_cache_refuses_symlinks_out_of_cache_dir`,
  `test_cache_clear_list_and_prune_stay_in_cache_dir`,
  `test_cache_refusals_create_nothing`,
  `test_cache_prune_skips_unresolvable_paths`). The writer runs after the
  same check; a symlink inside the cache is written through.
- Legacy detection reads two bytes and compares them. The header read is
  bounded.
- A well-formed entry is served as model output. The cache directory is
  trusted for content as before: the format removes code execution from
  reading it and does not authenticate who wrote an entry.

## Not this design

- **Removing orphaned temporary files** left by a process killed during a
  store, by prune or by age. `cache_clear` removes them.
- **Pickle compatibility shims.** `ModelOutput.__setstate__`
  (`src/inspect_ai/model/_model_output.py`) and the
  `getattr(block, "cache_breakpoint", None)` helpers in
  `src/inspect_ai/model/_openai.py` and
  `src/inspect_ai/model/_providers/anthropic.py` exist for old pickled cache
  entries; nothing in the cache loads pickle now, so they can be reviewed for
  removal, with their tests in
  `tests/model/providers/test_openai_prompt_cache.py` and
  `test_anthropic_cache_control.py`.
- **`DiskSampleStore`** (`src/inspect_ai/_eval/task/store.py`) pickles
  samples to a private temporary file it creates and reads back within one
  process; it is not a cache format and is left as is.
- **Cache size limits or eviction** beyond expiry.
- **Non-regular files at an entry path.** Lookup opens `<key>.jsonl`
  without checking that it is a regular file, so a FIFO placed there
  (directly or through an in-cache symlink) blocks the lookup; list and prune
  skip such paths.
