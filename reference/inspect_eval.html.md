# inspect_eval – Inspect

Evaluate tasks.

Monitor a running eval from another shell with `inspect ctl` (see `inspect ctl --help`).

#### Usage

``` text
inspect eval [OPTIONS] [TASKS]...
```

#### Options

| Name | Type | Description | Default |
|----|----|----|----|
| `--json` | boolean | Emit machine-readable launch output as JSON lines on stdout (implies –display none): a ‘launch’ record printed once the control-channel server is bound — reporting run_id, pid, log_dir, and the control socket path (‘control’ is null when the server is disabled or failed to bind, so its presence guarantees `inspect ctl` is usable) — and a ‘done’ record with each task’s log location and status when the eval finishes. To launch in the background instead, use –detach (which implies –json). | `False` |
| `--detach` / `--no-detach` | boolean | Run the eval in the background: prints the launch record (implies –json) once the control endpoint is bound, then returns, leaving the eval running detached from the terminal (the detached process’s output goes to a file reported as ‘output_file’ in the launch record). While it runs, monitor with `inspect ctl task list` and cancel with `inspect ctl task cancel`. The process exits when the eval finishes, leaving a ‘done’ record — overall success plus each task’s status and log_location — as the output file’s last line; a process that exited without one died mid-run, with diagnostics in the same file. Pass –ctl-server=keep to instead keep the process alive (and queryable via `inspect ctl`) after the eval finishes, until `inspect ctl process release`. | `False` |
| `--model` | text | Model used to evaluate tasks. | `Sentinel.UNSET` |
| `--model-base-url` | text | Base URL for for model API | `Sentinel.UNSET` |
| `-M` | text | One or more native model arguments (e.g. -M arg=value) | `Sentinel.UNSET` |
| `--model-config` | text | YAML or JSON config file with model arguments. | `Sentinel.UNSET` |
| `--model-spec` | text | Model to evaluate along with its own generate config, model args, and base url, as inline YAML or JSON, e.g. –model-spec “{model: openai/gpt-4o, temperature: 0}” (same fields as –model-role, plus base_url). Repeat the option to evaluate several models, each with its own options. Cannot be combined with –model, –model-base-url, –model-config, or -M. | `Sentinel.UNSET` |
| `--run-config` | text | YAML or JSON file with full run configuration (task, model, model roles, generate config, solver, eval config). CLI flags override values from this file. Cannot be combined with –generate-config, –task-config, or –solver-config. | `Sentinel.UNSET` |
| `--model-role` | text | Named model role with model name or YAML/JSON config, e.g. –model-role critic=openai/gpt-4o or –model-role grader=“{model: mockllm/model, temperature: 0.5}”. Bind multiple models to a role with a comma-separated list of names or a YAML/JSON list of configs, e.g. –model-role grader=openai/gpt-4o,google/gemini-2.0-flash | `Sentinel.UNSET` |
| `-T` | text | One or more task arguments (e.g. -T arg=value) | `Sentinel.UNSET` |
| `--task-config` | text | YAML or JSON config file with task arguments. | `Sentinel.UNSET` |
| `--solver` | text | Solver to execute (overrides task default solver) | `Sentinel.UNSET` |
| `-S` | text | One or more solver arguments (e.g. -S arg=value) | `Sentinel.UNSET` |
| `--solver-config` | text | YAML or JSON config file with solver arguments. | `Sentinel.UNSET` |
| `--scanner` | text | Scanner(s) to apply after each sample. Pass a YAML/JSON config file (ScannerConfig schema), a Python file with @scanner functions (use <file.py@func> to pick one), or a registry reference (pkg/name). | `Sentinel.UNSET` |
| `--scanner-arg` | text | One or more scanner arguments (e.g. –scanner-arg key=value). | `Sentinel.UNSET` |
| `--scans` | text | Location to write scan results to (defaults to /scans/). | `Sentinel.UNSET` |
| `--scan-name` | text | Scan name written to \_scan.json (defaults to “eval_set”). | `Sentinel.UNSET` |
| `--scan-tags` | text | Comma-separated tags written to the scan spec. | `Sentinel.UNSET` |
| `--scan-metadata` | text | Metadata written to the scan spec (e.g. –scan-metadata key=value). | `Sentinel.UNSET` |
| `-F`, `--scan-filter` | text | SQL WHERE clause(s) applied per-sample to skip transcripts that don’t match (e.g. -F “error = ’’”). | `Sentinel.UNSET` |
| `--scan-model` | text | Model used by scanners’ get_model() (overrides the eval model). | `Sentinel.UNSET` |
| `--scan-model-base-url` | text | Base URL for the scanner-side model API. | `Sentinel.UNSET` |
| `--scan-model-arg` | text | One or more scanner-side model arguments (e.g. –scan-model-arg key=value). | `Sentinel.UNSET` |
| `--scan-model-config` | text | YAML or JSON config file with scanner-side model arguments. | `Sentinel.UNSET` |
| `--scan-model-role` | text | Named scanner-side model role with model name or YAML/JSON config (e.g. –scan-model-role grader=mockllm/model). Bind multiple models to a role with a comma-separated list of names or a YAML/JSON list of configs. | `Sentinel.UNSET` |
| `--scan-generate-config` | text | YAML or JSON config file with GenerateConfig for scanner model calls. | `Sentinel.UNSET` |
| `--tags` | text | Tags to associate with this evaluation run. | `Sentinel.UNSET` |
| `--metadata` | text | Metadata to associate with this evaluation run (more than one –metadata argument can be specified). | `Sentinel.UNSET` |
| `--approval` | text | Config file for tool call approval. | `Sentinel.UNSET` |
| `--notification` | text | Send out-of-band notifications when a human-in-the-loop interaction (`ask_user` or human approval) is posted. Bare `--notification` reads URL(s) from the `INSPECT_EVAL_NOTIFICATION` environment variable (a single Apprise URL, a comma-separated list, or a path to an Apprise config file). `--notification <path>` reads from an Apprise YAML/text config file. URLs are not accepted directly on the command line so secrets never end up in shell history. Requires `pip install apprise`. | None |
| `--sandbox` | text | Sandbox environment type (with optional config file). e.g. ‘docker’ or ‘docker:compose.yml’ | `Sentinel.UNSET` |
| `--no-sandbox-cleanup` | boolean | Do not cleanup sandbox environments after task completes | `False` |
| `--sandbox-prebuilt` | boolean | Treat sandbox images as prebuilt (skip builds and fail at startup when an image is missing) | `False` |
| `--checkpoint` | text | Periodically checkpoint sample state so the eval can be resumed via `inspect eval retry`. Specify –checkpoint for the default (every 500k tokens), –checkpoint=token:N{k,m,b} / time:N{s,m,h,d} / <turn:N> / manual for a shorthand trigger, or pass a YAML/JSON file path for a full CheckpointConfig. | None |
| `--acp-server` | text | Expose this eval via an Agent Client Protocol server for various clients (e.g. the `inspect acp` command). Bare flag enables a default AF_UNIX socket; pass an integer to bind a TCP loopback port (e.g. `--acp-server=4444`); pass `host:port` to bind on a specific interface (e.g. `--acp-server=0.0.0.0:4444`); pass a filesystem path for a custom UNIX socket. When this flag is set, all human-in-the-loop interactions (`approver: human` and the `ask_user` tool) route exclusively through attached ACP clients; the in-proc Textual panel and console handlers are bypassed. If no client is connected when an interaction fires, the eval parks until one attaches. | None |
| `--ctl-server` | text | Control-channel server for this eval process (default: enabled on an AF_UNIX socket — the endpoint the `inspect ctl` CLI, scripted agents, and TUIs query). Pass `false` to disable it. Pass `keep` to also keep the process running after the eval finishes so its state and results stay readable; the process exits when `inspect ctl process release` is run (or POST /release is sent to the control endpoint). Without `keep` the process exits as soon as the eval body returns, taking the control surface with it. Observe the run from another shell with `inspect ctl task list`. | None |
| `--limit` | text | Limit samples to evaluate e.g. 10 or 10-20 | `Sentinel.UNSET` |
| `--sample-id` | text | Evaluate specific sample(s) (comma separated list of ids) | `Sentinel.UNSET` |
| `--sample-shuffle` | text | Shuffle order of samples (pass a seed to make the order deterministic) | None |
| `--epochs` | integer | Number of times to repeat dataset (defaults to 1) | `Sentinel.UNSET` |
| `--epochs-reducer` | text | Method for reducing per-epoch sample scores into a single score. Built in reducers include ‘mean’, ‘median’, ‘mode’, ‘max’, and ‘at_least\_{n}’. | `Sentinel.UNSET` |
| `--no-epochs-reducer` | boolean | Do not reduce per-epoch sample scores. | `False` |
| `--max-connections` | integer | Maximum number of concurrent connections to Model API (defaults to 10) | `Sentinel.UNSET` |
| `--adaptive-connections` | text | Adaptive concurrency for Model API connections, automatically scaling between bounds based on rate-limit feedback (default: enabled, with min=10, start=20, max=100). Pass `false` to opt out, an integer N for a custom max (e.g. `200`), or bounds as `min-max` (e.g. `4-80`) or `min-start-max` (e.g. `4-20-80`). Explicit `--max-connections` and `--batch` take precedence. | None |
| `--max-retries` | integer | Maximum number of times to retry model API requests (defaults to unlimited) | `Sentinel.UNSET` |
| `--timeout` | integer | Model API request timeout in seconds (defaults to no timeout) | `Sentinel.UNSET` |
| `--attempt-timeout` | integer | Timeout (in seconds) for any given attempt (if exceeded, will abandon attempt and retry according to max_retries). | `Sentinel.UNSET` |
| `--max-samples` | integer | Maximum number of samples to run in parallel (default is running all samples in parallel) | `Sentinel.UNSET` |
| `--max-dataset-memory` | integer range (`0` and above) | Maximum MB of dataset sample data to hold in memory per task. When exceeded, samples are paged to disk. | `Sentinel.UNSET` |
| `--max-tasks` | integer | Maximum number of tasks to run in parallel (default is 1 for eval and 10 for eval-set) | `Sentinel.UNSET` |
| `--max-subprocesses` | integer | Maximum number of subprocesses to run in parallel (default is os.cpu_count()) | `Sentinel.UNSET` |
| `--max-sandboxes` | integer | Maximum number of sandboxes (per-provider) to run in parallel. | `Sentinel.UNSET` |
| `--message-limit` | integer | Limit on total messages used for each sample. | `Sentinel.UNSET` |
| `--token-limit` | text | Limit on tokens used for each sample (e.g. 500000, ‘500k’, or ‘1m’; prefix with ‘output:’ to limit only output tokens, e.g. ‘output:1m’, or with a formula over ‘input’/‘output’, e.g. ’(input\*0.1)+output:1m’). | `Sentinel.UNSET` |
| `--turn-limit` | integer | Limit on total turns (model generations) used for each sample. | `Sentinel.UNSET` |
| `--cost-limit` | float | Limit on total cost (in dollars) for each sample. | `Sentinel.UNSET` |
| `--model-cost-config` | text | YAML or JSON file with model prices for cost tracking. | `Sentinel.UNSET` |
| `--time-limit` | integer | Limit on total running time for each sample. | `Sentinel.UNSET` |
| `--working-limit` | integer | Limit on total working time (e.g. model generation, tool calls, etc.) for each sample. | `Sentinel.UNSET` |
| `--fail-on-error` | float | Threshold of sample errors to tolerage (by default, evals fail when any error occurs). Value between 0 to 1 to set a proportion; value greater than 1 to set a count. | `Sentinel.UNSET` |
| `--no-fail-on-error` | boolean | Do not fail the eval if errors occur within samples (instead, continue running other samples) | `False` |
| `--continue-on-fail` | boolean | Do not immediately fail the eval if the error threshold is exceeded (instead, continue running other samples until the eval completes, and then possibly fail the eval). | None |
| `--retry-on-error` | text | Retry samples if they encounter errors (by default, no retries occur). Specify –retry-on-error to retry a single time, or specify e.g. `--retry-on-error=3` to retry multiple times. | None |
| `--score-on-error` | boolean | Score samples that error rather than failing the eval mid-run. Errors still count toward the –fail-on-error threshold for marking the log as ‘error’. Only fires after retries (if any) are exhausted. | None |
| `--no-log-samples` | boolean | Do not include samples in the log file. | `False` |
| `--no-log-realtime` | boolean | Do not log events in realtime (affects live viewing of samples in inspect view) | `False` |
| `--log-images` / `--no-log-images` | boolean | Retain inline image and other media bytes in the log file. This option does not control media fetching. | `True` |
| `--log-model-api` / `--no-log-model-api` | boolean | Log raw model api requests and responses. Note that error requests/responses are always logged. | None |
| `--log-refusals` / `--no-log-refusals` | boolean | Log warnings for model refusals. | `False` |
| `--log-buffer` | integer | Number of samples to buffer before writing log file. If not specified, an appropriate default for the format and filesystem is chosen (10 for most all cases, 100 for JSON logs on remote filesystems). | `Sentinel.UNSET` |
| `--log-shared` | text | Sync sample events to log directory so that users on other systems can see log updates in realtime (defaults to no syncing). If enabled will sync every 10 seconds (or pass a value to sync every `n` seconds). | None |
| `--no-score` | boolean | Do not score model output (use the inspect score command to score output later) | `False` |
| `--no-score-display` | boolean | Do not display scoring metrics in realtime. | `False` |
| `--generate-config` | text | YAML or JSON config file with GenerateConfig (alternatively, use the options for individual config values). | `Sentinel.UNSET` |
| `--max-tokens` | integer | The maximum number of tokens that can be generated in the completion (default is model specific) | `Sentinel.UNSET` |
| `--system-message` | text | Override the default system message. | `Sentinel.UNSET` |
| `--best-of` | integer | Generates best_of completions server-side and returns the ‘best’ (the one with the highest log probability per token). OpenAI only. | `Sentinel.UNSET` |
| `--frequency-penalty` | float | Number between -2.0 and 2.0. Positive values penalize new tokens based on their existing frequency in the text so far, decreasing the model’s likelihood to repeat the same line verbatim. OpenAI, Google, Grok, Groq, llama-cpp-python and vLLM only. | `Sentinel.UNSET` |
| `--presence-penalty` | float | Number between -2.0 and 2.0. Positive values penalize new tokens based on whether they appear in the text so far, increasing the model’s likelihood to talk about new topics. OpenAI, Google, Grok, Groq, llama-cpp-python and vLLM only. | `Sentinel.UNSET` |
| `--logit-bias` | text | Map token Ids to an associated bias value from -100 to 100 (e.g. “42=10,43=-10”). OpenAI, Grok, and Grok only. | `Sentinel.UNSET` |
| `--seed` | integer | Random seed. OpenAI, Google, Groq, Mistral, HuggingFace, and vLLM only. | `Sentinel.UNSET` |
| `--stop-seqs` | text | Sequences where the API will stop generating further tokens. The returned text will not contain the stop sequence. | `Sentinel.UNSET` |
| `--temperature` | float | What sampling temperature to use, between 0 and 2. Higher values like 0.8 will make the output more random, while lower values like 0.2 will make it more focused and deterministic. | `Sentinel.UNSET` |
| `--top-p` | float | An alternative to sampling with temperature, called nucleus sampling, where the model considers the results of the tokens with top_p probability mass. | `Sentinel.UNSET` |
| `--top-k` | integer | Randomly sample the next word from the top_k most likely next words. Anthropic, Google, HuggingFace, and vLLM only. | `Sentinel.UNSET` |
| `--num-choices` | integer | How many chat completion choices to generate for each input message. OpenAI, Grok, Google, TogetherAI, and vLLM only. | `Sentinel.UNSET` |
| `--logprobs` | boolean | Return log probabilities of the output tokens. OpenAI, Google, TogetherAI, Huggingface, llama-cpp-python, and vLLM only. | `False` |
| `--top-logprobs` | integer | Number of most likely tokens (0-20) to return at each token position, each with an associated log probability. OpenAI, Google, TogetherAI, Huggingface, and vLLM only. | `Sentinel.UNSET` |
| `--prompt-logprobs` | integer | Number of log probabilities to return per prompt token (1-20). vLLM only. | `Sentinel.UNSET` |
| `--parallel-tool-calls` / `--no-parallel-tool-calls` | boolean | Whether to enable parallel function calling during tool use (defaults to True) OpenAI and Groq only. | `True` |
| `--internal-tools` / `--no-internal-tools` | boolean | Whether to automatically map tools to model internal implementations (e.g. ‘computer’ for anthropic). | `True` |
| `--max-tool-output` | integer | Maximum size of tool output (in bytes). Defaults to 16 \* 1024. | `Sentinel.UNSET` |
| `--cache-prompt` | choice (`auto` \| `true` \| `false`) | Whether to cache the prompt prefix. Enabled by default. Set to False to disable. Anthropic only. | `Sentinel.UNSET` |
| `--fallback-models` | text | Fallback models (comma-separated, tried in order) when the model’s safety classifiers refuse the request. Anthropic Claude API only. | `Sentinel.UNSET` |
| `--verbosity` | choice (`low` \| `medium` \| `high`) | Constrains the verbosity of the model’s response. Lower values will result in more concise responses, while higher values will result in more verbose responses. GPT 5.x models only (defaults to “medium” for OpenAI models) | `Sentinel.UNSET` |
| `--effort` | choice (`low` \| `medium` \| `high` \| `xhigh` \| `max`) | Control how many tokens are used for a response, trading off between response thoroughness and token efficiency. Claude 4.5, 4.6, 4.7 only (`max` only supported on 4.6+, `xhigh` only supported on 4.7). | `Sentinel.UNSET` |
| `--reasoning-effort` | choice (`none` \| `minimal` \| `low` \| `medium` \| `high` \| `xhigh` \| `max`) | Constrains effort on reasoning. Defaults vary by provider and model and not all models support all values (please consult provider documentation for details). | `Sentinel.UNSET` |
| `--reasoning-mode` | choice (`standard` \| `pro`) | Reasoning mode. “pro” performs more model work for greater reliability on difficult tasks, at higher latency and token usage. OpenAI GPT-5.6+ models only (“standard” is the default). | `Sentinel.UNSET` |
| `--reasoning-tokens` | integer | Maximum number of tokens to use for reasoning. Anthropic Claude models only. | `Sentinel.UNSET` |
| `--reasoning-summary` | choice (`none` \| `concise` \| `detailed` \| `auto`) | Provide summary of reasoning steps (OpenAI reasoning models only). Use ‘auto’ to access the most detailed summarizer available for the current model (defaults to ‘auto’ if your organization is verified by OpenAI). | `Sentinel.UNSET` |
| `--reasoning-history` | choice (`none` \| `all` \| `last` \| `auto`) | Include reasoning in chat message history sent to generate (defaults to “auto”, which uses the recommended default for each provider) | `Sentinel.UNSET` |
| `--response-schema` | text | JSON schema for desired response format (output should still be validated). OpenAI, Google, and Mistral only. | `Sentinel.UNSET` |
| `--cache` | text | Policy for caching of model generations. Specify –cache to cache with 7 day expiration (7D). Specify an explicit duration (e.g. (e.g. 1h, 3d, 6M) to set the expiration explicitly (durations can be expressed as s, m, h, D, W, M, or Y). Alternatively, pass the file path to a YAML or JSON config file with a full [CachePolicy](../reference/inspect_ai.model.html.md#cachepolicy) configuration. | None |
| `--batch` | text | Batch requests together to reduce API calls when using a model that supports batching (by default, no batching). Specify –batch to batch with default configuration, specify a batch size e.g. `--batch=1000` to configure batches of 1000 requests, or pass the file path to a YAML or JSON config file with batch configuration. | None |
| `--modalities` | text | Additional output modalities beyond text (e.g. ‘image’). Comma-separated names or a YAML/JSON config file path. OpenAI and Google only. | `Sentinel.UNSET` |
| `--log-format` | choice (`eval` \| `json`) | Format for writing log files. | `Sentinel.UNSET` |
| `--log-level-transcript` | choice (`debug` \| `trace` \| `http` \| `info` \| `warning` \| `error` \| `critical` \| `notset`) | Set the log level of the transcript (defaults to ‘info’) | `info` |
| `--log-level` | choice (`debug` \| `trace` \| `http` \| `info` \| `warning` \| `error` \| `critical` \| `notset`) | Set the log level (defaults to ‘warning’) | `warning` |
| `--log-dir` | text | Directory for log files. | `./logs` |
| `--display` | choice (`full` \| `conversation` \| `rich` \| `plain` \| `log` \| `none`) | Set the display type (defaults to ‘full’) | `full` |
| `--traceback-locals` | boolean | Include values of local variables in tracebacks (note that this can leak private data e.g. API keys so should typically only be enabled for targeted debugging). | `False` |
| `--env` | text | Define an environment variable e.g. –env NAME=value (–env can be specified multiple times) | `Sentinel.UNSET` |
| `--debug` | boolean | Wait to attach debugger | `False` |
| `--debug-port` | integer | Port number for debugger | `5678` |
| `--debug-errors` | boolean | Raise task errors (rather than logging them) so they can be debugged. | `False` |
| `--help` | boolean | Show this message and exit. | `False` |
