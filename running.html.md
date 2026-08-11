# Running Evals – Inspect

Once an evaluation is developed, Inspect provides a number of tools for running it reliably and at scale:

|  |  |
|----|----|
| [Eval Sets](./eval-sets.html.md) | Describe, run, and analyse larger sets of evaluation tasks with automatic retry and resumption. |
| [Parallelism](./parallelism.html.md) | Run multiple tasks and models in parallel and tune sandbox concurrency. |
| [Handling Errors](./handling-errors.html.md) | Deal with runtime errors and recover from crashes during evaluation. |
| [Setting Limits](./setting-limits.html.md) | Set time, message, token, and cost limits on tasks, samples, and agent execution. |
| [Control Channel](./control-channel.html.md) | Observe running evals from another process: task and sample status, errors, and transcript events. |
| [Early Stopping](./early-stopping.html.md) | End tasks early based on the scores of previously completed samples. |
| [Tracing](./tracing.html.md) | Diagnose runtime issues with advanced execution tracing tools. |

If you are just getting started running evaluations, see the [`inspect eval`](./options.html.md) command line interface and the [eval()](./reference/inspect_ai.html.md#eval) function covered in the [Welcome](./index.html.md#sec-hello-inspect) tutorial.

> **NOTE:**
>
> If you use a coding agent to run evals, the [inspect-skills](https://github.com/meridianlabs-ai/inspect-skills#install) plugin provides skills that teach it to launch evals in the background, monitor progress, and catch stalls and errors early.
