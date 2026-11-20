# Model cache format

## Overview

The model output cache stores each cached generation as a small JSON Lines
file instead of a pickle, so that reading the cache can only ever parse data.
Each entry file has two lines: a header with the format version, the cache
key and the expiry time, and then the `ModelOutput` as JSON. A cache lookup
reads the header, checks the version, key and expiry, and validates the
output with the same Pydantic models that read eval logs; anything that does
not parse or validate is a cache miss. `inspect cache list --pruneable` and
`inspect cache prune` read only the header line and judge an entry by it
alone.

Entries written by earlier versions (pickles) are never loaded. New entries
use a different file name (`<key>.jsonl` beside the old `<key>`), so an
upgraded Inspect simply misses on old entries and regenerates them (there
is no migration), and
`inspect cache prune` deletes the old files, which it recognizes by name and
by their first two bytes without deserializing them. The cache key, the
directory layout and the public cache API are unchanged.

## Why

Loading a cache file must never execute code, whatever bytes the file holds.
`pickle.load()` can execute code while it reads, before the caller sees a
value, so no check made after loading can provide that guarantee. Today the
cache calls `pickle.load()` on every lookup and, in `inspect cache list
--pruneable` and `inspect cache prune`, on every file in the cache directory,
including files that are not cache entries. The format has to change so that
the reader only parses data.

The cached value is already a Pydantic model that eval logs serialize to JSON
(`ModelEvent.output`), so a JSON format reuses existing serialization and
validation rather than adding a new one.

## Goals and non-goals

Goals:

- No cache code path (lookup, list, prune, clear, size) deserializes a file
  with pickle or any other mechanism that can construct arbitrary objects.
  Files are parsed as JSON and validated against fixed Pydantic models.
- On lookup, a file whose header or body does not parse or validate is a
  cache miss. It never raises into `generate()`.
- List and prune read only a bounded header, never the cached output, so
  they judge an entry by its header alone: a file whose header does not
  parse or validate is skipped, and an entry with a valid expired header is
  listed and pruned whatever its body holds.
- The format carries a version so later changes can be detected.
- Existing pickle entries are never loaded on any path, and prune removes
  them.
- Cache keys, directory layout, `CachePolicy` and the public functions
  (`cache_clear`, `cache_list_expired`, `cache_path`, `cache_prune`,
  `cache_size`) keep their signatures.

Non-goals:

- Making the *content* of a well-formed entry trustworthy. A valid entry is
  served as the model's response, as today. The format makes reading safe;
  it does not authenticate who wrote the entry.
- Migrating existing pickle entries. No command or option converts them,
  because converting means unpickling (decision: Ransom, 2026-11-20).
- Atomic writes, a cache index, size limits or compression (see Not this
  design and Alternatives).
- Changing the cache key computation.

## Current behaviour

All in `src/inspect_ai/model/_cache.py` unless noted.

- **Layout.** An entry lives at `cache_path(model) / entry.key`
  (`_cache_entry_path`, line 63), where `entry.key` is a 32-character
  lowercase hex MD5 (`_cache_key`, line 320) and the model directory is the
  model name, possibly nested (`openai/gpt-...`). The root is
  `INSPECT_CACHE_DIR/generate` or the platform user cache directory
  (`_cache_root`, line 478). Path-safety checks (`_path_is_in_cache`,
  `_is_safe_model_name`) keep entries inside the root.
- **Store.** `cache_store` (line 372) writes `pickle.dump((expiry, output))`
  (line 397), where `expiry` is a timezone-aware UTC `datetime` or `None`
  (`_cache_expiry`, line 355). The write is not atomic. Any exception is
  traced and the output is not cached. Content-filter outputs are never
  cached.
- **Lookup.** `cache_fetch` (line 404) opens the key's file and calls
  `pickle.load()` (line 413), then checks the value is a `ModelOutput` and
  that it has not expired; an expired entry is deleted (line 426). Any
  exception is traced and treated as a miss. The only caller is
  `Model._generate` (`src/inspect_ai/model/_model.py:1813`, store at
  `:2167`).
- **List and prune.** `cache_list_expired` (line 563) walks the whole cache
  tree (or the model directories asked for) and calls `pickle.load()` on
  every file (line 599), whatever its name, to read the expiry.
  `cache_prune` (line 610) loads each candidate again with `pickle.load()`
  (line 628) before deleting it. The CLI (`src/inspect_ai/_cli/cache.py`,
  `list_caches` line 98 and `prune` line 123) calls these.
- **Size and clear.** `cache_size` only `stat()`s files; `cache_clear`
  removes directories with `rmtree`. Neither reads file contents.
- **Pickle compatibility shims.** Because unpickling bypasses Pydantic
  defaults, `ModelOutput.__setstate__`
  (`src/inspect_ai/model/_model_output.py:335`) and the
  `getattr(block, "cache_breakpoint", None)` helpers in
  `src/inspect_ai/model/_openai.py` and
  `src/inspect_ai/model/_providers/anthropic.py` exist to read entries
  pickled by older versions.
- **On-disk evidence.** Existing entries begin with the pickle protocol
  header `0x80` followed by the protocol number (`0x80 0x05` on the local
  cache checked, written under Python 3.14; Inspect does not pass a
  protocol, so it is `pickle.DEFAULT_PROTOCOL`: 4 on Python 3.11–3.13 and 5
  on 3.14).
- **Users of the API.** Within this repo only `Model._generate` and the
  `inspect cache` CLI call the cache functions; the test helper
  `tests/test_helpers/output_cache.py` builds an entry path from
  `cache_path(model) / entry.key`. None of inspect_scout, inspect_flow,
  inspect_evals, inspect_swe, inspect_swarm or inspect_vscode calls the
  generate-cache API or reads its directory.
- **JSON fidelity.** The output models' validators are pure data
  transformations (stop-reason migration, document name and MIME type from
  the string, message ID assignment when absent): none imports, opens files
  or evaluates anything. Eval-log reading already validates the same models
  from files written by others. Measured on 6,916 `ModelEvent.output` values
  from 30 real eval logs, parsing the JSON-mode dump with the stdlib `json`
  module and validating it with `ModelOutput.model_validate` reproduced
  every output exactly (0 mismatches), message IDs included.

## Design

### File name

A current-format entry is stored at `cache_path(model) / f"{key}.jsonl"`,
where `key` is today's `entry.key`. The key computation and model directory
are unchanged. The old name `cache_path(model) / key` is no longer written
or read by lookup.

### File content (format version 1)

A UTF-8 file of exactly two lines, each terminated by `\n` (written as
bytes, so no platform newline translation):

1. **Header**, a JSON object:

   ```json
   {"version": 1, "key": "3f2a...e9", "expiry": "2026-11-27T11:06:00.123456+00:00"}
   ```

   - `version`: integer format version, `1` for this design.
   - `key`: the entry's cache key, which must equal the key in the file name.
   - `expiry`: ISO 8601 timestamp with a UTC offset, or `null` for an entry
     that never expires. A timestamp without an offset is invalid.

2. **Body**: the `ModelOutput`, as one line of JSON.

Both lines use the JSON dialect eval logs use: non-finite floats are written
as the constants `NaN`, `Infinity` and `-Infinity` (see
[NaN score serialization](nan-serialization.md)), and other values are
standard JSON.

The round trip preserves every value of a JSON-representable output. Two
cases need the mechanism named here:

- **Non-finite floats** in any float field (logprobs, `time`,
  `usage.total_cost`). The writer dumps the output in Pydantic's JSON mode
  and encodes it with the stdlib `json` encoder with `allow_nan=True`. A
  spike (Pydantic 2.14) showed that `ModelOutput.model_dump_json()` writes
  `null` for a non-finite `time` or `usage.total_cost`, and that a wrapper
  root model with `ser_json_inf_nan="constants"` still writes `null` for a
  `-inf` logprob in a nested model.
- **Lone surrogates** in strings (message content, tool-call arguments),
  which Python strings can hold and pickle preserved. The stdlib encoder
  writes them as `\ud800`-style escapes. The reader parses the body with the
  stdlib `json` module and then validates the parsed value against
  `ModelOutput`; a spike showed this preserves them, while
  `ModelOutput.model_validate_json()` rejects the same bytes as invalid JSON,
  which would make such an output miss on every lookup.

The header is read the same way.

The header is a Pydantic model, internal to `_cache.py`. Unknown header
fields are ignored, so a later additive change that old readers can ignore
need not bump the version; `version` changes only when an old reader would
misread the file.

### Reading rules

One reader, used by lookup, list and prune, parses a header and reports one
of: *valid* (with its expiry), *unknown version*, or *invalid* (the header
line is missing, longer than 4 KiB, not a JSON object, fails validation, or
its `key` does not match the file name). Only lookup parses the body. All
parsing is stdlib `json` parsing of bytes followed by validation against
fixed Pydantic models; nothing in
the cache module imports `pickle` or calls any other object-constructing
deserializer.

- **Lookup** (`cache_fetch`) reads `<key>.jsonl` only. A missing file, an
  invalid or unknown-version header, a key mismatch, or a body that fails
  `ModelOutput` validation is a miss: traced, never raised. An expired entry
  is a miss and is deleted, as today. The body is parsed only for a valid,
  unexpired header. Validation runs without the log deserialization context,
  so the stored message IDs are kept as written. A miss leads to a normal
  generation whose `cache_store` overwrites the file.
- **List** (`cache_list_expired`) walks the same directories as today but
  considers only regular files whose names match an entry pattern; it never
  opens other files. It reads only the header line and never the body. It
  returns current-format entries whose header is valid and expired, and
  legacy entries (below). An entry with a valid expired header is returned
  whether its body is complete, truncated or invalid: it can no longer be
  served either way. Files with an invalid or unknown-version header are
  skipped (traced), since they may be partial writes in progress or entries
  of a newer Inspect.
- **Prune** (`cache_prune`) re-classifies each file it is given in the same
  way, from the header alone, before deleting it, keeping today's
  inside-the-cache check, and deletes only current-format entries with a
  valid expired header and legacy entries.

### Legacy entries

A file is a **legacy entry** when its name is exactly 32 lowercase hex
characters (no suffix) and its first two bytes are a pickle protocol header:
`0x80` followed by a protocol number from 2 to 5. Reading two bytes and
comparing them is the only access; the file is never deserialized.

- Lookup never reads legacy entries (it looks only at `<key>.jsonl`), so on
  upgrade every existing entry is a miss and is regenerated on first use.
- List reports legacy entries as pruneable, whatever their expiry, because
  this version can never serve them. The CLI table title says entries can be
  pruned because they expired or were written by an earlier version of
  Inspect.
- Prune deletes them. `inspect cache clear` removes them as today.

Files that match neither pattern, and key-named files without a pickle
header, are left alone by list and prune.

### Store

`cache_store` writes the two-line file at `<key>.jsonl` and leaves any
legacy `<key>` file in place. The content-filter rule and path checks are
unchanged. If the output cannot be serialized to JSON (for example a
third-party provider puts a non-JSON object in `metadata`), the output is
not cached, `generate()` returns it normally, and a `warn_once` per model
says caching was skipped because the output is not JSON-serializable.
Today such an output is cached only if it pickles; built-in providers put
only JSON values in output metadata.

A cache hit returns the output as JSON reads it back. For built-in providers
this equals the stored output; values in `metadata` that are not native JSON
types come back as their JSON form (a `datetime` as a string), which is what
the eval log records for the same output.

### Concurrency and failure

Writes stay non-atomic, as today. A lookup that sees a partly written file
finds an invalid header or body and treats it as a miss. List and prune see
only the header: a partly written file whose header line is incomplete is
skipped, and one whose complete header is already expired is listed and
pruned like any other expired entry. There is no new locking. No cache failure on any path raises into
`generate()`; the CLI commands keep their current error behaviour.

### Format versions

A reader handles every version it knows and treats a higher version as a
miss (lookup) or skips it (list and prune). A later Inspect that changes the
format bumps `version`, keeps reading version 1 if it is cheap to, and
otherwise lets version 1 entries miss and makes them pruneable the way this
design treats pickles. An older Inspect that meets a newer entry misses and
overwrites it with its own version.

## Alternatives considered

- **Validate after `pickle.load()`, or a restricted unpickler.** Validating
  after loading cannot work: code runs during the load. A restricted
  `Unpickler.find_class` allow-list narrows which globals can be referenced
  but still runs the reduce and `__setstate__` machinery of every allowed
  class, needs an allow-list covering every class reachable from
  `ModelOutput` (kept in step as models change), and is a hardening measure
  rather than a guarantee. JSON is simpler and gives the guarantee outright.
- **An opt-in migration command** (`inspect cache migrate`) converting
  legacy entries with `pickle.load()`. It would preserve long-lived and
  never-expiring caches, but keeps a pickle-loading path in Inspect.
  Rejected: no path unpickles existing entries, and they are regenerated
  instead (decision: Ransom, 2026-11-20).
- **Same file name (`<key>`) with the new content.** Avoids a second file per
  key during the transition and overwrites each legacy entry on its first
  miss. Rejected because two Inspect versions sharing the default user cache
  directory would overwrite each other's entries on every shared key, and
  because legacy files could then only be recognized by their bytes. With a
  new name the versions coexist, and the old files are removed by prune.
- **One JSON object with the header fields first.** Reading only the
  metadata would need a streaming parser, and ijson does not accept the
  `NaN`/`Infinity` constants. A separate header line is read with one
  bounded `readline`.
- **Expiry in the file name or mtime.** Prune would read nothing, but lookup
  would have to search for a name by key, and mtime does not survive copies.
- **An index database (SQLite) for metadata.** Faster listing for huge
  caches, but adds a second source of truth to keep consistent under
  concurrent writers. Header reads are already cheaper than today's full
  loads (below).
- **Compressing the body.** gzip would cut the measured entries by about
  3x, but makes entries unreadable with ordinary tools and adds a codec to
  the format. Plain JSON is already smaller than pickle. A later version
  can add compression.
- **Deleting a key's legacy file when its new entry is stored.** Cleans up
  without a prune, but deletes entries an older Inspect sharing the
  directory still uses, and adds a write-path side effect. Prune is the
  single cleanup path.

### Size and speed

Measured on the 6,916 real outputs above (Python 3.14, warm file cache):

| | pickle | JSON (this format) |
| --- | --- | --- |
| median entry size | 2,670 B | 2,377 B |
| total for all outputs | 30.3 MB | 28.7 MB |
| serialize, per entry | 13–32 µs | 7–23 µs |
| load and validate, per entry | 10–19 µs | 14–32 µs |

The ranges are three runs; the JSON load was measured both with
`model_validate_json` and with the specified stdlib parse followed by
`model_validate` (16 µs against pickle's 10 µs in the same run). Per-entry
costs are microseconds against model calls of seconds. For 20,000 entry
files, scanning expiry took 0.73 s with today's full `pickle.load()` and
0.51 s reading only the JSON header line; a full JSON load and validation of
every file took 0.81 s. On disk both
formats took about 120 MB for those 20,000 files, since most entries are
smaller than a filesystem block.

## Compatibility and migration

- **Existing caches.** After upgrading, no existing entry is used: every
  previously cached call is a miss once, is regenerated, and is stored in
  the new format. For a user with a large cache, including one configured
  never to expire, this means paying for those generations again: there is
  no migration (decision: Ransom, 2026-11-20). The old files stay on disk,
  taking their current space, until `inspect cache prune` or `inspect cache
  clear` removes them; until then a cache can hold both formats for the
  same keys. The caching docs and the change note must say this.
- **Older and newer Inspect sharing a cache directory.** Each reads only its
  own files. An older Inspect's prune tries `pickle.load()` on new files,
  which fails on the first byte (`{` is not a pickle opcode) and skips them.
  A newer Inspect's prune deletes the older version's entries.
- **Public API and CLI.** Signatures unchanged. `cache_list_expired` and
  `cache_prune` also return and delete legacy entries; their docstrings and
  the `inspect cache list --pruneable` and `inspect cache prune` help and
  table title say so. `cache_size` and `cache_clear` are unchanged.
- **Outputs.** A cache hit returns the JSON round trip of the stored output
  (see Store). Outputs that cannot be serialized to JSON are no longer
  cached and produce a warning.
- **Eval logs, schemas and viewer types.** Unchanged. `ModelEvent.cache`
  values and the cache key are unchanged.

## Security

Untrusted input reaching the new code: the bytes of any file under the cache
root, file names in it, and symlinks. Handling:

- Lookup reads one path derived from the key; list and prune open only files
  whose names match an entry pattern, after today's inside-the-cache check,
  which resolves symlinks.
- Content is parsed only by the stdlib `json` module and then validated
  against fixed Pydantic models whose validators
  are pure data transformations (Current behaviour). No path in the cache
  module deserializes with pickle; a test enforces that `_cache.py` does not
  import it.
- Legacy detection reads two bytes and compares them.
- The header read is bounded at 4 KiB. Lookup reads the whole entry file, as
  today; a very large file costs memory, not execution.
- A well-formed entry is served as model output, exactly as a well-formed
  pickle entry is today. The cache directory is trusted for content to the
  same degree as before; this design removes code execution from reading it,
  and does not change who may write it.

## Testing

All in `tests/model/test_cache.py` unless noted; none need network, Docker
or a model provider (they use `mockllm` and `INSPECT_CACHE_DIR` under
`tmp_path`).

- **Never deserialized.** A crafted file whose unpickling would have a side
  effect (a pickle whose reduce step creates a marker file) is placed (a) at
  a key's legacy path `<key>`, (b) at `<key>.jsonl`, and (c) under an
  unrelated name. `generate(cache=True)` for that key, `cache_list_expired()`,
  `cache_prune()` and the `inspect cache list --pruneable` and `inspect
  cache prune` commands all run, and the marker never appears. The same test
  patches `pickle.load`, `pickle.loads` and `pickle.Unpickler` to fail if
  called.
- **Tripwire.** `_cache.py` does not import `pickle` (in the style of the
  `url2pathname` tripwire in `tests/util/test_file.py`).
- **Round trip.** Store then fetch returns an equal output, including the
  assistant message ID, tool calls with JSON arguments, reasoning content,
  and non-finite floats (`-inf` logprob, `NaN` time, `inf` total cost).
- **Lone surrogates.** Store then fetch of an output whose message content
  and tool-call arguments hold lone surrogates (`"a\ud800b"`, `"\udcff"`)
  is a hit that returns an equal output.
- **Invalid headers.** For `<key>.jsonl` holding random bytes, a header
  without a newline, a header over 4 KiB, a header with `version: 2`, a
  header whose `key` differs from the file name, or an expiry without an
  offset: lookup misses and calls the provider; with the file in place,
  list does not report it and prune does not delete it.
- **Invalid bodies are judged by the header.** A valid unexpired header
  followed by a missing, truncated or invalid body is a lookup miss that
  calls the provider, and is neither listed nor pruned. A valid expired
  header followed by such a body is listed and pruned.
- **Expiry.** An expired current-format entry is a miss and is deleted on
  lookup, is listed, and is pruned; an unexpired one is not listed or
  pruned; `expiry: null` never expires.
- **Legacy entries.** A real legacy entry (pickled `(expiry, ModelOutput)`,
  unexpired) is a miss on lookup, is listed by `cache_list_expired()`, is
  deleted by `cache_prune()`, and `--model` filtering applies to it. A
  key-named file without a pickle header is not listed or deleted.
- **Unserializable output.** An output with a non-JSON object in `metadata`
  is returned by `generate()`, is not cached, and produces one warning.
- **Updated tests.** Tests that read or write pickles directly
  (`test_cache_entry_from_before_input_context_tokens`, the pickle writes in
  the trace and layout tests) move to the new format or are removed;
  `test_cache_layout_unchanged_for_normal_model_names` asserts the
  `.jsonl` name. `tests/test_helpers/output_cache.py` builds the entry path
  with the new name.

## Implementation plan

1. **New format and reader** (`src/inspect_ai/model/_cache.py`,
   `tests/model/test_cache.py`, `tests/test_helpers/output_cache.py`).
   Header model, writer and reader; `cache_store` and `cache_fetch` on
   `<key>.jsonl`; `cache_list_expired` and `cache_prune` on entry-name
   patterns with header-only reads and legacy detection; remove the `pickle`
   import; the warning for unserializable outputs. Tests: never-deserialized,
   tripwire, round trip, lone surrogates, invalid headers, invalid bodies,
   expiry, legacy entries, unserializable output, and the updated existing
   tests.
2. **CLI and docs** (`src/inspect_ai/_cli/cache.py`, `docs/caching.qmd`).
   Pruneable table title and help text; a caching docs section on the entry
   format, that entries from earlier versions are not reused, and that
   `inspect cache prune` removes them. This can ship in the same PR as
   step 1; its change note says existing cache entries are not reused after
   upgrading.

## Open questions

None.

## Not this design

- **Atomic cache writes** (write to a temporary file and rename). Partial
  files are already misses; atomic writes would avoid the wasted generation
  when two identical calls race.
- **Pickle compatibility shims.** `ModelOutput.__setstate__` and the
  `getattr(..., "cache_breakpoint", None)` helpers in `_openai.py` and
  `anthropic.py` exist for old pickled cache entries; once nothing in the
  cache loads pickle they can be reviewed for removal, with their tests in
  `tests/model/providers/test_openai_prompt_cache.py` and
  `test_anthropic_cache_control.py`.
- **`DiskSampleStore`** (`src/inspect_ai/_eval/task/store.py`) pickles
  samples to a private temporary file it creates and reads back within one
  process; it is not a cache format and is left as is.
- **Cache size limits or eviction** beyond expiry.
