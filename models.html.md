# Using Models – Inspect

## Overview

Inspect has support for a wide variety of language model APIs and can be extended to support arbitrary additional ones. Support for the following providers is built in to Inspect:

|  |  |
|----|----|
| Lab APIs | [OpenAI](./providers.html.md#openai), [Anthropic](./providers.html.md#anthropic), [Google](./providers.html.md#google), [Grok](./providers.html.md#grok), [Mistral](./providers.html.md#mistral), [DeepSeek](./providers.html.md#deepseek), [Moonshot AI](./providers.html.md#moonshot-ai), [Perplexity](./providers.html.md#perplexity) |
| Cloud APIs | [AWS Bedrock](./providers.html.md#aws-bedrock), [AWS SageMaker](./providers.html.md#aws-sagemaker), and [Azure AI](./providers.html.md#azure-ai) |
| Open (Hosted) | [Groq](./providers.html.md#groq), [Together AI](./providers.html.md#together-ai), [Fireworks AI](./providers.html.md#fireworks-ai), [Cloudflare](./providers.html.md#cloudflare), [HF Inference Providers](./providers.html.md#hf-inference-providers), [SambaNova](./providers.html.md#sambanova) |
| Open (Local) | [Hugging Face](./providers.html.md#hugging-face), [vLLM](./providers.html.md#vllm), [Ollama](./providers.html.md#ollama), [Lllama-cpp-python](./providers.html.md#llama-cpp-python), [SGLang](./providers.html.md#sglang), [TransformerLens](./providers.html.md#transformer-lens), [nnterp](./providers.html.md#nnterp) |

\

If the provider you are using is not listed above, you may still be able to use it if:

1.  It provides an OpenAI compatible API endpoint. In this scenario, use the Inspect [OpenAI Compatible API](./providers.html.md#openai-api) interface.

2.  It is available via OpenRouter (see the docs on using [OpenRouter](./providers.html.md#openrouter) with Inspect).

You can also create [Model API Extensions](./extensions-model-api.html.md#model-apis) to add model providers using their native interface.

Below we’ll describe various ways to specify and provide options to models in Inspect evaluations. Review this first, then see the provider-specific sections for additional usage details and available options.

## Selecting a Model

To select a model for an evaluation, pass it’s name on the command line or use the `model` argument of the [eval()](./reference/inspect_ai.html.md#eval) function:

``` bash
inspect eval arc.py --model openai/gpt-4o-mini
inspect eval arc.py --model anthropic/claude-sonnet-4-0
```

Or:

``` python
eval("arc.py", model="openai/gpt-4o-mini")
eval("arc.py", model="anthropic/claude-sonnet-4-0")
```

Alternatively, you can set the `INSPECT_EVAL_MODEL` environment variable (either in the shell or a `.env` file) to select a model externally:

``` bash
INSPECT_EVAL_MODEL=google/gemini-2.5-pro
```

#### No Model

Some evaluations will either not make use of models or call the lower-level [get_model()](./reference/inspect_ai.model.html.md#get_model) function to explicitly access models for different roles (see the [Model API](#model-api) section below for details on this).

In these cases, you are not required to specify a `--model`. If you happen to have an `INSPECT_EVAL_MODEL` defined and you want to prevent your evaluation from using it, you can explicitly specify no model as follows:

``` bash
inspect eval arc.py --model none
```

Or from Python:

``` python
eval("arc.py", model=None)
```

#### Multiple Models

To evaluate several models with the same options, pass a comma-separated list:

``` bash
inspect eval arc.py --model openai/gpt-4o,anthropic/claude-sonnet-4-0
```

To give each model its own options, use `--model-spec`. Each option holds one inline YAML or JSON mapping. A mapping takes the same fields as a [model role](#model-roles) — a required `model`, any generation config field, and `model_args` — plus a `base_url`:

``` bash
inspect eval arc.py \
    --model-spec '{model: openai/gpt-4o, temperature: 0}' \
    --model-spec '{model: openai/gpt-4o, temperature: 1}'
```

This runs the same model twice, once at each temperature. `--model` cannot do that, because it applies one shared parameter set to every model it names.

Or:

``` python
eval("arc.py", model=[
    get_model("openai/gpt-4o", config=GenerateConfig(temperature=0)),
    get_model("openai/gpt-4o", config=GenerateConfig(temperature=1)),
])
```

A spec supplies the whole model, so you cannot combine `--model-spec` with `--model`, `--model-base-url`, `--model-config`, `-M`, or the `model` field of a `--run-config` file. Put those values in each spec instead.

An option you type beats an ambient environment value, so `--model-spec` and `INSPECT_EVAL_MODEL` never fail together. A spec you type replaces an `INSPECT_EVAL_MODEL`, and an `INSPECT_EVAL_MODEL_SPEC` yields to a `--model` you type.

A generation config option on the command line still applies to every model, and it overrides the same field in every spec. For example, `--temperature 0.9` added to the command above runs both models at 0.9. Set the temperature only in the specs to keep the two values apart.

`INSPECT_EVAL_MODEL_SPEC` holds one spec per model, separated by a space, in the same way as `INSPECT_EVAL_MODEL_ARGS`. A comma cannot separate the specs, because a spec uses commas between its own fields. Write each spec as JSON without spaces:

``` bash
export INSPECT_EVAL_MODEL_SPEC='{"model":"openai/gpt-4o","temperature":0} {"model":"openai/gpt-4o","temperature":1}'
```

`--model-spec` combines with `--model-role`, because a spec fills the main model and a role fills a named one. A role applies to every spec, and it does not override a spec. A role you leave unset inherits the spec that is running, so each model grades its own samples:

``` bash
inspect eval arc.py \
    --model-spec '{model: openai/gpt-4o, temperature: 0}' \
    --model-spec '{model: openai/gpt-4o, temperature: 1}' \
    --model-role grader=anthropic/claude-sonnet-4-0
```

`inspect eval-set` accepts `--model-spec` as well. Task identity includes the model’s generation config, so two specs for one model stay two units of work. Task identity does not include `base_url` or credential model args such as `api_key`, so an eval set rejects two specs that differ only in those as not distinct; give each spec a distinct generation config, or run them with `inspect eval` instead. See [Eval Sets](./eval-sets.html.md).

## Generation Config

There are a variety of configuration options that affect the behaviour of model generation. There are options which affect the generated tokens (`temperature`, `top_p`, etc.) as well as the connection to model providers (`timeout`, `max_retries`, etc.)

You can specify generation options either on the command line or in direct calls to [eval()](./reference/inspect_ai.html.md#eval). For example:

``` bash
inspect eval arc.py --model openai/gpt-4 --temperature 0.9
inspect eval arc.py --model google/gemini-2.5-pro --max-connections 20
```

Or:

``` python
eval("arc.py", model="openai/gpt-4", temperature=0.9)
eval("arc.py", model="google/gemini-2.5-pro", max_connections=20)
```

Use `inspect eval --help` to learn about all of the available generation config options.

> **NOTE: NoteTemperature is not random assignment**
>
> Do not use model sampling as the source of random assignment in an eval. Increasing `temperature` can make outputs more variable, but it does not make equivalent labels, choices, or orderings equally likely.
>
> If the eval needs randomness, randomize in the dataset, solver, or setup code (for example, with [sample shuffling](./datasets.html.md#shuffling) or [choice shuffling](./datasets.html.md#choice-shuffling)). If the task intentionally asks the model to make a stochastic choice, run repeated [epochs](./metrics.html.md#reducing-epochs) first and report the observed label distribution, for example with a categorical scorer and [frequency()](./metrics.html.md#built-in-metrics).

## Model Args

If there is an additional aspect of a model you want to tweak that isn’t covered by the [GenerateConfig](./reference/inspect_ai.model.html.md#generateconfig), you can use model args to pass additional arguments to model clients. For example, here we specify the `location` option for a Google Gemini model:

``` bash
inspect eval arc.py --model google/gemini-2.5-pro -M location=us-east5
```

See the documentation for the requisite model provider for information on how model args are passed through to model clients.

## Max Connections

Inspect uses an asynchronous architecture to run task samples in parallel. If your model provider can handle 100 concurrent connections, then Inspect can utilise all of those connections to get the highest possible throughput. The limiting factor on parallelism is therefore not typically local parallelism (e.g. number of cores) but rather what the underlying rate limit is for your interface to the provider.

By default, Inspect uses a `max_connections` value of 10. You can increase this consistent with your account limits. If you are experiencing rate-limit errors you will need to experiment with the `max_connections` option to find the optimal value that keeps you under the rate limit (see [Model Concurrency](./models-concurrency.html.md) for additional documentation, including the `--adaptive-connections` option that tunes this for you automatically).

## Model API

The `--model` which is set for an evaluation is automatically used by the [generate()](./reference/inspect_ai.solver.html.md#generate) solver, as well as for other solvers and scorers built to use the currently evaluated model. If you are implementing a [Solver](./reference/inspect_ai.solver.html.md#solver) or [Scorer](./reference/inspect_ai.scorer.html.md#scorer) and want to use the currently evaluated model, call [get_model()](./reference/inspect_ai.model.html.md#get_model) with no arguments:

``` python
from inspect_ai.model import get_model

model = get_model()
response = await model.generate("Say hello")
```

If you want to use other models in your solvers and scorers, call [get_model()](./reference/inspect_ai.model.html.md#get_model) with an alternate model name, along with optional generation config. For example:

``` python
model = get_model("openai/gpt-4o")

model = get_model(
    "openai/gpt-4o",
    config=GenerateConfig(temperature=0.9)
)
```

You can also pass provider specific parameters as additional arguments to [get_model()](./reference/inspect_ai.model.html.md#get_model). For example:

``` python
model = get_model("hf/openai-community/gpt2", device="cuda:0")
```

### Model Caching

By default, calls to [get_model()](./reference/inspect_ai.model.html.md#get_model) are memoized, meaning that calls with identical parameters resolve to a cached version of the model. You can disable this by passing `memoize=False`:

``` python
model = get_model("openai/gpt-4o", memoize=False)
```

Finally, if you prefer to create and fully close model clients at their place of use, you can use the async context manager built in to the [Model](./reference/inspect_ai.model.html.md#model) class. For example:

``` python
async with get_model("openai/gpt-4o") as model:
    eval(mytask(), model=model)
```

If you are not in an async context there is also a sync context manager available:

``` python
with get_model("hf/Qwen/Qwen2.5-72B") as model:
    eval(mytask(), model=model)
```

Note though that this *won’t work* with model providers that require an async close operation (OpenAI, Anthropic, Grok, Together, Groq, Ollama, llama-cpp-python, and CloudFlare).

### Streaming Events

[generate()](./reference/inspect_ai.solver.html.md#generate) accepts an optional `on_stream` async callback which receives incremental [StreamEvent](./reference/inspect_ai.model.html.md#streamevent)s while the response streams. This is a side-channel for UI display — the final result is still the returned [ModelOutput](./reference/inspect_ai.model.html.md#modeloutput):

``` python
from inspect_ai.model import StreamEvent, get_model

async def show(event: StreamEvent) -> None:
    if event.type == "text":
        print(event.text, end="", flush=True)

model = get_model()
response = await model.generate("Say hello", on_stream=show)
```

Events include text deltas (`type="text"`), reasoning deltas (`type="reasoning"`), tool-call argument deltas (`type="tool_call"`), and retry boundaries (`type="retry"`). A retry boundary signals that the call is being retried after a failed attempt: deltas received so far belong to that failed attempt and should be discarded, since the final [ModelOutput](./reference/inspect_ai.model.html.md#modeloutput) comes entirely from the attempt that succeeds.

### Stream Idle Timeout

Streaming responses occasionally stall: the provider stops delivering chunks but nothing closes the connection, so the call sits until a coarse timeout fires. The `stream_idle_timeout` generation config option (`--stream-idle-timeout` on the CLI) abandons and retries an attempt when a *streaming* response delivers no chunk for the specified number of seconds — a much sharper signal than `timeout` or `attempt_timeout`, which must be set above the slowest healthy call:

``` bash
inspect eval ctf.py --stream-idle-timeout 30 --attempt-timeout 600
```

An expired attempt is retried exactly like an `attempt_timeout` expiry (per `max_retries`, within the `timeout` budget). Setting the option requests streaming, in the same way that passing `on_stream` does (a provider-level streaming opt-out still wins, in which case the option is inert). It has no effect on calls that do not stream, and it only protects providers whose streaming loops report chunks: currently Anthropic, Google, OpenAI, OpenAI-compatible (including Together), Grok, and SageMaker. On other providers the option is silently inert, and it never covers a hang before the response stream opens — use `attempt_timeout` as the coarse whole-attempt backstop in both cases (the two options compose).

Choose a value above the provider’s longest legitimate inter-chunk gap — for example, time-to-first-token after the stream opens can reach tens of seconds for reasoning models when providers don’t surface keepalive pings. Provider-internal continuation requests count against the idle window too: when a provider issues a follow-up HTTP request mid-attempt (such as Anthropic `pause_turn` or server-tool continuations), the connect and time-to-first-byte of that new request is inter-chunk silence from this option’s perspective, so size the value to accommodate it. The silence clock likewise runs until the provider call returns rather than until the response stream ends, so once armed it also ticks through a provider SDK’s own internal retry backoff (its sleep and reconnect are silence too) — keep the value above those backoff windows.

## Model Roles

Model roles enable you to create aliases for the various models used in your tasks, and then dynamically vary those roles when running an evaluation. For example, you might have a “critic” or “monitor” role, or perhaps “red_team” and “blue_team” roles. Roles are included in the log and displayed in model events within the transcript.

Here is a scorer that utilises a “grader” role when binding to a model:

``` python
@scorer(metrics=[accuracy(), stderr()])
def model_grader() -> Scorer:
    async def score(state: TaskState, target: Target):
        model = get_model(role="grader")
        ...
```

By default if there is no “grader” role specified, the default model for the evaluation will be returned.

Model roles can be specified in several ways:

**In the task definition:**

``` python
Task(
    ...,
    model_roles={"grader": "openai/gpt-4o"}
)
```

**With generation config in the task definition:**

``` python
Task(
    ...,
    model_roles={
        "grader": {
            "model": "openai/gpt-4o",
            "temperature": 0.5,
            "max_tokens": 2048
        }
    }
)
```

**With [task_with()](./reference/inspect_ai.html.md#task_with):**

``` python
task_with(my_task(), model_roles={"grader": "google/gemini-2.0-flash"})
```

**With [eval()](./reference/inspect_ai.html.md#eval):**

``` python
eval("math.py", model_roles={"grader": "google/gemini-2.0-flash"})
```

**On the CLI** with simple model names:

``` bash
inspect eval math.py --model-role grader=google/gemini-2.0-flash
```

**On the CLI** with inline JSON/YAML for generation config:

``` bash
# JSON
inspect eval math.py \
    --model-role 'grader={"model": "openai/gpt-4o", "temperature": 0.5}'
# YAML
inspect eval math.py \
    --model-role 'grader={model: openai/gpt-4o, temperature: 0.5}'
```

Note that the built-in [model-graded scorers](./model-graded.html.md) (e.g. [model_graded_qa()](./reference/inspect_ai.scorer.html.md#model_graded_qa), [model_graded_fact()](./reference/inspect_ai.scorer.html.md#model_graded_fact)) look for the `grader` role by default.

### Multiple Models per Role

A role can also be bound to a *list* of models:

``` python
eval(
    "math.py",
    model_roles={
        "grader": [
            "openai/gpt-4o",
            "google/gemini-2.0-flash",
            "anthropic/claude-sonnet-4-0"
        ]
    }
)
```

Or equivalently on the CLI with comma-separated model names:

``` bash
inspect eval math.py \
    --model-role grader=openai/gpt-4o,google/gemini-2.0-flash,anthropic/claude-sonnet-4-0
```

When a list is bound to the role used by a [model-graded scorer](./model-graded.html.md), each model grades independently and the final grade is chosen by majority vote (the same behaviour as passing a list of models to the scorer’s `model` parameter). Prefer an odd number of graders: with an even-sized ensemble, a tied vote is resolved in favour of the earliest-listed model. Elsewhere, `get_model(role="...")` resolves to the first model in the list—use [model_roles()](./reference/inspect_ai.model.html.md#model_roles) (from `inspect_ai.model`) to access all of the models bound to a role. Note that a single-element list is equivalent to binding the single model directly.

Model roles can also be specified in a `--run-config` file alongside the full eval configuration. See [Run Config File](./tasks.html.md#run-config).

For how model roles fit into the broader override and precedence model, see [Configuration](./tasks.html.md#model-roles).

### Role Resolution

Model roles are resolved based on what is passed to [eval()](./reference/inspect_ai.html.md#eval). This means that if you fully construct tasks before calling [eval()](./reference/inspect_ai.html.md#eval) (e.g. by calling their `@task` function) then the initialization code for tasks, solvers, and scorers for can’t see the model role definitions.

Given this, you should always call [get_model()](./reference/inspect_ai.model.html.md#get_model) *inside* the implementation of your solver or scorer function rather than during initialization. For example:

**Don’t do this (model role not yet visible)**

``` python
@scorer(metrics=[accuracy(), stderr()])
def model_grader() -> Scorer:
1    model = get_model(role="grader")
    async def score(state: TaskState, target: Target):   
        ...
```

1  
Role is not yet visible when `@task` function is called before [eval()](./reference/inspect_ai.html.md#eval).

**Rather do this (defer until role is visible)**

``` python
@scorer(metrics=[accuracy(), stderr()])
def model_grader() -> Scorer:
    async def score(state: TaskState, target: Target):  
1        model = get_model(role="grader")
        ...
```

1  
Role is visible since we are calling this after [eval()](./reference/inspect_ai.html.md#eval).

### Role Defaults

By default if there is a no role explicitly defined then `get_model(role="...")` will return the default model for the evaluation. You can specify an alternate default model as follows:

``` python
model = get_model(role="grader", default="openai/gpt-4o")
```

This means that you can use model roles as a means of external configurability even if you aren’t yet explicitly taking advantage of them.

### Roles for Tasks

In some cases it may not be convenient to specify `model_roles` in the top level call to [eval()](./reference/inspect_ai.html.md#eval). For example, you might be running an [Eval Set](./eval-sets.html.md) to explore the behaviour of different models for a given role. In this case, do not specify `model_roles` at the eval level, rather, specify them at the task level.

For example, imagine we have a task named `blues_clues` that we want to vary the red and blue teams for in an eval set:

``` python
from inspect_ai import eval_set, task_with
from ctf_tasks import blues_clues 

tasks = [
    task_with(blues_clues(), model_roles = {
        "red_team": "openai/gpt-4o",
        "blue_team": "google/gemini-2.0-flash"
    }),
    task_with(blues_clues(), model_roles = {
        "red_team": "google/gemini-2.0-flash",
        "blue_team": "openai/gpt-4o"
    })
]

eval_set(tasks, log_dir="...")
```

Note that we also don’t specify a `model` for this eval (it doesn’t have a main model but rather just the red and blue team roles).

As illustrated above, you can define as many named roles as you need. When using [eval()](./reference/inspect_ai.html.md#eval) or [Task](./reference/inspect_ai.html.md#task) roles are specified using a dictionary. When using `inspect eval` you can include multiple `--model-role` options on the command line:

``` bash
inspect eval math.py \
   --model-role red_team=google/gemini-2.0-flash \
   --model-role blue_team=openai/gpt-4o-mini
```

## Learning More

- [Providers](./providers.html.md) covers usage details and available options for the various supported providers.

- [Caching](./caching.html.md) explains how to cache model output to reduce the number of API calls made.

- [Compaction](./compaction.html.md) covers compacting message histories for long-running agents that exceed the context window.

- [Multimodal](./multimodal.html.md) describes the APIs available for creating multimodal evaluations (including images, audio, and video).

- [Reasoning](./reasoning.html.md) documents the additional options and data available for reasoning models.

- [Batch Mode](./models-batch.html.md) covers using batch processing APIs for model inference.

- [Structured Output](./structured.html.md) explains how to constrain model output to a particular JSON schema.
