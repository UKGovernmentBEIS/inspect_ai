# Changelog

## v0.3.3 (28 April 2024)

- `inspect view` command for viewing eval log files.
- `Score` now has an optional `answer` field, which denotes the answer text extracted from model output.
- Accuracy metrics now take an optional `ValueToFloat` function for customizing how textual values mapped to float.
- Made `model_graded_qa` more flexible with separate `instruction` template and `grade_pattern`, as well providing `partial_credit` as an option.
- Modify the default templates for `chain_of_thought()` and `self_critique()` to instruct the model to reply with `ANSWER: $ANSWER` at the end on its own line. 
- Improved numeric extraction for `match(numeric=True)` (better currency and decimal handling).
- Improve `answer()` patterns so that they detect letter and word answers both within and at the end of model output.
- `Plan` now has an optional `cleanup` function which can be used to free per-sample resources (e.g. Docker containers) even in the case of an evaluation error.
- Add `Dataset.filter` method for filtering samples using a predicate.
- `Dataset` slices (e.g. `dataset[0:100]`) now return a `Dataset` rather than `list[Sample]`.
- Relative path to `INSPECT_LOG_DIR` in `.env` file is now correctly resolved for execution within subdirectories.
- `inspect list tasks` and `list_tasks()` now only parse source files (rather than loading them), ensuring that it is fast even for task files that have non-trivial global initialisation.
- `inspect list logs` and `list_eval_logs()` now enumerate log files recursively by default, and only enumerate json files that match log file naming conventions.
- Provide `header_only` option for `read_eval_log()` and `inspect info log-file` for bypassing the potentially expensive reading of samples.
- Provide `filter` option for `list_eval_logs()` to filter based on log file header info (i.e. anything but samples).
- Added `__main__.py` entry point for invocation via `python3 -m inspect_ai`.
- Removed prompt and callable from model `ToolDef` (renamed to `ToolInfo`).
- Fix issue with accesses of `completion` property on `ModelOutput` with no choices.

## v0.3.2 (21 April 2024)

- Initial release.
