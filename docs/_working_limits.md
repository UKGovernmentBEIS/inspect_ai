The `working_limit` differs from the `time_limit` in that it measures only the time spent working (as opposed to retrying in response to rate limits or waiting on other shared resources). Working time is clock time minus the time the sample spends waiting. The sample is waiting while any of these is in progress:

- Waiting for a model connection or a `concurrency()` slot (including `max_sandboxes` and `max_subprocesses`).
- A model request that fails and is retried (e.g. a rate limited request), and the backoff before the retry.
- A batch request waiting to be submitted.
- Tool approval or review, by a person or a model.
- Waiting for a person to answer a question.
- A model call held by `inspect ctl pause --now`.
- Code inside `suspend_working_limit()`.

There is one exception: while any task in the sample is running a model request, a sandbox command, or a tool call, the sample is working, even if another task is waiting. A model request that fails and is retried does not count as working. A tool call or sandbox command that is itself waiting (for example for approval or a `max_subprocesses` slot) is not counted as working for that time. Model requests and tool calls made inside a wait (for example by a model approver or a monitor) are not counted as working either. This exception does not apply to a command run with `exec_remote()` once it has started, or to sandbox commands run inside `sandbox_agent_bridge()`, such as the one that launches a bridged agent, because Inspect cannot see when they are working. A tool call that runs such a command is still counted as working, and so are a bridged agent's model requests and bridged tool calls.

Waits that overlap count once, so working time is never negative and never more than clock time.

::: {.callout-warning appearance="simple"}
Other work done while a wait is in progress is not charged. This includes background processes in a sandbox, the commands a sandboxed agent runs on its own, and the work of in-process agent libraries. Working time can therefore undercount, and a sample can run much longer than its working limit. Always set a `time_limit` alongside a `working_limit` to bound clock time.
:::

::: {.callout-note appearance="simple"}
To tell a successful request apart from retries inside the model client, Inspect measures the request through hooks into the HTTP client of most model packages. When a provider reports no request time (for example `azureai`, `sagemaker` and in-process providers such as `hf`), or measures the whole call (`grok`), the `working_time` includes any retries the model client performs.
:::
