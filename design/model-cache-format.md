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
alone. Before storing an output, the cache reads the serialized entry back
with the lookup's own reader and stores it only if the result equals the
original (leaving `metadata` fields out of the comparison), so a cache hit
returns what was stored. Each entry is written to a temporary file in its
directory and renamed into place, so a reader sees either a whole entry or
none.

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
- A cache hit returns the output that was stored. An output that does not
  read back equal is not cached, so a hit never changes content, tool calls
  or their arguments; the only changes a hit can show are that a `metadata`
  value of a non-JSON type comes back in its JSON form and that an empty
  `completion` comes back filled from the message text, as validation fills
  it (Store).
- A reader never sees a partly written entry, and concurrent writers of the
  same key leave one whole entry, not a mix of both.
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
- A cache index, size limits or compression (see Not this design and
  Alternatives).
- Changing the cache key computation.

## Current behaviour

All in `src/inspect_ai/model/_cache.py` unless noted.

- **Layout.** An entry lives at `cache_path(model) / entry.key`
  (`_cache_entry_path`), where `entry.key` is a 32-character lowercase hex
  MD5 (`_cache_key`) and the model directory is the model name, possibly
  nested (`openai/gpt-...`). The root is `INSPECT_CACHE_DIR/generate` or the
  platform user cache directory (`_cache_root`). Path-safety checks
  (`_path_is_in_cache`, `_is_safe_model_name`) keep entries inside the root.
- **Store.** `cache_store` writes `pickle.dump((expiry, output))`, where
  `expiry` is a timezone-aware UTC `datetime` or `None` (`_cache_expiry`).
  The write is not atomic: the entry is opened with `open(filename, "wb")`
  and written in place, so a concurrent reader can see a partly written file,
  and two processes storing the same key can leave a file that mixes both
  bodies yet parses. An exception while writing is traced and the output is
  not cached. Content-filter outputs are never cached.
- **Path setup.** Both `cache_store` and `cache_fetch` resolve the entry
  path with `_cache_entry_path` before their exception handler. It catches
  only the `ValueError` of the outside-the-cache refusal; `cache_path`
  creates the cache root with `mkdir`, so a failure there (for example a
  regular file at `INSPECT_CACHE_DIR/generate`, which gives
  `FileExistsError`) raises into `generate()` from both.
- **Lookup.** `cache_fetch` opens the key's file and calls `pickle.load()`,
  then checks the value is a `ModelOutput` and that it has not expired; an
  expired entry is deleted. An exception while reading is traced and
  treated as a miss (path setup, above, is outside that handler).
  The only caller is `Model._generate` (`src/inspect_ai/model/_model.py`),
  which also calls `cache_store`.
- **List and prune.** `cache_list_expired` walks the whole cache tree (or
  the model directories asked for) and calls `pickle.load()` on every file,
  whatever its name, to read the expiry. `cache_prune` loads each candidate
  again with `pickle.load()` before deleting it. The CLI commands
  `list_caches` and `prune` (`src/inspect_ai/_cli/cache.py`) call these.
- **Size and clear.** `cache_size` only `stat()`s files; `cache_clear`
  removes directories with `rmtree`. Neither reads file contents.
- **Pickle compatibility shims.** Because unpickling bypasses Pydantic
  defaults, `ModelOutput.__setstate__`
  (`src/inspect_ai/model/_model_output.py`) and the
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
- **JSON fidelity.** The output models' validators are data
  transformations (stop-reason migration, tool-call type migration, document
  name and MIME type from the string, message ID assignment when absent, and
  `ModelOutput.set_completion`, which sets an empty `completion` to the first
  choice's message text). The last one changes a value an in-memory output
  can hold: the Anthropic provider's `pause_turn` continuation merges the
  first response's content into the continuation's message and keeps the
  continuation's empty `completion`, so such an output reads back with a
  different `completion`. Outputs read from eval logs have already been
  through the validator, so the corpus below cannot show it. None imports or evaluates
  anything, constructs an object the input chooses, or opens a path the
  input names; the one file access is `mimetypes.guess_type` in
  `ContentDocument.set_name_and_mime_type` (`src/inspect_ai/_util/content.py`),
  which loads the system MIME database the first time it runs. Eval-log
  reading already validates the same models from files written by others. Measured on 6,916 `ModelEvent.output` values
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

Both lines use the JSON dialect eval logs use (see
[NaN score serialization](nan-serialization.md)), which the Round trip test
checks. Strings are written as UTF-8 rather than `\u` escapes; a string
holding a surrogate code point cannot be encoded, so such an output fails
serialization and is not cached (Store).

The header is a Pydantic model, internal to `_cache.py`. Unknown header
fields are ignored, so a later additive change that old readers can ignore
need not bump the version; `version` changes only when an old reader would
misread the file.

### Reading rules

One reader, used by lookup, list and prune, parses a header and reports it
*valid* (with its expiry) or *invalid*: the header line is missing, longer
than 4 KiB, not a JSON object, fails validation, has a `version` other than
1, or its `key` does not match the file name. Only lookup parses the body. All
parsing is stdlib `json` parsing of bytes followed by validation against
fixed Pydantic models; nothing in
the cache module imports `pickle` or calls any other object-constructing
deserializer.

- **Lookup** (`cache_fetch`) reads `<key>.jsonl` only. A missing file, an
  invalid header, or a body that fails
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
  served either way. Files with an invalid header are skipped (traced),
  since they may be damaged files or entries of another format version.
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
unchanged. Before writing, the writer checks the round trip: it serializes
the output, parses and validates those bytes with the lookup's own reader,
and compares the result with the original using `==`, leaving the `metadata`
fields (`ModelOutput.metadata`, `ChatMessageAssistant.metadata`,
`ModelFallback.metadata`) out of the comparison and treating an empty
`completion` on the original as the first choice's message text, which is
what `set_completion` gives on reading (so merged `pause_turn` outputs stay
cached). It writes the same bytes only if they are equal. If serialization or reading fails, or the result is
not equal, the output is not cached: `generate()` returns it normally, and a
`warn_once` per model says caching was skipped and why. Lookup is unchanged.

The check makes the guarantee hold whatever an output holds, without listing
the types JSON cannot carry. Among the outputs it refuses:

- Tool-call arguments (`dict[str, Any]`) holding values JSON returns in
  another form: a `date` comes back as a string, a set as a list, `bytes` as
  text, a dataclass or Pydantic model as a plain dictionary, and an integer
  key merged with the string key of the same digits (`{1: "a", "1": "b"}`
  becomes `{"1": "b"}`). Model text reaches several of these through the YAML
  fallback of tool-call argument parsing (`parse_tool_call` in
  `src/inspect_ai/model/_call_tools.py`).
- Strings holding a surrogate code point (U+D800–U+DFFF). As a value it
  fails UTF-8 encoding; as a dictionary key Pydantic's JSON mode replaces it,
  which can merge two keys.
- Non-finite floats. Infinite floats round-trip and are cached. An output
  holding NaN may fail the equality check and then is not cached; this is
  accepted.
- `metadata` that does not serialize, such as a non-JSON object from a
  third-party provider; today it is cached only if it pickles.

`metadata` values of non-JSON types that do serialize come back in their
JSON form (a `datetime` as a string), which is what the eval log records for
the same output; leaving `metadata` out of the comparison keeps such outputs
cached. Likewise a hit returns an empty `completion` filled from the message
text, as a read of the eval log does. So a cache hit never returns changed
content, tool calls or arguments, and these two normalizations are the only
differences a hit can show. Of the 6,916 real outputs measured in Current behaviour, none was
refused. The guarantee is `==` equality, not type identity: a value that
compares equal to its JSON form, such as an `IntEnum` or a `defaultdict` in
tool-call arguments, is cached and comes back as an `int` or a `dict`; no
built-in provider produces such arguments.

Cost: one extra parse, validation and comparison per store, about 25 µs on
those outputs (the whole check took 39 µs per entry against 15 µs for
serialization alone), and refused outputs reach the provider on every call,
where pickle caches them today.

### Concurrency and failure

`cache_store` writes the entry with `atomic_write_bytes(path, data,
fsync=False)` (`src/inspect_ai/_util/atomic_write.py`), the writer eval logs
use: it writes a temporary file in the entry's directory and renames it into
place. A reader therefore sees the previous whole entry, the new whole entry
or none, and when two processes store the same key the entry is one
writer's whole file. A write that fails leaves the existing entry and no
temporary file, and the output is not cached (traced); on Windows that
includes a rename refused while another process has the entry open. The
helper's permission handling, including that its temporary copy can be
more readable than a restricted entry while it is written or after a
killed store, is its accepted behaviour, as for eval logs. There is no
`fsync`: after a system crash an entry may be empty or partial, which
readers treat as invalid. There is no new locking.

List and prune never match temporary files, so they neither list nor delete
a write in progress. `cache_size` counts and `cache_clear` removes
temporary files left by a process killed between creating and renaming
one.

No cache failure raises into `generate()`. `cache_fetch` and `cache_store`
resolve the entry path and create directories inside their exception
handler, so a failure there is traced and is a miss or a skipped store,
like a failure while reading or writing; the outside-the-cache refusal keeps
its warning. The CLI commands keep their current error behaviour.

### Format versions

A reader treats any `version` other than 1 as an invalid header; a later
format change bumps `version`.

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
- **A type-by-type rule for which outputs may be cached** (JSON-native
  values only outside `metadata`, plus a surrogate scan). It has to name
  every type JSON changes and inspect values before a model dump erases
  their types (a dataclass argument dumps to a plain dictionary), and each
  missed type is a hit that returns changed data. Rejected for the
  store-time round-trip check, which compares what lookup would return with
  the original (decision: Ransom, 2026-11-20).
- **A body hash in the header, checked on lookup, instead of atomic
  writes.** It would turn a mixed or partial file into a miss, but readers
  would still see such files, every lookup would hash the body, and list and
  prune, which read only the header, could not use it. A temporary file
  renamed into place prevents those files from existing (decision: Ransom,
  2026-11-23).
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

The corpus is mostly English. Text in other scripts costs more than pickle:
for a synthetic output of about 3,000 Chinese characters, appearing in both
the message content and a tool argument, the UTF-8 body was 18.7 KB against
pickle's 9.9 KB (pickle stores the repeated string once) and 36.9 KB with
`\u` escapes, which is why the format writes UTF-8.

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
- **Outputs.** A cache hit returns the stored output, with non-JSON
  `metadata` values in their JSON form and an empty `completion` filled from
  the message text (see Store). Outputs that do not read
  back equal (for example YAML-parsed dates, non-string keys or objects in
  tool-call arguments, surrogate code points, some NaN values) and outputs
  that
  do not serialize are no longer cached and produce a warning; they call the
  provider every time.
- **Eval logs, schemas and viewer types.** Unchanged. `ModelEvent.cache`
  values and the cache key are unchanged.

## Security

Untrusted input reaching the new code: the bytes of any file under the cache
root, file names in it, and symlinks. Handling:

- The writer is `atomic_write_bytes`, run after today's inside-the-cache
  check. A symlink inside the cache is written through, as `open(path,
  "wb")` does today; containment is unchanged.
- Lookup reads one path derived from the key; list and prune open only files
  whose names match an entry pattern, after today's inside-the-cache check,
  which resolves symlinks.
- Content is parsed only by the stdlib `json` module and then validated
  against fixed Pydantic models. Validation constructs no object the input
  chooses and opens no path the input names; it may load the system MIME
  database through `mimetypes` (Current behaviour). No path in the cache
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
  and infinite floats both in typed fields (`-inf` logprob, `inf` total
  cost) and nested in tool-call arguments (`{"a": inf, "b": {"c": -inf}}`,
  values the argument parser produces from JSON numeric overflow). The
  argument cases matter because a Pydantic JSON-mode dump writes untyped
  infinities as `null`, which the equality check would refuse.
- **Non-ASCII text.** Store then fetch of an output with non-Latin text and
  an emoji in content and tool arguments returns an equal output, and the
  body holds the text as UTF-8.
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
- **Lossy outputs are not cached.** One parametrized test: each case is
  returned by `generate()`, writes no entry, reaches the provider again on a
  second identical call, and produces one warning. Cases: a surrogate code
  point in a tool-call argument key; tool-call arguments that the YAML
  fallback of `parse_tool_call` (with a one-parameter tool) decodes from
  model text into a `date` (the text `2026-01-01`) and into colliding keys
  (the text `1: first` and `"1": second` on two lines, giving `{1: "first",
  "1": "second"}`); a dataclass instance and a Pydantic model instance as
  tool-call argument values; and a non-JSON object in `metadata` (which
  fails serialization).
- **NaN refused.** Called directly through `cache_store`, because
  `Model._generate` replaces `output.time` with the measured duration before
  storing: an output whose `time` is `float("nan")` is not stored (no entry,
  one warning).
- **Normalized outputs are still cached.** The counterpart cases of the
  lossy-outputs test, each cached and returned on the second call without
  reaching the provider: an output with a `datetime` in `metadata`, whose
  hit returns it as its ISO string; and an output with an empty
  `completion` and non-empty message text (the shape of a merged Anthropic
  `pause_turn` output), whose hit returns `completion` equal to that text.
- **Concurrent writers and a reader.** Two processes repeatedly store
  different large outputs (megabytes of text) under one key while a third
  repeatedly fetches it. After the first store completes, every fetch is a
  hit equal to one of the two outputs, and no temporary file remains at the
  end. Written in place, a fetch sees a partly written file in a large share
  of reads (a spike of this shape found 238 of 585 reads partial in place,
  none with a temporary file and rename), so the test fails without atomic
  writes.
- **Failed write.** A store whose write raises is skipped and `generate()`
  returns its output.
- **Temporary files are not entries.** A leftover temporary file
  holding a valid expired entry is not listed or pruned, is counted by
  `cache_size`, and is removed by `cache_clear`.
- **Path setup failures are misses.** With a regular file at
  `INSPECT_CACHE_DIR/generate`, `generate(cache=True)` returns the output on
  two identical calls, calling the provider both times, and raises nothing.
- **Containment tests keep their purpose.** The existing tests that check
  lookup, list, prune and clear stay inside the cache directory
  (`test_cache_store_and_fetch_stay_in_cache_dir`,
  `test_cache_refuses_symlinks_out_of_cache_dir`,
  `test_cache_clear_list_and_prune_stay_in_cache_dir`,
  `test_cache_layout_unchanged_for_normal_model_names`,
  `test_cache_refusals_create_nothing`,
  `test_cache_prune_skips_unresolvable_paths`) plant entries the new reader
  would otherwise act on: current-format entries with a valid expired
  header and legacy pickle entries, each under a key-derived name
  (`<key>.jsonl`, or 32 hex characters for a legacy entry). A refusal
  assertion must not pass merely because the planted file is a bare-key
  pickle that lookup no longer reads, or has a name such as `expired` or
  `old` that list and prune now ignore.
- **Updated tests.** Tests that read or write pickles directly
  (`test_cache_entry_from_before_input_context_tokens`, the pickle writes in
  the trace and layout tests) move to the new format or become legacy-entry
  fixtures; `test_cache_layout_unchanged_for_normal_model_names` asserts the
  `.jsonl` name. `tests/test_helpers/output_cache.py` builds the entry path
  with the new name.

## Implementation plan

1. **New format and reader** (`src/inspect_ai/model/_cache.py`,
   `tests/model/test_cache.py`, `tests/test_helpers/output_cache.py`).
   Header model, writer and reader; `cache_store` and `cache_fetch` on
   `<key>.jsonl`; `cache_list_expired` and `cache_prune` on entry-name
   patterns with header-only reads and legacy detection; remove the `pickle`
   import; the store-time round-trip check and the warning for outputs not
   cached; writing with `atomic_write_bytes`; path setup inside the lookup
   and store handlers.
   Tests: never-deserialized, tripwire, round trip, non-ASCII text, invalid
   headers, invalid bodies, expiry, legacy entries, lossy outputs, NaN
   refused, normalized outputs, concurrent writers and a reader, failed
   write, temporary files, path setup failures, the containment tests, and
   the updated existing tests.
2. **CLI and docs** (`src/inspect_ai/_cli/cache.py`, `docs/caching.qmd`).
   Pruneable table title and help text; a caching docs section on the entry
   format, that entries from earlier versions are not reused, and that
   `inspect cache prune` removes them. This can ship in the same PR as
   step 1; its change note says existing cache entries are not reused after
   upgrading.

## Open questions

None.

## Not this design

- **Removing orphaned temporary files** left by a process killed during a
  store, by prune or by age. `cache_clear` removes them.
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
