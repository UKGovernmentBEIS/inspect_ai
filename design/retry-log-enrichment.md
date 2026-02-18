# Retry Log Enrichment

## Problem

When inspect retries failed model requests, log messages lack context about which task, sample, and provider triggered the retry. In a concurrent runner processing many samples across many tasks, messages like:

```
Retrying request to /responses in 0.396765 seconds
```

are unhelpful for debugging. You can't tell which sample is rate-limited or which provider is flaking.

## Two Retry Layers

There are two independent retry mechanisms producing log messages:

1. **OpenAI SDK built-in retry** (`openai._base_client`): Logs `"Retrying request to %s in %f seconds"`. Only knows the URL path.

2. **Inspect's tenacity retry** (`log_model_retry` in `model/_model.py`): Logs `"-> {model_name} retry N (retrying in N seconds)"`. Has model name but no task/sample.

Both fire during normal operation — the SDK handles its own 2 retries, then tenacity handles the outer retry loop.

## Design

### Enriched Format

All retry messages get a compact context prefix:

```
[{sample_uuid} {task}/{sample_id}/{epoch} {model}]
```

Example (inspect's own retry, with error summary):
```
[Abc12xY mmlu/42/1 openai/gpt-4o] -> openai/gpt-4o retry 2 (retrying in 6 seconds) [RateLimitError 429 rate_limit_exceeded]
```

Example (SDK retry, via logging filter):
```
[Abc12xY mmlu/42/1 openai/gpt-4o] Retrying request to /responses in 0.396765 seconds
```

When no active sample exists (e.g., retries during setup), messages pass through unchanged.

### Context Source

`ActiveSample` is available via the `sample_active()` ContextVar from `inspect_ai.log._samples`. It carries:

| Field | Source | Description |
|-------|--------|-------------|
| `sample_uuid` | `active.id` | shortuuid for this specific rollout |
| `task` | `active.task` | Task name |
| `sample_id` | `active.sample.id` | Dataset entry ID (int, str, or None) |
| `epoch` | `active.epoch` | Current epoch number |
| `model` | `active.model` | Model name string |

### Error Summary

Inspect's tenacity retry messages include an error summary suffix extracted from the exception:

```
[{ExceptionType} {status_code?} {error_code?}]
```

- **Exception type**: e.g. `RateLimitError`, `ConnectError`, `ReadTimeout`
- **HTTP status code**: if available via `.status_code` or `.response.status_code`
- **API error code**: if available via `.code` (e.g. `rate_limit_exceeded`, `server_error`)
- **Never** includes the full error message body (could leak prompt content or API keys)

Examples:
```
[RateLimitError 429 rate_limit_exceeded]
[APIStatusError 503]
[ConnectError]
```

### SDK Message Enrichment (Logging Filter)

A `SampleContextFilter` attached to the `openai` logger intercepts SDK log messages and:

1. Sets structured fields on the `LogRecord` as extra attributes (`sample_uuid`, `sample_task`, `sample_id`, `sample_epoch`, `sample_model`) — available to JSON/structured log formatters
2. Prepends the compact prefix to `record.msg` — works with plain text formatters

The filter passes records through unchanged when no active sample exists.

## Implementation

### Shared Helpers (`src/inspect_ai/_util/retry.py`)

Two new functions:

- `sample_context_prefix() -> str` — returns `"[uuid task/id/epoch model] "` or `""` if no active sample
- `retry_error_summary(retry_state) -> str` — returns `" [Type status code]"` or `""` if no exception

### File Changes

| File | Change |
|------|--------|
| `src/inspect_ai/_util/retry.py` | Add `sample_context_prefix()`, `retry_error_summary()`, `SampleContextFilter` class, and `install_sample_context_logging()` |
| `src/inspect_ai/model/_model.py` | Update `log_model_retry()` to use prefix + error summary |
| `src/inspect_ai/_util/httpx.py` | Update `log_httpx_retry_attempt()` to use prefix |
| Eval startup path | Call `install_sample_context_logging()` once |
