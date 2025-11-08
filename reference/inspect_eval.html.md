# inspect eval


Evaluate tasks.

#### Usage

``` text
inspect eval [OPTIONS] [TASKS]...
```

#### Options

| Name | Type | Description | Default |
|----|----|----|----|
| `--model` | text | Model used to evaluate tasks. | `Sentinel.UNSET` |
| `--model-base-url` | text | Base URL for for model API | `Sentinel.UNSET` |
| `-M` | text | One or more native model arguments (e.g. -M arg=value) | `Sentinel.UNSET` |
| `--model-config` | text | YAML or JSON config file with model arguments. | `Sentinel.UNSET` |
| `--model-role` | text | Named model role with model name or YAML/JSON config, e.g. –model-role critic=openai/gpt-4o or –model-role grader=“{model: mockllm/model, temperature: 0.5}” | `Sentinel.UNSET` |
| `-T` | text | One or more task arguments (e.g. -T arg=value) | `Sentinel.UNSET` |
| `--task-config` | text | YAML or JSON config file with task arguments. | `Sentinel.UNSET` |
| `--solver` | text | Solver to execute (overrides task default solver) | `Sentinel.UNSET` |
| `-S` | text | One or more solver arguments (e.g. -S arg=value) | `Sentinel.UNSET` |
| `--solver-config` | text | YAML or JSON config file with solver arguments. | `Sentinel.UNSET` |
| `--tags` | text | Tags to associate with this evaluation run. | `Sentinel.UNSET` |
| `--metadata` | text | Metadata to associate with this evaluation run (more than one –metadata argument can be specified). | `Sentinel.UNSET` |
| `--approval` | text | Config file for tool call approval. | `Sentinel.UNSET` |
| `--sandbox` | text | Sandbox environment type (with optional config file). e.g. ‘docker’ or ‘docker:compose.yml’ | `Sentinel.UNSET` |
| `--no-sandbox-cleanup` | boolean | Do not cleanup sandbox environments after task completes | `False` |
| `--limit` | text | Limit samples to evaluate e.g. 10 or 10-20 | `Sentinel.UNSET` |
| `--sample-id` | text | Evaluate specific sample(s) (comma separated list of ids) | `Sentinel.UNSET` |
| `--sample-shuffle` | text | Shuffle order of samples (pass a seed to make the order deterministic) | None |
| `--epochs` | integer | Number of times to repeat dataset (defaults to 1) | `Sentinel.UNSET` |
| `--epochs-reducer` | text | Method for reducing per-epoch sample scores into a single score. Built in reducers include ‘mean’, ‘median’, ‘mode’, ‘max’, and ‘at_least\_{n}’. | `Sentinel.UNSET` |
| `--no-epochs-reducer` | boolean | Do not reduce per-epoch sample scores. | `False` |
| `--max-connections` | integer | Maximum number of concurrent connections to Model API (defaults to 10) | `Sentinel.UNSET` |
| `--max-retries` | integer | Maximum number of times to retry model API requests (defaults to unlimited) | `Sentinel.UNSET` |
| `--timeout` | integer | Model API request timeout in seconds (defaults to no timeout) | `Sentinel.UNSET` |
| `--attempt-timeout` | integer | Timeout (in seconds) for any given attempt (if exceeded, will abandon attempt and retry according to max_retries). | `Sentinel.UNSET` |
| `--max-samples` | integer | Maximum number of samples to run in parallel (default is running all samples in parallel) | `Sentinel.UNSET` |
| `--max-tasks` | integer | Maximum number of tasks to run in parallel (default is 1 for eval and 4 for eval-set) | `Sentinel.UNSET` |
| `--max-subprocesses` | integer | Maximum number of subprocesses to run in parallel (default is os.cpu_count()) | `Sentinel.UNSET` |
| `--max-sandboxes` | integer | Maximum number of sandboxes (per-provider) to run in parallel. | `Sentinel.UNSET` |
| `--message-limit` | integer | Limit on total messages used for each sample. | `Sentinel.UNSET` |
| `--token-limit` | integer | Limit on total tokens used for each sample. | `Sentinel.UNSET` |
| `--time-limit` | integer | Limit on total running time for each sample. | `Sentinel.UNSET` |
| `--working-limit` | integer | Limit on total working time (e.g. model generation, tool calls, etc.) for each sample. | `Sentinel.UNSET` |
| `--fail-on-error` | float | Threshold of sample errors to tolerage (by default, evals fail when any error occurs). Value between 0 to 1 to set a proportion; value greater than 1 to set a count. | `Sentinel.UNSET` |
| `--no-fail-on-error` | boolean | Do not fail the eval if errors occur within samples (instead, continue running other samples) | `False` |
| `--continue-on-fail` | boolean | Do not immediately fail the eval if the error threshold is exceeded (instead, continue running other samples until the eval completes, and then possibly fail the eval). | `False` |
| `--retry-on-error` | text | Retry samples if they encounter errors (by default, no retries occur). Specify –retry-on-error to retry a single time, or specify e.g. `--retry-on-error=3` to retry multiple times. | None |
| `--no-log-samples` | boolean | Do not include samples in the log file. | `False` |
| `--no-log-realtime` | boolean | Do not log events in realtime (affects live viewing of samples in inspect view) | `False` |
| `--log-images` / `--no-log-images` | boolean | Include base64 encoded versions of filename or URL based images in the log file. | `True` |
| `--log-buffer` | integer | Number of samples to buffer before writing log file. If not specified, an appropriate default for the format and filesystem is chosen (10 for most all cases, 100 for JSON logs on remote filesystems). | `Sentinel.UNSET` |
| `--log-shared` | text | Sync sample events to log directory so that users on other systems can see log updates in realtime (defaults to no syncing). If enabled will sync every 10 seconds (or pass a value to sync every `n` seconds). | None |
| `--no-score` | boolean | Do not score model output (use the inspect score command to score output later) | `False` |
| `--no-score-display` | boolean | Do not score model output (use the inspect score command to score output later) | `False` |
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
| `--parallel-tool-calls` / `--no-parallel-tool-calls` | boolean | Whether to enable parallel function calling during tool use (defaults to True) OpenAI and Groq only. | `True` |
| `--internal-tools` / `--no-internal-tools` | boolean | Whether to automatically map tools to model internal implementations (e.g. ‘computer’ for anthropic). | `True` |
| `--max-tool-output` | integer | Maximum size of tool output (in bytes). Defaults to 16 \* 1024. | `Sentinel.UNSET` |
| `--cache-prompt` | choice (`auto` \| `true` \| `false`) | Cache prompt prefix (Anthropic only). Defaults to “auto”, which will enable caching for requests with tools. | `Sentinel.UNSET` |
| `--reasoning-effort` | choice (`minimal` \| `low` \| `medium` \| `high`) | Constrains effort on reasoning for reasoning models (defaults to `medium`). Open AI o-series and gpt-5 models only. | `Sentinel.UNSET` |
| `--reasoning-tokens` | integer | Maximum number of tokens to use for reasoning. Anthropic Claude models only. | `Sentinel.UNSET` |
| `--reasoning-summary` | choice (`none` \| `concise` \| `detailed` \| `auto`) | Provide summary of reasoning steps (OpenAI reasoning models only). Use ‘auto’ to access the most detailed summarizer available for the current model (defaults to ‘auto’ if your organization is verified by OpenAI). | `Sentinel.UNSET` |
| `--reasoning-history` | choice (`none` \| `all` \| `last` \| `auto`) | Include reasoning in chat message history sent to generate (defaults to “auto”, which uses the recommended default for each provider) | `Sentinel.UNSET` |
| `--response-schema` | text | JSON schema for desired response format (output should still be validated). OpenAI, Google, and Mistral only. | `Sentinel.UNSET` |
| `--batch` | text | Batch requests together to reduce API calls when using a model that supports batching (by default, no batching). Specify –batch to batch with default configuration, specify a batch size e.g. `--batch=1000` to configure batches of 1000 requests, or pass the file path to a YAML or JSON config file with batch configuration. | None |
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
