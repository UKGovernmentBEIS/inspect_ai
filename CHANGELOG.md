# Changelog

## v0.3.14 (04 June 2024)

- Stream samples to the evaluation log as they are completed (subject to the new `--log-buffer` option). Always write completed samples in the case of an error or cancelled task.
- New `"cancelled"` status in eval log for tasks interrupted with SIGINT (e.g. Ctrl-C). Logs are now written for cancellations (previously they were not).
- Default `--max-samples` (maximum concurrent samples) to `--max-connections`, which will result in samples being more frequently completed and written to the log file.
- For `eval_retry()`, copy previously completed samples in the log file being retried so that work is not unnecessarily repeated.
- New `inspect eval-retry` command to retry a log file from a task that ended in error or cancellation. 
- New `retryable_eval_logs()` function and `--retryable` option for `inspect list logs` to query for tasks not yet completed within a log directory.
- Add `shuffled` property to datasets to determine if they were shuffled.
- Remove unused `extensions` argument from `list_eval_logs()`

## v0.3.13 (31 May 2024)

- Bugfix: Inspect view was not reliably updating when new evaluation logs were written.

## v0.3.12 (31 May 2024)

- Bugfix: `results` was not defined when no scorer was provided resulting in an error being thrown. Fixed by setting `results = EvalResults()` when no scorer is provided.
- Bugfix: The viewer was not properly handling samples without scores.

## v0.3.11 (30 May 2024)

- Update to non-beta version of Anthropic tool use (remove legacy xml tools implementation).

## v0.3.10 (29 May 2024)

- **BREAKING:** The `pattern` scorer has been modified to match against any (or all) regex match groups. This replaces the previous behaviour when there was more than one group, which would only match the second group.
- Improved performance for Inspect View on very large datasets (virtualized sample list).
- ToolChoice `any` option to indicate the model should use at least one tool (supported by Anthropic and Mistral, mapped to `auto` for OpenAI).
- Tool calls can now return a simple scalar or `list[ContentText | ContentImage]`
- Support for updated Anthropic tools beta (tool_choice and image tool results)
- Report tool_error back to model if it provides invalid JSON for tool calls arguments (formerly this halted the entire eval with an error).
- New `max_samples` option to control how many samples are run in parallel (still defaults to running all samples in parallel).
- Add `boolq.py` benchmark.
- Add `piqa.py` benchmark.
- View: Improved markdown rendering (properly escape reference links)
- Improved typing for example_dataset function.
- Setuptools entry point for loading custom model extensions.
- Break optional `tuple` return out of `ToolResult` type.
- Bugfix: always read original sample message(s) for `TaskState.input_text`.
- Bugfix: remove write counter from log (could have resulted in incomplete/invalid logs propagating to the viewer)
- Bugfix: handle task names that include spaces in log viewer.

## v0.3.9 (14 May 2024)

- Add `ollama` local model provider.
- Add `multi_scorer()` and `majority_vote()` functions for combining multiple scorers into a single score.
- Add support for multiple model graders in `model_graded_qa()`.
- Raise `TypeError` for solvers and scorers not declared as `async`.
- Fallback to standard parase if `NaN` or `Inf` is encountered while reading log file header.
- Remove deprecated support for matching partial model names (e.g. "gpt" or "claude").

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
