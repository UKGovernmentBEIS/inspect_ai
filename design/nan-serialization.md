# NaN score serialization

NaN is the unscored sentinel for score values: a scalar NaN marks the whole
sample unscored, and a NaN dict leaf or list element marks that key/position
unscored for that sample. Reducers and `results.py` exclude NaN from metrics
and count it toward `unscored_samples`.

## The problem

JSON has no NaN. Pydantic's default (`ser_json_inf_nan='null'`) serializes
non-finite floats as `null`, which destroys the sentinel:

- **dict leaf** — `null` reloads as `None` (the `Mapping` variant of `Value`
  admits it), slips past NaN filtering, and `value_to_float()` coerces it to
  `0.0`. Metrics shift toward zero and scored/unscored counts are wrong, so
  an `eval_set` retry that reloads completed samples reports different
  metrics than a first-try success.
- **list element** — the `Sequence` variant of `Value` rejects `None`, so the
  log fails revalidation entirely: the run errors and the log is unreadable
  (#4491).
- `null` is also ambiguous on read: a dict-leaf `null` could be a legitimate
  `None` the scorer returned, so no read-side coercion can recover intent.

## The fix: `ser_json_inf_nan="constants"` on every wire root

Non-finite floats serialize as the JSON constants `NaN` / `Infinity` /
`-Infinity` (valid in Python's `json`, pydantic, and JSON5 — not in strict
JSON; see reader tolerance below).

Pydantic reads `ser_json_inf_nan` from the **dump-root model only** — config
on a nested model is ignored, so configuring `Score` alone does nothing when
it is serialized inside `EvalSample`. Every model that is itself a
serialization root for score-bearing data must therefore repeat the config:

| Wire root | Serialized at |
| --- | --- |
| `EvalSample` | `samples/*.json` in `.eval` zips |
| `EvalSampleSummary` | `summaries.json` and journal summaries |
| `EvalSampleReductions` | `reductions.json` |
| `EvalLog` | `header.json`; entire `.json`-format logs |
| `ScoreEvent`, `ScoreEditEvent` | realtime buffer db event rows |
| `Samples`, `SampleData`, `Manifest` | buffer filestore sync, view server responses |
| `Score`, `ScoreEdit` | direct dumps (defensive; unit-level consistency) |

`test_non_finite_serialization_configured_on_all_wire_roots` guards this
enumeration. FastAPI response serialization wraps response models in its own
type adapter (a dump root without the config), so `/pending-samples` builds
its `InspectJsonResponse` explicitly rather than returning the model.

## Reader tolerance

`NaN` constants have appeared in logs since Aug 2025 — an accidental side
effect of the unicode-surrogate fix (#2316), which preserved *scalar* NaN
(only) through `to_json_safe`. Readers were already hardened as a result:

- Python `json.loads` and pydantic (jiter) parse the constants natively.
- ijson does not; both streaming call sites fall back to `json.load` via
  `is_ijson_nan_inf_error` (added in #3123 after the tokens appeared).
- The TS viewer's `asyncJsonParse` falls back to JSON5 when strict
  `JSON.parse` fails.
- View server responses use `InspectJsonResponse` (`allow_nan=True`);
  starlette's default `JSONResponse` would raise.

External strict-JSON consumers (`jq`, raw `JSON.parse`, DuckDB) cannot parse
logs containing non-finite values. Logs with no non-finite floats are
byte-identical to before.

## Old logs

Logs written before this fix already contain `null` where NaN was meant:
dict leaves reload as `None` (and miscount as `0.0`), and list elements fail
validation. That corruption happened at write time and is not recoverable
with certainty (see ambiguity above). Any backward-compat coercion should be
scoped to deserialization and, ideally, to list/scalar positions where a
`null` is provably a serialization artifact (`None` is unconstructible
there).
