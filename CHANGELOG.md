# Changelog

## Unreleased

- [Store](https://inspect.ai-safety-institute.org.uk/agents-api.html#sharing-state) for manipulating arbitrary sample state from within solvers and tools.
- [Transcript](https://inspect.ai-safety-institute.org.uk/agents-api.html#transcripts) for detailed sample level tracking of model and tool calls, state changes, logging, etc.
- [Subtasks](https://inspect.ai-safety-institute.org.uk/agents-api.html#sec-subtasks) for delegating work to helper models, sub-agents, etc.
- Integration with Anthropic [prompt caching](https://inspect.ai-safety-institute.org.uk/caching.html#sec-provider-caching).
- Specify `init` value in default Docker compose file so that exit signals are handled correctly (substantially improves container shutdown performance).
- Add `function` field to `ChatMessageTool` to indicate the name of the function called.
- Added [RACE](https://github.com/UKGovernmentBEIS/inspect_ai/tree/main/benchmarks/race-h/) benchmark.

## v0.3.24 (18 August 2024)

- Support for tool calling for Llama 3.1 models on Bedrock.
- Report JSON schema validation errors to model in tool response.
- Support for `strict` mode in OpenAI tool calls (update to v1.40.0 of `openai` package required).

## v0.3.23 (16 August 2024)

- Support for tool calling for Llama 3.1 models on Azure AI and CloudFlare.
- Incrase default `max_tokens` from 1024 to 2048.
- Record individual sample reductions along with results for multi-epoch evals.
- Change default to not log base64 encoded versions of images, as this often resulted in extremely large log files (use `--log-images` to opt back in).
- Update to new Mistral API (v1.0.1 of `mistralai` is now required).
- Support for Llama 3.1 models on Amazon Bedrock
- Eliminate Bedrock dependency on anthropic package (unless using an Anthropic model).
- Improved resolution of AWS region for Bedrock (respecting already defined AWS_REGION and AWS_DEFAULT_REGION)
- Fix bug in match scorer whereby numeric values with periods aren't correctly recognized.
- Added [HumanEval](https://github.com/UKGovernmentBEIS/inspect_ai/tree/main/benchmarks/humaneval), [WinoGrande](https://github.com/UKGovernmentBEIS/inspect_ai/tree/main/benchmarks/winogrande) and [Drop](https://github.com/UKGovernmentBEIS/inspect_ai/tree/main/benchmarks/drop) benchmarks.

## v0.3.22 (07 August 2024)

- Fix issue affecting results of `pass_at_{k}` score reducer.

## v0.3.21 (07 August 2024)

- Add `pass_at_{k}` score reducer to compute the probability of at least 1 correct sample given `k` epochs.
- Improved metrics `value_to_float` string conversion (handle numbers, "true", "false", etc.)
- Log viewer: Ctrl/Cmd+F to find text when running in VS Code.
- Set Claude default `max_tokens` to 4096
- Combine user and assistant messages for Vertex models.
- Warn when using the `name` parameter with task created from `@task` decorated function.
- Make sample `metadata` available in prompt, grading, and self-criqique templates.
- Retry on several additional OpenAI errors (APIConnectionError | APITimeoutError | InternalServerError)
- Fix a regression which would cause the 'answer' to be improperly recorded when scoring a sample.

## v0.3.20 (03 August 2024)

- `Epochs` data type for specifying epochs and reducers together (deprecated `epochs_reducer` argument). 
- Enable customisation of model generation cache dir via `INSPECT_CACHE_DIR` environment variable.
- Use doc comment description rather than `prompt` attribute of `@tool` for descriptions.
- Include examples section from doc comments in tool descriptions.
- Add `tool_with()` function for adapting tools to have varying names and parameter descriptions.
- Improve recording of `@task` arguments so that dynamically created tasks can be retried.
- Only print `eval-retry` message to terminal for filesystem based tasks.
- Enhance Python logger messages to capture more context from the log record.
- Fix an issue that could result in duplicate display of scorers in log view when using multiple epoch reducers.

## v0.3.19 (02 August 2024)

- [vLLM](https://inspect.ai-safety-institute.org.uk/models.html#sec-vllm) model provider.
- [Groq](https://groq.com/) model provider.
- [Google Vertex](https://inspect.ai-safety-institute.org.uk/models.html#google-vertex) model provider.
- [Reduce scores](https://inspect.ai-safety-institute.org.uk/scorers.html##sec-reducing-epoch) in multi-epoch tasks before computing metrics (defaults to averaging sample values).
- Replace the use of the `bootstrap_std` metric with `stderr` for built in scorers (see [rationale](https://inspect.ai-safety-institute.org.uk/scorers.html#stderr-note) for details).
- Option to write Python logger entries to an [external file](https://inspect.ai-safety-institute.org.uk/log-viewer.html#sec-external-file).
- Rename `ToolEnvironment` to `SandboxEnvironment` and `tool_environment()` to `sandbox()` (moving the renamed types from `inspect_ai.tool` to `inspect_ai.util`). Existing symbols will continue to work but will print deprecation errors.
- Moved the `bash()`, `python()`, and `web_search()` functions from `inspect_ai.solver` to `inspect_ai.tool`.  Existing symbols will continue to work but will print deprecation errors.
- Enable parallel execution of tasks that share a working directory.
- Add `chdir` option to `@task` to opt-out of changing the working directory during task execution.
- Enable overriding of default safety settings for Google models.
- Use Python type annotations as the first source of type info for tool functions (fallback to docstrings only if necessary)
- Support for richer types (list, TypeDict, dataclass, Pydantic, etc.) in tool calling.
- Change `ToolInfo` parameters to be directly expressed in JSON Schema (making it much easier to pass them to model provider libraries).
- Validate tool call inputs using JSON Schema and report errors to the model.
- Gracefully handle tool calls that include only a single value (rather than a named dict of parameters).
- Support `tool_choice="any"` for OpenAI models (requires >= 1.24.0 of openai package).
- Make multiple tool calls in parallel. Parallel tool calls occur by default for OpenAI, Anthropic, Mistral, and Groq. You can disable this behavior for OpenAI and Groq with `--parallel-tool-calls false`.
- Invoke rate limit retry for OpenAI APITimeoutError (which they have recently begun returning a lot of more of as a result of httpx.ConnectTimeout, which is only 5 seconds by default.).
- Add `cwd` argument to `SandboxEnvironment.exec()`
- Use `tee` rather than `docker cp` for Docker sandbox environment implementation of `write_file()`.
- Handle duplicate tool call ids in Inspect View.
- Handle sorting sample ids of different types in Inspect View.
- Correctly resolve default model based on CLI --model argument.
- Fix issue with propagating API keys to Azure OpenAI provider.
- Add `azure` model arg for OpenAI provider to force binding (or not binding) to the Azure OpenAI back-end.
- Support for Llama 3 models with the Azure AI provider.
- Add `setup` field to `Sample` for providing a per-sample setup script.
- Score multiple choice questions without parsed answers as incorrect (rather than being an error). Llama 3 and 3.1 models especially often fail to yield an answer.
- Read JSON encoded `metadata` field from samples.
- Show task/display progress immediately (rather than waiting for connections to fill).
- Reduce foreground task contention for Inspect View history loading.
- Ability to host standalone version of Inspect View to view single log files.
- Throw `TimeoutError` if a call to `subprocess()` or `sandbox().exec()` times out (formerly a textual error was returned along with a non-zero exit code).
- Validate name passed to `example_dataset()` (and print available example dataset names).
- Resolve relative image paths within Dataset samples against the directory containing the dataset.
- Preserve `tool_error` text for Anthropic tool call responses.
- Fix issue with rate limit reporting being per task not per eval.
- Set maximum rate limit backoff time to 30 minutes
- Retry with exponential backoff for web_search Google provider.



## v0.3.18 (14 July 2024)

- [Multiple Scorers](https://inspect.ai-safety-institute.org.uk/scorers.html#sec-multiple-scorers) are now supported for evaluation tasks.
- [Multiple Models](https://inspect.ai-safety-institute.org.uk/parallelism.html#sec-multiple-models) can now be evaluated in parallel by passing a list of models to `eval()`.
- Add `api_key` to `get_model()` for explicitly specifying an API key for a model.
- Improved handling of very large (> 100MB) log files in Inspect View.
- Use `network_mode: none` for disabling networking by default in Docker tool environments.
- Shorten the default shutdown grace period for Docker container cleanup to 1 second.
- Allow sandbox environent providers to specify a default `max_samples` (set to 25 for the Docker provider).
- Prevent concurrent calls to `eval_async()` (unsafe because of need to change directories for tasks). Parallel task evaluation will instead be implemented as a top-level feature of `eval()` and `eval_async()`.
- Match scorers now return answers consistently even when there is no match.
- Relocate tool related types into a new top-level `inspect_ai.tool` module (previous imports still work fow now, but result in a runtime deprecation warning).
- Decouple tools entirely from solvers and task state (previously they had ways to interact with metadata, removing this coupling will enable tool use in lower level interactions with models). Accordingly, the `call_tools()` function now operates directly on messages rather than task state.
- Support token usage for Google models (Inspect now requires `google-generativeai` v0.5.3).

## v0.3.17 (25 June 2024)

- Optional increased control over the tool use loop via the `call_tools()` function and new `tool_calls` parameter for `generate()`.
- New `per_epoch` option for `CachePolicy` to allow caching to ignore epochs.
- Correctly handle `choices` and `files` when converting `Sample` images to base64. 

## v0.3.16 (24 June 2024)

-   Various fixes for the use of Docker tool environments on Windows.
-   Ability to disable cleanup of tool environments via `--no-toolenv-cleanup`.
-   New `inspect toolenv cleanup` command for manually cleaning up tool environments.
-   `ToolError` exception type for explicitly raising tool errors to the model. Formerly, any exception would be surfaced as a tool error to the model. Now, the `ToolError` exception is required for reporting to the model (otherwise other exception types go through the call stack and result in an eval error).
-   Resolve `INSPECT_LOG_DIR` in `.env` file relative to `.env` file parent directory.
-   Use `-` for delimiting `--limit` ranges rather than `,`.
-   Use HF model device for generate (compatibility with multi-GPU).

## v0.3.15 (15 June 2024)

-   [Sandbox Environments](https://inspect.ai-safety-institute.org.uk/agents.html#sec-sandbox-environments) for executing tool code in a sandbox.
-   [Caching](https://inspect.ai-safety-institute.org.uk/caching.html) to reduce the number of model API calls made.
-   The `multiple_choice()` solver now has support for questions with multiple correct answers.
-   More fine grained handling of Claude `BadRequestError` (400) errors (which were formerly all treated as content moderation errors).
-   Filter out empty TextBlockParam when playing messages back to Claude.
-   Automatically combine Claude user messages that include tool content.
-   Revert to "auto" rather than "none" after forced tool call.
-   Provide `TaskState.tools` getter/setter (where the setter automatically syncs the system messages to the specified set of tools).
-   The `use_tools()` function now uses the `TaskState.tools` setter, so replaces the current set of tools entirely rather than appending to it.
-   Set `state.completed = False` when `max_messages` is reached.
-   Allow tools to be declared with no parameters.
-   Allow for null `bytes` field in `Logprobs` and `TopLogprobs`.
-   Support all Llama series models on Bedrock.
-   Added `truthfulqa` benchmark.
-   Added `intercode-ctf` example.

## v0.3.14 (04 June 2024)

-   Stream samples to the evaluation log as they are completed (subject to the new `--log-buffer` option). Always write completed samples in the case of an error or cancelled task.
-   New `"cancelled"` status in eval log for tasks interrupted with SIGINT (e.g. Ctrl-C). Logs are now written for cancellations (previously they were not).
-   Default `--max-samples` (maximum concurrent samples) to `--max-connections`, which will result in samples being more frequently completed and written to the log file.
-   For `eval_retry()`, copy previously completed samples in the log file being retried so that work is not unnecessarily repeated.
-   New `inspect eval-retry` command to retry a log file from a task that ended in error or cancellation.
-   New `retryable_eval_logs()` function and `--retryable` option for `inspect list logs` to query for tasks not yet completed within a log directory.
-   Add `shuffled` property to datasets to determine if they were shuffled.
-   Remove unused `extensions` argument from `list_eval_logs()`.

## v0.3.13 (31 May 2024)

-   Bugfix: Inspect view was not reliably updating when new evaluation logs were written.

## v0.3.12 (31 May 2024)

-   Bugfix: `results` was not defined when no scorer was provided resulting in an error being thrown. Fixed by setting `results = EvalResults()` when no scorer is provided.
-   Bugfix: The viewer was not properly handling samples without scores.

## v0.3.11 (30 May 2024)

-   Update to non-beta version of Anthropic tool use (remove legacy xml tools implementation).

## v0.3.10 (29 May 2024)

-   **BREAKING:** The `pattern` scorer has been modified to match against any (or all) regex match groups. This replaces the previous behaviour when there was more than one group, which would only match the second group.
-   Improved performance for Inspect View on very large datasets (virtualized sample list).
-   ToolChoice `any` option to indicate the model should use at least one tool (supported by Anthropic and Mistral, mapped to `auto` for OpenAI).
-   Tool calls can now return a simple scalar or `list[ContentText | ContentImage]`.
-   Support for updated Anthropic tools beta (tool_choice and image tool results).
-   Report tool_error back to model if it provides invalid JSON for tool calls arguments (formerly this halted the entire eval with an error).
-   New `max_samples` option to control how many samples are run in parallel (still defaults to running all samples in parallel).
-   Add `boolq.py` benchmark.
-   Add `piqa.py` benchmark.
-   View: Improved markdown rendering (properly escape reference links).
-   Improved typing for example_dataset function.
-   Setuptools entry point for loading custom model extensions.
-   Break optional `tuple` return out of `ToolResult` type.
-   Bugfix: always read original sample message(s) for `TaskState.input_text`.
-   Bugfix: remove write counter from log (could have resulted in incomplete/invalid logs propagating to the viewer).
-   Bugfix: handle task names that include spaces in log viewer.

## v0.3.9 (14 May 2024)

-   Add `ollama` local model provider.
-   Add `multi_scorer()` and `majority_vote()` functions for combining multiple scorers into a single score.
-   Add support for multiple model graders in `model_graded_qa()`.
-   Raise `TypeError` for solvers and scorers not declared as `async`.
-   Fallback to standard parase if `NaN` or `Inf` is encountered while reading log file header.
-   Remove deprecated support for matching partial model names (e.g. "gpt" or "claude").

## v0.3.8 (07 May 2024)

-   Exclude null config values from listings in log viewer.

## v0.3.7 (07 May 2024)

-   Add support for logprobs to HF provider, and create uniform API for other providers that support logprobs (Together and OpenAI).
-   Provide an option to merge assistant messages and use it for Anthropoic models (as they don't allow consecutive assistant messages).
-   Supporting infrastructure in Inspect CLI for VS Code extension (additional list and info commands).

## v0.3.6 (06 May 2024)

-   Show first log file immediately (don't wait for fetching metadata for other logs)
-   Add `--version` CLI arg and `inspect info version` command for interrogating version and runtime source path.
-   Fix: exclude `null` config values in output from `inspect info log-file`

## v0.3.5 (04 May 2024)

-   Fix issue with logs from S3 buckets in inspect view.
-   Add `sort()` method to `Dataset` (defaults to sorting by sample input length).
-   Improve tokenization for HF provider (left padding, attention mask, and allow for custom chat template)
-   Improve batching for HF provider (generate as soon as queue fills, thread safety for future.set_result).
-   Various improvements to documentation.

## v0.3.4 (01 May 2024)

-   `write_eval_log()` now ignores unserializable objects in metadata fields.
-   `read_eval_log()` now takes a `str` or `FileInfo` (for compatibility w/ list returned from `list_eval_logs()`).
-   Registry name looks are now case sensitive (fixes issue w/ loading tasks w/ mixed case names).
-   Resiliancy to Python syntax errors that occur when enumerating tasks in a directory.
-   Do not throw error if unable to parse or load `.ipynb` file due to lack of dependencies (e.g. `nbformat`).
-   Various additions to log viewer display (log file name, dataset/scorer in listing, filter by complex score types).
-   Improvements to markdown rendering in log viewer (don't render intraword underscores, escape html tags).

## v0.3.3 (28 April 2024)

-   `inspect view` command for viewing eval log files.
-   `Score` now has an optional `answer` field, which denotes the answer text extracted from model output.
-   Accuracy metrics now take an optional `ValueToFloat` function for customising how textual values mapped to float.
-   Made `model_graded_qa` more flexible with separate `instruction` template and `grade_pattern`, as well providing `partial_credit` as an option.
-   Modify the default templates for `chain_of_thought()` and `self_critique()` to instruct the model to reply with `ANSWER: $ANSWER` at the end on its own line.
-   Improved numeric extraction for `match(numeric=True)` (better currency and decimal handling).
-   Improve `answer()` patterns so that they detect letter and word answers both within and at the end of model output.
-   `Plan` now has an optional `cleanup` function which can be used to free per-sample resources (e.g. Docker containers) even in the case of an evaluation error.
-   Add `Dataset.filter` method for filtering samples using a predicate.
-   `Dataset` slices (e.g. `dataset[0:100]`) now return a `Dataset` rather than `list[Sample]`.
-   Relative path to `INSPECT_LOG_DIR` in `.env` file is now correctly resolved for execution within subdirectories.
-   `inspect list tasks` and `list_tasks()` now only parse source files (rather than loading them), ensuring that it is fast even for task files that have non-trivial global initialisation.
-   `inspect list logs` and `list_eval_logs()` now enumerate log files recursively by default, and only enumerate json files that match log file naming conventions.
-   Provide `header_only` option for `read_eval_log()` and `inspect info log-file` for bypassing the potentially expensive reading of samples.
-   Provide `filter` option for `list_eval_logs()` to filter based on log file header info (i.e. anything but samples).
-   Added `__main__.py` entry point for invocation via `python3 -m inspect_ai`.
-   Removed prompt and callable from model `ToolDef` (renamed to `ToolInfo`).
-   Fix issue with accesses of `completion` property on `ModelOutput` with no choices.

## v0.3.2 (21 April 2024)

-   Initial release.
