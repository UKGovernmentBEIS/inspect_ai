# inspect eval


Evaluate tasks.

#### Usage

``` text
inspect eval [OPTIONS] [TASKS]...
```

#### Options

| Name | Type | Description | Default |
|----|----|----|----|
| `--model` | text | Model used to evaluate tasks. | None |
| `--model-base-url` | text | Base URL for for model API | None |
| `-M` | text | One or more native model arguments (e.g. -M arg=value) | None |
| `--model-config` | text | YAML or JSON config file with model arguments. | None |
| `--model-role` | text | Named model role, e.g. –model-role critic=openai/gpt-4o | None |
| `-T` | text | One or more task arguments (e.g. -T arg=value) | None |
| `--task-config` | text | YAML or JSON config file with task arguments. | None |
| `--solver` | text | Solver to execute (overrides task default solver) | None |
| `-S` | text | One or more solver arguments (e.g. -S arg=value) | None |
| `--solver-config` | text | YAML or JSON config file with solver arguments. | None |
| `--tags` | text | Tags to associate with this evaluation run. | None |
| `--metadata` | text | Metadata to associate with this evaluation run (more than one –metadata argument can be specified). | None |
| `--approval` | text | Config file for tool call approval. | None |
| `--sandbox` | text | Sandbox environment type (with optional config file). e.g. ‘docker’ or ‘docker:compose.yml’ | None |
| `--no-sandbox-cleanup` | boolean | Do not cleanup sandbox environments after task completes | `False` |
| `--limit` | text | Limit samples to evaluate e.g. 10 or 10-20 | None |
| `--sample-id` | text | Evaluate specific sample(s) (comma separated list of ids) | None |
| `--epochs` | integer | Number of times to repeat dataset (defaults to 1) | None |
| `--epochs-reducer` | text | Method for reducing per-epoch sample scores into a single score. Built in reducers include ‘mean’, ‘median’, ‘mode’, ‘max’, and ‘at_least\_{n}’. | None |
| `--max-connections` | integer | Maximum number of concurrent connections to Model API (defaults to 10) | None |
| `--max-retries` | integer | Maximum number of times to retry model API requests (defaults to unlimited) | None |
| `--timeout` | integer | Model API request timeout in seconds (defaults to no timeout) | None |
| `--max-samples` | integer | Maximum number of samples to run in parallel (default is running all samples in parallel) | None |
| `--max-tasks` | integer | Maximum number of tasks to run in parallel (default is 1) | None |
| `--max-subprocesses` | integer | Maximum number of subprocesses to run in parallel (default is os.cpu_count()) | None |
| `--max-sandboxes` | integer | Maximum number of sandboxes (per-provider) to run in parallel. | None |
| `--message-limit` | integer | Limit on total messages used for each sample. | None |
| `--token-limit` | integer | Limit on total tokens used for each sample. | None |
| `--time-limit` | integer | Limit on total running time for each sample. | None |
| `--working-limit` | integer | Limit on total working time (e.g. model generation, tool calls, etc.) for each sample. | None |
| `--fail-on-error` | float | Threshold of sample errors to tolerage (by default, evals fail when any error occurs). Value between 0 to 1 to set a proportion; value greater than 1 to set a count. | None |
| `--no-fail-on-error` | boolean | Do not fail the eval if errors occur within samples (instead, continue running other samples) | `False` |
| `--retry-on-error` | text | Retry samples if they encounter errors (by default, no retries occur). Specify –retry-on-error to retry a single time, or specify e.g. `--retry-on-error=3` to retry multiple times. | None |
| `--no-log-samples` | boolean | Do not include samples in the log file. | `False` |
| `--log-images` / `--no-log-images` | boolean | Include base64 encoded versions of filename or URL based images in the log file. | `True` |
| `--log-buffer` | integer | Number of samples to buffer before writing log file. If not specified, an appropriate default for the format and filesystem is chosen (10 for most all cases, 100 for JSON logs on remote filesystems). | None |
| `--log-shared` | text | Sync sample events to log directory so that users on other systems can see log updates in realtime (defaults to no syncing). If enabled will sync every 10 seconds (or pass a value to sync every `n` seconds). | None |
| `--no-score` | boolean | Do not score model output (use the inspect score command to score output later) | `False` |
| `--no-score-display` | boolean | Do not score model output (use the inspect score command to score output later) | `False` |
| `--max-tokens` | integer | The maximum number of tokens that can be generated in the completion (default is model specific) | None |
| `--system-message` | text | Override the default system message. | None |
| `--best-of` | integer | Generates best_of completions server-side and returns the ‘best’ (the one with the highest log probability per token). OpenAI only. | None |
| `--frequency-penalty` | float | Number between -2.0 and 2.0. Positive values penalize new tokens based on their existing frequency in the text so far, decreasing the model’s likelihood to repeat the same line verbatim. OpenAI, Google, Grok, Groq, llama-cpp-python and vLLM only. | None |
| `--presence-penalty` | float | Number between -2.0 and 2.0. Positive values penalize new tokens based on whether they appear in the text so far, increasing the model’s likelihood to talk about new topics. OpenAI, Google, Grok, Groq, llama-cpp-python and vLLM only. | None |
| `--logit-bias` | text | Map token Ids to an associated bias value from -100 to 100 (e.g. “42=10,43=-10”). OpenAI, Grok, and Grok only. | None |
| `--seed` | integer | Random seed. OpenAI, Google, Groq, Mistral, HuggingFace, and vLLM only. | None |
| `--stop-seqs` | text | Sequences where the API will stop generating further tokens. The returned text will not contain the stop sequence. | None |
| `--temperature` | float | What sampling temperature to use, between 0 and 2. Higher values like 0.8 will make the output more random, while lower values like 0.2 will make it more focused and deterministic. | None |
| `--top-p` | float | An alternative to sampling with temperature, called nucleus sampling, where the model considers the results of the tokens with top_p probability mass. | None |
| `--top-k` | integer | Randomly sample the next word from the top_k most likely next words. Anthropic, Google, HuggingFace, and vLLM only. | None |
| `--num-choices` | integer | How many chat completion choices to generate for each input message. OpenAI, Grok, Google, TogetherAI, and vLLM only. | None |
| `--logprobs` | boolean | Return log probabilities of the output tokens. OpenAI, Grok, TogetherAI, Huggingface, llama-cpp-python, and vLLM only. | `False` |
| `--top-logprobs` | integer | Number of most likely tokens (0-20) to return at each token position, each with an associated log probability. OpenAI, Grok, TogetherAI, Huggingface, and vLLM only. | None |
| `--parallel-tool-calls` / `--no-parallel-tool-calls` | boolean | Whether to enable parallel function calling during tool use (defaults to True) OpenAI and Groq only. | `True` |
| `--internal-tools` / `--no-internal-tools` | boolean | Whether to automatically map tools to model internal implementations (e.g. ‘computer’ for anthropic). | `True` |
| `--max-tool-output` | integer | Maximum size of tool output (in bytes). Defaults to 16 \* 1024. | None |
| `--cache-prompt` | choice (`auto` \| `true` \| `false`) | Cache prompt prefix (Anthropic only). Defaults to “auto”, which will enable caching for requests with tools. | None |
| `--reasoning-effort` | choice (`low` \| `medium` \| `high`) | Constrains effort on reasoning for reasoning models (defaults to `medium`). Open AI o-series models only. | None |
| `--reasoning-tokens` | integer | Maximum number of tokens to use for reasoning. Anthropic Claude models only. | None |
| `--reasoning-summary` | choice (`concise` \| `detailed` \| `auto`) | Provide summary of reasoning steps (defaults to no summary). Use ‘auto’ to access the most detailed summarizer available for the current model. OpenAI reasoning models only. | None |
| `--reasoning-history` | choice (`none` \| `all` \| `last` \| `auto`) | Include reasoning in chat message history sent to generate (defaults to “auto”, which uses the recommended default for each provider) | None |
| `--response-schema` | text | JSON schema for desired response format (output should still be validated). OpenAI, Google, and Mistral only. | None |
| `--log-format` | choice (`eval` \| `json`) | Format for writing log files. | None |
| `--log-level-transcript` | choice (`debug` \| `trace` \| `http` \| `info` \| `warning` \| `error` \| `critical`) | Set the log level of the transcript (defaults to ‘info’) | `info` |
| `--log-level` | choice (`debug` \| `trace` \| `http` \| `info` \| `warning` \| `error` \| `critical`) | Set the log level (defaults to ‘warning’) | `warning` |
| `--log-dir` | text | Directory for log files. | `./logs` |
| `--display` | choice (`full` \| `conversation` \| `rich` \| `plain` \| `none`) | Set the display type (defaults to ‘full’) | `full` |
| `--env` | text | Define an environment variable e.g. –env NAME=value (–env can be specified multiple times) | None |
| `--debug` | boolean | Wait to attach debugger | `False` |
| `--debug-port` | integer | Port number for debugger | `5678` |
| `--debug-errors` | boolean | Raise task errors (rather than logging them) so they can be debugged. | `False` |
| `--help` | boolean | Show this message and exit. | `False` |
