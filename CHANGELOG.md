## 0.3.182 (24 February 2026)

- AzureAI: Pass `max_completion_tokens` to gpt-5 and o-series models.
- Events: Add timeline functions for providing additional structure for event viewing and traversal.
- Inspect View: Add support for downloading sample JSON.

## 0.3.181 (23 February 2026)

- Hooks: New `on_sample_init()` hook that fires before sandbox environments are created, enabling hooks to gate sandbox resource provisioning.
- Model API: Add `content_list` property to `ChatMessage` for consistent access to content as a list.
- OpenAI Compatible: Send `max_completion_tokens` when interacting with gpt-5 or o-series models.
- Anthropic: Use `output_config` directly (rather than via `extra_body`) which is compatible with batch mode.
- Google: Add latest Gemini models to model info database.
- Sandboxes: Verify execute result size automatically for all sandbox exec calls.
- Sandboxes: Export `exec_remote()` types from root namespace and add docs.
- Eval Set: Add `TASK_IDENTIFIER_VERSION` to support persistence of task identifiers in inspect_flow.
- Eval Retry: Don't retry with `model_base_url` unless it was explicitly specified by the user.
- Agent Bridge: Add model_aliases to agent bridge and pass Model to GenerateFilter.
- Dependencies: Update to nest-asyncio2 v1.7.2 to address anyio threading issue.
- Inspect View: Display all non-undefined edited score values.
- Bugfix: Don't reuse eval_set logs when `sample_shuffle` changes and `limit` constrains sample selection.
- Bugfix: `eval_set` now correctly handles pending tasks and incomplete tasks (e.g. limit/epoch changes) in a single pass, instead of skipping incomplete tasks when new tasks were present.
- Bugfix: Reuse S3 clients in log recorders to fix session leak.
- Bugfix: Create eval set bundle even when all logs are already complete.
- Bugfix: Fix `epochs_changed` false positives in `eval_set` caused by comparing reducer closure `__name__` instead of registry log name.
- Bugfix: Fix async ZIP parser crash on valid `.eval` files whose compressed data contained a false ZIP64 EOCD Locator signature.
- Bugfix: Skip non-JSON lines in MCP server stdout parsing,
- Bugfix: Remove doubled MIME prefix in MCP content conversion.
- Bugfix: Ensure that `eval()` specified `model_roles` override task-level roles.
- Bugfix: Improve max sample size error.

## 0.3.180 (20 February 2026)

- Agent Bridge: Google Gemini API is now supported for in-process and sandbox bridges.
- Task Execution: Cancelled samples are now logged in the same fashion as samples with errors.
- Anthropic: Increase max_tokens caps for Claude 4.5 and 4.6 models.
- Anthropic: Update to new sdk types released with Sonnet 4.6 (v0.80.0 of `anthropic` package is now required).
- Anthropic: Remove uses of Sonnet 3.7 from tests (no longer available).
- Hugging Face: More flexible control over application of chat templates (enables support for generation from base models).
- VLLM: Don't retry when the error indicates that the VLLM server has crashed.
- Analysis: Async reading of logs/samples in `samples_df()` (now 50x faster).
- Sandboxes: Don't require Docker compatible sandboxes to implement `config_deserialize()`.
- Sandboxes: New `exec_remote()` method for async execution of long-running commands.
- Compaction: Add `type` field to `CompactionEvent` to record compaction type.
- Web Search: Treat Tavily query character limits as ToolErrors.
- Limits: New `cost_limit()` context manager for scoped application of cost limits.
- Performance: Disable expensive per-sample options when running high-throughput workloads.
- Events: Rename `EventNode` to `EventTreeNode` and `SpanNode` to `EventTreeSpan` (old type names will still work at runtime with a deprecation warning).
- Inspect View: Make samples in task detail sortable, inline epoch filter, show sample status.
- Bugfix: Shield sandbox cleanup after cancelled exception.
- Bugfix: Protect against leading zero-width characters when printing tool output to the terminal.
- Bugfix: Google batch JSONL serialization now correctly nests generation config fields (e.g. `thinking_config`) under `generation_config` in the REST schema.
- Bugfix: Google batch polling no longer hangs forever when a batch job reaches `EXPIRED` or `PARTIALLY_SUCCEEDED` state.

## 0.3.179 (12 February 2026)

- Bugfix: Fix shutdown hang by draining nest_asyncio event loop.
- Bugfix: Fix regression in live sample display in Inspect View.

## 0.3.178 (11 February 2026)

- Google: Hard failure for quota exceeded errors with `limit: 0` (indicating the model or feature is fully restricted).
- Compaction: Improve token counting by using input tokens reported from call to `generate()`.
- Model API: for 400 errors, print the error after the request payload rather than before.
- Eval Logs: Add progress callback interface for reading eval logs
- Sandboxes: Added `http_proxy` example for intercepting and remapping HTTP requests from agents using mitmproxy.
- Inspect View: Fix regression in log viewer navigation in VSCode.
- Inspect View: Improve transcript display appearance in VSCode.
- Inspect View: Improve log events display in transcripts.
- Bugfix: Fix off-by-one in `_read_all_summaries` that skipped the last sample summary.

## 0.3.177 (10 February 2026)

- Anthropic: Do not pass through unrecognized `extra_body` fields.

## 0.3.176 (10 February 2026)

- Eval Logs: Async parallel reading of eval log headers from S3, reducing time from 12+ minutes to ~12 seconds for ~600 files.
- Bugfix: Correct handling of `ComposeConfig` for Docker sandbox provider.

## 0.3.175 (10 February 2026)

- OpenRouter: Retry 500 and 504 errors returned in request JSON body.
- Scoring: Allow customisation of grouped metric names.
- Model API: Don't strictly require OpenAI and Anthropic versions when they aren't in use.
- Inspect View: Show live requests and responses for model call events in the transcript.
- Inspect View: Improve scroll performance when viewing sample transcripts and messages.

## 0.3.174 (09 February 2026)

- Compaction: Remove reasoning blocks from `compact()` result for Anthropic provider.

## 0.3.173 (08 February 2026)

- Compaction: Correct capture of compaction results for Anthropic streaming mode.
- Compaction: Improved prefix handling (drop all by system messages) for native compaction.
- Compaction: Improved display of OpenAI and Anthropic compaction data in the viewer.

## 0.3.172 (06 February 2026)

- Inspect View: Fix a regression which affected the display of samples within VSCode.

## 0.3.171 (06 February 2026)

- Compaction: New `CompactionNative` strategy which uses provider-native compaction (currently only available for OpenAI and Anthropic Claude 4.6).
- Compaction: New `CompactionAuto` strategy which uses `CompactionNative` if possible and falls back to `CompactionSummary`.
- `store_from_events()` and `store_from_events_as()` functions for reconstructing the store from a list of events.
- OpenAI: Updated to 2.17.0 of `openai` package to get correct types for web search `ActionFind`.
- Anthropic: Built-in tool (e.g. web search, code execution) compatibility for Claude 4.6.
- Anthropic: Support `--reasoning-effort` (via adaptive thinking) and  `--effort=max` option for Claude 4.6.
- Added `extra_headers` to `GenerateConfig` for sending extra HTTP headers along with provider requests.
- Together Batch API: Update to version 2.0.0 of `together` package.
- Inspect View: Add sticky headers for transcript events and show turn number to improve "where am I" UX.
- Inspect View: Show errors in model call events in the transcript.
- Inspect View: Show tracebacks in model call events in the transcript.
- Inspect View: Fix slow performance loading samples caused by unnecessary repeat load calls in SampleDetailView.
- Inspect View: Fix incorrectly disabled sample navigation when viewing samples with numeric sample ids.
- Inspect View: Fix issue where a large number of logs could result in laggy or hung viewer in VSCode.
- Bugfix: `handoff()` now respects `react()` name parameter when creating the transfer_to_X tool name.
- Bugfix: Correctly handle optional `content` field in Anthropic agent bridge `tool_result`.

## 0.3.170 (03 February 2026)

- Added `stable_message_ids()` function for yielding stable ids based on model content (but always unique within a given conversation).
- Model API: Added `CompactionEvent` for model compactions.
- Sandboxes: Enable sandbox providers to declare Docker compatibility, which will result in Docker config files being passed to them.
- Docker Sandbox: Store auto-compose files in centralized project-keyed location (rather than alongside tasks).
- Inspect View: Improve reliability of code syntax highlighting in messages and events.
- Inspect View: Support zstd compression of eval log file contents.
- Inspect View: Fix issue where viewing sample events could result in flashing and scroll oscillation.
- Inspect View: Render `<think>` tags when included in user messages.
- Bugfix: Correct handling for `--reasoning-history` CLI argument (don't parse as boolean).
- Bugfix: Submit to `human_cli()` with no answer now correctly completes task.

## 0.3.169 (01 February 2026)

- Anthropic: Correct handling of beta server tool use blocks for bridge clients that use the beta API (e.g. PydanticAI).
- OpenAI: Workaround for openai Python SDK inability to round trip 'find_in_page' web search actions.
- Reasoning: Don't process `<think>` tags in assistant message loading (now all done directly by model providers).
- Web Search: Use internal search providers by default when no external provider is defined (previously they required explicit enabling).
- Web Search: Fallback to Google CSE provider only when Google CSE environment variables are defined (the CSE service has been deprecated by Google).
- Eval Logs: Improve eval log loading performance with JSON cache key for messages.
- Eval Logs: Support Zstd compression of eval logs for improved performance via `INSPECT_USE_ZSTD` environment variable.
- Agent Bridge: Make sandbox_agent_bridge cleanup errors non-fatal when agent completes
- Compaction: Add source="compaction" to InfoEvent created by compaction.

## 0.3.168 (31 January 2026)

- [nnterp](https://inspect.aisi.org.uk/providers.html#nnterp) model provider enabling use of `StandardizedTransformer` models with Inspect.
- OpenAI Compatible: More generic handling for reasoning payloads (playback reasoning in exactly the same body field it was captured from).
- Eval Logs: Add `EvalStatus` type alias for evaluation status literals (`"started"`, `"success"`, `"cancelled"`, `"error"`).
- Bugfix: raise PrerequisiteError when bundling to a subdirectory of the log dir (instead of deleting the logs from the log dir).

## 0.3.167 (29 January 2026)

- Early Stopping: Check for early stopping after sample semaphore is acquired rather than before.
- Revert use of `json.dumps` for message cache keys (incompatible with `BaseModel` types).

## 0.3.166 (29 January 2026)

- Scoring: Add `model_usage` field to `ScoreEvent` for tracking token usage vs score.
- Compaction: Compact server tool uses in `CompactionEdit` strategy (previously only client tool uses were compacted).
- Docker: Avoid mutable default env arguments in execution helpers.
- Eval Logs: Add `exclude_fields` parameter to `read_eval_log_sample()` for memory-efficient loading of large samples.
- Inspect View: Fix issue where switching from a running to a non-running evaluation could display incorrect metrics in the title region.
- Inspect View: Fix sample switching when viewing live transcripts.

## 0.3.165 (26 January 2026)

- Eval Logs: Improve load time by using JSON in duplicate message cache rather than `frozendict`.
- Compaction: Remove citations after compaction to avoid dangling citation references (updated `trim_message()` to use the same behavior).
- Inspect View: Fix "Cannot add property timestamp, object is not extensible" error when viewing live transcripts.

## 0.3.164 (24 January 2026)

- Google: Provide JSON schema directly rather than converting it to Google Schema type.
- Agent Bridge: Support bridge clients that use the Anthropic Beta API.
- Agent Bridge: Serialize `ContentReasoning` as `<think>` with attributes to prevent bridge clients from doing a more lossy `<think>` tag conversion.
- Compaction: Correct handling of thinking mode in Anthropoic `count_tokens()` method.
- Compaction: Correct handling of consecutive tool messages in Anthropic `count_tokens()` method.
- Bash Session: Increase bash session transport timeout and make new session timeouts fatal.
- Inspect View: Timestamps for USER and ASSISTANT transcript of model events, `yyyy-mm-dd hh:mm:ss` format (keep local time zone).
- Inspect View: Remove events from JSON before parsing if Sample JSON is too large.
- Bugfix: Include type field in JSON Schema for Literal and Enum types.
- Bugfix: Handle maps and lists in registry_kwargs().

## 0.3.163 (21 January 2026)

- Anthropic: Only re-order reasoning blocks for Claude 3 (as we use interleaved thinking for Claude 4).
- Analysis: Read all samples at once in implementation of `samples_df()`.
- Agent Bridge: Handle OpenAI assistant message params with no 'type' field (Pydantic AI compatibility).
- Inspect View: Improve sample summary truncation (use markdown truncation instead of line clamping).
- Inspect View: Fix issue with typing over selection in 'Find'
- Inspect View: Fix issues with 'Find' scrolling, keyboard behavior, and restoration of scroll position / panel expansion.
- Inspect View: Support find using JSON-like syntax.

## 0.3.162 (18 January 2026)

- Google: Add `streaming` model arg to opt-in to streaming generation.
- TogetherAI: Support for parsing logprobs returned in OpenAI format (e.g. for gpt-oss-20b).
- HF tasks: Support for `image_input` (data URI) in field spec for multimodal tasks
- Scoring: Enable editing scores for samples that do not yet have a score.
- Task Display: Throttle updates to running samples according to total samples.
- Sandbox: Support passing a `ComposeConfig` directly to Docker sandbox provider.
- Sandbox: Remove `supported_fields` parameter from `parse_compose_yaml()` (packages handle their own validation).
- Sandbox Service: Provide option to trigger request processing manually.
- Inspect View: Fix regression where viewing samples with identical id/epoch would re-use the previous sample details.
- Inspect View: Show event timestamp in tooltips in all types of events in transcripts.
- Inspect View: Show sample invalidation status in sample header.
- Bugfix: Compose models now correctly handle x- extensions at all levels (inner models discarded them, outer models accepted non-extensions).

## 0.3.161 (10 January 2026)

- Sandbox: `parse_compose_yaml()` for parsing Docker Compose files into typed configuration for sandbox providers.
- Google: Yield system_instructions as list of str (improved compatibility with opentelemetry capture).
- Google: Raise error if batch processing is used with Vertex hosted models.
- OpenAI Compatible: Always pass function definitions with `strict=True`. This is required by HF Inference Providers and Fireworks (and possibly others).
- OpenAI Compatible: Convert function arguments to JSON if they are provided as a string (as is done by xAI and perhaps other providers).
- Model API: Improvements in model detection for hosting providers (e.g. Azure, Bedrock, etc.).
- Eval Log: Add version of the package exporting the task (if any) to the eval log.
- Analysis: Convert mixed-type object columns to string for PyArrow conversion.
- Sandboxing: Add INSPECT_SANDBOX_SETUP_TIMEOUT env var to override default 300s setup timeout.
- Human Agent: Fixed non-scalar intermediate score values breaking task commands like `task status` and `task stop`.
- Bugfix: Print only enabled hooks at CLI startup.
- Bugfix: Fix eval_set log reuse when setting limits as eval set args.

## 0.3.160 (09 January 2026)

- Agent Bridge: Consolidate bridged tools implementation into the existing sandbox model proxy service (eliminate Python requirement for using bridged tools).
- Anthropic: Correctly replay reasoning when sourced from Inspect cache.
- Anthropic: Tolerate `{}` as value for `additionalProperties` in tool schema.
- OpenAI Compatible: Don't ever send `background` parameter as this is OpenAI service-specific.
- OpenAI Compatible: Added support for disabling reasoning history emulation.
- Grok: Correctly replay tool calling errors in message history.
- VLLM and SGLang: Don't require API key environment variable to be set when running in local mode.
- Google: Support `minimal` and `medium` reasoning effort levels for Gemini 3 Flash.
- Fireworks: Use streaming when `max_tokens` is greater than 16000.
- Model API: Add `combined_from` metadata field when combining consecutive user or assistant messages for call to generate.
- HF Tasks: Require >1.0.0 of huggingface_hub package.
- Eval Set: Include task version and limits in task identifier hash to prevent incorrect log reuse.
- Scoring: Match only last line of output in answer(pattern="line").
- JSON Datasets: Support passing arbitrary `kwargs` to JSON readers (built-in reader and jsonlines reader).
- Filesystems: Use default_fs_options() for `async_connection()`
- Inspect View: Don't attempt to display events when the events are too large for the browser to deserialize (e.g. 350MB+ of events).
- Inspect View: Improve rendering of tool output with ANSI codes. Support viewing raw/unrendered ANSI output.
- Inspect View: Scale ANSI display in messages view to preserve row/column layout without wrapping.
- Inspect View: Render custom tool view when viewing messages.
- Inspect View: Fix cmd+click on tasks/samples to open in new tab.
- Inspect View: Only stream log bytes when requested chunks are large (>50MB)
- Inspect View: Add Show Retried Logs button when inside an eval set and some logs were retried (both Tasks and Samples are now de-duplicated by default).
- Inspect View: Improved non-native find for virtualized lists (better CTRL-f)
- Bugfix: Prevent component not found error during Human Agent transition.
- Bugfix: Use `builtins` module rather than `__builtins__` when parsing tool function types.

## 0.3.159 (03 January 2026)

- [Compaction](https://inspect.aisi.org.uk/compaction.html.md): Compacting message histories for long-running agents that exceed the context window.
- Model API: `count_tokens()` method for estimating token usage for messages.
- Model API: `ModelInfo` for retrieving information about models (e.g. organization, context window, reasoning, release date, etc.)
- Eval Retry: Initialize model usage from usage recorded in retried eval log.
- Anthropic: Use service model name when detecting tool compatibility.
- Google: Various mitigations for Gemini returning MALFORMED_FUNCTION_CALL.
- OpenRouter: Improved integration with `reasoning_details` (map onto standard reasoning fields for viewer).
- Human CLI Agent: Ability to add custom instructions and .bashrc commands to agent shell.
- Properly handle working time reporting for overlapping coroutines waiting on semaphores.
- Eval Logs: Support reading from `IO[bytes]` via `read_eval_log()`.
- Inspect View: Properly display dict scores in sample list.
- Inspect View: Improve display of Codex `shell_command` tool calls.
- Inspect View: Improve the display of very wide metrics results in the results dialog.

## 0.3.158 (24 December 2025)

- [skill()](https://inspect.aisi.org.uk/tools-standard.html#sec-skill) tool to make agent skills available to models.
- Bugfix: Fix log file cache lookup using incorrect comparison key.

## 0.3.157 (22 December 2025)

- Eval Set: Correct log reuse behavior when epochs and limit change.
- Solvers: Capture all parameters (including defaults) used to create solvers and agents.
- Tasks: Improved validation of Hugging Face Hub task definitions.
- HF Inference Providers: Specify "strict" for function tool definitions.
- Agent API: Improved capture of agent name with nested @agent decorators.
- Agent Bridge: Ensure that OpenAI responses params have an "id" field before validation.
- Sandbox Service: Continue with warning if request polling raises a `RuntimeError`.

## 0.3.156 (20 December 2025)

- Anthropic: Treat reasoning text as a summary (true for all models after Sonnet 3.7).
- Open AI: Remove custom transport to respect HTTP proxy settings.
- Bedrock: Handle additional Converse stop reasons (improved context overflow detection).
- OpenRouter: Handle `reasoning_details` field to forward native reasoning replay to models.
- Reasoning: Include reasoning `summary` in serialization for agent bridge.
- Agent API: Correctly handle `@agent` functions with no return type decoration.
- ReAct Agent: Add `retry_refusals` option to retry on stop_reason == "content_filter".
- Eval Log: Include sample `choices` in `EvalSampleSummary`.
- Inspect View: Add "robots" meta tag with "noindex,noai,noimageai".
- Inspect View: Enhance `inspect view bundle` to publish `hf/` prefixed targets to Hugging Face Spaces.
- Inspect View: Improve rendering of Open Router reaasoning blocks.
- Inspect View: Correct the filter type for `Log File` column of the samples list.
- Bugfix: Only use Anthropic computer_20251124 tool for Claude Opus 4.5 (not all Claude 4.5 models).
- Bugfix: Only use OpenAI computer_use_preview tool for models with "computer-use-preview" in name.
- Bugfix: Expand allowable JSONSchema `type` field to enable lists of types.

## 0.3.155 (16 December 2025)

- Eval Set: Defer reading eval samples until they are actually needed (prevents memory overload for large logs being retried).
- Anthropic: Support for inference on Azure Foundry (`anthropic/azure`).
- Grok: Don't use streaming responses by default (enable explicitly with `-M streaming=true`).
- Logging: Optimize snapshots for track_store_changes and state_jsonable.
- Improve granulaity of working time tracking (report working time immediately on outer retry rather than waiting for generate to succeed).
- Inspect View: Display timestamp in sample limit events tooltip.
- Inspect View: Fix issue where stale log files could be displayed in static deployments of the viewer.
- Inspect View: Fix issue where switching away from Viewer in VSCode could cause an error when returning to the viewer tab.
- Inspect View: Tasks filter split as into per-column filters. Option to display scorer columns in Choose Columns popover.

## 0.3.154 (14 December 2025)

- [Early Stopping](https://inspect.aisi.org.uk/early-stopping.html.md) API for ending tasks early based on previously scored samples.
- Logging: Support for writing logs to Azure Blob Storage (`az://`).
- Tasks: Ability to run Inspect tasks defined within datasets on [Hugging Face Hub](https://inspect.aisi.org.uk/tasks.html#hugging-face).
- Sample invalidation which enables marking samples as invalid (forcing a retry in eval sets).
- Tasks: Run `cleanup()` function at the end of the sample (after scoring) rather than after solvers.
- Grok: Option to disable GRPC retries (`disable_retry`) for waiting time tracking.
- OpenAI: Added support for `--verbosity` generation option.
- OpenAI: Added support for "xhigh" `reasoning_effort` option.
- OpenAI: Support `temperature`, `top_p`, and `logprobs` for GPT 5.x models with reasoning disabled.
- OpenAI: Tolerate missing "detail" field for image urls.
- Google: Include request content when printing 400 errors.
- HF Inference Providers: Streaming for chat completion requests (enabled by default, use `-M stream=false` to disable).
- OpenAI Compatible: Added support for `stream` option (disabled by default, use `-M stream=true` to enable).
- Agent Bridge: `model` option is now used only as a fallback if the request model is not for "inspect" or "inspect/*".
- React Agent: Remove newlines from default prompts.
- Human Agent: Support for non-scalar values returned from intermediate scoring.
- Request tracking: Log warning rather than raise error for unexpected hook states.
- Inspect View: Print IP address of remote server when binding to 0.0.0.0.
- Computer Tool: Add computer use tool version support for Claude Opus 4.5.
- Computer Tool: Auto-acknowledge OpenAI computer tool safety checks.
- Bugfix: Copy `metadata` field to new eval for `eval-retry`.
- Bugfix: Retry when parsing an incomplete bridged tool call response.
- Bugfix: Delay after launching bridged tool service to prevent asyncio race condition.

## 0.3.153 (05 December 2025)

- Agent Bridge: Don't print serialization warnings when going from Pydantic -> JSON (as we use beta types that can cause warnings even though serialization works as intended).
- Batch Processing: Enable customizing of batch status rendering.
- Inspect View: Expand dictionary scores into separate scores when viewing samples.

## 0.3.152 (04 December 2025)

- [Update Plan](https://inspect.aisi.org.uk/tools-standard.html#sec-update-plan) tool for tracking steps and progress across longer horizon tasks.
- [Code Execution](https://inspect.aisi.org.uk/tools-standard.html#sec-code-execution) tool for executing Python code in a stateless sandbox running on model provider servers. 
- Anthropic: Support for new [Effort](https://platform.claude.com/docs/en/build-with-claude/effort) setting (`--effort`) for trading off between response thoroughness and token efficiency. 
- Anthropic: Include native `web_fetch` tool as part of `web_search()` implementation (matching capability of other providers that have native web search).
- Anthropic: Use required `caller` field for server tool uses (required by package version 0.75, which is now the minimum version).
- OpenAI: Check for mismatches between specified model and Azure deployment URL.
- Mistral: Use the new Conversation API by default (disable with `-M conversation_api=False`).
- Mistral: Added support for native web_search and code_execution tools (executed server side).
- Mistral: Added support for document input.
- Grok: Support for server-side MCP tool calling.
- VLLM and SGLang: Default to 5 second retry policy when server rejects requests due to saturated GPU (customize with model arg `retry_delay`).
- Model API: Assign new message ID when combining messages for replay to providers.
- MCP Tools Bridge: Added `BridgedToolsSpec` and `bridged_tools` parameter to `sandbox_agent_bridge()` for exposing host-side Inspect tools to sandboxed agents via MCP protocol.
- Analysis: Support passing `EvalLog` objects directly to dataframe functions (`samples_df()`, `evals_df()`, `messages_df()`, `events_df()`).
- Dependencies: Update to `mcp` package version 1.23.0.
- Inspect View: Fix regression where the display of samples with errors would result in unusuably wide sample list view.
- Inspect View: Properly compute sample list columns for running evaluations that return dictionary scores.
- Bugfix: Ensure that entry points are not scanned repeatedly when there are no targets.

## 0.3.151 (30 November 2025)

- Memory tool: Added [memory()](https://inspect.aisi.org.uk/tools-standard.html#sec-memory) tool and bound it to native definitions for providers that support it (currently only Anthropic).
- Grok: Correctly reconstruct assistant tool calls when replaying messages to API.
- Grok: Round trip encrypted reasoning (made available in v1.4.0 of `xai_sdk`, which is now required).
- Anthropic: Protect against signature not being replayed (can occur for agent bridge) by saving a side list of signatures.
- Sandboxes: For "local" and "docker" sandbox providers, treat `output_limit` as a cap enforced with a circular buffer (rather than a limit that results in killing the process and raising).
- Sandboxes: Added `evals_in_eval` example for running Inspect evaluations inside other evaluations.
- Model API: Enable model providers to have custom retry wait strategies (use 5 second fixed wait for vllm).
- Prevent querying of local timezone and forbid naïve `datetime`'s via DTZ lint rule. 
- Dependencies: Change jsonpath-ng requirement to >=1.6.0 (formerly required >= 1.7.0).
- Dependencies: Move from unmaintained `nest_asyncio`, which is fundamentally incompatible with Python 3.14, to `nest_asyncio2`, which has explicit 3.14 compatibility.
- Inspect View: Improve markdown rendering performance.
- Inspect View: Reduce use of virtualized display for smaller transcripts and message lists.
- Inspect View: Add support for copying sample messages (as text).
- Inspect View: Improved JSON parsing performance & scalability.
- Bugfix: Correct normalization of sample id for `read_eval_log()` with JSON log files.
- Bugfix: Correctly handle more complex list operations when detecting changes in state and store.

## 0.3.150 (25 November 2025)

- Anthropic: Enable [interleaved-thinking](https://platform.claude.com/docs/en/build-with-claude/extended-thinking#interleaved-thinking) by default for Claude 4 models.
- Anthropic: Smarter `max_tokens` handling to prevent exceeding model max tokens when reasoning tokens are specified. 
- OpenAI: Limit reasoning summary capability probe to 1 request.
- Google: Attach thought signature to first function call, even if a message also has text.
- Grok: Correctly handle web_search tool intermixed with other tool types.
- OpenRouter: Pass reasoning_effort = "none" through to models rather enabled=False.
- Model API: Conversion functions for translating raw model input and output into Inspect types.
- Hooks: Ensure that on_sample_start and on_sample_end are called on the same coroutine.
- Registry: Add `RegistryInfo` and `registry_info()` to the public API. 
- Bugfix: Ensure that `prompt_cache_retention` is correctly forwarded by agent bridge to responses API.

## 0.3.149 (23 November 2025)

- Inspect View: Truncate display of large sample summary fields to improve performance.
- Inspect View: Fix regression in displaying S3 log files in VS Code.
- Bugfix: Truncate large target fields in sample summaries.

## 0.3.148 (21 November 2025)

- Bugfix: Fix Google provider serialization of thought signatures on replay.

## 0.3.147 (21 November 2025)

- Google: Support for `--reasoning-effort` on Gemini 3.0 models.
- Anthropic: Support for [Structured Output](https://inspect.aisi.org.uk/structured.html) for Sonnet 4.5 and Opus 4.1.
- Anthropic: Don't insert "(no content)" when replaying empty assistant messages with tool calls.
- OpenAI: Don't remove consecutive reasoning blocks (earlier versions of the API would give 400 errors, this no longer occurs).
- OpenAI: Add `prompt_cache_retention` custom model arg (bump required version of `openai` package to v2.8.0).
- Eval Set: Task identifiers can now vary on `model_args` (which enables sweeping over these variables).
- Eval Logs: Compatibility with Hugging Face filesystem (hf://).
- Eval Logs: Don't forward credentials when using aioboto3 with S3 (was preventing use of AWS credential chain).
- Inspect View: Streaming for log bytes requests in fastapi view server.
- Bugfix: Fix incorrect approver behavior with multiple tool calls
- Bugfix: Correctly handle distinguishing eval set tasks based on `solver` passed to `eval_set()`.

## 0.3.146 (15 November 2025)

- Added `cache` configuration to `GenerateConfig` (formerly was only available as a parameter to `generate()`).
- ReAct agent: `on_continue` can now return a new `AgentState`.
- OpenAI: Retries for `APIConnectionError`.
- OpenAI: Support for `reasoning_effort="none"` (now available with gpt-5.1).
- Grok: Retries for 520 (UNKNOWN) errors.
- Bugfix: Properly load scorer metrics when using solver scoring.
- Bugfix: Properly handle `None` as value of `arguments` when parsing tool calls.
- Bugfix: Fix sandbox tools install for sandbox envs with non-root default user.
- Bugfix: Fix model name preservation in eval logs for service-prefixed models.

## 0.3.145 (09 November 2025)

- OpenAI: Show reasoning summaries by default (auto-detect whether current account is capable of reasoning summaries and fallback as required).
- OpenAI: Support for `logprobs` and `top_logprobs` in Responses API (note that logprobs are not supported for reasoning models).
- Grok: Updated provider implementation using `xai_sdk` package (rather than using OpenAI compatible endpoint).
- Grok: Support for server-side `web_search()` tool.
- Grok: Support for generating structured outputs (outputs constrained by JSON Schema).
- OpenRouter: Add `reasoning_enabled` model arg to optionally disable reasoning for hybrid models.
- Eval Set: Enable optional explicit specification of `eval_set_id` 
- Bugfix: Properly handle `content` of type `str` in Responses API agent bridge.

## 0.3.144 (05 November 2025)

- Eval Set: Task identifiers can now vary on `GenerateConfig` and `solver` (which enables sweeping over these variables).
- Eval Logs: Don't resolve attachments within `ModelEvent.call` by default, which prevents O(N) memory footprint for reading transcripts.
- OpenAI: Update for typing change to `ResponseOutputText` in v2.7.0 of `openai` package.
- Grok: Correct handling of `reasoning_effort` parameter (only supported by `grok-3-mini` and only `low` and `high`values are supported).
- Inspect View: Fixed theming issue with the score selector control in VS Code.
- Inspect View: Improve display of grouped metrics
- Inspect View: Don't render markdown images in the sample list input, target, or answer.
- Inspect View: Add Copy UUID button to sample toolbar.
- Inspect View: Add new samples view which displays a grid of all samples within a given folder of tasks (recursively).
- Inspect View: Invalidate client side caches for updates to statically deployed versions of the viewer.
- Inspect View: Fix flash of error that can occur when viewing folders with no eval-set info in statically deployed versions of the viewer.

## 0.3.143 (29 October 2025)

- Google: Correct capture and playback of `thought_signature` in `ContentReasoning` blocks.
- Anthropic: Set 4k as default max_token limit for Claude 3.5 (same as Claude 3.0).
- Scoring: Support for using `@scanner` functions as scorers.
- Bugfix: Prevent condensing of model event `output` during execution (only condense `call`).
- Bugfix: Defer binding of default value for `logs` in data frame functions.

## 0.3.142 (27 October 2025)

- Google: Distribute citations from web search to individual ContentText parts (rather than concatenating into a single part).
- Google: Support options (time interval) for Gemini Web Search.
- Inspect View: Fix performance regression when loading a log view from an S3 bucket.
- Inspect View: Fix flash of 'No events' message when loading sample transcripts.

## 0.3.141 (27 October 2025)

- OpenAI: Use `responses_store=false` by default (handling reasoning via the "reasoning.encrypted_content" include option).
- OpenAI: Don't include "metadata" extra body parameter when `responses_store` is False.
- Anthropic: Increase default `max_tokens` to 32,000 for Claude 4 models.
- OpenRouter: Classify `JSONDecodeError` as a retry-able infrastructure error.
- Remove Goodfire model provider (as the goodfire package has been archived/deprecated).
- Eval logs: Track dirty working tree state in `EvalRevision` (includes `dirty` field indicating uncommitted changes or untracked files at eval time).
- Inspect View: Display copy button for model events api request and response JSON.
- Inspect View: Support selecting multiple scorers for display in the sample list.
- Inspect View: Show multiple scores in sample view.
- Inspect View: Fix issue where samples would jump around when viewing running evals with high concurrency.
- Inspect View: Improve log and sample list performance by adding a persistent local cache.
- Inspect View: Display a message when there are no events to display in a transcript.
- Bugfix: Correctly resolve relative sandbox config paths in `eval-retry` when CWD differs from task directory.
- Bugfix: Don't check working time limit when there is a model generation in flight.
- Bugfix: Fix broken Pydantic @model_validator's that assumed the input was a dict.
- Bugfix: Fix `run_coroutine` to exit internal catch handler before running the coroutine.

## 0.3.140 (20 October 2025)

- Tests: Skip git revision detection and realtime logging during pytest runs to improve test performance.
- Inspect View: Fix regression that resulted in an error when displaying JSON log files.

## 0.3.139 (18 October 2025)

- OpenAI: Handle `Message` input types that have no `"type"` field in responses API.
- Google: Improve model API call diagnostics to accurately reflect request body sent by the Python client.
- Model API: Support for refreshing API keys during long-running evaluations via the `override_api_key()` hook.
- Datasets: Use readahead content caching by default for reading CSV and JSON datasets from S3.
- Datasets: Enable json dataset reader to support `dict` as well as `list` for underlying data.
- Inspect View: Improve the display of grouped metrics.
- Bugfix: Fix `edit_score()` silently editing only first epoch in multi-epoch evaluations (now requires explicit `epoch` parameter).
- Bugfix: Fix errors that could occur when re-scoring with duplicated scorer names.
- Bugfix: Fix regression in running samples display resulting from condensing model event messages.

## 0.3.138 (16 October 2025)

- Added model API for [Hugging Face Inference Providers](https://inspect.aisi.org.uk/providers.html#hugging-face-inference-providers).
- Agent bridge: Support for OpenAI 'custom' tools (required by Codex apply_patch tool).
- Agent bridge: New `messages_to_openai_responses()` function.
- OpenAI: Use background processing for `gpt-5-pro` by default.
- OpenAI: Use "developer" role for system messages for all models (formerly was only o-series and gpt5).
- Anthropic: Support `parallel_tool_calls` option for tool choice.
- Google: Enable support for `logprobs` and `top_logprobs`.
- Groq: Update "model_length" stop reason detection for latest way of reporting bad requests.
- Bedrock: Detect `model_length` stop reason based on additional error pattern.
- Bedrock: Ensure that list of `content` can never be empty.
- VLLM: Catch additional model_length stop reasons.
- Scoring: New `edit_score()` and `recompute_metrics()` functions for modifying evaluation scores with provenance tracking and metric recomputation.
- Scoring: When re-scoring an eval, use the correct sample uuid in TaskState.
- Scoring: Periodically flush samples when scoring with streaming enabled.
- Model API: Added `attempt_timeout` to `GenerateConfig` (governs timeout for individual attempts and still retries if timeout is exceeded).
- Analysis: Handle string columns which exceed the pyarrow 2GB limit (convert to large_string).
- Logging: Condense `ModelEvent` immediately to prevent O(N) memory usage for long message histories.
- Adjust terminal progress display to accommodate longer task names.
- Inspect View: Properly display task error when a task error is present in the log file.
- Inspect View: Improve display of running eval sets (correct duplicate files and incorrect progress display).
- Inspect View: Provide option to run `inspect view` server using uvicorn / fastapi.
- Python Versions: Use explicit `Union` for `TypeAlias` (required by Python 3.14).
- Bugfix: Fix improperly scoped use of restrictive `umask` that led to permission problems with `bash_session` tool.
- Bugfix: Ensure that init span is always cleaned up even when sandbox init fails.
- Bugfix: Ensure that calls to generate always sync the cache state to the current sample's epoch.
- Bugfix: Don't use default values for `list` and `dict` parameters (rather use `None` and initialize on use).
- Bugfix: When reading log files, tolerate `SubtaskEvent.input` values that aren't of the required `dict` type.

## 0.3.137 (07 October 2025)

- OpenAI: Support for tool calls returning images (requires v2.0 of `openai` package, which is now required).
- Anthropic: Retry requests that get an error body payload with 'internal server error'
- Agents: Improve overload return value typing for agent `run()` function.
- Task display: Improved reporting of errors that occur during log initialization.
- Event API: Created new `inspect_ai.event` module with event related tyeps and functions.
- Model API: Use context var for managing background task group.
- Model API: Add canonical model naming for consistent querying across service routing prefixes (vertex/, azure/, bedrock/).
- Inspect View: Properly truncate sample input and and target (in sample header) even when it contains large pre-formatted text blocks.
- Dependencies: Update to fsspec 2025.9.0 to match upper bound of HF datasets.
- Dependencies: Allow any version of `rich` > 13.3.3 save for 14.0.0 (which had an infinite recursion bug affecting stack traces with exception groups).
- Dependencies: Unpin textual dependency (was <= 4.0.0 is now >=2.1.0) as we have mitigated layout issue we saw in 4.0.0.
- Bugfix: Honor `resolve_attachments` in score command when `stream=True`.
- Bugfix: Allow cancellation errors to propagate when `fail_on_error=False`.
- Bugfix: text_editor tool now supports relative file paths.
- Bugfix: Fix crash when determining tool_param based on type hint of Any in Python 3.10 w/Pydantic 2.12.0.

## 0.3.136 (02 October 2025)

- Google: Manage Google client lifetime to scope of call to `generate()`.
- Eval logs: Add message count tracking to evaluation logs for quick analysis without loading full samples.
- Scoring: Fix regression in `inspect score` command (and `inspect_score` function) when scoring log files on S3.
- Inspect View: Improve display of OpenAI Codex tool calls in transcript and messages.
- Inspect View: Display eval set progress in the lower right corner of the log list.
- Inspect View: Make message and event link affordances slightly more discoverable.
- Inspect View: Preserve query parameters in log viewer URLs when copying links.
- Inspect View: Fix issue where sometimes the incorrect log is displayed when new logs are added to a log directory while viewing a log.

## 0.3.135 (29 September 2025)

- OpenAI: Capture reasoning summaries even when there is encrypted reasoning content.
- Anthropic: Update text editor tool detection to support latest text editor tool for Claude Sonnet 4.5.
- Inspect View: Improve rendering for Codex CLI shell tool output.

## 0.3.134 (27 September 2025)

- Agent bridge: Enable bridge filters to modify generation inputs (messages, tools, config, etc.).
- Agent bridge: Ensure that bridge filters also take advantage of `retry_refusals` loop.
- Agent bridge: Workaround Codex CLI not passing `detail` along with images.
- OpenAI: Automatically switch to the completions API when `--num-choices` is specified.
- Model APIs: Improve legibility/clarify of error messages when updated versions of anthropic or openai packages are required.
- Dataframes: Added `SampleScores` column group for extracting score answer, explanation, and metadata.
- Sandbox tools: Rewrite `inspect-ai` package installation type detection code.
- Task: Support mixed metrics (both direct metrics and dict groupings in the same list), matching the flexibility of the @scorer decorator.
- Inspect View: Fix regression sorting folder and logs in list (folders should sort to the front of the list)
- Inspect View: Properly reset page when navigating between folders.
- Inspect View: Always show reasoning blocks (previously we hid them when there was no content, i.e. Responses API store=True).
- Inspect View: Improve the display of Codex Agent `update_plan` and `shell` tool inputs.
- Inspect View: Fix flash of error message when initially viewing a log file in VS Code.
- Inspect View: Properly create tree for transcripts when tasks include async work generating spans and events.
- Bugfix: Properly deserialize `EvalSet` when optional values are missing.
- Bugfix: Fix "auto" message truncation in react agent.
- Bugfix: Update various tests to react to Google's deprecation of old models.

## 0.3.133 (22 September 2025)

- Sandbox tools: bash_session, text_editor, and sandbox MCP servers no longer require a separate pipx install (they are now automatically injected into sandbox as a static binary with no Python dependencies).
- Agent bridge: Python is no longer required within containers using the sandbox agent bridge.
- Agent bridge: Enhance automatic state tracking by ignoring shorter sub-agent generations.
- Agent bridge: Add `retry_refusals` option for automatically retrying refusals a set number of times.
- Eval logs: Option to resolve attachments for `convert_eval_logs()`.
- Eval logs: Option to stream processing for `convert_eval_logs()`.
- Google: Support disabling thinking for Gemini 2.5 Flash (warn if thinking is disabled for 2.5-Pro which doesn't support disabling thinking).
- Bedrock: Support for reasoning content in Bedrock models.
- Model grading: `model_graded_qa()`, `model_graded_fact()`) now look for the "grader" model-role by default.
- Human agent: Enable installation even when default tool user is not root.
- Hooks: Added `on_sample_scoring()` and `on_model_cache_usage()` hooks.
- Hooks: Propagate LimitExceededError so that hooks can raise limit errors.
- Hooks: Emit `on_run_end()` even when the eval is cancelled.
- Scoring: Allow scorers to return `None` to indicate that they did not score the sample. Such samples are excluded from reductions and metrics.
- Scoring: Resolve task metrics on to scores returned by solvers.
- Scoring: Use `Sequence` and `Mapping` types for metrics on scorer decorator.
- Scoring: Properly make sample events available in the transcript during re-scoring an eval log.
- Inspect View: Display pending tasks in eval sets (tasks that have not yet started running)
- Inspect View: Fine tune status appearance to improve legibility
- Inspect View: Fix issue displaying folders with with overlapping path prefixes.
- Bugfix: Fix Google Gemini 2.5 function calling configuration error when using native search tools.
- Bugfix: Enable passing no reducers to `async_score` in eval score.
- Bugfix: Handle non-contiguous task sequences in task batching.

## 0.3.132 (12 September 2025)

- Anthropic: Support for images with mime type image/bmp.
- Sandbox Service: Specify instance externally so a single script can service multiple instances.
- Agent Bridge: Capture message history in agent state for all bridge generations.
- Agent Bridge: Embed sandbox service client in sandbox bridge proxy (for ease of bundling).
- Agent Bridge: Respect `store=False` from bridge client and don't insist on `id` being included with reasoning (as it is not returned in `store=False` mode).
- Sandboxes: Add Sandbox Injection API for Dynamic Environment Setup.
- Scoring: Resolve task or eval level metrics onto scorers immediately rather than waiting until scoring.
- Logging: Flush log more frequently for very small numbers of samples.
- Model Roles: Support specifying model roles on the CLI with config and model args (via YAML or JSON).
- Inspect View: Add support for cmd + arrow up/down to navigate the samples list.
- Inspect View: Improve scroll keyboard handling in sample transcript view.
- Inspect View: Improve scroll keyboard handling in sample messages view.
- Inspect View: Improve find support within sample list, transcript, and messages.
- Inspect View: Fix issue that would result in `attachments:/` appearing in content when viewing running samples.
- Bugfix: Fix file info on filesystem without mtime.
- Bugfix: Correct rendering of tool call errors in running samples transcript.
- Bugfix: Use AzureAI token provider even when no API key is available.
- Bugfix: Ensure that assistant content without reasoning is always passed to responses API.
  
## 0.3.131 (08 September 2025)

- OpenAI: Correct serialization of web search tool calls (prevent 400 errors).

## 0.3.130 (06 September 2025)

- Agent Bridge: Option to force the sandbox agent bridge to use a specific model.
- Agent Bridge: New `filter` option to enable bridge to filter model generate calls.
- Agent Bridge: Ensure that Anthropic can't yield an empty system parameter.
- Agent Bridge: Increase polling interval for sandbox agent bridge to 2 seconds (was 0.2 seconds).
- OpenAI Compatible: Add support for using Responses API via `responses_api` model arg.
- Eval Set: Enable running additional epochs against an already completed eval set.
- Eval Set: Add `eval_set_id` to log file (unique id for eval set across invocations for the same `log_dir`).
- Eval Retry: Use the same `log_format` as the log which is being retried.
- Task Display: Render tool outputs based on model events rather than tool events (compatible w/ external tool calling e.g. for agent bridge).
- Sandbox Service: Don't emit sandbox events for sandbox service RPC calls.
- Hooks: New `EvalSetStart` and `EvalSetEnd` hook methods.
- Scoring: `inspect score` now supports streaming via the `--stream` argument.
- Inspect View: Starting the view server with a path to a specific log file will automatically open that log file (if it exists) rather than showing the log list.
- Inspect View: Improve sample scoring detail layout
- Inspect View: Reduce h1-h6 heading sizes
- Inspect View: Fix error that caused 'json too large' message to appear incorrectly for sample JSON.
- Inspect View: Improve filtering of log files in log list (improve performance and loading progress).
- Inspect View: Add cmd+F shortcut for filtering log in log list.
- Inspect View: Fix regression in tool input syntax highlighting.
- Inspect View: Focus transcript or messages when sample dialog is loaded, allowing use of keyboard shortcuts like cmd + arrow down for scrolling.
- Inspect View: Focus log list when the log list is shown, allowing use of keyboard shortcuts like cmd + F.
- Bugfix: Ensure ETags always match content when reading S3 logs to prevent write conflicts.

## 0.3.129 (03 September 2025)

- Agent Bridge: Don't use `concurrency()` for agent bridge interactions (not required for long-running proxy server or cheap polling requests).
- Sandboxes: Add `concurrency` parameter to `exec()` to advise whether the execution should be subject to local process concurrency limits.

## 0.3.128 (02 September 2025)

- Agent Bridge: Correctly dispatch LimitExceededError which occurs during proxied model calls.
- Agent Bridge: Respect reference vs. value semantics of agent caller (enables preservation of messages when agent is run via `as_solver()`).
- OpenAI: Update types to match `openai` v1.104.1 (which is now the minimum required version).
- Mistral: Support for updated use of `ThinkChunk` types in mistralai v1.9.10.
- Groq: Support for `--reasoning-effort` parameter (works w/ gpt-oss models).
- Scoring: Use fallback unicode numeric string parser when default `str_to_float()` fails.
- Bugfix: Work around OpenAI breaking change that renamed "find" web search action to "find_in_page" (bump required version of `openai` package to v1.104.0).

## 0.3.127 (01 September 2025)

- Bugfix: Preserve sample list state (e.g. scroll position, selection) across sample open/close.

## 0.3.126 (01 September 2025)

- Agent Bridge: OpenAI Responses API and Anthropic API are now supported alongside the OpenAI Completions API for both in-process and sandbox-based agent bridges.
- Agent Bridge: Bridge can now automatically keep track of `AgentState` changes via inspecting model traffic running over the bridge.
- Agent Bridge: Improved id stability across generations to prevent duplicated messages in `messages_df()`.
- Agent Bridge: Ensure that explicitly specified `GenerateConfig` values for models override bridged agent config.
- Agent `handoff()`: Use `content_only()` filter by default for handoff output and improve detection of new content from handed off to agents. 
- Model API: Refine available tool types for `ContentToolUse` ("web_search" or "mcp_call")
- Model API: Remove `internal` field from `ChatMessageBase` (no longer used).
- OpenAI: Added `responses_store` model arg for explicitly enabling or disabling the responses API.
- Google: Pass tool parameter descriptions for nullable and `enum` typed fields.
- Google: Support `thought_signature` for thought parts.
- Google: Use role="user" for tool call results rather than role="function".
- MCP: Export MCP server configuration types (`MCPServerConfig` and Stdio and HTTP variants).
- Sandbox Service: New `instance` option for multiple services of the same type in a single container.
- Sandbox Service: New `polling_interval` option for controlling polling interval from sandbox to scaffold (defaults to 2 seconds, overridden to 0.2 seconds for Docker sandbox).
- ReAct Agent: Add submit tool content to assistant message (in addition to setting the `completion`).
- Metrics: Compute metrics when an empty list of reducers is provided (do not reduce the scores before computing metrics). Add `--no-epochs-reducer` CLI flag for specifying no reducers.
- Scoring: Make `match` more lenient when numeric matches container markdown formatting.
- Concurrency: Add `visible` option for `concurrency()` contexts to control display in status bar.
- Inspect View: Add support for filtering sample transcripts by event types. Be default, filter out `sample_init`, `sandbox`, `store`, and `state` events.
- Inspect View: Add support for displaying raw markdown source when viewing sample data.
- Inspect View: Remove sample list / title content when sample is displaying (prevents find from matching content behind the sample detail).
- Inspect View: Custom rendering for TodoWrite tool calls.
- Bugfix: Fix error in reducing scores when all scores for a sample are NaN.
- Bugfix: Correctly extract authorization token from header in MCP remote server config.

## 0.3.125 (25 August 2025)

- Scoring: Refactor `inspect score` to call same underlying code as `score()`.
- Bugfix: Fix regression in CLI scoring.

## 0.3.124 (24 August 2025)

- Agent Bridge: New context-manager based `agent_bridge()` that replaces the deprecated `bridge()` function.
- Agent Bridge: `sandbox_agent_bridge()` to integrate with CLI based agents running inside sandboxes.
- Agent Bridge: Inspect model roles can now be addressed by bridged agents (e.g. "inspect/red-team").
- ReAct Agent: Allow for a ToolDef to be passed to an AgentSubmit type.
- Model API: `user_prompt()` function for getting the last user message from a list of messages.
- Model API: `messages_to_openai()` and `messages_from_openai()` functions for converting to and from OpenAI-style message dicts.
- Groq: Support `response_schema` option for providing a JSON schema for model output.
- VLLM: Allow specifying the port when starting up a new vllm server.
- Eval Log: For sample summaries, preserve all sample and score fields that are less than 1k in size.
- CLI: Yield error exit code (1) if no tasks to evaluate are found at the specified path.
- Eval Set: You can now run eval sets in log dirs containing unrelated eval log files using the `--log-dir-allow-dirty` option.
- Add `--continue-on-fail` option for `eval()` and `eval_set()`.
- Scoring: Add `copy` option to `score_async()` (defaults to `True`) to control whether the log is deep copied before scoring.
- Inspect View: Convert samples in the sample list to use simple a tags for navigation. This allows typical user gestures like cmd+click to work correctly.
- Inspect View: Update document titles when viewing a sample, log, or log dir to better disambiguate tabs or windows. Use reverse pyramid to place details at the head of the title.
- Inspect View: Increase sample size limit to 100MB (samples larger than that are not browsable in the viewer).
- Tool Support: Converted to a new runtime reconnaissance and injection architecture for `inspect_tool_support`. 
- Bugifx: Properly handle surrogates in JSON serialization.
- Bugfix: Google and Mistral providers now generate unique tool call IDs to prevent collisions when calling the same tool multiple times.
- Bugfix: Enable use of custom reducers with `eval-retry` by delaying their creation until after task creation.
- Bugfix: Fix custom json schema generation code for `CitationBase` so that it no longer leads to an invalid schema.
- Bugfix: Only pass `background` to OpenAI Responses if specified.
- Bugfix: Do not pass unsupported `tool_choice` to Anthropic thinking models.

## 0.3.123 (16 August 2025)

- Support for [PDF input](https://inspect.aisi.org.uk/multimodal.html#pdf) for OpenAI, Anthropic, and Google via new `ContentDocument` type.
- MCP: Use [Remote MCP Servers](https://inspect.aisi.org.uk/tools-mcp.html#remote-mcp) with OpenAI and Anthropic models.
- OpenAI: Use types from latest SDK (v1.99.7) and make that the minimum required version of the `openai` package.
- OpenAI: Automatically use background-mode for deep research models.
- Anthropic: Automatically use streaming when `max_tokens` is 8k or higher.
- Anthropic: Improved retry behavior via detection of more "overloaded" error conditions.
- Anthropic: Add `betas` custom model arg (`-M`) for opting in to beta features.
- Scoring: NaN values returned from scorers will be excluded from reductions when reducing epochs.
- Scoring: String to float conversion now extracts the first valid float from the string (ignoring trailing characters that are invalid for floats).
- Scoring: Provide access to `sample_limits()` within scorers.
- Prepare: Added `score_to_float()` function for converting score columns to float values.
- Eval logs: Add `if_match_etag` parameter for `write_eval_log()` and `etag` field to `EvalLog` for safe concurrent log modification.
- ModelOutput: Setting the `completion` property now does not affect the underlying `message` content.
- Inspect View: Improved handling of scores and messages with large or complex metadata.
- Inspect View: Web search and other server-side tool calls (e.g. remote MCP) are now shown in the transcript.
- Inspect View: Properly display scores with list values.
- Tests: Added @flaky_retry(max_retries=) decorator for necessarily flaky tests.
- Bugfix: Don't inspect stack in `span()` function until required for logging.

## 0.3.122 (11 August 2025)

- OpenAI: Enable native `web_search()` tool for GPT-5.
- OpenAI: Convert "web_search" tool choice to native "web_search_preview" type.
- Apply `sample_shuffle` for eval retry.

## 0.3.121 (10 August 2025)

- [SambaNova](https://inspect.aisi.org.uk/providers.html#sambanova) model provider.
- [Goodfire](https://inspect.aisi.org.uk/providers.html#goodfire) model provider.
- Google: Pass `timeout` generation config option through to API `Client`.
- Google: Ability to specify a custom `GOOGLE_VERTEX_BASE_URL`.
- OpenAI: Add `background`, `safety_identifier` and `prompt_cache_key` custom model args (bump required version of `openai` package to v1.98).
- OpenAI: Set `client_timeout` to 900s when flex processing is enabled.
- Ollama: Forward `reasoning_effort` option to `reasoning` dict.
- MCP: Support for `mcp_server_http()` (which replaces the deprecated SSE server mode).
- MCP: Added `authorization` to provide OAuth Bearer token for HTTP based servers.
- Task display: Sample cancel button now works immediately (no longer needs to wait for a cooperative check).
- Limits: Sample working limit is now enforced even during long running generations and sandbox operations.
- Store: Support for serializing complex nested types (e.g. to read in an offline scorer).
- Tools: Code viewer now handles function calls with `list[str]` rather than `str` without crashing.
- Basic Agent: Only set `message_limit` to 50 when both `message_limit` and `token_limit` are `None`.
- Tests: Improve sandbox self_check to handle test failure via `with pytest.raises`, add test for env vars.
- Tests: Improve sandbox self_check to handle test failure via `with pytest.raises`, add test for env vars.
- Tests: Added the ability to provide a generator like callback function for `MockLLM`.
- Scoring: Improve multiple_choice answer parsing, making it more strict in interpreting answers like `ANSWER: None of the above`. Allow answers to end with full stop (`.`).
- Tool Support: Converted `inspect_tool_support` to use a Unix socket rather than a tcp port for intra-container RPC. 
- Bugfix: `background()` task is now scoped to the sample lifetime in the presence of `retry_on_error`.
- Bugfix: Correct recording of `waiting_time` from within coroutines spawned from the main sample coroutine.
- Bugfix: Update `inspect-tool-support` reference container to support executing tool code with non-root accounts.
- Bugfix: Correct forwarding of `reasoning_effort` and `reasoning_tokens` for OpenRouter provider.
- Bugfix: `bridge()` no longer causes a recursion error when running a large number of samples with openai models
- Bugfix: Ensure that `model_roles` are available within task initialization code.

## 0.3.120 (07 August 2025)

- OpenAI: Update model version checks for GPT-5.
- OpenAI: Support for specifying "minimal" for `reasoning_effort`.
- Bugfix: Conform to breaking changes in `openai` package (1.99.2).
- Bugfix: Ensure that `sample_shuffle` is `None` (rather than 0) when not specified on the command line.

## 0.3.119 (04 August 2025)

- Analysis functions are out of beta (`inspect_ai.analysis.beta` is deprecated in favor of `inspect_ai.analysis`).
- Scoring: Provide access to sample `store` for scorers run on existing log files.

## 0.3.118 (02 August 2025)

- Remove support for `vertex` provider as the google-cloud-aiplatform package has [deprecated](https://pypi.org/project/google-cloud-aiplatform/) its support for Vertex generative models. Vertex can still be used via the native `google` and `anthropic` providers.
- Tool calling: Added support for emulated tool calling (`emulate_tools` model arg) to OpenAI API compatible providers.
- Task display: Improved display for multiple scorers/metrics in task results summary.
- Scoring: Improved error message for scorers missing a return type annotation.
- Datasets: Added `--sample-shuffle` eval option to control sample shuffling (takes an optional seed for determinism).
- Batch Processing: Enable batch support when using Google model provider.

## 0.3.117 (31 July 2025)

- Added [Fireworks AI](https://inspect.aisi.org.uk/providers.html#fireworks-ai) model provider.
- OpenAI: Add `user` and `http_client` custom model arguments.
- vLLM: Add `is_mistral` model arg for mistral compatible tool calling.
- Hugging Face: Add `hidden_states` model arg to get model activations.
- Model API: `--max-connections`, `--max-retries`, and `--timeout` now provide defaults for all models rather than only the main model being evaluated.
- Tool calling: Do middle truncation when enforcing `max_tool_output`.
- Datasets: Support for directories in sample `files` field.
- Added sample, message, and event linking to `log_viewer()` data preparation function.
- Analysis: Added `full` option to `samples_df()` for reading full sample metadata.
- Analysis: Renamed `EvalConfig` column defs to `EvalConfiguration`.
- Improved `_repr_` for `EvalLog` (print JSON representation of log header).
- Added `metadata_as()` typesafe `metadata` accessor to `ChatMessageBase`.
- Hooks: Emit run end hook when unhandled exceptions occur.
- Batch Processing: Add batch processing support for Together AI
- Batch Processing: Improve batch processing scalability when handling very large concurrent batch counts.
- Batch Processing: Log retry attempts to the task display console.
- Batch Processing: Move batch retry logic to base class to reduce logic duplication and simplify provider implementations.
- Batch Processing: Enable batch support when using OpenAI Responses API.
- Inspect View: Do not use instance cache for S3FileSystem (eliminates some errors with large eval sets)
- Bugfix: Correct mapping for organization and model name in `model_info()` operation.
- Bugfix: Fix bug that failed to detect when an entire batch gets rejected by OpenAI.

## 0.3.116 (27 July 2025)

- Added `display_name` property to `Task` (e.g. for plotting).
- Analysis: `task_info()` operation for data frame preparation.

## 0.3.115 (26 July 2025)

- Analysis: `model_info()` and `frontier()` operations for data frame preparation.
- ReAct Agent: Require submit tool to have no errors before you exit the react loop.
- Mistral: Type updates for `ThinkChunk` and `AudioChunk` in package v1.9.3 (which is now the minimum required version).
- Inspect View: Use MathJax rather than Katex for math rendering.
- Inspect View: Fix issue with scores 'More...' link not being displayed in some configurations.
- Inspect View: Fix issue displaying tool calls in transcript in some configurations.
- Bugfix: Strip smuggled `<think>` and `<internal>` tags from tool messages to prevent leakage in multi-agent scenarios where an _inner_ assistant message can be coerced into a tool message.
- Bugfix: Handle descriptions of nested `BaseModel` types in tool call schemas.
- Bugfix: Update workaround of OpenAI reasoning issue to retain only the last (rather than the first) in a run of consecutive reasoning items.


## 0.3.114 (17 July 2025)

- OpenAI: Move model classification functions into `ModelAPI` class so that subclasses can override them.
- Azure: Support for authenticating with Microsoft Entra ID managed identities.
- Analysis: `prepare()` function for doing common data preparation tasks and `log_viewer()` operation for adding log viewer URLs to data frames.
- ReAct Agent: Require submit tool to have no errors before you exit the react loop.
- Inspect View: Use MathJax rather than Katex for math rendering.
- Inspect View: Supporting linking to events via `uuid` field (or `event_id` in analysis data frames).
- Bugfix: Use the output filesystem when creating directories in `inspect log convert`

## 0.3.113 (16 July 2025)

- [Batch processing](https://inspect.aisi.org.uk/models-batch.html) API support for OpenAI and Anthropic models.
- [TransformerLens](https://inspect.aisi.org.uk/providers.html#transformer-lens) model provider enabling use of `HookedTransformer` models with Inspect.
- Web search: Added support for Grok as an internal search provider.
- Google: Set `thought=True` on content when replaying `ContentReasoning` back to the model.
- Transcript: Add globally unique `uuid` field and `metadata` field to `Event`.
- Transcript: Add `message_id` field to `ToolEvent` for corresponding `ChatMessageTool`.
- Eval log: Add option to select sample by `uuid` in `read_eval_log_sample()`.
- ReAct agent: Add `keep_in_messages` option to `AgentSubmit` to preserve calls to `submit()` in message history.
- Scoring: Change `Value` type to use covariant types (`Mapping` and `Sequence`).
- Scoring: Add `display` parameter to `score()` to control display type.
- Scoring: Nan values returned from scorers will be excluded from computation of metrics. Scorers in results include `scored_samples` and `unscored_samples` fields to indicate how many samples were scored and how many were not. The viewer will display these values if there are unscored samples.
- Eval Log: Protect against removing excessive numbers of samples at once from realtime database.
- Eval Log: Add `--resolve-attachments` option to `inspect log dump`.
- Hooks: Provide full `EvalSample` (rather than only the summary) to `on_sample_end()` hook.
- Inspect View: Compatiblility for sites published to GitHub Pages for `inspect view bundle`.
- Inspect View: The bundle produced for deployment now includes a much more compact manifest, improving support for bundling large numbers of files.
- Bugfix: Fix failure to allow Anthropic native web search for some model names such as `claude-3-7-sonnet-latest`.
- Bugfix: Fix Anthropic citation support code when it encounters citations created by external search providers such as Tavily.
- Bugfix: Break after finding final assistant message when implementing fallback for `AgentState` `output` field.
- Bugfix: Fix `run_in_background` allowing it to properly function outside the context of a task.
- Bugfix: `None` out `TaskLogger`'s `SampleBufferDatabase` after cleaning it up to avoid crashing on subsequent logging attempts.
- Bugfix: Disassociate the logger used by batch processing's background task from any particular sample.
- Bugfix: Improve the compactness and efficiency of eval files with extremely large text user inputs. 
- Bugfix: Fixed bugs in batch process as the size of a batch approached the model provider's maximum batch size of 256MB.
- Bugfix: Fix regression that allowed computer tool screenshot truncation to occur despite not being valid for OpenAI.
- Bugfix: Fix agent bridge scenarios that failed when used with reasoning models.
- Bugfix: Fix cases where <think> blocks are dropped in OpenAI choices because they are not at the front of text content. 

## 0.3.112 (03 July 2025)

- [Hooks](https://inspect.aisi.org.uk/extensions.html#hooks): Generic lifecycle hooks for Inspect extensions.
- Datasets: Expand glob wildcards when processing `--sample_id` filter for datasets.
- OpenAI: Enable web search for o3 and o4-mini models.
- OpenAI: Enable emulated tool call image results for o-series.
- Analysis: Provide `score_headline_stderr` field in standard evals column definitions.
- Analysis: Provide `task_name` without package namespace by default.
- Analysis: Don't show dataframe import progress by default in notebooks (leaves empty cell output artifact).
- Analysis: Include `order` field in `messages_df()` and `events_df()`.
- Eval: Introduce `run_samples` option to disable running samples (resulting in a log file with status "started" and no samples).
- Logging: Improvements to `--display=log` (improved task info formatting, ability to disable rich logging)
- Task Display: Limit console to a maximum of 100 lines to prevent rendering performance problems.
- Inspect View: Fix failure to restore VSCode state when switching to/from tabs for some class of log files.
- Bugfix: Conform to breaking changes in `mistralai` package (1.9.1).

## 0.3.111 (29 June 2025)

- Inspect View: Fix issue with tab switching when running in VS Code.

## 0.3.110 (28 June 2025)

- Bugfix: Return inner exception from `run_sample`.

## 0.3.109 (27 June 2025)

- Analysis: More forgiving column reading (use Pandas default reader rather than PyArrow).
- Fix store_as examples, document inspect_ai.scorer.score
- Delay cleanup of sample buffer database to account for potential sharing of data dir.
- Vertex: Ignore types to workaround update that removes type information from some of their sub-packages (tests still pass).
- MCP: Conform to breaking changes in latest mcp package (1.10.0).
- Docs: Correct docs for `web_browser()` and `bash_session()` to indicate that you must pass an `instance` explicitly to get distinct processes. 
- Docs: Correct shared documentation snippet that describes Dockerfile customization for Inspect Tool Support.
- Inspect View: Properly wrap log configuration values in evaluation header.
- Inspect View: Support for displaying and navigating directories of evaluation logs.
- Inspect View: Improved handling of agent handoffs in transcript outline view.
- Inspect View: Use numerical rather the correct/incorrect UI for scores with 0/1 values.
- Bugfix: Prevent concurrent accesses of eval event database from raising lock errors.
- Bugfix: Fix infinite recursion edge case in _flatten_exception.


## 0.3.108 (25 June 2025)

- Bugfix: Don't raise error on Anthropic cited_text not being a `str`.

## 0.3.107 (24 June 2025)

- Bugfix: Shield critical shutdown code from cancel scope.

## v0.3.106 (21 June 2025)

- OpenAI: Use prefix matching when detecting compatible models for `web_search()`.
- Groq: Capture `executed_tools` field as model output metadata.
- ReAct agent: Always send `str` returned from `on_continue` to the model (formerly this was only done if there were no tool calls).
- Web Search: Added provider for Perplexity's internal web search tool.
- Eval: Wrap eval execution in TaskGroup.
- Bugfix: Remove correlated reasoning content items when removing submit tool calls from ChatMessageAssistant instances in multi-agent scenarios.

## v0.3.105 (17 June 2025)

- [background()](https://inspect.aisi.org.uk/agent-custom.html#background) function for executing work in the background of the current sample.
- [sandbox_service()](https://inspect.aisi.org.uk/agent-custom.html#sandbox-service) function for making available methods to a sandbox for calling back into the main Inspect process.
- [sample_limits()](https://inspect.aisi.org.uk/errors-and-limits.html#query-usage) function for determining the current status of sample limits.
- React agent: Only do substitution on parts of the prompt that may contain a {submit} reference.
- Agent handoff: Ensure that handoff tool call responses immediately follow the call.
- Agent handoff: Only print handoff agent prefix if there is assistant message content.
- Subprocess: Ensure that streams are drained when a cancellation occurs (prevent hanging on calls with large output payloads).
- Eval log: Capture only limits that terminated the sample as `sample.limit` (as opposed to ones bound to context managers or agents).
- Inspect View: Display metadata for Chat Messages.
- Inspect View: Increase transcript outline font size.
- Inspect View: Add support for filtering by sample id, sample metadata.
- Bugfix: Eval set now correctly handles retries for tasks with defaulted args (regressed in v0.3.104).
- Bugfix: Use correct bindings for Claude v4 native `text_editor` tool; don't use native tool definition for Haiku 3.5 or Opus 3.0.  
- Bugfix: Restore preservation of `ContentReasoning` blocks for Gemini (regressed in v0.3.104). 
- Bugfix: Dataset shuffling now works correctly with `seed` of 0.

## v0.3.104 (12 June 2025)

- Web Search: Added provider for Anthropic's internal web search tool.
- Web Search: Added provider for [Exa](https://exa.ai/exa-api) Search API.
- Web Search: Added provider for Google's [Grounding with Google Search](https://ai.google.dev/gemini-api/docs/grounding) .
- Mistral: Support for capturing reasoning blocks for magistral models.
- Add [Perplexity](https://inspect.aisi.org.uk/providers.html#perplexity) model provider.
- ChatMessage: Add `metadata` field for arbitrary additional metadata.
- Content: Added `ContentData` for model specific content blocks.
- Citations: Added `Citation` suite of types and included citations in `ContentText` (supported for OpenAI and Anthropic models).
- Eval log: `task_args` now includes defaulted args (formerly it only included explicitly passed args).
- Eval set: `retry_connections` now defaults to 1.0 (resulting in no reduction in connections across passes).
  OpenAI: Work around OpenAI Responses API issue by filtering out leading consecutive reasoning blocks.
- OpenAI compatible provider: Substitute `-` with `_` when looking up provider environment variables.
- MCP: Update to types in latest release (1.9.4, which is now required).
- Added development container (`.devcontainer`) configuration.
- `trim_messages()` now removes any trailing assistant message after compaction.
- Task display: Ensure that full path to log file is always displayed (wrap as required).
- Task display: Wrap scorers and scores in the task detail display.
- Inspect View: Add support for displaying citations for web searches in the transcript.
- Inspect View: Correctly update browser URL when navigation between samples.
- Bugfix: Properly honor `responses_api=False` when pass as an OpenAI model config arg.
- Bugfix: Limits passed to handoffs can be used multiple times (if agent is handed off to multiple times).
- Bugfix: Replace invalid surrogate characters when serializing strings to JSON.
- Bugfix: Prevent error writing Nan values to the `logs.json` summary file during bundling.

## v0.3.103 (06 June 2025)

- Eval set: Do not read full eval logs into memory at task completion.

## v0.3.102 (05 June 2025)

- OpenAI: Use responses API for codex models.
- Bugfix: Temporarily revert change to eval set header reading to investigate regression.

## v0.3.101 (05 June 2025)

- Eval set: Default `max_tasks` to the greater of 4 and the number of models being evaluated.
- Eval set: Do not read full eval logs into memory at task completion.
- pass_at_k: Treat threshold as the the minimum inclusive value for passing (rather than checking equality)
- Web search: Include links specified by providers in the results.
- Inspect View: Display sample id & epoch in sample dialog title bar.
- Inspect View: Don't open sample dialog when simply navigating the sample list.
- Inspect View: Fix error that could occur when determine transcript outline collapse state.
- Inspect View: Show the correct sample when opening a sample from a sorted list.
- Bugfix: Ensure that dataset shuffle_choices=True always uses a distinct random seed.
- Bugfix: Don't attempt to use OpenAI's web search preview against models that are known to not support it.

## v0.3.100 (01 June 2025)

- [time_limit()](https://inspect.aisi.org.uk/errors-and-limits.html#time-limit) and [working_limit()](https://inspect.aisi.org.uk/errors-and-limits.html#working-limit) context managers for scoped application of time limits.
- Abiliy to query current usage for scoped limits (e.g. time or tokens).
- Added native OpenAI web search to [web_search()](https://inspect.aisi.org.uk/tools-standard.html#sec-web-search) tool.
- Limit `docker compose` concurrency to 2 * os.cpu_count() by default (override with `INSPECT_DOCKER_CLI_CONCURRENCY`).
- ReAct agent: Only send custom `on_continue` message to the model if the model made no tool calls.
- Tool calling: Support for `Enum` types in tool arguments.
- AzureAI: Automatically fold user and tool messages for Mistral models.
- Task display: Simplify task display for `plain` mode (no outline, don't expand tables to console width).
- Task display: Truncate task config to prevent overflow (collapse dicts, limit individual values to 50 chars, limit overall output to 500 chars).
- Task display: Always show the sample init event in the task transcript display.
- Task display: Fix mouse support on ghostty (and possibly other terminals).
- Inspect View: Outline view for transcript which enables high level navigation to solvers, agents, scorers, etc.
- Inspect View: Fix an issue that prevented the display of the viewer in VSCode when the viewer tab was moved to the background.
- Inspect View: Don't error when metadata contains null values.

## v0.3.99 (22 May 2025)

- Exported `view()` function for running Inspect View from Python.
- Always return tasks in the same order they were passed to `eval()` or `eval_set()`.
- Google: Updated required version of `google-genai` to 1.16.1 (which includes support for reasoning summaries and is now compatible with the trio async backend).
- Anthropic: More flexible detection of "overloaded_error" for retires.
- Inspect View: Improve text zooming and wrapping when rendering sample errors.
- Inspect View: Preserve log mtime-ordering in the bundle output directory

## v0.3.98 (18 May 2025)

- Google: Disable reasoning when `reasoning_tokens` is set to 0.
- Temporarily pin to textual < 3.0.0 to work around event loop breakage.
- CLI display: improve performance of sample rendering by only rendering the 10 most recent events.
- Inspect View: Improve sample score column layout, markdown render explanation.

## v0.3.97 (16 May 2025)

- React agent: Use of `submit()` tool is now [optional](https://inspect.aisi.org.uk/agent.html#submit-tool).
- Agents: `is_agent()` typeguard function for checking whether an object is an `Agent`.
- Anthropic: Show warning when generation config incompatible with extended thinking is used (affects `temperature`, `top_p`, and `top_k`).
- AzureAI: Don't include `tools` or `tool_choice` in  requests when emulating tool calling (avoiding a 400 error).
- AzureAI: Accept `<tool_calls>` plural from Llama models (as it sometimes uses this instead of `<tool_call>`).
- AzureAI: Correctly handle tool calls with no arguments.
- Eval retry: Improve error message when attempting to retry tasks in packages that have not been registered.
- Warn when a passed `--sample-id` is not found in the target dataset (raise error if there are no matches at all).
- Dataframes: [parallel](https://inspect.aisi.org.uk/dataframe.html#parallel-reading) option to read samples in parallel using multiprocessing.
- Dataframes: Include underlying `EvalLog` and `Exception` in `ColumnError`.
- Dataframes: Use native pyarrow column storage with pd.NA for missing values.
- Inspect View: Improve the performance and memory efficiency of the viewer when viewing large samples with long, complex transcripts.
- Inspect View: Improve the performance of the viewer when viewing large, complex sample or task metadata. 
- Inspect View: Live display of subtask, tool and other child events when viewing a running evaluation.
- Inspect View: Transcript rendering improvements including less complex overall layout, more collapsible entities, and improved rendering of sandbox events, tool calls, and other events.
- Inspect View: Message rendering improvement including coloring user messages, reducing layout complexity, and other minor improvements.
- Inspect View: Render metadata for samples and tasks as an interactive tree.
- Inspect View: When deployed via `inspect view bundle`, support linking to individual transcript events or messages.
- Inspect View: Reduce the maximum size of the header (before it is collapsed) when evals have large numbers of metrics.
- Bugfix: More robust handling of non-529 "overloaded_error" for Anthropic.
- Bugfix: More robust handling of no result returned from tool call.

## v0.3.96 (13 May 2025)

- Dataframes: `events_df()` function, improved message reading, log filtering, don't re-sort passed logs
- Model Context Protocol: Upgrade sandbox client to typing changes made in v1.8.0 of `mcp` package.
- vLLM/SGLang: Fix dynamic port binding for local server on Mac OS X.
- React Agent: Improve continue prompt to remind the model to include the answer in their call to `submit()`.
- Inspect View: Properly sort samples by score even when there are samples with errors.
- Inspect View: Allow filtering of samples by score when evals are running.

## v0.3.95 (10 May 2025)

- [Dataframe](https://inspect.aisi.org.uk/dataframe.html) functions for reading dataframes from log files.
- Web Search: Added provider for [Tavily](https://inspect.aisi.org.uk/tools-standard.html#tavily-provider) Research API.
- Multiple Choice: `max_tokens` option to control tokens used for `generate()`.
- Don't enforce sample `working_limit` after solvers have completed executing (matching behavior of other sample limits).
- Only pass `user` parameter on to sandboxes if is not `None` (eases compatibility with older sandbox providers).
- Anthropic: Retry when `type` in the error message body is "overloaded_error". 
- Agent Bridge: Compatibility with `request()` method in v1.78.0 of `openai` package (now the minimum required version).
- Model Context Protocol: Update to typing changes made in v1.8.0 of `mcp` package (now the minimum required version).
- TaskState: `input_text` and `user_prompt` properties now read the last rather than first user message.
- Inspect View: Properly display 'more' options when content is collapsed.
- Inspect View: Fix issue that prevented filtering of sample list when viewing a running evaluation.
- Inspect View: Fix selection of specific metrics within scorers when a scorer produces more than one metric.
- Ignore OSError that occurs while rotating trace files.
- Restore logging `metadata` from `TaskState` rather than from `Sample`.
- Bugfix: Restore ability of operator to terminate the current sample in tool call approval.
- Bugfix: Ensure that "init" span is exited in the same async context when sandbox connection errors occur.
- Bugfix: Protect against no `thought` argument being passed to `think()` tool.
- Bugfix: Correct handling of `text_editor()` tool for Claude Sonnet 3.5.

## v0.3.94 (06 May 2025)

- [span()](https://inspect.aisi.org.uk/agent-custom.html#grouping-with-spans) function for grouping transcript events.
- [collect()](https://inspect.aisi.org.uk/agent-custom.html#grouping-with-spans) function for enclosing parallel tasks in spans.
- [Event tree](https://inspect.aisi.org.uk/reference/inspect_ai.log.html#event-tree) functions for organising transcript events into a tree of spans.
- `inspect log convert` now always fully re-writes log files even of the same format (so that e.g. sample summaries always exist in the converted logs).
- React agent: `answer_only` and `answer_delimiter` to control how submitted answers are reflected in the assistant message content. 
- Python tool: Execute using a bash login shell for consistency of Python versions across `bash()` and `python()` tools.
- Task display: Realtime display of events that occur within tool calls and subtasks.
- Multiple choice: Support for more than 26 choices.
- Bugfix: Ensure that each MCP server gets its own cached tool list.

## v0.3.93 (01 May 2025)

- [Scoped Limits](https://inspect.aisi.org.uk/errors-and-limits.html#scoped-limits) for enforcing token and message limits using a context manager.
- [Agent Limits](https://inspect.aisi.org.uk/errors-and-limits.html#agent-limits) for enforcing token and message limits for agent execution.
- Enhanced `bash_session()` tool to provide richer interface to model and to support interactive sessions (e.g. logging in to a remote server).
- [read_eval_log_sample_summaries()](https://inspect.aisi.org.uk/eval-logs.html#summaries) function for reading sample summaries (including scoring) from eval logs.
- Updated [vLLM](https://inspect.aisi.org.uk/providers.html#vllm) provider to use local server rather than in process `vllm` package (improved concurrency and resource utilization).
- New [SGLang](https://inspect.aisi.org.uk/providers.html#sglang) provider (using similar local server architecture as vLLM provider).
- Anthropic: Added `streaming` model argument to control whether streaming API is used (by default, streams when using extended thinking).
- `--sample-id` option can now include task prefixes (e.g. `--sample-id=popularity:10,security:5)`).
- Improved write performance for realtime event logging.
- `--no-log-realtime` option for disabling realtime event logging (live viewing of logs is disabled when this is specified).
- Packaging: Exclude `_resources` directories from package (reduces pressure on path lengths for Windows).
- Inspect View: Split info tab into task, models, and info for improved layout.
- Bugfix: Avoid validation errors when loading old log files which contain "output_limit" tool errors.

## v0.3.92 (26 April 2025)

- OpenAI: In responses API, don't pass back assistant output that wasn't part of the output included in the server response (e.g. output generated from a call to a `submit()` tool).
- Bugfix: Correctly pass tool arguments back to model for OpenAI responses API.

## v0.3.91 (26 April 2025)

- Support for using tools from [Model Context Protocol](https://inspect.aisi.org.uk/tools-mcp.html) providers.
- New [retry_on_error](https://inspect.aisi.org.uk/errors-and-limits.html#sample-retries) option to enable sample level retry of errors (retries occur immediately rather than waiting until the next full eval retry).
- OpenAI: [reasoning_summary](https://inspect.aisi.org.uk/reasoning.html#reasoning-history) generation option for reasoning models.
- OpenAI: `responses_store` model argument to control whether the `store` option is enabled (it is enabled by default for reasoning models to support reasoning playback).
- OpenAI: Support for [flex processing](https://inspect.aisi.org.uk/providers.html#flex-processing), which provides lower inference costs in exchange for slower response times and occasional resource unavailability (added in v1.75.0, which is now required).
- OpenAI: Responses API is now used by default for all reasoning models.
- OpenAI: Automatically alias reserved internal tool names (e.g. `python`) for responses API.
- Anthropic: Warn only once if unable to call count_tokens() for a model.
- Google: Update to 1.12.1 of `google-genai` (which is now required).
- Google: Support for `reasoning_tokens` option for Gemini 2.5 models.
- Grok: Support for `reasoning_effort` option and capturing reasoning content.
- OpenRouter: Forward `reasoning_effort` and `reasoning_tokens` to `reasoning` field.
- Model API: `ToolSource` for dynamic tools inputs (can be used in calls to `model.generate()` and `execute_tools()`)
- ReAct Agent: Ability to fully repleace the default `submit()` tool.
- Human Agent: Added `user` parameter for running the human agent cli as a given user.
- Scoring: Support for multimodal inputs to `model_graded_qa()` and `model_graded_fact()`.
- Scoring: Handle parsing unicode fractions when evaluating numeric input for `match()` scorer.
- Scoring: Add `sample_metadata_as()` method to `SampleScore`.
- Sandbox API: Added `user` parameter to `connection()` method for getting connection details for a given user.
- Docker: Register samples for cleanup immediately (so they are still cleaned up even if interrupted during startup).
- Docker: Support sample metadata interpolation for image names in compose files. 
- Tool calling: Support for additional types (`datetime`, `date`, `time`, and `Set`)
- Log API: Functions for reading/writing eval logs can now take a `Path`.
- Registry: Evaluate string annotations when creating registry objects. 
- Error handling: Added `--traceback-locals` CLI option to print values of local variables in tracebacks.
- Error handling: Fully unwrap inner errors from exception groups for reporting.
- Inspect View: Support for viewing logs in Google Cloud Storage (gc://).
- Inspect View: Improved display of reasoning blocks.
- Inspect View: Improved display and layout of transcript and events.
- Inspect View: Improved Tool input and output display.
- Inspect View: Improved display of sample input, target, answer, and scoring information (improve column width behavior).
- Inspect View: Add support for linking to logs, specific log tabs, individual samples, and sample tabs within samples.
- Inspect View: Collapse sample init view by default.
- Inspect: Properly store and restore NaN values when viewing logs in VSCode.
- Documentation: Update tutorial to use HuggingFaceH4/MATH-500 as math dataset.
- Documentation: Add scorer.py example that uses the expression_equivalence custom scorer from the tutorial.
- Bugfix: Correct parsing of `CUDA_VISIBLE_DEVICES` environment variable for vLLM provider
- Bugfix: Don't require saved response message id for openai assistant messages.
- Bugfix: Don't show empty `<think>` tag in conversation view if there is no reasoning content.
- Bugfix: Properly handle multiple reasoning blocks and empty reasoning summaries in OpenAI responses API.
- Bugfix: Tolerate assistant messages with no internal representation in Open AI responses API.
- Bugifx: Correct reporting of seconds until next retry for model generate calls.

## v0.3.90 (21 April 2025)

- Inspect View: Collapse user messages after 15 lines by default.
- Inspect View: Improved spacing between transcript events.
- Bugfix: Prevent duplicate sample init events in transcript.
- Bugfix: Properly collapse initialization events in the transcript.
- Bugfix: Properly pre-wrap source code in the transcript.

## v0.3.89 (17 April 2025)

- [Model Roles](https://inspect.aisi.org.uk/models.html#model-roles) for creating aliases to models used in a task (e.g. "grader", "red_team", "blue_team", etc.)
- New [openai-api](https://inspect.aisi.org.uk/providers.html#openai-api) model provider for interfacing with arbitrary services that have Open AI API compatible endpoints.
- ReAct Agent: [truncation](https://inspect.aisi.org.uk/agents.html#truncation) option to trim conversation messages when the model context window is exceeded.
- ReAct Agent: Improve default `on_continue` message, including using a dynamic name for the submit tool.
- Agent Bridge: Add `metadata` field to bridge input for backward compatibility with solver-based bridge.
- Added `default` argument to `get_model()` to explicitly specify a fallback model if the specified model isn't found.
- Approval: Approvers now take `history` argument (rather than `TaskState`) to better handle agent conversation state.
- Anthropic: Update string matching to correctly handle BadRequestErrors related to prompt + max_tokens being too long.
- Google: Return "(no content)" when a generate call results in no completion choices.
- CloudFlare: Use OpenAI compatible REST endpoint for interface to models.
- Azure AI: Use `2025-03-01-preview` as default API version if none explicitly specified.
- Model API: `trim_messages()` function for pruning messages to fit within model context windows.
- Model API: Improved detection of context window overflow for Grok, Groq, and CloudFlare.
- Task Display: Show both provider and model name when concurrency context is not shared across all models for a given provider.
- Registry: Exported `registry_create()` function for dynamic creation of registry objects (e.g. `@task`, `@solver`, etc.).
- Remove `chdir` option from `@task` (tasks can no longer change their working directory during execution).
- `INSPECT_EVAL_LOG_FILE_PATTERN` environment variable for setting the eval log file pattern.
- Bugfix: Eval retry now works correctly for models with a service prefix (e.g. `openai/azure/model-name`).
- Bugfix: Correctly resolve approvers in the same source file as tasks. 
- Bugfix: Ensure agent decorator resolves string annotations from `__future__` as needed.
- Bugfix: Correctly handle string `dict` keys that are numeric in store diffs.

## v0.3.88 (11 April 2025)

- Tools: Restore formerly required (but now deprecated) `type` field to `ToolCall`.
- Approval: Raise operator limit exceeded error for tool approval termination action.
- Anthropic: Don't include side count of `reasoning_tokens` in `total_tokens` (they are already included).
- Anthropic: Update string matching to correctly handle BadRequestErrors related to prompts being too long.

## v0.3.87 (10 April 2025)

- Eval: Fix an error when attempting to display realtime metrics for an evaluation.
- Log Viewer: Fix an error when displaying a running log with a null metric value.

## v0.3.86 (09 April 2025)

- Open AI: Treat `UnprocessableEntityError` as bad request so we can include the request payload in the error message.
- Eval Retry: Correctly restore model-specific generation config on retry.
- Inspect View: Resolve sample attachments before including in realtime event stream.
- Bugfix: Properly handle special characters in IDs during event database cleanup.

## v0.3.85 (08 April 2025)

- Remove support for `goodfire` model provider (dependency conflicts).
- React Agent: Enable specification of `description` without `name`.

## v0.3.84 (07 April 2025)

- Bugfix: Suppress link click behavior in vscode links.

## v0.3.83 (07 April 2025)

- Inspect View: [Live updates](https://inspect.aisi.org.uk/log-viewer.html#live-view) to running evaluation logs.
- [Agent](https://inspect.aisi.org.uk/agents.html) protocol and [inspect_ai.agent](https://inspect.aisi.org.uk/reference/inspect_ai.agent.html) module with new system for creating, composing, and executing agents.
- Scoring: New [grouped()](https://inspect.aisi.org.uk/scoring.html#metric-grouping) metric wrapper function, which applies a given metric to subgroups of samples defined by a key in sample metadata.
- Basic Agent: New `submit_append` option to append the submit tool output to the completion rather than replacing the completion (note that the new `react()` agent appends by default).
- Model API: New [execute_tools()](https://inspect.aisi.org.uk/reference/inspect_ai.model.html#execute_tools) function (replaces deprecated `call_tools()` function) which handles agent handoffs that occur during tool calling.
- Model API: `generate_loop()` method for calling generate with a tool use loop.
- Model API: Provide optional sync context manager for `Model` (works only with providers that don't require an async close).
- Anthropic: Add support for `tool_choice="none"` (added in v0.49.0, which is now required).
- Together AI: Updated `logprobs` to pass `1` rather than `True` (protocol change).
- Tools: `bash_session()` and `web_browser()` now create a distinct sandbox process each time they are instantiated.
- Computer Tool: Support for use of the native Open AI computer tool (available in the model `openai/computer-use-preview`)
- Task API: `task_with()` and `tool_with()` no longer copy the input task or tool (rather, they modify it in place and return it).
- Eval Set: Resolve tasks before each pass (ensure that each pass runs against an entirely new task instance).
- Eval Retry: Ability to retry any task in the registry, even if it has a custom `name` (save `registry_name` separately).
- Human Agent: Start task with clock paused and then automatically start it on container logins.
- Typed Store: `instance` option for `store_as()` for using multiple instances of a `StoreModel` within a sample.
- Typed Store: Raise error if attempting to embed a `StoreModel` within another `StoreModel`.
- Sandbox: New `sandbox_default()` context manager for temporarily changing the default sandbox.
- Docker: `write_file()` function now gracefully handles larger input file sizes (was failing on files > 2MB).
- Docker: Prevent low timeout values (e.g. 1 second) from disabling timeout entirely when they are retried.
- Display: Print warnings after task summaries for improved visibility.
- Inspect View: Fallback to content range request if initial HEAD request fails.
- Inspect View: Improve error message when view bundles are server from incompatible servers.
- Inspect View: Render messages in `user` and `assistant` solver events.
- Inspect View: Improved support for display of nested arrays.
- Inspect View: Improved rendering of complex scores and metrics.
- Inspect View: Properly handle filtering of dictionary scores.
- Inspect View: Render math in model input and output using katex.
- Inspect View: Improve sample score rendering (single scoring tab with scores rendered in a table).
- Inspect View: Improve sample count display in sample list footer.
- Inspect View: Properly refresh running evals when restoring from being backgrounded.
- Bugfix: Support for calling the `score()` function within Jupyter notebooks.
- Bugfix: Handle process lookup errors that can occur during timeout race conditions.
- Bugfix: Correctly capture and return logs from `eval()` when a cancellation occurs.
- Bugfix: Correctly handle custom `api_version` model argument for OpenAI on Azure.
- Bugfix: Correct handling for `None` passed to tool call by model for optional parameters.
- Bugfix: Cleanup automatically created `.compose.yml` when not in working directory.
- Bugfix: Prevent exception when navigating to sample that no longer exists in running samples display.

## v0.3.82 (02 April 2025)

- Bugfix: Correct handling of backward compatibility for inspect-web-browser-tool image.
- Bugfix: Eval now properly exits when `max_tasks` is greater than total tasks

## v0.3.81 (30 March 2025)

- Requirements: Temporarily upper-bound `rich` to < 14.0.0 to workaround issue.

## v0.3.80 (30 March 2025)

- Google: Compatibility with httpx client in `google-genai` >= 1.8.0 (which is now required).
- Mistral: Compatibility with tool call schema for `mistralai` >= v1.6.0 (which is now required).
- Inspect View: Correctly parse NaN values (use JSON5 for all JSON parsing)

## v0.3.79 (26 March 2025)

- Google: Compatibility with v1.7 of google-genai package (create client per-generate request)
- Bugfix: Properly record scorer and metrics when there are multiple tasks run in an eval.

## v0.3.78 (25 March 2025)

- OpenAI: Ensure that assistant messages always have the `msg_` prefix in responses API.

## v0.3.77 (25 March 2025)

- New [think()](https://inspect.aisi.org.uk/tools-standard.html#sec-think) tool that provides models with the ability to include an additional thinking step.
- OpenAI: Support for the new [Responses API](https://inspect.ai-safety-institute.org.uk/providers.html#responses-api) and [o1-pro](https://platform.openai.com/docs/models/o1-pro) models.
- OpenAI: Remove base64-encoded audio content from API call JSON in ModelEvent.
- AzureAI: Support for use of native [OpenAI](https://inspect.ai-safety-institute.org.uk/providers.html#openai-on-azure) and [Mistral](https://inspect.ai-safety-institute.org.uk/providers.html#mistral-on-azure-ai) clients using service qualifiers (e.g. `openai/azure/gpt-4o-mini` or `mistral/azure/Mistral-Large-2411`). 
- OpenRouter: Handle "error" field in response object and retry for empty responses.
- Added `--metadata` option to eval for associating metadata with eval runs.
- Task display: Show reasoning tokens for models that report them.
- Anthropic: Include reasoning tokens in computation of total tokens
- Inspect View: Properly wrap tool input for non-code inputs like `think`.

## v0.3.76 (23 March 2025)

- [bash_session()](https://inspect.ai-safety-institute.org.uk/tools-standard.html#sec-bash-session) tool for creating a stateful bash shell that retains its state across calls from the model.
- [text_editor()](https://inspect.ai-safety-institute.org.uk/tools-standard.html#sec-text-editor) tool which enables viewing, creating and editing text files.
- Structured Output: Properly handle Pydantic BaseModel that contains other BaseModel definitions in its schema.
- OpenAI: Support for .wav files in audio inputs for gpt-4o-audio-preview.
- OpenAI: Strip 'azure' prefix from model_name so that model type checks all work correctly.
- OpenAI: Don't send `reasoning_effort` parameter to o1-preview (as it is not supported).
- Inspect View: Fix error sorting numeric or categorical score results.
- Inspect View: Properly wrap model API call text in the transcript.
- Bugfix: Only initialise display in eval_set if it wasn't initialised from the CLI
- Bugfix: Set the global log level based on the specified Inspect log level.
- Bugfix: Resolve issue when deserialising a SubtaskEvent from a log file which does not have a completed time.
- Bugfix: Fix unnecessary warnings about task arguments.
- Bugfix: When a task does not take a kwargs argument, only warn if the provided argument is not valid.

## v0.3.75 (18 March 2025)

- Model API: Specifying a default model (e.g. `--model`) is no longer required (as some evals have no model or use `get_model()` for model access).
- Tasks can now directly specify a `model`, and model is no longer a required axis for parallel tasks.
- Eval Set: Improved parallelisation in scheduler (all pending tasks are now run together rather than in model groups).
- Don't generate `id` for `ChatMessage` when deserialising (`id` is now `str | None` and is only populated when messages are directly created).
- Log: Support for zip64 extensions required to read some log files that are larger than 4GB.
- Anthropic: Provide `reasoning_tokens` for standard thinking blocks (redacted thinking not counted).
- Google: Improve checking of `APIError` status codes for retry.
- CLI: Added `--env` option for defining environment variables for the duration of the `inspect` process.
- Inspect View: Fix issue generating diffs for nested arrays.
- Inspect View: Fix layout issue with sample error display in sample detail summary.
- Inspect View: Better support large eval files (in excess of 4GB).
- Inspect View: Correctly display 'None' when passed in tool calls.
- Inspect View: Fix 'Access Denied' error when using `inspect view` and viewing the log in a browser.
- Bugfix: Properly handle nested Pydantic models when reading typed store (`store_as()`) from log.
- Bugfix: Enable passing `solver` list to `eval()` (decorate `chain` function with `@solver`).
- Bugfix: Support deserializing custom sandbox configuration objects when said sandbox plugin is not installed.
- Bugfix: Fix error in sample filtering autocomplete (could cause autocomplete to fail and show an error in js console).

## v0.3.74 (15 March 2025)

- Bugfix: Exclude chat message `id` from cache key (fixes regression in model output caching).

## v0.3.73 (14 March 2025)

- Constrain model output to a particular JSON schema using [Structured Output](https://inspect.aisi.org.uk/structured.html) (supported for OpenAI, Google, and Mistral).
- New "HTTP Retries" display (replacing the "HTTP Rate Limits" display) which counts all retries and does so much more consistently and accurately across providers.
- The `ModelAPI` class now has a `should_retry()` method that replaces the deprecated `is_rate_limit()` method.
- The "Generate..." progress message in the Running Samples view now shows the number of retries for the active call to `generate()`.
- New `inspect trace http` command which will show all HTTP requests for a run.
- More consistent use of `max_retries` and `timeout` configuration options. These options now exclusively control Inspect's outer retry handler; model providers use their default behaviour for the inner request, which is typically 2-4 retries and a service-appropriate timeout.
- Improved async implementation using AnyIO (can now optionally run Trio rather than asyncio as the [async backend](https://inspect.aisi.org.uk/parallelism.html#async-backends)).
- Agent Bridge: Correct handling for `tool_choice` option.
- Model API: `ChatMessage` now includes an `id` field (defaults to auto-generated uuid).
- OpenAI: More flexible parsing of content parts (some providers omit the "type" field); support for "reasoning" content parts.
- Anthropic: Retry api connection errors and remote protocol errors that occur during streaming.
- Mistral: Update to new Mistral API (v1.5.1 of `mistralai` is now required).
- Logging: Inspect no longer sets the global log level nor does it allow its own messages to propagate to the global handler (eliminating the possibility of duplicate display). This should improve compatibility with applications that have their own custom logging configured. 
- Tasks: For filesystem based tasks, no longer switch to the task file's directory during execution (directory switching still occurs during task loading). Specify `@task(chdir=True)` to preserve the previous behavior.
- Bugfix: Fix issue with deserializing custom sandbox configuration objects.
- Bugfix: Handle `parallel_tool_calls` correctly for OpenAI models served through Azure.

## v0.3.72 (03 March 2025)

- Computer: Updated tool definition to match improvements in Claude Sonnet 3.7.

## v0.3.71 (01 March 2025)

- Anthropic: Support for [extended thinking](https://inspect.aisi.org.uk/reasoning.html#claude-3.7-sonnet) features of Claude Sonnet 3.7 (minimum version of `anthropic` package bumped to 0.47.1).
- Reasoning: `ContentReasoning` type for representing model reasoning blocks.
- Reasoning: `reasoning_tokens` for setting maximum reasoning tokens (currently only supported by Claude Sonnet 3.7)
- Reasoning: `reasoning_history` can now be specified as "none", "all", "last", or "auto" (which yields a provider specific recommended default).
- Web Browser: [Various improvements](https://github.com/UKGovernmentBEIS/inspect_ai/pull/1314) to performance and robustness along with several bug fixes.
- OpenAI: Provide long connection (reasoning friendly) socket defaults in http client 
- OpenAI: Capture `reasoning_tokens` when reported.
- OpenAI: Retry on rate limit requests with "Request too large".
- OpenAI: Tolerate `None` for assistant content (can happen when there is a refusal).
- Google: Retry requests on more HTTP status codes (selected 400 errors and all 500 errors). 
- Event Log: Add `working_start` attribute to events and `completed` and `working_time` to model, tool, and subtask events.
- Human Agent: Add `task quit` command for giving up on tasks.
- Human Agent: Don't emit sandbox events for human agent
- Inspect View: Improve rendering of JSON within logging events.
- Inspect View: Improve virtualized rendering of Sample List, Sample Transcript, and Sample Messages.
- Task Display: Let plugins display counters ('rich' and 'full' display modes only).
- Inspect View: Fix layout issues with human agent terminal session playback.
- Inspect View: Improve tool input / output appearance when rendered in VSCode.
- Inspect View: Display reasoning tokens in model usage for the samples and for the complete eval.
- Inspect View: Improve model api request / response output when rendered in VSCode.
- Inspect View: Improve rendering of some tool calls in the transcript.
- Bugfix: Fix audio and video inputs for new Google GenAI client.
- Bugfix: Ensure that token limits are not enforced during model graded scoring.
- Bugfix: Catch standard `TimeoutError` for running shell commands in the computer tool container.
- Bugfix: Correct combination of consecutive string based user messages for Anthropic provider.

## v0.3.70 (25 February 2025)

- [working_limit](https://inspect.aisi.org.uk/errors_and_limits.html#working-limit) option for specifying a maximum working time (e.g. model generation, tool calls, etc.) for samples.
- Added `SandboxEvent` to transcript for recording sandbox execution and I/O.
- Sandboxes: `as_type()` function for checked downcasting of `SandboxEnvironment`
- Remove root logging handlers upon Inspect logger initialisation (as they result in lots of log spam if left installed).
- Only explicitly set `state.completed=True` when entering scoring (`basic_agent()` no longer sets `completed` so can be used in longer compositions of solvers).
- Add `uuid` property to `TaskState` and `EvalSample` (globally unique identifier for sample run).
- Add `cleanup` to tasks for executing a function at the end of each sample run.
- Agent `bridge()` is now compatible with the use of a custom `OPENAI_BASE_URL`.
- Mistral: Bump required version of `mistralai` package to 1.5 (required for `working_limit`).
- Truncate tracebacks included in evaluation log to a maximum of 1MB.
- Compatibility with textual version 2.0 (remove upper bound).
- Align with HF datasets `fsspec` version constraints to avoid pip errors when installing alongside `datasets`.
- Bugfix: Fix issue with tools that had an ordinary `dict` as a parameter.
- Bugfix: Print the correct container `sample_id` for `--no-sandbox-cleanup`.

## v0.3.69 (20 February 2025)

- Google provider updated to use the [Google Gen AI SDK](https://googleapis.github.io/python-genai/), which is now the recommended API for Gemini 2.0 models.
- Task display: Use cooperative cancellation for cancel buttons in task display.
- Task display: Print task progress every 5 seconds for 'plain' display mode.
- Task display: Handle click on running samples tab when there is no transcript.
- Docker: Print stderr from `compose up` when no services startup successfully. 
- Docker: Print sample id and epoch for each container when using `--no-sandbox-cleanup`
- Mistral: Create and destroy client within generate.
- Inspect View: Fix display of score dictionaries containing boolean values
- Bugfix: Catch standard `TimeoutError` for subprocess timeouts (ensure kill/cleanup of timed out process).

## v0.3.68 (19 February 2025)

- Task display: Improve spacing/layout of final task display.
- Textual: speicfy broader range of compatible versions (v0.86.2 to v1.0.0)

## v0.3.67 (18 February 2025)

- Memoize calls to `get_model()` so that model instances with the same parameters are cached and re-used (pass `memoize=False` to disable).
- Async context manager for `Model` class for optional scoped usage of model clients.
- New `assistant_message()` solver.
- Prompt templates: Ignore template placeholders that don't map to passed parameters in `prompt_template()`, and system/user/assistant solvers.
- Google: Handle system messages with content lists and input with system but no user messages.
- Google: Ensure that a completion choice is provided even when none are returned by the service.
- Inspect View: Improve the display of subtasks with no inputs or events.
- Inspect View: Fix transcript display of phantom subtask or other phantom events.
- Inspect View: Fix formatting issues in sample error display
- Bugfix: Raise error for empty dataset (rather than providing a dummy sample).
- Bugfix: Specify markup=False for textual static controls (stricter parser in textual 2.0 leading to exceptions).
- Bugfix: Temporarily pin to textual==1.0.0 while they chase all of their regressions in 2.0

## v0.3.66 (17 February 2025)

- Docker: Correct compose file generation for Dockerfiles w/ custom stem or extension.
- Escape brackets when rendering task config (another textual 2.0 fix)

## v0.3.65 (16 February 2025)

- Compatibility with textual 2.0 (which had several breaking changes).
- Inspect View: Improve scorer display formatting.
- Bugfix: Inspect view now correctly renders arrays with embedded `null` values.
- Bugfix: Inspect view now correctly handles scorers with no metrics.

## v0.3.64 (14 February 2025)

- [Reference documentation](https://inspect.aisi.org.uk/reference/) for Python API and CLI commands.
- Add support for [clustered standard errors](https://inspect.aisi.org.uk/scorers.html#clustered-standard-errors) via a new `cluster` parameter for the `stderr()` metric.
- Improvements to [scoring workflow](https://inspect.aisi.org.uk/scorers.html#sec-scorer-workflow) (`inspect score` command and `score()` function).
- Metrics now take `list[SampleScore]` rather than `list[Score]` (previous signature is deprecated but still works with a warning).
- Use a sample adjustment for the `var()` metric.
- Google: Speculative fix for completion candidates not being returned as a list.
- Python and Bash tools: Add `sandbox` argument for running in non-default sandboxes.
- Transcript: Log `ScoreEvent` (with `intermediate=True`) when the `score()` function is called.
- Transcript: Add `source` field to `InfoEvent` and use it for events logged by the human agent.
- Docker: Support Dockerfiles with `.Dockerfile` extension.
- Docker: Raise error when there is an explicitly configured `container_name` (incompatible with epochs > 1).
- Docker: Dynamically set `compose up` timeout when there are `healthcheck` entries for services.
- Log: Validate that `log_dir` is writeable at startup.
- Log: Write eval config defaults into log file (rather than `None`).
- Bugfix: Always honor level-level-transcript setting for transcript logging.
- Bugfix: Fix some dynamic layout issues for sample sandbox view.

## v0.3.63 (07 February 2025)

- Add [OpenRouter](https://inspect.aisi.org.uk/providers.html#openrouter) model provider.
- Inspect View: Convert codebase from JS/Preact to Typescript/React
- Add `shuffle_choices` to dataset and dataset loading functions. Deprecate `shuffle` parameter to the `multiple_choice` solver.
- Add `stop_words` param to the `f1` scorer. `stop_words` will be removed from the target and answer during normalization.
- Tools: Handle return of empty list from tool calls.
- Computer: Moved out of beta (i.e. from `inspect_ai.tool.beta` into `inspect_ai.tool`).
- Sandboxes: Docker now uses `tee` for write_file operations.
- Inspect View: Handle Zip64 zip files (for log files greater than 4GB)
- Bugfix: Change `type` parameter of `answer()` to `pattern` to address registry serialisation error.
- Bugfix: Restore printing of request payloads for 400 errors from Anthropic.
- Bugfix: Log transcript event for solver provided scores (improves log viewer display of solver scoring)

## v0.3.62 (03 February 2025)

- Various improvements for [reasoning models](https://github.com/UKGovernmentBEIS/inspect_ai/pull/1229) including extracting reasoning content from assistant messages.
- OpenAI: Handle `reasoning_effort`, `max_tokens`, `temperature`, and `parallel_tool_calls` correctly for o3 models.
- OpenAI: Map some additional 400 status codes to `content_filter` stop reason.
- Anthropic: Handle 413 status code (Payload Too Large) and map to `model_length` StopReason.
- Tasks: Log sample with error prior to raising task-ending exception.
- Python: Enhance prompt to emphasise that it is a script rather than a notebook.
- Computer: Various improvements to image including desktop, python, and VS Code configuration.
- Bugfix: Don't download full log from S3 for header_only reads.

## v0.3.61 (31 January 2025)

- Computer: Enable viewing computer tool's remote mouse cursor via VNC.
- Computer: Disable lock screen on from computer tool reference image.
- Limits: Amend `SampleLimitExceededError` with current `state` so that messages, etc. are preserved when limits are hit.
- Tools: Properly handle image dispatching when multiple tool calls are made by assistant.
- Anthropic: Raise error on 400 status not identified as model_length or content_filter.
- Basic Agent: `incorrect_message` can now optionally be an async function.
- Bugfix: Remove `suffix` from `eval-set` CLI args.
- Bugfix: Only catch `Exception` from sandboxenv_init (allow cancelled to propagate)

## v0.3.60 (29 January 2025)

- [Agent Bridge](https://inspect.aisi.org.uk/agent-bridge.html) for integrating external agent frameworks with Inspect.
- [Goodfire](https://inspect.aisi.org.uk/models.html#goodfire) model provider.
- Add `@wraps` to functions wrapped by Inspect decorators to preserve type information.
- Hugging Face: Add support for stop sequences for HF models.
- Docker: More robust parsing of version strings (handle development versions).
- Vertex: Support for Anthropic models hosted on Vertex.
- OpenAI: Read `refusal` field from assistant message when provided.
- OpenAI: Use qualifiers rather than model args for OpenAI on other providers (`openai/azure`)
- Anthropic: Don't insert '(no content)' into canonical messages list (do only on replay)
- Anthropic: Use qualifiers rather than model args for Anthropic on other providers (`anthropic/bedrock`, `anthropic/vertex`).
- Anthropic: Support for `extra_body` model arg (for adding additional JSON properties to the request)
- Basic Agent: Append `tools` to `state` so that tools added in `init` are preserved.
- Scoring: Always provide half-again the sample time limit for scoring.
- Bugfix: Fix issue w/ approvals for samples with id==0.
- Bugfix: Use "plain" display when running eval_async() outside of eval().
- Bugfix: Fix issue with multiple scorers of the same type in a task.

## v0.3.59 (24 January 2025)

- Beta version of [computer()](https://inspect.aisi.org.uk/tools-standard.html#sec-computer) tool which models with a computer desktop environment.
- `user_message()` solver for appending parameterised user messages.
- `prompt_template()`, `system_message()` and `user_message()` solver now also include the sample `store` in substitution parameters.
- Limits: Enforce token and message limit at lower level (not longer required to check `state.completed` for limit enforcement).
- Limits: Enforce [custom limits](https://inspect.aisi.org.uk/errors-and-limits.html#custom-limit) for samples by raising `SampleLimitExceededError`.
- Tasks: Optional ability for solvers to [yield scores](https://inspect.aisi.org.uk/solvers.html#sec-scoring-in-solvers) for a task.
- Model API: Log model calls that result in bad request errors.
- Tools: `model_input` option that determines how tool call result content is played back to the model.
- Tools: Don't attempt to marshall arguments of dynamic `ToolDef` with `**kwargs: Any` (just pass them through).
- Log warning when a non-fatal sample error occurs (i.e. errors permitted by the `fail_on_error` option) 
- Inspect View: allow filtering samples by compound expressions including multiple scorers. (thanks @andrei-apollo)
- Inspect View: improve rendering performance and stability for the viewer when viewing very large eval logs or samples with a large number of steps.
- Task display: Improved `plain` mode with periodic updates on progress, metrics, etc.
- Google: Update to v0.8.4 of google-generativeai (py.typed support and removal of logprobs generation options)
- Google: Support for string enums (e.g. `Literal["a", "b", "c"])`) in tool function declarations.

## v0.3.58 (16 January 2025)

- Support for [audio and video](https://inspect.aisi.org.uk/multimodal.html) inputs for Open AI and Google Gemini models.
- Task display: Added Timeout Tool button for manually timing out a tool call.
- Task display: Automatically switch to "plain" mode when running in a background thread
- Sandboxes: Setup and initialisation errors are now handled at the sample level.
- Sandboxes: Increase setup script timeout to 5 minutes (from 30 seconds) and do not retry setup scripts (in case they aren't idempotent).
- Sandboxes: Add `timeout_retry` option (defaulting to `True`) to `exec()` function.
- Sandboxes: Add `type` and  optional `container` properties to `SandboxConnection`.
- Docker: Services which exit with status 0 during setup no longer cause an error.
- `task_with()` function for creating task variants.
- Added `--filter` argument to trace CLI commands for filtering on trace log message content.
- Print model conversations to terminal with `--display=conversation` (was formerly `--trace`, which is now deprecated).
- HuggingFace: Support models that don't provide a chat template (e.g. gpt2)
- Eval Set: Ensure that logs with status 'started' are retried.
- Rename the built in `bootstrap_std` metric to `bootstrap_stderr` (deprecate `bootstrap_std`)
- Bugfix: Fix duplication of summaries when eval log file is rewritten.

## v0.3.57 (09 January 2025)

- [Tracing API](https://inspect.aisi.org.uk/tracing.html#tracing-api) for custom trace logging.
- Inspect View: never truncate tool result images and display at default width of 800px.
- Inspect View: display tool error messages in transcript when tool errors occur.
- Inspect View: display any completed samples even if the task fails because of an error
- Inspect View: don't display the 'input' column heading if there isn't an input
- Open AI: Handle additional bad request status codes (mapping them to appropriate `StopReason`)
- Open AI: Use new `max_completion_tokens` option for o1 full.
- Web Browser: raise error when both `error` and `web_at` fields are present in response.
- Sandboxes: Apply dataset filters (limit and sample id) prior to sandbox initialisation.
- Docker: Prevent issue with container/project names that have a trailing underscore. 
- Store: initialise `Store` from existing dictionary.
- Log: provide `metadata_as` and `store_as` typed accessors for sample metadata and store.
- Tool parameters with a default of `None` are now supported.
- More fine graned HTML escaping for sample transcripts displalyed in terminal.
- Bugfix: prevent errors when a state or storage value uses a tilde or slash in the key name.
- Bugfix: Include input in sample summary when the sample input contains a simple string.

## v0.3.56 (01 January 2025)

- [Human Agent](https://inspect.aisi.org.uk/human-agent.html) solver for human baselining of computing tasks.
- [Typed interfaces](https://inspect.aisi.org.uk/typing.html) to `Sample` store and metadata using Pydantic models.
- [Approval policies](https://inspect.aisi.org.uk/approval.html#task-approvers) can now be defined at the `Task` level (`eval` level approval policies take precedence).
- Tools can now return `ContentText` and `ContentImage`.
- Move tool result images into subsequent user messages for models that don't support tools returning images.
- `SandboxConnection` that contains login information from sandboxes.
- `display_type()` function for detecting the current display type (e.g. "full", "rich", etc.)
- Trace: improved handling of `eval()` running in multiple processes at once (trace file per-process)
- Docker: don't apply timeouts to `docker build` and `docker pull` commands.
- Bugfix: fix issue w/ `store.get()` not auto-inserting `default` value.

## v0.3.55 (29 December 2024)

- Bedrock: redact authentication model args from eval logs.
- OpenAI: warn when `temperature` is used with o1 models (as it is not supported).
- Bugfix: spread args for cache trace logging.

## v0.3.54 (26 December 2024)

- [Tracing](https://inspect.aisi.org.uk/tracing.html) for diagnosing runs with unterminated action (e.g. model calls, docker commands, etc.).
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
- Scoring: When using a dictionary to map metrics to score value dictionaries, you may now use globs as keys. See our [scorer documentation](https://inspect.aisi.org.uk/scorers.html#sec-multiple-scorers) for more information.
- `EvalLog` now includes a [location](https://github.com/UKGovernmentBEIS/inspect_ai/pull/872) property indicating where it was read from.
- Use [tool views](https://inspect.aisi.org.uk/approval.html#tool-views) when rendering tool calls in Inspect View.
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
- Scoring: When using a dictionary to map metrics to score value dictionaries, you may now use globs as keys. See our [scorer documentation](https://inspect.aisi.org.uk/scorers.html#sec-multiple-scorers) for more information.
- Sample limit events will now appear in the transcript if a limit (e.g. message, token, or time limit) halt a sample. The sample list and sample detail also display the limit, if applicable.

## v0.3.46 (12 November 2024)

- [eval](https://inspect.aisi.org.uk/eval-logs.html#sec-log-format) is now the default log format (use `--log-format=json` to use old format).
- Base 64 images are now logged by default for all log formats (disable with `--no-log-images`).
- The log viewer now properly displays sample errors in the sample list for `eval` format log files.
- Improve path handling when using `inspect log convert` to convert a single log file.
- Web browser tool: Subtasks now each have independent web browser sessions.
- Anthropic: Ensure that assistant messages created in generate never have empty content lists.
- Increase sandbox `exec()` output limit from 1 MiB to 10 MiB.

## v0.3.45 (11 November 2024)

- [time_limit](https://inspect.aisi.org.uk/errors_and_limits.html#sample-limits) option for specifying a maximum execution time for samples.
- [read_eval_log_samples()](https://inspect.aisi.org.uk/eval-logs.html#streaming) function for streaming reads of `.eval` log files.
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

- New binary [log format](https://inspect.aisi.org.uk/eval-logs.html#sec-log-format) which yields substantial size and speed improvements (JSON format log files are still fully supported and utilities for converting between the formats are provided).
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

- [ToolDef](https://inspect.aisi.org.uk/tools-custom.html#sec-dynamic-tools) class for dynamically creating tool definitions.
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

- [Approval mode](https://inspect.aisi.org.uk/approval.html) for extensible approvals of tool calls (human and auto-approvers built in,  arbitrary other approval schemes via extensions).
- [Trace mode](https://inspect.aisi.org.uk/interactivity.html#sec-trace-mode) for printing model interactions to the terminal.
- Add `as_dict()` utility method to `Score`
- [Sample limits](https://inspect.aisi.org.uk/errors_and_limits.html#sample-limits) (`token_limit` and `message_limit`) for capping the number of tokens or messages used per sample ( `message_limit` replaces deprecated `max_messages`).
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

- [Web Browser](https://inspect.aisi.org.uk/tools-standard.html#sec-web-browser) tool which provides a headless Chromium browser that supports navigation, history, and mouse/keyboard interactions.
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

- Added `fork()` function to fork a `TaskState` and evaluate it against multiple solvers in parallel.
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

- [basic_agent()](https://inspect.aisi.org.uk/agents.html#sec-basic-agent) that provides a ReAct tool loop with support for retries and encouraging the model to continue if its gives up or gets stuck.
- [score()](https://inspect.aisi.org.uk/solvers.html#sec-scoring-in-solvers) function for accessing scoring logic from within solvers.
- Ability to [publish](https://inspect.aisi.org.uk/log-viewer.html#sec-publishing) a static standalone Inspect View website for a log directory.
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

- [Eval Sets](https://inspect.aisi.org.uk/eval-sets.html) for running groups of tasks with automatic retries.
- [Per-sample](https://inspect.aisi.org.uk/sandboxing.html#sec-per-sample-sandbox) Sandbox environments can now be specified (e.g. allowing for a distinct Dockerfile or Docker compose file for each sample).
- [input_screen()](https://inspect.aisi.org.uk/interactivity.html) context manager to temporarily clear task display for user input.
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

- `Store` for manipulating arbitrary sample state from within solvers and tools.
- `Transcripts` for detailed sample level tracking of model and tool calls, state changes, logging, etc.
- `Subtasks` for delegating work to helper models, sub-agents, etc.
- Integration with Anthropic [prompt caching](https://inspect.aisi.org.uk/caching.html#sec-provider-caching).
- [fail_on_error](https://inspect.aisi.org.uk/errors-and-limits.html#failure-threshold) option to tolerate some threshold of sample failures without failing the evaluation.
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

- [vLLM](https://inspect.aisi.org.uk/models.html#sec-vllm) model provider.
- [Groq](https://groq.com/) model provider.
- [Google Vertex](https://inspect.aisi.org.uk/models.html#google-vertex) model provider.
- [Reduce scores](https://inspect.aisi.org.uk/scorers.html##sec-reducing-epoch) in multi-epoch tasks before computing metrics (defaults to averaging sample values).
- Replace the use of the `bootstrap_std` metric with `stderr` for built in scorers (see [rationale](https://inspect.aisi.org.uk/scorers.html#stderr-note) for details).
- Option to write Python logger entries to an [external file](https://inspect.aisi.org.uk/log-viewer.html#sec-external-file).
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

- [Multiple Scorers](https://inspect.aisi.org.uk/scorers.html#sec-multiple-scorers) are now supported for evaluation tasks.
- [Multiple Models](https://inspect.aisi.org.uk/parallelism.html#sec-multiple-models) can now be evaluated in parallel by passing a list of models to `eval()`.
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

-   [Sandbox Environments](https://inspect.aisi.org.uk/sandboxing.html) for executing tool code in a sandbox.
-   [Caching](https://inspect.aisi.org.uk/caching.html) to reduce the number of model API calls made.
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
