# Changelog

## v0.3.55 (29 December 2024)

- Bedrock: redact authentication model args from eval logs.
- OpenAI: warn when `temperature` is used with o1 models (as it is not supported).
- Bugfix: spread args for cache trace logging.

## v0.3.54 (26 December 2024)

- [Tracing](https://inspect.ai-safety-institute.org.uk/tracing.html) for diagnosing runs with unterminated action (e.g. model calls, docker commands, etc.).
- Provide default timeout/retry for docker compose commands to mitigate unreliability in some configurations.
- Switch to sync S3 writes to overcome unreliability observed when using async interface.
- Task display: Added `--no-score-display` option to disable realtime scoring metrics.
- Bugfix: Fix failure to fully clone samples that have message lists as input.
- llama-cpp-python: Support for `logprobs`.

## v0.3.53 (20 December 2024)

- OpenAI: Support for o1 including native tool calling and `reasoning_effort` generation option.
- Task API: Introduce `setup` step that always runs even if `solver` is replaced.
- Bedrock: Support for tool calling on Nova models.
- Bedrock: Support for custom `model_args` passed through to `session.Client`.
- Bedrock: Support for `jpeg` images.
- Bedrock: Correct max_tokens for llama3-8b, llama3-70b models on Bedrock.
- Inspect View: Various improvements to appearance of tool calls in transcript.
- Task display: Ensure that widths of progress elements are kept consistent across tasks.
- Sandboxes: New `max_sandboxes` option for (per-provider) maximum number of running sandboxes.
- Sandboxes: Remove use of aiofiles to mitigate potential for threading deadlocks.
- Concurrency: Do not use `max_tasks` as a lower bound for `max_samples`.
- Log recorder: Always re-open log buffer for `eval` format logs.
- Bugfix: Proper handling of text find for eval raw JSON display
- Bugfix: Correct handling for `--sample-id` integer comparisons.
- Bugfix: Proper removal of model_args with falsey values (explicit check for `None`)
- Bugfix: Properly handle custom metrics that return dictionaries or lists
- Bugfix: Proper sample count display when retrying an evaluation
- Bugfix: Fix inability to define and run tasks in a notebook.

## v0.3.52 (13 December 2024)

- Eval: `--sample-id` option for evaluating specific sample id(s).
- Bedrock: Detect and report HTTP rate limit errors.
- Azure AI: Add `emulate_tools` model arg to force tool emulation (emulation is enabled by default for Llama models).
- Basic Agent: Add `max_tool_output` parameter to override default max tool output from generate config.
- Inspect View: Correct display of sample ID for single sample tasks.
- Trace: Show custom tool views in `--trace` mode.
- Bugfix: Support for dynamic metric names in realtime scoring display.

## v0.3.51 (13 December 2024)

- Bugfix: Task display fails to load when no scorers are defined for a task.

## v0.3.50 (12 December 2024)

- Tools: Improved typing/schema support (unions, optional params, enums).
- Tools: Added `append` argument to `use_tools()` for adding (rather than replacing) the currently available tools.
- Docker sandbox: Streamed reads of stderr/stdout (enabling us to enforce output limits for read_file and exec at the source).
- Sandbox API: Enable passing `BaseModel` types for sandbox `config` (formerly only a file path could be passed).
- Task display: Show all task scores in realtime (expand task progress to see scores).
- Task display: Show completed samples and align progress more closely to completed samples (as opposed to steps).
- Task display: Show sample messages/tokens used (plus limits if specified).
- Task display: Resolve issue where task display would lose mouse input after VS Code reload.
- Datasets: Validate that all IDs in datasets are unique (as several downstream problems occur w/ duplicate IDs).
- Inspect View: Fix issue with incorrectly displayed custom tool views.
- Human approval: Use fullscreen display (makes approval UI async and enables rapid processing of approvals via the `Enter` key).
- Added `input_panel()` API for adding custom panels to the fullscreen task display.
- Log recorder: Methods are now async which will improve performance for fsspec filesystems with async implementations (e.g. S3)
- Log recorder: Improve `.eval` log reading performance for remote filesystem (eagerly fetch log to local buffer).
- Add `token_usage` property to `TaskState` which has current total tokens used across all calls to `generate()` (same value that is used for enforcing token limits).
- Add `time` field to `ModelOutput` that records total time spent within call to ModelAPI `generate()`.
- Web browser: Remove base64 images from web page contents (prevent filling up model context with large images).
- Match scorer: If the target of a match isn’t numeric, ignore the numeric flag and instead use text matching (improved handling for percentages).
- Hugging Face: Support for native HF tool calling for Llama, Mistral, Qwen, and others if they conform to various standard schemas.
- Hugging Face: `tokenizer_call_args` dict to specify custom args during tokenization, such as `max_length` and `truncation`.
- Azure AI: Fix schema validation error that occurred when model API returns `None` for `content`.
- Display: Throttle updating of sample list based on number of samples.
- Display: Add explicit 'ctrl+c' keybinding (as textual now disables this by default).
- Bugfix: Correct rate limit error display when running in fullscreen mode.
- Bugfix: `hf_dataset` now explicitly requires the `split` argument (previously, it would crash when not specified).
- Bugfix: Prevent cascading textual error when an error occurs during task initialisation.
- Bugfix: Correctly restore sample summaries from log file after amend.
- Bugfix: Report errors that occur during task finalisation.
  
## v0.3.49 (03 December 2024)

- Logging: Only call CreateBucket on Amazon S3 when the bucket does not already exist.
- Improve cancellation feedback and prevent multiple cancellations when using fullscreen display.
- Inspect View: Prevent circular reference error when rendering complex tool input.
- Inspect View: Resolve display issue with sorting by sample then epoch.

## v0.3.48 (01 December 2024)

- [Realtime display](https://github.com/UKGovernmentBEIS/inspect_ai/pull/865) of sample transcripts (including ability to cancel running samples).
- Scoring: When using a dictionary to map metrics to score value dictionaries, you may now use globs as keys. See our [scorer documentation](https://inspect.ai-safety-institute.org.uk/scorers.html#sec-multiple-scorers) for more information.
- `EvalLog` now includes a [location](https://github.com/UKGovernmentBEIS/inspect_ai/pull/872) property indicating where it was read from.
- Use [tool views](https://inspect.ai-safety-institute.org.uk/approval.html#tool-views) when rendering tool calls in Inspect View.
- Consistent behavior for `max_samples` across sandbox and non-sandbox evals (both now apply `max_samples` per task, formerly evals with sandboxes applied `max_samples` globally).
- Log files now properly deal with scores that produce Nan. (fixes [#834](https://github.com/UKGovernmentBEIS/inspect_ai/issues/834))
- Bash tool: add `--login` option so that e.g. .bashrc is read before executing the command.
- Google: Support for tools/functions that have no parameters.
- Google/Vertex: Support for `logprobs` and other new 1.5 (002 series) options.
- AzureAI: Change default max_tokens for Llama models to 2048 (4096 currently yields an error w/ Llama 3.1).
- Mistral: Various compatibility changes for their client and tool calling implementation.
- Handle exponents in numeric normalisation for match, include, and answer scorers.
- hf_dataset: Added `cached` argument to control whether to use a previously cached version of the dataset if available (defaults to `True`).
- hf_dataset: Added `revision` option to load a specific branch or commit SHA (when using `revision` datasets are always revalidated on Hugging Face, i.e. `cached` is ignored).
- Log viewer: Display sample ids rather than indexes.
- Log viewer: Add timestamps to transcript events.
- Log viewer: Metadata which contains images will now render the images.
- Log viewer: Show custom tool call views in messages display.
- Bugfix: Correctly read and forward image detail property.
- Bugfix: Correct resolution of global eval override of task or sample sandboxes.
- Bugfix: Don't do eval log listing on background threads (s3fs can deadlock when run from multiple threads).

## v0.3.47 (18 November 2024)

- Basic agent: Ensure that the scorer is only run once when max_attempts = 1.
- Basic agent: Support custom function for incorrect_message reply to model.
- Tool calling: Execute multiple tool calls serially (some models assume that multiple calls are executed this way rather than in parallel).
- Google: Combine consecutive tool messages into single content part; ensure no empty text content parts.
- AzureAI: Create and close client with each call to generate (fixes issue w/ using azureai on multiple passes of eval).
- Bedrock: Migrate to the [Converse API](https://docs.aws.amazon.com/bedrock/latest/userguide/conversation-inference-supported-models-features.html), which supports many more features including tool calling and multimodal models.
- Scoring: When using a dictionary to map metrics to score value dictionaries, you may now use globs as keys. See our [scorer documentation](https://inspect.ai-safety-institute.org.uk/scorers.html#sec-multiple-scorers) for more information.
- Sample limit events will now appear in the transcript if a limit (e.g. message, token, or time limit) halt a sample. The sample list and sample detail also display the limit, if applicable.

## v0.3.46 (12 November 2024)

- [eval](https://inspect.ai-safety-institute.org.uk/eval-logs.html#sec-log-format) is now the default log format (use `--log-format=json` to use old format).
- Base 64 images are now logged by default for all log formats (disable with `--no-log-images`).
- The log viewer now properly displays sample errors in the sample list for `eval` format log files.
- Improve path handling when using `inspect log convert` to convert a single log file.
- Web browser tool: Subtasks now each have independent web browser sessions.
- Anthropic: Ensure that assistant messages created in generate never have empty content lists.
- Increase sandbox `exec()` output limit from 1 MiB to 10 MiB.

## v0.3.45 (11 November 2024)

- [time_limit](https://inspect.ai-safety-institute.org.uk/errors_and_limits.html#sec-sample-limits) option for specifying a maximum execution time for samples.
- [read_eval_log_samples()](https://inspect.ai-safety-institute.org.uk/eval-logs.html#streaming) function for streaming reads of `.eval` log files.
- Mistral: Support for multi-modal models (requires v1.2 of mistralai package).
- Groq: Support for multi-modal models (requires v0.11.0 of groq package).
- AzureAI: Use Model Inference API (preview) for implementation of model client.
- Bedrock: Fix parsing of Bedrock Mistral Large 2407 responses
- Apply standard sample error handling (fail-on-error, etc.) when running scorers.
- Fix issue with correctly logging task_args for eval-set tasks which are interrupted.
- Move `INSPECT_DISABLE_MODEL_API` into `generate()` (as opposed to `get_model()`)
- Always treat `.eval` files as logs (don't apply file name pattern restrictions as we do with `.json`).
- Log model calls when model providers return bad request errors
- Better lay out large numbers of configuration and parameters when displaying log files.
- The log viewer now properly displays sample scores for running tasks.
- Add `metadata` field to `ModelOutput` and provide various fields for the Groq provider.

## v0.3.44 (04 November 2024)

- Revert change to single epoch reducer behavior (regressed some scoring scenarios).

## v0.3.43 (04 November 2024)

- New binary [log format](https://inspect.ai-safety-institute.org.uk/eval-logs.html#sec-log-format) which yields substantial size and speed improvements (JSON format log files are still fully supported and utilities for converting between the formats are provided).
- [Grok](https://docs.x.ai/) model provider.
- [llama-cpp-python](https://llama-cpp-python.readthedocs.io/en/latest/) local model provider.
- Extensions: correctly load extensions in packages where package name differs from dist name.
- Added `--model-config`, `--task-config`, and `--solver-config` CLI arguments for specifying model, task, and solver args using a JSON or YAML config file.
- View: properly render complex score objects in transcript.
- Write custom tool call views into transcript for use by Inspect View.
- Use `casefold()` for case-insensitive compare in `includes()`, `match()`, `exact()`, and `f1()` scorers.
- OpenAI: eliminate use of `strict` tool calling (sporadically supported across models and we already internally validate).
- Mistral: fix bug where base_url was not respected when passing both an api_key and base_url.
- Don't include package scope for task name part of log files.
- Improve performance of write_file for Docker sandboxes.
- Use user_data_dir rather than user_runtime_dir for view notifications.
- Implement `read_eval_log_sample()` for JSON log files.
- Log the list of dataset sample IDs.
- Limit `SandboxEnvironment.exec()` output streams to 1 MiB. Limit `SandboxEnvironment.read_file()` to 100 MiB.
- Add `INSPECT_DISABLE_MODEL_API` environment variable for disabling all Model APIs save for mockllm.
- Add optional `tool_call_id` param to `ModelOutput.for_tool_call()`.
- Support all JSON and CSV dataset arguments in `file_dataset()` function.

## v0.3.42 (23 October 2024)

- [ToolDef](https://inspect.ai-safety-institute.org.uk/tools.html#sec-dynamic-tools) class for dynamically creating tool definitions.
- Added `--tags` option to eval for tagging evaluation runs.
- Added APIs for accessing sample event transcripts and for creating and resolving attachments for larger content items.
- Cleanup Docker Containers immediately for samples with errors.
- Support Dockerfile as config path for Docker sandboxes (previously only supported compose files).
- Anthropic: remove stock tool use chain of thought prompt (many Anthropic models now do this internally, in other cases its better for this to be explicit rather than implicit).
- Anthropic: ensure that we never send empty text content to the API.
- Google: compatibility with google-generativeai v0.8.3
- Llama: remove extraneous <|start_header_id|>assistant<|end_header_id|> if it appears in an assistant message.
- OpenAI: Remove tool call id in user message reporting tool calls to o1- models.
- Use Dockerhub aisiuk/inspect-web-browser-tool image for web browser tool.
- Use ParamSpec to capture types of decorated solvers, tools, scorers, and metrics.
- Support INSPECT_EVAL_MODEL_ARGS environment variable for calls to `eval()`.
- Requirements: add lower bounds to various dependencies based on usage, compatibility, and stability.
- Added `include_history` option to model graded scorers to optionally include the full chat history in the presented question.
- Added `delimiter` option to `csv_dataset()` (defaults to ",")
- Improve answer detection in multiple choice scorer.
- Open log files in binary mode when reading headers (fixes ijson deprecation warning).
- Capture `list` and `dict` of registry objects when logging `plan`.
- Add `model_usage` field to `EvalSample` to record token usage by model for each sample.
- Correct directory handling for tasks that are imported as local (non-package) modules.
- Basic agent: terminate agent loop when the context window is exceeded.
- Call tools sequentially when they have opted out of parallel calling.
- Inspect view bundle: support for bundling directories with nested subdirectories.
- Bugfix: strip protocol prefix when resolving eval event content
- Bugfix: switch to run directory when running multiple tasks with the same run directory.
- Bugfix: ensure that log directories don't end in forward/back slash.

## v0.3.41 (11 October 2024)

- [Approval mode](https://inspect.ai-safety-institute.org.uk/approval.html) for extensible approvals of tool calls (human and auto-approvers built in,  arbitrary other approval schemes via extensions).
- [Trace mode](https://inspect.ai-safety-institute.org.uk/interactivity.html#sec-trace-mode) for printing model interactions to the terminal.
- Add `as_dict()` utility method to `Score`
- [Sample limits](https://inspect.ai-safety-institute.org.uk/errors_and_limits.html#sec-sample-limits) (`token_limit` and `message_limit`) for capping the number of tokens or messages used per sample ( `message_limit` replaces deprecated `max_messages`).
- Add `metadata` field to `Task` and record in log `EvalSpec`.
- Include datetime and level in file logger.
- Correct llama3 and o1 tool calling when empty arguments passed.
- Allow resolution of any sandbox name when there is only a single environment.
- Introduce `--log-level-transcript` option for separate control of log entries recorded in the eval log file
- Improve mime type detection for image content encoding (fixes issues w/ webp images).
- Fix memory leak in Inspect View worker-based JSON parsing.
- Add `fail_on_error` option for `eval_retry()` and `inspect eval-retry`.
- Defer resolving helper models in `self_critique()` and `model_graded_qa()`.
- Fix Docker relative path resolution on Windows (use PurePosixPath not Path)
- Restore support for `--port` and `--host` on Inspect View.

## v0.3.40 (6 October 2024)

- Add `interactive` option to `web_browser()` for disabling interactive tools (clicking, typing, and submitting forms).
- Provide token usage and raw model API calls for OpenAI o1-preview.
- Add support for reading CSV files of dialect 'excel-tab'.
- Improve prompting for Python tool to emphasise the need to print output.
- For `basic_agent()`, defer to task `max_messages` if none is specified for the agent (default to 50 is the task does not specify `max_messages`).
- Add optional `content` parameter to `ModelOutput.for_tool_call()`.
- Display total samples in Inspect View
- Prune `sample_reductions` when returning eval logs with `header_only=True`.
- Improved error message for undecorated solvers.
- For simple matching scorers, only include explanation if it differs from answer.

## v0.3.39 (3 October 2024)

- The sample transcript will now display the target for scoring in the Score Event (for newly run evaluations).
- Provide setter for `max_messages` on `TaskState`.
- Provide `max_messages` option for `basic_agent()` (defaulting to 50) and use it rather than any task `max_messages` defined.
- Improved implementation of disabling parallel tool calling (also fixes a transcript issue introduced by the original implementation).
- Improve quality of error messages when a model API key environment variable is missing.
- Improve prompting around letting the model know it should not attempt parallel web browser calls.

## v0.3.38 (3 October 2024)

- Rename `web_browser_tools()` to `web_browser()`, and don't export individual web browsing tools.
- Add `parallel` option to `@tool` decorator and specify `parallel=False` for web browsing tools.
- Improve prompting for web browser tools using more explicit examples.
- Improve prompting for `</tool_call>` end sequence for Llama models.
- Fix issue with failure to execute sample setup scripts.

## v0.3.37 (2 October 2024)

- Move evals into [inspect_evals](https://github.com/UKGovernmentBEIS/inspect_evals) package.

## v0.3.36 (2 October 2024)

- [Web Browser](https://inspect.ai-safety-institute.org.uk/tools.html#sec-web-browser) tool which provides a headless Chromium browser that supports navigation, history, and mouse/keyboard interactions.
- `auto_id` option for dataset readers to assign an auto-incrementing ID to records.
- Task args: don't attempt to serialise registry objects that don't have captured parameters.

## v0.3.35 (1 October 2024)

- Catch o1-preview "invalid_prompt" exception and convert to normal content_filter refusal.
- Terminate timed out subprocesses.
- Support 'anthropoic/bedrock/' service prefix for Anthropic models hosted on AWS Bedrock.
- Change score reducer behavior to always reduce score metadata to the value of the `metadata` field in the first epoch
- Improve task termination message (provide eval-retry prompt for tasks published in packages)
- Preserve type for functions decorated with `@task`.
- Various improvements to layout and display for Inspect View transcript.

## v0.3.34 (30 September 2024)

- Support for `max_tokens` on OpenAI o1 models (map to `max_completion_tokens`).
- Fix regression of log and debug options on `inspect view`
- Improved focus management for Inspect View
- Raise error if `epochs` is less than 1
- Improve code parsing for HumanEval (compatibility with Llama model output)

## v0.3.33 (30 September 2024)

- StopReason: Added "model_length" for exceeding token window and renamed "length" to "max_tokens".
- Capture solver input params for subtasks created by `fork()`.
- Option to disable ANSI terminal output with `--no-ansi` or `INSPECT_NO_ANSI`
- Add chain of thought option to `multiple_choice()` and export `MultipleChoiceTemplate` enumeration
- Allow Docker sandboxes configured with `x-default` to be referred to by their declared service name.
- Improved error messages for Docker sandbox initialisation.
- Improve legibility of Docker sandbox log entries (join rather than displaying as array)
- Display user message immediately proceeding assistant message in model call transcripts.
- Display images created by tool calls in the Viewer.
- Fix duplicated tool call output display in Viewer for Gemini and Llama models.
- Require a `max_messages` for use of `basic_agent()` (as without it, the agent could end up in an infinite loop).
- Load extension entrypoints per-package (prevent unnecessary imports from packages not being referenced).
- Track sample task state in solver decorator rather than solver transcript.
- Display solver input parameters for forked subtasks.
- Improvements to docker compose down cleanup: timeout, survive missing compose files.
- Always produce epoch sample reductions even when there is only a single epoch.
- Scores produced after being reduced retain `answer`, `explanation`, and `metadata` only if equal across all epochs.

## v0.3.32 (25 September 2024)

- Fix issue w/ subtasks not getting a fresh store() (regression from introduction of `fork()` in v0.3.30)
- Fix issue w/ subtasks that return None invalidating the log file.
- Make subtasks collapsible in Inspect View.
- Improved error reporting for missing `web_search()` provider environment variables.

## v0.3.31 (24 September 2024)

- Deprecated `Plan` in favor of `Solver` (with `chain()` function to compose multiple solvers).
- Added `max_tool_output` generation option (defaults to 16KB).
- Improve performance of `header_only` log reading (switch from json-stream to ijson).
- Add support for 0 retries to `eval-set` (run a single `eval` then stop).
- Tool calling fixes for update to Mistral v1.1. client.
- Always show `epochs` in task status (formerly wasn't included for multiple task display)
- Render transcript `info()` strings as markdown
- Eliminate log spam from spurious grpc fork message.
- Fix issue with hf_dataset shuffle=True not actually shuffling.
- Improved error handling when loading invalid setuptools entrypoints.
- Don't catch TypeError when calling tools (we now handle this in other ways)

## v0.3.30 (18 September 2024)

- Added [fork()](https://inspect.ai-safety-institute.org.uk/agents-api.html#sec-forking) function to fork a `TaskState` and evaluate it against multiple solvers in parallel.
- Ensure that Scores produced after being reduced still retain `answer`, `explanation`, and `metadata`.
- Fix error when running `inspect info log-types`
- Improve scorer names imported from modules by not including the the module names.
- Don't mark messages read from cache with source="cache" (as this breaks the cache key)
- Add `cache` argument to `basic_agent()` for specifying cache policy for the agent.
- Add `cache` field to `ModelEvent` to track cache reads and writes.
- Compatibility with Mistral v1.1 client (now required for Mistral).
- Catch and propagate Anthropic content filter exceptions as normal "content_filter" responses.
- Fix issue with failure to report metrics if all samples had a score value of 0.
- Improve concurrency of Bedrock models by using aioboto3.
- Added [SWE Bench](https://github.com/UKGovernmentBEIS/inspect_evals/tree/main/src/inspect_evals/swe_bench), [GAIA](https://github.com/UKGovernmentBEIS/inspect_evals/tree/main/src/inspect_evals/gaia), and [GDM CTF](https://github.com/UKGovernmentBEIS/inspect_evals/tree/main/src/inspect_evals/gdm_capabilities/in_house_ctf) evals.

## v0.3.29 (16 September 2024)

- Added `--plan` and `-P` arguments to `eval` and `eval-set` commands for replacing the task default plan with another one.
- Improved support for eval retries when calling `eval()` or `eval_set()` with a `plan` argument.
- Don't log base64 images by default (re-enable logging with `--log-images`).
- Provide unique tool id when parsing tool calls for models that don't support native tool usage.
- Fix bug that prevented `epoch_reducer` from being used in eval-retry.
- Fix bug that prevented eval() level `epoch` from overriding task level `epoch`.

## v0.3.28 (14 September 2024)

- [basic_agent()](https://inspect.ai-safety-institute.org.uk/agents.html#sec-basic-agent) that provides a ReAct tool loop with support for retries and encouraging the model to continue if its gives up or gets stuck.
- [score()](https://inspect.ai-safety-institute.org.uk/solvers.html#sec-scoring-in-solvers) function for accessing scoring logic from within solvers.
- Ability to [publish](https://inspect.ai-safety-institute.org.uk/log-viewer.html#sec-publishing) a static standalone Inspect View website for a log directory.
- `system_message()` now supports custom parameters and interpolation of `metadata` values from `Sample`.
- `generate()` solver now accepts arbitrary generation config params.
- `use_tools()` now accepts a variadic list of `Tool` in addition to literal `list[Tool]`.
- `bash()` and `python()` tools now have a `user` parameter for choosing an alternate user to run code as.
- `bash()` and `python()` tools now always return stderr and stdout no matter the exit status.
- Support for OpenAI o1-preview and o1-mini models.
- Input event for recording screen input in sample transcripts.
- Record to sample function for CSV and JSON dataset readers can now return multiple samples.
- Added `debug_errors` option to `eval()` to raise task errors (rather than logging them) so they can be debugged.
- Properly support metrics that return a dict or list of values
- Improved display of prerequisite errors when running `eval()` from a script or notebook.
- Fix `eval_set()` issue with cleaning up failed logs on S3.
- Cleanup Docker containers that fail during sample init.
- Add support for computing metrics for both individual keys within a dictionary but also for the dictionary as a whole
- Fix for Vertex tool calling (don't pass 'additionalProperties').
- Added [SQuAD](https://github.com/UKGovernmentBEIS/inspect_evals/tree/main/src/inspect_evals/squad), [AGIEval](https://github.com/UKGovernmentBEIS/inspect_evals/tree/main/src/inspect_evals/agieval), [IFEval](https://github.com/UKGovernmentBEIS/inspect_ai/blob/main/src/inspect_evals/ifeval/), [PubMedQA](https://github.com/UKGovernmentBEIS/inspect_evals/tree/main/src/inspect_evals/pubmedqa), and [MBPP](https://github.com/UKGovernmentBEIS/inspect_evals/tree/main/src/inspect_evals/mbpp) benchmarks.

## v0.3.27 (6 September 2024)

- Fix missing timestamp issue with running `eval_set()` with an S3-backed log directory.
- Correct rounding behavior for `f1()` and `exact()` scorers.
- Correct normalized text comparison for `exact()` scorer.
- Improved appearance and navigation for sample transcript view.
- Added [MathVista](https://github.com/UKGovernmentBEIS/inspect_evals/tree/main/src/inspect_evals/mathvista) benchmark.

## v0.3.26 (6 September 2024)

- [Eval Sets](https://inspect.ai-safety-institute.org.uk/eval-sets.html) for running groups of tasks with automatic retries.
- [Per-sample](https://inspect.ai-safety-institute.org.uk/sandboxing.html#sec-per-sample-sandbox) Sandbox environments can now be specified (e.g. allowing for a distinct Dockerfile or Docker compose file for each sample).
- [input_screen()](https://inspect.ai-safety-institute.org.uk/interactivity.html) context manager to temporarily clear task display for user input.
- Introduce two new scorers, `f1()` (precision and recall in text matching) and `exact()` (whether normalized text matches exactly).
- Task `metrics` now override built in scorer metrics (previously they were merged). This enables improved re-use of existing scorers where they only change required is a different set of metrics.
- `write_log_dir_manifest()` to write a log header manifest for a log directory.
- Relocate `store()` and `@subtask` from solver to utils module; relocate `transcript()` from solver to log module.
- Add optional user parameter to SandboxEnvironment.exec for specifying the user. Currently only DockerSandboxEnvironment is supported.
- Fix issue with resolving Docker configuration files when not running from the task directory.
- Only populate Docker compose config metadata values when they are used in the file.
- Treat Sandbox exec `cwd` that are relative paths as relative to sample working directory.
- Filter base64 encoded images out of model API call logs.
- Raise error when a Solver does not return a TaskState.
- Only run tests that use model APIs when the `--runapi` flag is passed to `pytest` (prevents unintended token usage)
- Remove `chdir` option from `@tasks` (tasks now always chdir during execution).
- Do not process `.env` files in task directories (all required vars should be specified in the global `.env`).
- Only enable `strict` mode for OpenAI tool calls when all function parameters are required.
- Added [MMMU](https://github.com/UKGovernmentBEIS/inspect_evals/tree/main/src/inspect_evals/mmmu), [CommonsenseQA](https://github.com/UKGovernmentBEIS/inspect_evals/tree/main/src/inspect_evals/commonsense_qa), [MMLU-Pro](https://github.com/UKGovernmentBEIS/inspect_evals/tree/main/src/inspect_evals/mmlu_pro), and [XSTest](https://github.com/UKGovernmentBEIS/inspect_evals/tree/main/src/inspect_evals/xstest) benchmarks.

## v0.3.25 (25 August 2024)

- [Store](https://inspect.ai-safety-institute.org.uk/agents-api.html#sharing-state) for manipulating arbitrary sample state from within solvers and tools.
- [Transcript](https://inspect.ai-safety-institute.org.uk/agents-api.html#transcripts) for detailed sample level tracking of model and tool calls, state changes, logging, etc.
- [Subtasks](https://inspect.ai-safety-institute.org.uk/agents-api.html#sec-subtasks) for delegating work to helper models, sub-agents, etc.
- Integration with Anthropic [prompt caching](https://inspect.ai-safety-institute.org.uk/caching.html#sec-provider-caching).
- [fail_on_error](https://inspect.ai-safety-institute.org.uk/errors-and-limits.html#failure-threshold) option to tolerate some threshold of sample failures without failing the evaluation.
- Specify `init` value in default Docker compose file so that exit signals are handled correctly (substantially improves container shutdown performance).
- Add `function` field to `ChatMessageTool` to indicate the name of the function called.
- Added [RACE](https://github.com/UKGovernmentBEIS/inspect_evals/tree/main/src/inspect_evals/race-h/) benchmark.

## v0.3.24 (18 August 2024)

- Support for tool calling for Llama 3.1 models on Bedrock.
- Report JSON schema validation errors to model in tool response.
- Support for `strict` mode in OpenAI tool calls (update to v1.40.0 of `openai` package required).

## v0.3.23 (16 August 2024)

- Support for tool calling for Llama 3.1 models on Azure AI and CloudFlare.
- Increase default `max_tokens` from 1024 to 2048.
- Record individual sample reductions along with results for multi-epoch evals.
- Change default to not log base64 encoded versions of images, as this often resulted in extremely large log files (use `--log-images` to opt back in).
- Update to new Mistral API (v1.0.1 of `mistralai` is now required).
- Support for Llama 3.1 models on Amazon Bedrock
- Eliminate Bedrock dependency on anthropic package (unless using an Anthropic model).
- Improved resolution of AWS region for Bedrock (respecting already defined AWS_REGION and AWS_DEFAULT_REGION)
- Fix bug in match scorer whereby numeric values with periods aren't correctly recognized.
- Added [HumanEval](https://github.com/UKGovernmentBEIS/inspect_evals/tree/main/src/inspect_evals/humaneval), [WinoGrande](https://github.com/UKGovernmentBEIS/inspect_evals/tree/main/src/inspect_evals/winogrande) and [Drop](https://github.com/UKGovernmentBEIS/inspect_evals/tree/main/src/inspect_evals/drop) benchmarks.

## v0.3.22 (07 August 2024)

- Fix issue affecting results of `pass_at_{k}` score reducer.

## v0.3.21 (07 August 2024)

- Add `pass_at_{k}` score reducer to compute the probability of at least 1 correct sample given `k` epochs.
- Improved metrics `value_to_float` string conversion (handle numbers, "true", "false", etc.)
- Log viewer: Ctrl/Cmd+F to find text when running in VS Code.
- Set Claude default `max_tokens` to 4096
- Combine user and assistant messages for Vertex models.
- Warn when using the `name` parameter with task created from `@task` decorated function.
- Make sample `metadata` available in prompt, grading, and self-critique templates.
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
- Allow sandbox environment providers to specify a default `max_samples` (set to 25 for the Docker provider).
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

-   [Sandbox Environments](https://inspect.ai-safety-institute.org.uk/sandboxing.html) for executing tool code in a sandbox.
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
-   Fallback to standard parse if `NaN` or `Inf` is encountered while reading log file header.
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
-   Resiliency to Python syntax errors that occur when enumerating tasks in a directory.
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
