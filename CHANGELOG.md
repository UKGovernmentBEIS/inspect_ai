# Changelog

## v0.3.8 (07 May 2024)

- Exclude null config values from listings in log viewer.

## v0.3.7 (07 May 2024)

- Add support for logprobs to HF provider, and create uniform API for other providers that support logprobs (Together and OpenAI).
- Provide an option to merge asssistant messages and use it for Anthropoic models (as they don't allow consecutive assistant messages).
- Supporting infrastructure in Inspect CLI for VS Code extension (additional list and info commands).

## v0.3.6 (06 May 2024)

- Show first log file immediately (don't wait for fetching metadata for other logs)
- Add `--version` CLI arg and `inspect info version` command for interogating version and runtime source path.
- Fix: exclude `null` config values in output from `inspect info log-file`

## v0.3.5 (04 May 2024)

- Fix issue with logs from S3 buckets in inspect view.
- Add `sort()` method to `Dataset` (defaults to sorting by sample input length).
- Improve tokenization for HF provider (left padding, attention mask, and allow for custom chat template)
- Improve batching for HF provider (generate as soon as queue fills, thread safety for future.set_result).
- Various improvements to documentation.

## v0.3.4 (01 May 2024)

- `write_eval_log()` now ignores unserializable objects in metadata fields.
- `read_eval_log()` now takes a `str` or `FileInfo` (for compatibility w/ list returned from `list_eval_logs()`).
- Registry name looks are now case sensitive (fixes issue w/ loading tasks w/ mixed case names).
- Resiliancy to Python syntax errors that occur when enumerating tasks in a directory.
- Do not throw error if unable to parse or load `.ipynb` file due to lack of dependencies (e.g. `nbformat`).
- Various additions to log viewer display (log file name, dataset/scorer in listing, filter by complex score types).
- Improvements to markdown rendering in log viewer (don't render intraword underscores, escape html tags).

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
