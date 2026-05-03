# inspect_ai – Inspect

## Evaluation

### eval

Evaluate tasks using a Model.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/36eecc0b14b68251ce2dc513bcff43c82cef2555/src/inspect_ai/_eval/eval.py#L90)

``` python
def eval(
    tasks: Tasks,
    model: str | Model | list[str] | list[Model] | None | NotGiven = ...,
    model_base_url: str | None = ...,
    model_args: dict[str, Any] | str = ...,
    model_roles: dict[str, str | Model] | None = ...,
    task_args: dict[str, Any] | str = ...,
    sandbox: SandboxEnvironmentType | None = ...,
    sandbox_cleanup: bool | None = ...,
    solver: Solver | SolverSpec | Agent | list[Solver] | None = ...,
    tags: list[str] | None = ...,
    metadata: dict[str, Any] | None = ...,
    trace: bool | None = ...,
    display: DisplayType | None = ...,
    approval: str | list[ApprovalPolicy] | ApprovalPolicyConfig | None = ...,
    log_level: str | None = ...,
    log_level_transcript: str | None = ...,
    log_dir: str | None = ...,
    log_format: Literal['eval', 'json'] | None = ...,
    limit: int | tuple[int, int] | None = ...,
    sample_id: str | int | list[str] | list[int] | list[str | int] | None = ...,
    sample_shuffle: bool | int | None = ...,
    epochs: int | Epochs | None = ...,
    fail_on_error: bool | float | None = ...,
    continue_on_fail: bool | None = ...,
    retry_on_error: int | None = ...,
    score_on_error: bool | None = ...,
    debug_errors: bool | None = ...,
    message_limit: int | None = ...,
    token_limit: int | None = ...,
    time_limit: int | None = ...,
    working_limit: int | None = ...,
    cost_limit: float | None = ...,
    model_cost_config: str | dict[str, ModelCost] | None = ...,
    max_samples: int | None = ...,
    max_dataset_memory: int | None = ...,
    max_tasks: int | None = ...,
    max_subprocesses: int | None = ...,
    max_sandboxes: int | None = ...,
    log_samples: bool | None = ...,
    log_realtime: bool | None = ...,
    log_images: bool | None = ...,
    log_model_api: bool | None = ...,
    log_refusals: bool | None = ...,
    log_buffer: int | None = ...,
    log_shared: bool | int | None = ...,
    log_header_only: bool | None = ...,
    run_samples: bool = ...,
    score: bool = ...,
    score_display: bool | None = ...,
    eval_set_id: str | None = ...,
    task_retry_attempts: int | None = ...,
    *,
    max_retries: int | None = ...,
    timeout: int | None = ...,
    attempt_timeout: int | None = ...,
    max_connections: int | None = ...,
    adaptive_connections: bool | AdaptiveConcurrency | None = ...,
    system_message: str | None = ...,
    max_tokens: int | None = ...,
    top_p: float | None = ...,
    temperature: float | None = ...,
    stop_seqs: list[str] | None = ...,
    best_of: int | None = ...,
    frequency_penalty: float | None = ...,
    presence_penalty: float | None = ...,
    logit_bias: dict[int, float] | None = ...,
    seed: int | None = ...,
    top_k: int | None = ...,
    num_choices: int | None = ...,
    logprobs: bool | None = ...,
    top_logprobs: int | None = ...,
    prompt_logprobs: int | None = ...,
    parallel_tool_calls: bool | None = ...,
    internal_tools: bool | None = ...,
    max_tool_output: int | None = ...,
    cache_prompt: Literal['auto'] | bool | None = ...,
    verbosity: Literal['low', 'medium', 'high'] | None = ...,
    effort: Literal['low', 'medium', 'high', 'xhigh', 'max'] | None = ...,
    reasoning_effort: Literal['none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max'] | None = ...,
    reasoning_tokens: int | None = ...,
    reasoning_summary: Literal['none', 'concise', 'detailed', 'auto'] | None = ...,
    reasoning_history: Literal['none', 'all', 'last', 'auto'] | None = ...,
    response_schema: ResponseSchema | None = ...,
    extra_headers: dict[str, str] | None = ...,
    extra_body: dict[str, Any] | None = ...,
    modalities: list[OutputModality] | None = ...,
    cache: bool | CachePolicy | None = ...,
    batch: bool | int | BatchConfig | None = ...,
) -> list[EvalLog]
```

`tasks` [Tasks](../reference/inspect_ai.html.md#tasks)  
Task(s) to evaluate. If None, attempt to evaluate a task in the current working directory

`model` str \| [Model](../reference/inspect_ai.model.html.md#model) \| list\[str\] \| list\[[Model](../reference/inspect_ai.model.html.md#model)\] \| None \| NotGiven  
Model(s) for evaluation. If not specified use the value of the INSPECT_EVAL_MODEL environment variable. Specify `None` to define no default model(s), which will leave model usage entirely up to tasks.

`model_base_url` str \| None  
Base URL for communicating with the model API.

`model_args` dict\[str, Any\] \| str  
Model creation args (as a dictionary or as a path to a JSON or YAML config file)

`model_roles` dict\[str, str \| [Model](../reference/inspect_ai.model.html.md#model)\] \| None  
Named roles for use in [get_model()](../reference/inspect_ai.model.html.md#get_model).

`task_args` dict\[str, Any\] \| str  
Task creation arguments (as a dictionary or as a path to a JSON or YAML config file)

`sandbox` SandboxEnvironmentType \| None  
Sandbox environment type (or optionally a str or tuple with a shorthand spec)

`sandbox_cleanup` bool \| None  
Cleanup sandbox environments after task completes (defaults to True)

`solver` [Solver](../reference/inspect_ai.solver.html.md#solver) \| [SolverSpec](../reference/inspect_ai.solver.html.md#solverspec) \| [Agent](../reference/inspect_ai.agent.html.md#agent) \| list\[[Solver](../reference/inspect_ai.solver.html.md#solver)\] \| None  
Alternative solver for task(s). Optional (uses task solver by default).

`tags` list\[str\] \| None  
Tags to associate with this evaluation run.

`metadata` dict\[str, Any\] \| None  
Metadata to associate with this evaluation run.

`trace` bool \| None  
Trace message interactions with evaluated model to terminal.

`display` [DisplayType](../reference/inspect_ai.util.html.md#displaytype) \| None  
Task display type (defaults to ‘full’).

`approval` str \| list\[[ApprovalPolicy](../reference/inspect_ai.approval.html.md#approvalpolicy)\] \| ApprovalPolicyConfig \| None  
Tool use approval policies. Either a path to an approval policy config file, an ApprovalPolicyConfig, or a list of approval policies. Defaults to no approval policy.

`log_level` str \| None  
Level for logging to the console: “debug”, “http”, “sandbox”, “info”, “warning”, “error”, “critical”, or “notset” (defaults to “warning”)

`log_level_transcript` str \| None  
Level for logging to the log file (defaults to “info”)

`log_dir` str \| None  
Output path for logging results (defaults to file log in ./logs directory).

`log_format` Literal\['eval', 'json'\] \| None  
Format for writing log files (defaults to “eval”, the native high-performance format).

`limit` int \| tuple\[int, int\] \| None  
Limit evaluated samples (defaults to all samples).

`sample_id` str \| int \| list\[str\] \| list\[int\] \| list\[str \| int\] \| None  
Evaluate specific sample(s) from the dataset. Use plain ids or preface with task names as required to disambiguate ids across tasks (e.g. `popularity:10`)..

`sample_shuffle` bool \| int \| None  
Shuffle order of samples (pass a seed to make the order deterministic).

`epochs` int \| [Epochs](../reference/inspect_ai.html.md#epochs) \| None  
Epochs to repeat samples for and optional score reducer function(s) used to combine sample scores (defaults to “mean”)

`fail_on_error` bool \| float \| None  
`True` to fail on first sample error (default); `False` to never fail on sample errors; Value between 0 and 1 to fail if a proportion of total samples fails. Value greater than 1 to fail eval if a count of samples fails.

`continue_on_fail` bool \| None  
`True` to continue running and only fail at the end if the `fail_on_error` condition is met. `False` to fail eval immediately when the `fail_on_error` condition is met (default).

`retry_on_error` int \| None  
Number of times to retry samples if they encounter errors (by default, no retries occur).

`score_on_error` bool \| None  
Score samples that error rather than failing the eval mid-run. Errors still count toward the `fail_on_error` threshold for marking the eval log as ‘error’. Only takes effect after retries (if any) are exhausted.

`debug_errors` bool \| None  
Raise task errors (rather than logging them) so they can be debugged (defaults to False).

`message_limit` int \| None  
Limit on total messages used for each sample.

`token_limit` int \| None  
Limit on total tokens used for each sample.

`time_limit` int \| None  
Limit on clock time (in seconds) for samples.

`working_limit` int \| None  
Limit on working time (in seconds) for sample. Working time includes model generation, tool calls, etc. but does not include time spent waiting on retries or shared resources.

`cost_limit` float \| None  
Limit on total cost (in dollars) for each sample. Requires model cost data via set_model_cost() or –model-cost-config.

`model_cost_config` str \| dict\[str, [ModelCost](../reference/inspect_ai.model.html.md#modelcost)\] \| None  
YAML or JSON file with model prices for cost tracking or dict of model -\> [ModelCost](../reference/inspect_ai.model.html.md#modelcost)

`max_samples` int \| None  
Maximum number of samples to run in parallel (default is max_connections)

`max_dataset_memory` int \| None  
Maximum MB of dataset sample data to hold in memory per task. When exceeded, samples are paged to a temporary file on disk (defaults to None, which keeps all samples in memory).

`max_tasks` int \| None  
Maximum number of tasks to run in parallel (defaults to number of models being evaluated)

`max_subprocesses` int \| None  
Maximum number of subprocesses to run in parallel (default is os.cpu_count())

`max_sandboxes` int \| None  
Maximum number of sandboxes (per-provider) to run in parallel.

`log_samples` bool \| None  
Log detailed samples and scores (defaults to True)

`log_realtime` bool \| None  
Log events in realtime (enables live viewing of samples in inspect view). Defaults to True.

`log_images` bool \| None  
Log base64 encoded version of images, even if specified as a filename or URL (defaults to False)

`log_model_api` bool \| None  
Log raw model api requests and responses. True logs all calls, False logs only errors, None (default) logs the first few calls per model plus errors.

`log_refusals` bool \| None  
Log warnings for model refusals.

`log_buffer` int \| None  
Number of samples to buffer before writing log file. If not specified, an appropriate default for the format and filesystem is chosen (10 for most all cases, 100 for JSON logs on remote filesystems).

`log_shared` bool \| int \| None  
Sync sample events to log directory so that users on other systems can see log updates in realtime (defaults to no syncing). Specify `True` to sync every 10 seconds, otherwise an integer to sync every `n` seconds.

`log_header_only` bool \| None  
If `True`, the function should return only log headers rather than full logs with samples (defaults to `False`).

`run_samples` bool  
Run samples. If `False`, a log with `status=="started"` and an empty `samples` list is returned.

`score` bool  
Score output (defaults to True)

`score_display` bool \| None  
Show scoring metrics in realtime (defaults to True)

`eval_set_id` str \| None  
Unique id for eval set (this is passed from [eval_set()](../reference/inspect_ai.html.md#eval_set) and should not be specified directly).

`task_retry_attempts` int \| None  
Number of times to retry tasks (defaults to 0)

`max_retries` int \| None  
Maximum number of times to retry request (defaults to unlimited).

`timeout` int \| None  
Request timeout (in seconds).

`attempt_timeout` int \| None  
Timeout (in seconds) for any given attempt (if exceeded, will abandon attempt and retry according to max_retries).

`max_connections` int \| None  
Maximum number of concurrent connections to Model API (default is model specific).

`adaptive_connections` bool \| [AdaptiveConcurrency](../reference/inspect_ai.util.html.md#adaptiveconcurrency) \| None  
Enable adaptive concurrency for model API connections. `True` for defaults (min=4, start=20, max=200), or pass [AdaptiveConcurrency](../reference/inspect_ai.util.html.md#adaptiveconcurrency) to customize bounds and tuning (cooldown_seconds, decrease_factor, scale_up_percent). An explicit `max_connections` overrides this and uses static concurrency.

`system_message` str \| None  
Override the default system message.

`max_tokens` int \| None  
The maximum number of tokens that can be generated in the completion (default is model specific).

`top_p` float \| None  
An alternative to sampling with temperature, called nucleus sampling, where the model considers the results of the tokens with top_p probability mass.

`temperature` float \| None  
What sampling temperature to use, between 0 and 2. Higher values like 0.8 will make the output more random, while lower values like 0.2 will make it more focused and deterministic.

`stop_seqs` list\[str\] \| None  
Sequences where the API will stop generating further tokens. The returned text will not contain the stop sequence.

`best_of` int \| None  
Generates best_of completions server-side and returns the ‘best’ (the one with the highest log probability per token). vLLM only.

`frequency_penalty` float \| None  
Number between -2.0 and 2.0. Positive values penalize new tokens based on their existing frequency in the text so far, decreasing the model’s likelihood to repeat the same line verbatim. OpenAI, Google, Grok, Groq, and vLLM only.

`presence_penalty` float \| None  
Number between -2.0 and 2.0. Positive values penalize new tokens based on whether they appear in the text so far, increasing the model’s likelihood to talk about new topics. OpenAI, Google, Grok, Groq, and vLLM only.

`logit_bias` dict\[int, float\] \| None  
Map token Ids to an associated bias value from -100 to 100 (e.g. “42=10,43=-10”). OpenAI and Grok only.

`seed` int \| None  
Random seed. OpenAI, Google, Mistral, Groq, HuggingFace, and vLLM only.

`top_k` int \| None  
Randomly sample the next word from the top_k most likely next words. Anthropic, Google, and HuggingFace only.

`num_choices` int \| None  
How many chat completion choices to generate for each input message. OpenAI, Grok, Google, and TogetherAI only.

`logprobs` bool \| None  
Return log probabilities of the output tokens. OpenAI, Google, Grok, TogetherAI, Huggingface, llama-cpp-python, and vLLM only.

`top_logprobs` int \| None  
Number of most likely tokens (0-20) to return at each token position, each with an associated log probability. OpenAI, Google, Grok, and Huggingface only.

`prompt_logprobs` int \| None  
Number of log probabilities to return per prompt token (1-20). When greater than 1, top-N alternative tokens are also returned. vLLM only.

`parallel_tool_calls` bool \| None  
Whether to enable parallel function calling during tool use (defaults to True). OpenAI and Groq only.

`internal_tools` bool \| None  
Whether to automatically map tools to model internal implementations (e.g. ‘computer’ for anthropic).

`max_tool_output` int \| None  
Maximum tool output (in bytes). Defaults to 16 \* 1024.

`cache_prompt` Literal\['auto'\] \| bool \| None  
Whether to cache the prompt prefix. Enabled by default. Set to False to disable. Anthropic only.

`verbosity` Literal\['low', 'medium', 'high'\] \| None  
Constrains the verbosity of the model’s response. Lower values will result in more concise responses, while higher values will result in more verbose responses. GPT 5.x models only (defaults to “medium” for OpenAI models).

`effort` Literal\['low', 'medium', 'high', 'xhigh', 'max'\] \| None  
Control how many tokens are used for a response, trading off between response thoroughness and token efficiency. Anthropic Claude Opus 4.5+ only (`max` only supported on 4.6 and 4.7, `xhigh` supported only on 4.7).

`reasoning_effort` Literal\['none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max'\] \| None  
Constrains effort on reasoning. Defaults vary by provider and model and not all models support all values (please consult provider documentation for details).

`reasoning_tokens` int \| None  
Maximum number of tokens to use for reasoning. Anthropic Claude models only.

`reasoning_summary` Literal\['none', 'concise', 'detailed', 'auto'\] \| None  
Provide summary of reasoning steps (OpenAI reasoning models only). Use ‘auto’ to access the most detailed summarizer available for the current model (defaults to ‘auto’ if your organization is verified by OpenAI).

`reasoning_history` Literal\['none', 'all', 'last', 'auto'\] \| None  
Include reasoning in chat message history sent to generate.

`response_schema` [ResponseSchema](../reference/inspect_ai.model.html.md#responseschema) \| None  
Request a response format as JSONSchema (output should still be validated). OpenAI, Google, and Mistral only.

`extra_headers` dict\[str, str\] \| None  
Extra headers to be sent with requests. Not supported for AzureAI, Bedrock, and Grok.

`extra_body` dict\[str, Any\] \| None  
Extra body to be sent with requests to OpenAI compatible servers. OpenAI, vLLM, and SGLang only.

`modalities` list\[[OutputModality](../reference/inspect_ai.model.html.md#outputmodality)\] \| None  
Additional output modalities to enable beyond text (e.g. \[“image”\]). OpenAI and Google only.

`cache` bool \| [CachePolicy](../reference/inspect_ai.model.html.md#cachepolicy) \| None  
Policy for caching of model generations.

`batch` bool \| int \| [BatchConfig](../reference/inspect_ai.model.html.md#batchconfig) \| None  
Use batching API when available. True to enable batching with default configuration, False to disable batching, a number to enable batching of the specified batch size, or a BatchConfig object specifying the batching configuration.

### eval_retry

Retry a previously failed evaluation task.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/36eecc0b14b68251ce2dc513bcff43c82cef2555/src/inspect_ai/_eval/eval.py#L844)

``` python
def eval_retry(
    tasks: str | EvalLogInfo | EvalLog | list[str] | list[EvalLogInfo] | list[EvalLog],
    log_level: str | None = None,
    log_level_transcript: str | None = None,
    log_dir: str | None = None,
    log_format: Literal["eval", "json"] | None = None,
    max_samples: int | None = None,
    max_tasks: int | None = None,
    max_subprocesses: int | None = None,
    max_sandboxes: int | None = None,
    sandbox_cleanup: bool | None = None,
    trace: bool | None = None,
    display: DisplayType | None = None,
    fail_on_error: bool | float | None = None,
    continue_on_fail: bool | None = None,
    retry_on_error: int | None = None,
    score_on_error: bool | None = None,
    debug_errors: bool | None = None,
    log_samples: bool | None = None,
    log_realtime: bool | None = None,
    log_images: bool | None = None,
    log_model_api: bool | None = None,
    log_refusals: bool | None = None,
    log_buffer: int | None = None,
    log_shared: bool | int | None = None,
    score: bool = True,
    score_display: bool | None = None,
    max_retries: int | None = None,
    timeout: int | None = None,
    attempt_timeout: int | None = None,
    max_connections: int | None = None,
    adaptive_connections: bool | AdaptiveConcurrency | None = None,
) -> list[EvalLog]
```

`tasks` str \| [EvalLogInfo](../reference/inspect_ai.log.html.md#evalloginfo) \| [EvalLog](../reference/inspect_ai.log.html.md#evallog) \| list\[str\] \| list\[[EvalLogInfo](../reference/inspect_ai.log.html.md#evalloginfo)\] \| list\[[EvalLog](../reference/inspect_ai.log.html.md#evallog)\]  
Log files for task(s) to retry.

`log_level` str \| None  
Level for logging to the console: “debug”, “http”, “sandbox”, “info”, “warning”, “error”, “critical”, or “notset” (defaults to “warning”)

`log_level_transcript` str \| None  
Level for logging to the log file (defaults to “info”)

`log_dir` str \| None  
Output path for logging results (defaults to file log in ./logs directory).

`log_format` Literal\['eval', 'json'\] \| None  
Format for writing log files (defaults to “eval”, the native high-performance format).

`max_samples` int \| None  
Maximum number of samples to run in parallel (default is max_connections)

`max_tasks` int \| None  
Maximum number of tasks to run in parallel (defaults to number of models being evaluated)

`max_subprocesses` int \| None  
Maximum number of subprocesses to run in parallel (default is os.cpu_count())

`max_sandboxes` int \| None  
Maximum number of sandboxes (per-provider) to run in parallel.

`sandbox_cleanup` bool \| None  
Cleanup sandbox environments after task completes (defaults to True)

`trace` bool \| None  
Trace message interactions with evaluated model to terminal.

`display` [DisplayType](../reference/inspect_ai.util.html.md#displaytype) \| None  
Task display type (defaults to ‘full’).

`fail_on_error` bool \| float \| None  
`True` to fail on a sample error (default); `False` to never fail on sample errors; Value between 0 and 1 to fail if a proportion of total samples fails. Value greater than 1 to fail eval if a count of samples fails.

`continue_on_fail` bool \| None  
`True` to continue running and only fail at the end if the `fail_on_error` condition is met. `False` to fail eval immediately when the `fail_on_error` condition is met (default).

`retry_on_error` int \| None  
Number of times to retry samples if they encounter errors (by default, no retries occur).

`score_on_error` bool \| None  
Score samples that error rather than failing the eval mid-run. Errors still count toward the `fail_on_error` threshold for marking the eval log as ‘error’. Only takes effect after retries (if any) are exhausted.

`debug_errors` bool \| None  
Raise task errors (rather than logging them) so they can be debugged (defaults to False).

`log_samples` bool \| None  
Log detailed samples and scores (defaults to True)

`log_realtime` bool \| None  
Log events in realtime (enables live viewing of samples in inspect view). Defaults to True.

`log_images` bool \| None  
Log base64 encoded version of images, even if specified as a filename or URL (defaults to False)

`log_model_api` bool \| None  
Log raw model api requests and responses. True logs all calls, False logs only errors, None (default) logs the first few calls per model plus errors.

`log_refusals` bool \| None  
Log warnings for model refusals.

`log_buffer` int \| None  
Number of samples to buffer before writing log file. If not specified, an appropriate default for the format and filesystem is chosen (10 for most all cases, 100 for JSON logs on remote filesystems).

`log_shared` bool \| int \| None  
Sync sample events to log directory so that users on other systems can see log updates in realtime (defaults to no syncing). Specify `True` to sync every 10 seconds, otherwise an integer to sync every `n` seconds.

`score` bool  
Score output (defaults to True)

`score_display` bool \| None  
Show scoring metrics in realtime (defaults to True)

`max_retries` int \| None  
Maximum number of times to retry request.

`timeout` int \| None  
Request timeout (in seconds)

`attempt_timeout` int \| None  
Timeout (in seconds) for any given attempt (if exceeded, will abandon attempt and retry according to max_retries).

`max_connections` int \| None  
Maximum number of concurrent connections to Model API (default is per Model API)

`adaptive_connections` bool \| [AdaptiveConcurrency](../reference/inspect_ai.util.html.md#adaptiveconcurrency) \| None  
Enable adaptive concurrency for Model API connections. `True` for defaults (min=4, start=20, max=200), or pass an [AdaptiveConcurrency](../reference/inspect_ai.util.html.md#adaptiveconcurrency) to customize bounds and tuning (cooldown_seconds, decrease_factor, scale_up_percent). An explicit `max_connections` overrides this and uses static concurrency.

### eval_set

Evaluate a set of tasks.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/36eecc0b14b68251ce2dc513bcff43c82cef2555/src/inspect_ai/_eval/evalset.py#L100)

``` python
def eval_set(
    tasks: Tasks,
    log_dir: str,
    retry_attempts: int | None = ...,
    retry_wait: float | None = ...,
    retry_connections: float | None = ...,
    retry_cleanup: bool | None = ...,
    retry_immediate: bool | None = ...,
    model: str | Model | list[str] | list[Model] | None | NotGiven = ...,
    model_base_url: str | None = ...,
    model_args: dict[str, Any] | str = ...,
    model_roles: dict[str, str | Model] | None = ...,
    task_args: dict[str, Any] | str = ...,
    sandbox: SandboxEnvironmentType | None = ...,
    sandbox_cleanup: bool | None = ...,
    solver: Solver | SolverSpec | Agent | list[Solver] | None = ...,
    tags: list[str] | None = ...,
    metadata: dict[str, Any] | None = ...,
    trace: bool | None = ...,
    display: DisplayType | None = ...,
    approval: str | list[ApprovalPolicy] | ApprovalPolicyConfig | None = ...,
    score: bool = ...,
    log_level: str | None = ...,
    log_level_transcript: str | None = ...,
    log_format: Literal['eval', 'json'] | None = ...,
    limit: int | tuple[int, int] | None = ...,
    sample_id: str | int | list[str] | list[int] | list[str | int] | None = ...,
    sample_shuffle: bool | int | None = ...,
    epochs: int | Epochs | None = ...,
    fail_on_error: bool | float | None = ...,
    continue_on_fail: bool | None = ...,
    retry_on_error: int | None = ...,
    score_on_error: bool | None = ...,
    debug_errors: bool | None = ...,
    message_limit: int | None = ...,
    token_limit: int | None = ...,
    time_limit: int | None = ...,
    working_limit: int | None = ...,
    cost_limit: float | None = ...,
    model_cost_config: str | dict[str, ModelCost] | None = ...,
    max_samples: int | None = ...,
    max_dataset_memory: int | None = ...,
    max_tasks: int | None = ...,
    max_subprocesses: int | None = ...,
    max_sandboxes: int | None = ...,
    log_samples: bool | None = ...,
    log_realtime: bool | None = ...,
    log_images: bool | None = ...,
    log_model_api: bool | None = ...,
    log_refusals: bool | None = ...,
    log_buffer: int | None = ...,
    log_shared: bool | int | None = ...,
    bundle_dir: str | None = ...,
    bundle_overwrite: bool = ...,
    log_dir_allow_dirty: bool | None = ...,
    eval_set_id: str | None = ...,
    embed_viewer: bool = ...,
    *,
    max_retries: int | None = ...,
    timeout: int | None = ...,
    attempt_timeout: int | None = ...,
    max_connections: int | None = ...,
    adaptive_connections: bool | AdaptiveConcurrency | None = ...,
    system_message: str | None = ...,
    max_tokens: int | None = ...,
    top_p: float | None = ...,
    temperature: float | None = ...,
    stop_seqs: list[str] | None = ...,
    best_of: int | None = ...,
    frequency_penalty: float | None = ...,
    presence_penalty: float | None = ...,
    logit_bias: dict[int, float] | None = ...,
    seed: int | None = ...,
    top_k: int | None = ...,
    num_choices: int | None = ...,
    logprobs: bool | None = ...,
    top_logprobs: int | None = ...,
    prompt_logprobs: int | None = ...,
    parallel_tool_calls: bool | None = ...,
    internal_tools: bool | None = ...,
    max_tool_output: int | None = ...,
    cache_prompt: Literal['auto'] | bool | None = ...,
    verbosity: Literal['low', 'medium', 'high'] | None = ...,
    effort: Literal['low', 'medium', 'high', 'xhigh', 'max'] | None = ...,
    reasoning_effort: Literal['none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max'] | None = ...,
    reasoning_tokens: int | None = ...,
    reasoning_summary: Literal['none', 'concise', 'detailed', 'auto'] | None = ...,
    reasoning_history: Literal['none', 'all', 'last', 'auto'] | None = ...,
    response_schema: ResponseSchema | None = ...,
    extra_headers: dict[str, str] | None = ...,
    extra_body: dict[str, Any] | None = ...,
    modalities: list[OutputModality] | None = ...,
    cache: bool | CachePolicy | None = ...,
    batch: bool | int | BatchConfig | None = ...,
) -> tuple[bool, list[EvalLog]]
```

`tasks` [Tasks](../reference/inspect_ai.html.md#tasks)  
Task(s) to evaluate. If None, attempt to evaluate a task in the current working directory

`log_dir` str  
Output path for logging results (required to ensure that a unique storage scope is assigned for the set).

`retry_attempts` int \| None  
Maximum number of retry attempts before giving up (defaults to 10).

`retry_wait` float \| None  
Time to wait between attempts, increased exponentially. (defaults to 30, resulting in waits of 30, 60, 120, 240, etc.). Wait time per-retry will in no case by longer than 1 hour.

`retry_connections` float \| None  
Reduce max_connections at this rate with each retry (defaults to 1.0, which results in no reduction).

`retry_cleanup` bool \| None  
Cleanup failed log files after retries (defaults to True)

`retry_immediate` bool \| None  
If True, will immediately retry tasks as they fail without waiting for all tasks to complete. If False, will maintain legacy retry behavior of waiting for all tasks to complete before retrying any tasks. When True, `retry_wait` and `retry_connections` are ignored (defaults to False).

`model` str \| [Model](../reference/inspect_ai.model.html.md#model) \| list\[str\] \| list\[[Model](../reference/inspect_ai.model.html.md#model)\] \| None \| NotGiven  
Model(s) for evaluation. If not specified use the value of the INSPECT_EVAL_MODEL environment variable. Specify `None` to define no default model(s), which will leave model usage entirely up to tasks.

`model_base_url` str \| None  
Base URL for communicating with the model API.

`model_args` dict\[str, Any\] \| str  
Model creation args (as a dictionary or as a path to a JSON or YAML config file)

`model_roles` dict\[str, str \| [Model](../reference/inspect_ai.model.html.md#model)\] \| None  
Named roles for use in [get_model()](../reference/inspect_ai.model.html.md#get_model).

`task_args` dict\[str, Any\] \| str  
Task creation arguments (as a dictionary or as a path to a JSON or YAML config file)

`sandbox` SandboxEnvironmentType \| None  
Sandbox environment type (or optionally a str or tuple with a shorthand spec)

`sandbox_cleanup` bool \| None  
Cleanup sandbox environments after task completes (defaults to True)

`solver` [Solver](../reference/inspect_ai.solver.html.md#solver) \| [SolverSpec](../reference/inspect_ai.solver.html.md#solverspec) \| [Agent](../reference/inspect_ai.agent.html.md#agent) \| list\[[Solver](../reference/inspect_ai.solver.html.md#solver)\] \| None  
Alternative solver(s) for evaluating task(s). Optional (uses task solver by default).

`tags` list\[str\] \| None  
Tags to associate with this evaluation run.

`metadata` dict\[str, Any\] \| None  
Metadata to associate with this evaluation run.

`trace` bool \| None  
Trace message interactions with evaluated model to terminal.

`display` [DisplayType](../reference/inspect_ai.util.html.md#displaytype) \| None  
Task display type (defaults to ‘full’).

`approval` str \| list\[[ApprovalPolicy](../reference/inspect_ai.approval.html.md#approvalpolicy)\] \| ApprovalPolicyConfig \| None  
Tool use approval policies. Either a path to an approval policy config file, an ApprovalPolicyConfig, or a list of approval policies. Defaults to no approval policy.

`score` bool  
Score output (defaults to True)

`log_level` str \| None  
Level for logging to the console: “debug”, “http”, “sandbox”, “info”, “warning”, “error”, “critical”, or “notset” (defaults to “warning”)

`log_level_transcript` str \| None  
Level for logging to the log file (defaults to “info”)

`log_format` Literal\['eval', 'json'\] \| None  
Format for writing log files (defaults to “eval”, the native high-performance format).

`limit` int \| tuple\[int, int\] \| None  
Limit evaluated samples (defaults to all samples).

`sample_id` str \| int \| list\[str\] \| list\[int\] \| list\[str \| int\] \| None  
Evaluate specific sample(s) from the dataset. Use plain ids or preface with task names as required to disambiguate ids across tasks (e.g. `popularity:10`).

`sample_shuffle` bool \| int \| None  
Shuffle order of samples (pass a seed to make the order deterministic).

`epochs` int \| [Epochs](../reference/inspect_ai.html.md#epochs) \| None  
Epochs to repeat samples for and optional score reducer function(s) used to combine sample scores (defaults to “mean”)

`fail_on_error` bool \| float \| None  
`True` to fail on first sample error (default); `False` to never fail on sample errors; Value between 0 and 1 to fail if a proportion of total samples fails. Value greater than 1 to fail eval if a count of samples fails.

`continue_on_fail` bool \| None  
`True` to continue running and only fail at the end if the `fail_on_error` condition is met. `False` to fail eval immediately when the `fail_on_error` condition is met (default).

`retry_on_error` int \| None  
Number of times to retry samples if they encounter errors (by default, no retries occur).

`score_on_error` bool \| None  
Score samples that error rather than failing the eval mid-run. Errors still count toward the `fail_on_error` threshold for marking the eval log as ‘error’. Only takes effect after retries (if any) are exhausted.

`debug_errors` bool \| None  
Raise task errors (rather than logging them) so they can be debugged (defaults to False).

`message_limit` int \| None  
Limit on total messages used for each sample.

`token_limit` int \| None  
Limit on total tokens used for each sample.

`time_limit` int \| None  
Limit on clock time (in seconds) for samples.

`working_limit` int \| None  
Limit on working time (in seconds) for sample. Working time includes model generation, tool calls, etc. but does not include time spent waiting on retries or shared resources.

`cost_limit` float \| None  
Limit on total cost (in dollars) for each sample. Requires model cost data via set_model_cost() or –model-cost-config.

`model_cost_config` str \| dict\[str, [ModelCost](../reference/inspect_ai.model.html.md#modelcost)\] \| None  
YAML or JSON file with model prices for cost tracking.

`max_samples` int \| None  
Maximum number of samples to run in parallel (default is max_connections)

`max_dataset_memory` int \| None  
Maximum MB of dataset sample data to hold in memory per task. When exceeded, samples are paged to a temporary file on disk (defaults to None, which keeps all samples in memory).

`max_tasks` int \| None  
Maximum number of tasks to run in parallel (defaults to the greater of 4 and the number of models being evaluated)

`max_subprocesses` int \| None  
Maximum number of subprocesses to run in parallel (default is os.cpu_count())

`max_sandboxes` int \| None  
Maximum number of sandboxes (per-provider) to run in parallel.

`log_samples` bool \| None  
Log detailed samples and scores (defaults to True)

`log_realtime` bool \| None  
Log events in realtime (enables live viewing of samples in inspect view). Defaults to True.

`log_images` bool \| None  
Log base64 encoded version of images, even if specified as a filename or URL (defaults to False)

`log_model_api` bool \| None  
Log raw model api requests and responses. Note that error requests/responses are always logged.

`log_refusals` bool \| None  
Log warnings for model refusals.

`log_buffer` int \| None  
Number of samples to buffer before writing log file. If not specified, an appropriate default for the format and filesystem is chosen (10 for most all cases, 100 for JSON logs on remote filesystems).

`log_shared` bool \| int \| None  
Sync sample events to log directory so that users on other systems can see log updates in realtime (defaults to no syncing). Specify `True` to sync every 10 seconds, otherwise an integer to sync every `n` seconds.

`bundle_dir` str \| None  
If specified, the log viewer and logs generated by this eval set will be bundled into this directory.

`bundle_overwrite` bool  
Whether to overwrite files in the bundle_dir. (defaults to False).

`log_dir_allow_dirty` bool \| None  
If True, allow the log directory to contain unrelated logs. If False, ensure that the log directory only contains logs for tasks in this eval set (defaults to False).

`eval_set_id` str \| None  
ID for the eval set. If not specified, a unique ID will be generated.

`embed_viewer` bool  
If True, embed a log viewer into the log directory.

`max_retries` int \| None  
Maximum number of times to retry request (defaults to unlimited).

`timeout` int \| None  
Request timeout (in seconds).

`attempt_timeout` int \| None  
Timeout (in seconds) for any given attempt (if exceeded, will abandon attempt and retry according to max_retries).

`max_connections` int \| None  
Maximum number of concurrent connections to Model API (default is model specific).

`adaptive_connections` bool \| [AdaptiveConcurrency](../reference/inspect_ai.util.html.md#adaptiveconcurrency) \| None  
Enable adaptive concurrency for model API connections. `True` for defaults (min=4, start=20, max=200), or pass [AdaptiveConcurrency](../reference/inspect_ai.util.html.md#adaptiveconcurrency) to customize bounds and tuning (cooldown_seconds, decrease_factor, scale_up_percent). An explicit `max_connections` overrides this and uses static concurrency.

`system_message` str \| None  
Override the default system message.

`max_tokens` int \| None  
The maximum number of tokens that can be generated in the completion (default is model specific).

`top_p` float \| None  
An alternative to sampling with temperature, called nucleus sampling, where the model considers the results of the tokens with top_p probability mass.

`temperature` float \| None  
What sampling temperature to use, between 0 and 2. Higher values like 0.8 will make the output more random, while lower values like 0.2 will make it more focused and deterministic.

`stop_seqs` list\[str\] \| None  
Sequences where the API will stop generating further tokens. The returned text will not contain the stop sequence.

`best_of` int \| None  
Generates best_of completions server-side and returns the ‘best’ (the one with the highest log probability per token). vLLM only.

`frequency_penalty` float \| None  
Number between -2.0 and 2.0. Positive values penalize new tokens based on their existing frequency in the text so far, decreasing the model’s likelihood to repeat the same line verbatim. OpenAI, Google, Grok, Groq, and vLLM only.

`presence_penalty` float \| None  
Number between -2.0 and 2.0. Positive values penalize new tokens based on whether they appear in the text so far, increasing the model’s likelihood to talk about new topics. OpenAI, Google, Grok, Groq, and vLLM only.

`logit_bias` dict\[int, float\] \| None  
Map token Ids to an associated bias value from -100 to 100 (e.g. “42=10,43=-10”). OpenAI and Grok only.

`seed` int \| None  
Random seed. OpenAI, Google, Mistral, Groq, HuggingFace, and vLLM only.

`top_k` int \| None  
Randomly sample the next word from the top_k most likely next words. Anthropic, Google, and HuggingFace only.

`num_choices` int \| None  
How many chat completion choices to generate for each input message. OpenAI, Grok, Google, and TogetherAI only.

`logprobs` bool \| None  
Return log probabilities of the output tokens. OpenAI, Google, Grok, TogetherAI, Huggingface, llama-cpp-python, and vLLM only.

`top_logprobs` int \| None  
Number of most likely tokens (0-20) to return at each token position, each with an associated log probability. OpenAI, Google, Grok, and Huggingface only.

`prompt_logprobs` int \| None  
Number of log probabilities to return per prompt token (1-20). When greater than 1, top-N alternative tokens are also returned. vLLM only.

`parallel_tool_calls` bool \| None  
Whether to enable parallel function calling during tool use (defaults to True). OpenAI and Groq only.

`internal_tools` bool \| None  
Whether to automatically map tools to model internal implementations (e.g. ‘computer’ for anthropic).

`max_tool_output` int \| None  
Maximum tool output (in bytes). Defaults to 16 \* 1024.

`cache_prompt` Literal\['auto'\] \| bool \| None  
Whether to cache the prompt prefix. Enabled by default. Set to False to disable. Anthropic only.

`verbosity` Literal\['low', 'medium', 'high'\] \| None  
Constrains the verbosity of the model’s response. Lower values will result in more concise responses, while higher values will result in more verbose responses. GPT 5.x models only (defaults to “medium” for OpenAI models).

`effort` Literal\['low', 'medium', 'high', 'xhigh', 'max'\] \| None  
Control how many tokens are used for a response, trading off between response thoroughness and token efficiency. Anthropic Claude Opus 4.5+ only (`max` only supported on 4.6 and 4.7, `xhigh` supported only on 4.7).

`reasoning_effort` Literal\['none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max'\] \| None  
Constrains effort on reasoning. Defaults vary by provider and model and not all models support all values (please consult provider documentation for details).

`reasoning_tokens` int \| None  
Maximum number of tokens to use for reasoning. Anthropic Claude models only.

`reasoning_summary` Literal\['none', 'concise', 'detailed', 'auto'\] \| None  
Provide summary of reasoning steps (OpenAI reasoning models only). Use ‘auto’ to access the most detailed summarizer available for the current model (defaults to ‘auto’ if your organization is verified by OpenAI).

`reasoning_history` Literal\['none', 'all', 'last', 'auto'\] \| None  
Include reasoning in chat message history sent to generate.

`response_schema` [ResponseSchema](../reference/inspect_ai.model.html.md#responseschema) \| None  
Request a response format as JSONSchema (output should still be validated). OpenAI, Google, and Mistral only.

`extra_headers` dict\[str, str\] \| None  
Extra headers to be sent with requests. Not supported for AzureAI, Bedrock, and Grok.

`extra_body` dict\[str, Any\] \| None  
Extra body to be sent with requests to OpenAI compatible servers. OpenAI, vLLM, and SGLang only.

`modalities` list\[[OutputModality](../reference/inspect_ai.model.html.md#outputmodality)\] \| None  
Additional output modalities to enable beyond text (e.g. \[“image”\]). OpenAI and Google only.

`cache` bool \| [CachePolicy](../reference/inspect_ai.model.html.md#cachepolicy) \| None  
Policy for caching of model generations.

`batch` bool \| int \| [BatchConfig](../reference/inspect_ai.model.html.md#batchconfig) \| None  
Use batching API when available. True to enable batching with default configuration, False to disable batching, a number to enable batching of the specified batch size, or a BatchConfig object specifying the batching configuration.

### score

Score an evaluation log.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/36eecc0b14b68251ce2dc513bcff43c82cef2555/src/inspect_ai/_eval/score.py#L70)

``` python
def score(
    log: EvalLog,
    scorers: "Scorers",
    metrics: list[Metric | dict[str, list[Metric]]]
    | dict[str, list[Metric]]
    | None = None,
    epochs_reducer: ScoreReducers | None = None,
    action: ScoreAction | None = None,
    display: DisplayType | None = None,
    copy: bool = True,
) -> EvalLog
```

`log` [EvalLog](../reference/inspect_ai.log.html.md#evallog)  
Evaluation log.

`scorers` 'Scorers'  
List of Scorers to apply to log

`metrics` list\[[Metric](../reference/inspect_ai.scorer.html.md#metric) \| dict\[str, list\[[Metric](../reference/inspect_ai.scorer.html.md#metric)\]\]\] \| dict\[str, list\[[Metric](../reference/inspect_ai.scorer.html.md#metric)\]\] \| None  
Alternative metrics (overrides the metrics provided by the specified scorer and log).

`epochs_reducer` ScoreReducers \| None  
Reducer function(s) for aggregating scores in each sample. Defaults to previously used reducer(s).

`action` ScoreAction \| None  
Whether to append or overwrite this score

`display` [DisplayType](../reference/inspect_ai.util.html.md#displaytype) \| None  
Progress/status display

`copy` bool  
Whether to deepcopy the log before scoring.

## Tasks

### Task

Evaluation task.

Tasks are the basis for defining and running evaluations.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/36eecc0b14b68251ce2dc513bcff43c82cef2555/src/inspect_ai/_eval/task/task.py#L60)

``` python
class Task
```

#### Methods

\_\_init\_\_  
Create a task.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/36eecc0b14b68251ce2dc513bcff43c82cef2555/src/inspect_ai/_eval/task/task.py#L66)

``` python
def __init__(
    self,
    dataset: Dataset | Sequence[Sample] | None = ...,
    setup: Solver | list[Solver] | None = ...,
    solver: Solver | Agent | list[Solver] = ...,
    cleanup: Callable[[TaskState], Awaitable[None]] | None = ...,
    scorer: 'Scorers' | None = ...,
    metrics: list[Metric | dict[str, list[Metric]]] | dict[str, list[Metric]] | None = ...,
    model: str | Model | None = ...,
    config: GenerateConfig = ...,
    model_roles: dict[str, str | Model] | None = ...,
    sandbox: SandboxEnvironmentType | None = ...,
    approval: str | ApprovalPolicyConfig | list[ApprovalPolicy] | None = ...,
    epochs: int | Epochs | None = ...,
    fail_on_error: bool | float | None = ...,
    continue_on_fail: bool | None = ...,
    score_on_error: bool | None = ...,
    message_limit: int | None = ...,
    token_limit: int | None = ...,
    time_limit: int | None = ...,
    working_limit: int | None = ...,
    cost_limit: float | None = ...,
    early_stopping: 'EarlyStopping' | None = ...,
    display_name: str | None = ...,
    name: str | None = ...,
    version: int | str = ...,
    metadata: dict[str, Any] | None = ...,
    tags: list[str] | None = ...,
    viewer: ViewerConfig | None = ...,
    *,
    plan: Plan | Solver | list[Solver] = ...,
    tool_environment: str | SandboxEnvironmentSpec | None = ...,
    epochs_reducer: ScoreReducers | None = ...,
    max_messages: int | None = ...,
) -> None
```

`dataset` [Dataset](../reference/inspect_ai.dataset.html.md#dataset) \| Sequence\[[Sample](../reference/inspect_ai.dataset.html.md#sample)\] \| None  
Dataset to evaluate

`setup` [Solver](../reference/inspect_ai.solver.html.md#solver) \| list\[[Solver](../reference/inspect_ai.solver.html.md#solver)\] \| None  
Setup step (always run even when the main `solver` is replaced).

`solver` [Solver](../reference/inspect_ai.solver.html.md#solver) \| [Agent](../reference/inspect_ai.agent.html.md#agent) \| list\[[Solver](../reference/inspect_ai.solver.html.md#solver)\]  
Solver or list of solvers. Defaults to generate(), a normal call to the model.

`cleanup` Callable\[\[[TaskState](../reference/inspect_ai.solver.html.md#taskstate)\], Awaitable\[None\]\] \| None  
Optional cleanup function for task. Called after all solvers and scorers have run for each sample (including if an exception occurs during the run)

`scorer` 'Scorers' \| None  
Scorer used to evaluate model output.

`metrics` list\[[Metric](../reference/inspect_ai.scorer.html.md#metric) \| dict\[str, list\[[Metric](../reference/inspect_ai.scorer.html.md#metric)\]\]\] \| dict\[str, list\[[Metric](../reference/inspect_ai.scorer.html.md#metric)\]\] \| None  
Alternative metrics (overrides the metrics provided by the specified scorer).

`model` str \| [Model](../reference/inspect_ai.model.html.md#model) \| None  
Default model for task (Optional, defaults to eval model).

`config` [GenerateConfig](../reference/inspect_ai.model.html.md#generateconfig)  
Model generation config for default model (does not apply to model roles)

`model_roles` dict\[str, str \| [Model](../reference/inspect_ai.model.html.md#model)\] \| None  
Named roles for use in [get_model()](../reference/inspect_ai.model.html.md#get_model).

`sandbox` SandboxEnvironmentType \| None  
Sandbox environment type (or optionally a str or tuple with a shorthand spec)

`approval` str \| ApprovalPolicyConfig \| list\[[ApprovalPolicy](../reference/inspect_ai.approval.html.md#approvalpolicy)\] \| None  
Tool use approval policies. Either a path to an approval policy config file, an ApprovalPolicyConfig, or a list of approval policies. Defaults to no approval policy.

`epochs` int \| [Epochs](../reference/inspect_ai.html.md#epochs) \| None  
Epochs to repeat samples for and optional score reducer function(s) used to combine sample scores (defaults to “mean”)

`fail_on_error` bool \| float \| None  
`True` to fail on first sample error (default); `False` to never fail on sample errors; Value between 0 and 1 to fail if a proportion of total samples fails. Value greater than 1 to fail eval if a count of samples fails.

`continue_on_fail` bool \| None  
`True` to continue running and only fail at the end if the `fail_on_error` condition is met. `False` to fail eval immediately when the `fail_on_error` condition is met (default).

`score_on_error` bool \| None  
`True` to score samples that error rather than failing the eval mid-run. Errors still count toward the `fail_on_error` threshold for marking the eval log as ‘error’. Only takes effect after retries (if any) are exhausted.

`message_limit` int \| None  
Limit on total messages used for each sample.

`token_limit` int \| None  
Limit on total tokens used for each sample.

`time_limit` int \| None  
Limit on clock time (in seconds) for samples.

`working_limit` int \| None  
Limit on working time (in seconds) for sample. Working time includes model generation, tool calls, etc. but does not include time spent waiting on retries or shared resources.

`cost_limit` float \| None  
Limit on total cost (in dollars) for each sample. Requires model cost data via set_model_cost() or –model-cost-config.

`early_stopping` 'EarlyStopping' \| None  
Early stopping callbacks.

`display_name` str \| None  
Task display name (e.g. for plotting). If not specified then defaults to the registered task name.

`name` str \| None  
Task name. If not specified is automatically determined based on the registered name of the task.

`version` int \| str  
Version of task (to distinguish evolutions of the task spec or breaking changes to it)

`metadata` dict\[str, Any\] \| None  
Additional metadata to associate with the task.

`tags` list\[str\] \| None  
Tags to associate with the task.

`viewer` [ViewerConfig](../reference/inspect_ai.viewer.html.md#viewerconfig) \| None  
Log viewer configuration for this task (controls how scanner results are rendered in the sidebar).

`plan` Plan \| [Solver](../reference/inspect_ai.solver.html.md#solver) \| list\[[Solver](../reference/inspect_ai.solver.html.md#solver)\]  

`tool_environment` str \| SandboxEnvironmentSpec \| None  

`epochs_reducer` ScoreReducers \| None  

`max_messages` int \| None  

### task_with

Task adapted with alternate values for one or more options.

This function modifies the passed task in place and returns it. If you want to create multiple variations of a single task using [task_with()](../reference/inspect_ai.html.md#task_with) you should create the underlying task multiple times.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/36eecc0b14b68251ce2dc513bcff43c82cef2555/src/inspect_ai/_eval/task/task.py#L236)

``` python
def task_with(
    task: Task,
    *,
    dataset: Dataset | Sequence[Sample] | None | NotGiven = NOT_GIVEN,
    setup: Solver | list[Solver] | None | NotGiven = NOT_GIVEN,
    solver: Solver | Agent | list[Solver] | NotGiven = NOT_GIVEN,
    cleanup: Callable[[TaskState], Awaitable[None]] | None | NotGiven = NOT_GIVEN,
    scorer: "Scorers" | None | NotGiven = NOT_GIVEN,
    metrics: list[Metric | dict[str, list[Metric]]]
    | dict[str, list[Metric]]
    | None
    | NotGiven = NOT_GIVEN,
    model: str | Model | NotGiven = NOT_GIVEN,
    config: GenerateConfig | NotGiven = NOT_GIVEN,
    model_roles: dict[str, str | Model] | NotGiven = NOT_GIVEN,
    sandbox: SandboxEnvironmentType | None | NotGiven = NOT_GIVEN,
    approval: str
    | ApprovalPolicyConfig
    | list[ApprovalPolicy]
    | None
    | NotGiven = NOT_GIVEN,
    epochs: int | Epochs | None | NotGiven = NOT_GIVEN,
    fail_on_error: bool | float | None | NotGiven = NOT_GIVEN,
    continue_on_fail: bool | None | NotGiven = NOT_GIVEN,
    score_on_error: bool | None | NotGiven = NOT_GIVEN,
    message_limit: int | None | NotGiven = NOT_GIVEN,
    token_limit: int | None | NotGiven = NOT_GIVEN,
    time_limit: int | None | NotGiven = NOT_GIVEN,
    working_limit: int | None | NotGiven = NOT_GIVEN,
    cost_limit: float | None | NotGiven = NOT_GIVEN,
    early_stopping: EarlyStopping | None | NotGiven = NOT_GIVEN,
    name: str | None | NotGiven = NOT_GIVEN,
    version: int | str | NotGiven = NOT_GIVEN,
    metadata: dict[str, Any] | None | NotGiven = NOT_GIVEN,
    tags: list[str] | None | NotGiven = NOT_GIVEN,
    viewer: ViewerConfig | None | NotGiven = NOT_GIVEN,
) -> Task
```

`task` [Task](../reference/inspect_ai.html.md#task)  
Task to adapt

`dataset` [Dataset](../reference/inspect_ai.dataset.html.md#dataset) \| Sequence\[[Sample](../reference/inspect_ai.dataset.html.md#sample)\] \| None \| NotGiven  
Dataset to evaluate

`setup` [Solver](../reference/inspect_ai.solver.html.md#solver) \| list\[[Solver](../reference/inspect_ai.solver.html.md#solver)\] \| None \| NotGiven  
Setup step (always run even when the main `solver` is replaced).

`solver` [Solver](../reference/inspect_ai.solver.html.md#solver) \| [Agent](../reference/inspect_ai.agent.html.md#agent) \| list\[[Solver](../reference/inspect_ai.solver.html.md#solver)\] \| NotGiven  
Solver or list of solvers. Defaults to generate(), a normal call to the model.

`cleanup` Callable\[\[[TaskState](../reference/inspect_ai.solver.html.md#taskstate)\], Awaitable\[None\]\] \| None \| NotGiven  
Optional cleanup function for task. Called after all solvers and scorers have run for each sample (including if an exception occurs during the run)

`scorer` 'Scorers' \| None \| NotGiven  
Scorer used to evaluate model output.

`metrics` list\[[Metric](../reference/inspect_ai.scorer.html.md#metric) \| dict\[str, list\[[Metric](../reference/inspect_ai.scorer.html.md#metric)\]\]\] \| dict\[str, list\[[Metric](../reference/inspect_ai.scorer.html.md#metric)\]\] \| None \| NotGiven  
Alternative metrics (overrides the metrics provided by the specified scorer).

`model` str \| [Model](../reference/inspect_ai.model.html.md#model) \| NotGiven  
Default model for task (Optional, defaults to eval model).

`config` [GenerateConfig](../reference/inspect_ai.model.html.md#generateconfig) \| NotGiven  
Model generation config for default model (does not apply to model roles)

`model_roles` dict\[str, str \| [Model](../reference/inspect_ai.model.html.md#model)\] \| NotGiven  
Named roles for use in [get_model()](../reference/inspect_ai.model.html.md#get_model).

`sandbox` SandboxEnvironmentType \| None \| NotGiven  
Sandbox environment type (or optionally a str or tuple with a shorthand spec)

`approval` str \| ApprovalPolicyConfig \| list\[[ApprovalPolicy](../reference/inspect_ai.approval.html.md#approvalpolicy)\] \| None \| NotGiven  
Tool use approval policies. Either a path to an approval policy config file, an ApprovalPolicyConfig, or a list of approval policies. Defaults to no approval policy.

`epochs` int \| [Epochs](../reference/inspect_ai.html.md#epochs) \| None \| NotGiven  
Epochs to repeat samples for and optional score reducer function(s) used to combine sample scores (defaults to “mean”)

`fail_on_error` bool \| float \| None \| NotGiven  
`True` to fail on first sample error (default); `False` to never fail on sample errors; Value between 0 and 1 to fail if a proportion of total samples fails. Value greater than 1 to fail eval if a count of samples fails.

`continue_on_fail` bool \| None \| NotGiven  
`True` to continue running and only fail at the end if the `fail_on_error` condition is met. `False` to fail eval immediately when the `fail_on_error` condition is met (default).

`score_on_error` bool \| None \| NotGiven  
`True` to score samples that error rather than failing the eval mid-run. Errors still count toward the `fail_on_error` threshold for marking the eval log as ‘error’. Only takes effect after retries (if any) are exhausted.

`message_limit` int \| None \| NotGiven  
Limit on total messages used for each sample.

`token_limit` int \| None \| NotGiven  
Limit on total tokens used for each sample.

`time_limit` int \| None \| NotGiven  
Limit on clock time (in seconds) for samples.

`working_limit` int \| None \| NotGiven  
Limit on working time (in seconds) for sample. Working time includes model generation, tool calls, etc. but does not include time spent waiting on retries or shared resources.

`cost_limit` float \| None \| NotGiven  
Limit on total cost (in dollars) for each sample. Requires model cost data via set_model_cost() or –model-cost-config.

`early_stopping` [EarlyStopping](../reference/inspect_ai.util.html.md#earlystopping) \| None \| NotGiven  
Early stopping callbacks.

`name` str \| None \| NotGiven  
Task name. If not specified is automatically determined based on the name of the task directory (or “task”) if its anonymous task (e.g. created in a notebook and passed to eval() directly)

`version` int \| str \| NotGiven  
Version of task (to distinguish evolutions of the task spec or breaking changes to it)

`metadata` dict\[str, Any\] \| None \| NotGiven  
Additional metadata to associate with the task.

`tags` list\[str\] \| None \| NotGiven  
Tags to associate with the task.

`viewer` [ViewerConfig](../reference/inspect_ai.viewer.html.md#viewerconfig) \| None \| NotGiven  
Log viewer configuration for this task (controls how scanner results are rendered in the sidebar).

### Epochs

Task epochs.

Number of epochs to repeat samples over and optionally one or more reducers used to combine scores from samples across epochs. If not specified the “mean” score reducer is used.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/36eecc0b14b68251ce2dc513bcff43c82cef2555/src/inspect_ai/_eval/task/epochs.py#L4)

``` python
class Epochs
```

#### Attributes

`reducer` list\[[ScoreReducer](../reference/inspect_ai.scorer.html.md#scorereducer)\] \| None  
One or more reducers used to combine scores from samples across epochs (defaults to “mean”)

#### Methods

\_\_init\_\_  
Task epochs.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/36eecc0b14b68251ce2dc513bcff43c82cef2555/src/inspect_ai/_eval/task/epochs.py#L12)

``` python
def __init__(self, epochs: int, reducer: ScoreReducers | None = None) -> None
```

`epochs` int  
Number of epochs

`reducer` ScoreReducers \| None  
One or more reducers used to combine scores from samples across epochs (defaults to “mean”)

### TaskInfo

Task information (file, name, and attributes).

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/36eecc0b14b68251ce2dc513bcff43c82cef2555/src/inspect_ai/_eval/task/task.py#L388)

``` python
class TaskInfo(BaseModel)
```

#### Attributes

`file` str  
File path where task was loaded from.

`name` str  
Task name (defaults to function name)

`attribs` dict\[str, Any\]  
Task attributes (arguments passed to `@task`)

### Tasks

One or more tasks.

Tasks to be evaluated. Many forms of task specification are supported including directory names, task functions, task classes, and task instances (a single task or list of tasks can be specified). None is a request to read a task out of the current working directory.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/36eecc0b14b68251ce2dc513bcff43c82cef2555/src/inspect_ai/_eval/task/tasks.py#L6)

``` python
Tasks: TypeAlias = (
    str
    | PreviousTask
    | ResolvedTask
    | TaskInfo
    | Task
    | Callable[..., Task]
    | type[Task]
    | list[str]
    | list[PreviousTask]
    | list[ResolvedTask]
    | list[PreviousTask | ResolvedTask]
    | list[TaskInfo]
    | list[Task]
    | list[Callable[..., Task]]
    | list[type[Task]]
    | None
)
```

## View

### view

Run the Inspect View server.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/36eecc0b14b68251ce2dc513bcff43c82cef2555/src/inspect_ai/_view/view.py#L25)

``` python
def view(
    log_dir: str | None = None,
    recursive: bool = True,
    host: str = DEFAULT_SERVER_HOST,
    port: int = DEFAULT_VIEW_PORT,
    authorization: str | None = None,
    log_level: str | None = None,
    fs_options: dict[str, Any] = {},
) -> None
```

`log_dir` str \| None  
Directory to view logs from.

`recursive` bool  
Recursively list files in `log_dir`.

`host` str  
Tcp/ip host (defaults to “127.0.0.1”).

`port` int  
Tcp/ip port (defaults to 7575).

`authorization` str \| None  
Validate requests by checking for this authorization header.

`log_level` str \| None  
Level for logging to the console: “debug”, “http”, “sandbox”, “info”, “warning”, “error”, “critical”, or “notset” (defaults to “warning”)

`fs_options` dict\[str, Any\]  
Additional arguments to pass through to the filesystem provider (e.g. `S3FileSystem`). Use `{"anon": True }` if you are accessing a public S3 bucket with no credentials.

## Decorators

### task

Decorator for registering tasks.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/36eecc0b14b68251ce2dc513bcff43c82cef2555/src/inspect_ai/_eval/registry.py#L97)

``` python
def task(*args: Any, name: str | None = None, **attribs: Any) -> Any
```

`*args` Any  
Function returning [Task](../reference/inspect_ai.html.md#task) targeted by plain task decorator without attributes (e.g. `@task`)

`name` str \| None  
Optional name for task. If the decorator has no name argument then the name of the function will be used to automatically assign a name.

`**attribs` Any  
(dict\[str,Any\]): Additional task attributes.
