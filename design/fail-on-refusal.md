# Fail on Refusal — terminate a sample when a model returns `content_filter`

> **Status: implemented** (meridianlabs-ai/inspect_ai#438). Originating
> issue: meridianlabs-ai/inspect_ai#437. Builds on the existing `StopReason`
> value `"content_filter"` rather than introducing a new signal. Deviations
> from the proposal found during implementation are noted inline as
> "Implementation note".

## Summary

Add a `fail_on_refusal` generate-config option. When enabled,
`Model.generate()` raises a new `ModelRefusalError` after a generation ends
with `stop_reason == "content_filter"`. The sample then fails as an ordinary
sample error, so it shows up loudly in the log, in the display, and in
`fail_on_error` accounting. Because it lives in `GenerateConfig`, it can be
set eval-wide, per task, per model, per model role, or per call, using
plumbing that already exists.

## Problem

Capabilities teams want to run arbitrary tasks and agents and be informed
loudly if a sample is hit by a model refusal. Today the agent quietly exits
after a few refusals and the sample is scored zero, which is
indistinguishable from a genuine failure of the task. Falling back to another
model is not appropriate for this use case: the run should stop and say why.

## What happens today

- `StopReason` already has `"content_filter"`
  (`src/inspect_ai/model/_model_output.py`). Every provider maps refusals and
  safety filters onto it, including the cases where a 4xx is converted into a
  refusal output (`_providers/anthropic.py`, `_providers/google.py`,
  `_providers/bedrock.py`, and the shared OpenAI helper
  `src/inspect_ai/model/_openai.py`). `stop_details` carries the
  category when the provider reports one. This is the signal the Slack thread
  asked us to build on, and it is the only trigger this design uses.
- `Model.generate()` notices the refusal only to count it and optionally log a
  warning via `--log-refusals` (`report_refusal()` in
  `src/inspect_ai/model/_model.py`, `src/inspect_ai/log/_refusal.py`).
  Nothing stops the sample.
- `react()` retries a refusal `retry_refusals` times (`_model_generate` in
  `src/inspect_ai/agent/_react.py`), then after 3 consecutive refusals
  silently breaks out of the loop. The sample proceeds to scoring and is
  typically scored zero. This is the "quietly exits" behaviour in the issue.
  The bridge does the same (`bridge_generate` in
  `src/inspect_ai/agent/_bridge/util.py`).
- `fallback_models` is Anthropic-only and server-side. It changes which model
  answers, which the issue says is not appropriate here.

## Proposal

### 1. New `GenerateConfig` field

```python
fail_on_refusal: bool | None = Field(default=None)
"""Raise a ModelRefusalError (failing the sample) when the model returns
stop_reason="content_filter". Defaults to False."""
```

Added to both `GenerateConfigArgs` and `GenerateConfig` in
`src/inspect_ai/model/_generate_config.py`. Default `None` means off, so
existing behaviour is unchanged.

Why `GenerateConfig` rather than a new `eval()` argument like `log_refusals`:
the request wants global, per-model and per-role control. Generate config can
already be set at every one of those levels (eval, task, model, role, call)
and already flows through `--model-role`, `--model-spec`, `--run-config`,
`ModelConfig` for roles, and the eval spec in the log. A standalone eval
option would need all of that built again. The precedence between those
levels is described in section 6.

### 2. New public exception

```python
class ModelRefusalError(Exception):
    """Raised by Model.generate() when fail_on_refusal is set and the
    model returned stop_reason="content_filter"."""
    output: ModelOutput   # full output, so stop_details/category are available
    model: str
    role: str | None
```

Exported from `inspect_ai.model`. Message format:
`Model refusal (<model>[, role <role>][, category <category>]): <first ~200 chars of completion>`.
Including the category and a stable `Model refusal` prefix makes these errors
easy to filter in the dataframe `error` column and in `inspect view`.

*Implementation note.* The sample runner records a generic exception's
`EvalError.message` as its repr (`ModelRefusalError('Model refusal (...)')`),
so in logs and dataframes the `Model refusal` text is a stable substring
rather than the first characters of the message. Filter with `contains`.

### 3. Raise point

In the outer frame of `Model.generate()`, as the last step before
`return output`, using the resolved config for that call. The refusal
counter (`report_refusal()`) runs at the end of `Model._generate()`; the
outer `generate()` then stamps `event.timestamp`, `event.working_start`,
`event.completed` and `event.working_time` on the `ModelEvent`, re-emits it
via `transcript()._event_updated(event)`, and calls
`_stamp_redacted_reasoning_tokens(output)`. The raise goes after all of that,
so a refusal `ModelEvent` in the log carries the same completion timing as
any other. Raising there, rather than in `_generate()`, inside the retry
loop, or in the provider, means:

- The `ModelEvent` is complete, with the refusal output and its timing, so
  the transcript shows the refusal and then the `ErrorEvent`.
- Usage, turn counting, the refusal counter, and telemetry all still run.
- Provider retries and the (non-)caching of refusal outputs are unaffected.
  Refusals are already never cached (`src/inspect_ai/model/_cache.py`).
- Callers that `await model.generate()` directly are covered without
  changes: the `generate()` solver, `react()`, synchronous `deepagent`
  subagents, in-process `agent_bridge()` scaffolds, custom agents,
  compaction, and model-graded scorers. One caveat for `agent_bridge()`: the
  error surfaces as a Python exception out of the patched SDK call inside the
  scaffold's own code, so a scaffold that wraps its API calls in a broad
  `except Exception` retry loop will swallow it and carry on, exactly as it
  would swallow a `LimitExceededError` today. In-process coverage therefore
  depends on the scaffold not catching broad exceptions around SDK calls, and
  the docs should say so. Three paths need extra handling; see "Known gaps"
  below.

The trigger predicate is
`not output.empty and output.stop_reason == "content_filter"`, the same
guard the refusal counter uses in `_generate()` (first choice). The
`retry_refusals` checks in `_model_generate` (`_react.py`) and
`bridge_generate` (`_bridge/util.py`) currently test `stop_reason` alone;
that is safe today only because `ModelOutput.stop_reason` indexes
`choices[0]` and so raises on an empty output anyway. The section 5 change
to those loops adopts the full guard, so the counter, the retry loops and
the raise stay in lockstep and there is no state where the counter says
"refusal" but the sample did not fail.

**Cache key.** `_cache_key_config` in `src/inspect_ai/model/_cache.py`
hashes every `GenerateConfig` field except those in
`_CACHE_KEY_DROPPED_FIELDS`, so a new field would otherwise change the key
and adding `--fail-on-refusal` to an existing run would get zero cache hits.
The field never reaches the provider request, so it is added to
`_CACHE_KEY_DROPPED_FIELDS`. Cached entries are never refusals, so a cache
hit can never need to raise.

*Implementation note.* `tests/model/test_cache.py` asserts that the cache
key's inert fields equal `GENERATE_CONFIG_FIELDS_TO_EXCLUDE` (eval-set task
identity), on the reasoning that both answer "can this field change what the
provider returns". `fail_on_refusal` is the first field where the two answers
differ: the provider never sees it (cache-inert) but it changes sample
outcomes (identity-relevant, section 7). The test now carves out a named
`_CACHE_NEUTRAL_OUTCOME_FIELDS` set for exactly this case rather than
forcing the field into one classification or the other.

*Implementation note.* Compaction is covered with one exception found in
review: `_handle_overflow` in `_react.py` wraps *forced* compaction (after a
`model_length` stop) in `except Exception` and degrades to the overflow
filter on failure, which would have swallowed a refused summary generation.
It now re-raises `ModelRefusalError` ahead of that handler.

**Known gaps.** Three paths do not go through `await model.generate()` in a
way that lets the error reach the sample runner, and a fourth (MCP sampling,
at the end of this list) is documented rather than fixed:

- Background `deepagent` subagents. `_run_background` in
  `src/inspect_ai/agent/_deepagent/agent_tool.py` catches `Exception`,
  records it on the future and logs a warning, so a `ModelRefusalError` there
  would surface to the parent as an errored subagent status rather than a
  sample failure. Proposed: add `ModelRefusalError` to the
  `(LimitExceededError, TerminateSampleError)` re-raise clause so it
  propagates to the sample like other sample-level control flow. The
  `background()` wrapper it runs under (the `run()` closure in
  `src/inspect_ai/util/_background.py`) re-raises every exception but logs
  anything outside the same two-type allowlist as `Background worker error`,
  so `ModelRefusalError` joins that `isinstance` check too; otherwise the
  refusal would propagate correctly but also be double-reported as a worker
  failure. Whether a background refusal should fail the parent sample is open
  question 4.
- Bridge filters. In `bridge_generate`, a `filter` that returns a
  `content_filter` `ModelOutput` bypasses `model.generate()` entirely, so
  nothing raises. Proposed: `bridge_generate` applies the same predicate to
  filter-produced outputs once refusal retries are exhausted, using the
  bridge model's resolved config. This is a small addition to the
  catch-and-re-raise change that `bridge_generate` needs anyway (section 5).
- Sandbox bridge. Bridged generations for `sandbox_agent_bridge()` run
  inside the sandbox service task, and nothing raised there reaches the
  sample runner. Two layers stand in the way. `_forward_provider_errors` in
  `src/inspect_ai/agent/_bridge/sandbox/service.py` catches `Exception`
  (re-raising only `LimitExceededError`) and returns the failure to the
  scaffold as a provider-dialect error response so the model proxy stays up.
  Behind it, the service dispatcher (`_handle_request` in
  `src/inspect_ai/util/_sandbox/service.py`) wraps every method call with a
  dedicated `except LimitExceededError` branch that calls
  `active.limit_exceeded(ex)` on the active sample, plus a generic
  `except Exception` that logs and writes an RPC error response.
  `LimitExceededError` ends the sample because of that `limit_exceeded()`
  hook, not because it is re-raised. So simply re-raising `ModelRefusalError`
  from `_forward_provider_errors` would land in the generic branch and reach
  the scaffold as an RPC error, which SDK clients typically retry or the
  scaffold exits on, and the sample would proceed to scoring.

  `SandboxAgentBridge.request_terminate`
  (`src/inspect_ai/agent/_bridge/sandbox/types.py`) already documents this
  constraint and solves it with a signal: it stores a reason, sets an
  `anyio.Event`, and raises so the current RPC unwinds with an error
  response; `_monitor_terminate` in `sandbox/bridge.py`, a task in the
  `sandbox_agent_bridge` task group, waits on the event and raises
  `TerminateSampleError` on the agent's side, where the task group unwinds
  the agent and the sample runner sees it. Proposed: generalize that signal
  to carry an exception. `SandboxAgentBridge` gains a `request_fail(error)`
  that stores the exception and sets the event (with `request_terminate`
  becoming the `TerminateSampleError` case), and `_monitor_terminate`
  becomes `_monitor_failure`, raising whatever was stored.
  `_forward_provider_errors` then catches `ModelRefusalError`, calls
  `bridge.request_fail(ex)`, and still returns the provider-dialect error
  payload so the scaffold is not left waiting on a reply; the monitor task
  tears the sample down regardless of what the scaffold does with that
  response. Two details for the implementer. `_forward_provider_errors`
  today closes over only the generate method and has no reference to the
  bridge, so it grows a `bridge` parameter (`run_model_service`, which
  builds the wrappers, already has it). And a `ModelRefusalError` has no
  `status_code`, so `provider_error_payload` (via `status_code_of`) gives it
  `status: None`; the existing `status is None` branch would then log it as
  "Agent bridge model request failed with a non-provider error" with a
  traceback. The refusal branch returns the payload without that warning,
  since the failure is reported once through the monitor task, the same
  double-reporting concern handled for `background()` above. The
  alternative is a service-level special case like the
  `LimitExceededError` branch in `_handle_request`; rejected because it would
  teach the generic sandbox service about a model-layer error type, whereas
  the bridge already owns a mechanism built for exactly this.
- MCP sampling. `sampling_fn` in `src/inspect_ai/tool/_mcp/sampling.py`
  answers a server-initiated `sampling/createMessage` request by calling
  `get_model().generate()` inside a bare `except Exception` that returns an
  MCP `ErrorData`, so a refusal raised there reaches the MCP server as an
  error and the sample continues. Re-raising would not help: the callback
  runs inside the mcp SDK's request dispatcher, which catches any exception
  from a handler, logs it with a traceback and answers the server with an
  `INTERNAL_ERROR` response (`mcp/shared/direct_dispatcher.py` and
  `jsonrpc_dispatcher.py` in mcp 2.x), the same constraint as the sandbox
  service dispatcher above. Failing the sample from there would need a
  failure signal into the task that owns the MCP connection, as the sandbox
  bridge has. `LimitExceededError` is swallowed on this path today for the
  same reason, so this is a pre-existing shape the new option inherits, and
  the path is niche (an MCP server asking Inspect to generate on its behalf).
  It is documented in `docs/fallbacks.qmd` next to the in-process bridge
  caveat and left as is.

### 4. Sample outcome

`ModelRefusalError` is a plain `Exception`, so the task runner's generic
handler turns it into an `EvalError` (`src/inspect_ai/_eval/task/run.py`).
Consequences, all intentional:

- The sample is marked errored rather than scored, and `fail_on_error`
  accounting treats it like any other sample error. Note the default:
  `eval()` declares `fail_on_error: bool | float | None = None`, and
  `_should_eval_fail` in `src/inspect_ai/_eval/task/error.py` treats `None`
  like `True`, failing the eval on the *first* sample error. So
  `--fail-on-refusal` on its own means one refusal in any sample aborts the
  whole eval. That is the "stop and say why" behaviour the issue asks for,
  but it is stricter than "this sample errored, the run continues". Users
  who want the latter combine the flag with `--no-fail-on-error`, a
  `--fail-on-error` threshold, or `--continue-on-fail`. The two flags read
  as if they compose independently, so the CLI docs for `--fail-on-refusal`
  must state this pairing plainly.
- `score_on_error` still works for users who want a score alongside the
  error.
- `retry_on_error` sample retries apply as to any other error. A fresh attempt
  is often what you want at a filter decision boundary. If that proves
  wasteful for deterministic refusals we can exclude the error type later.
- `eval_set()` retries any task whose log status is `error` up to
  `retry_attempts` times (default 10, `src/inspect_ai/_eval/evalset.py`).
  Under default `fail_on_error`, a deterministic refusal therefore becomes up
  to `retry_attempts` full re-runs of the task before the set gives up. The
  design leaves this as ordinary error behaviour, since a refusal at a
  filter boundary is not reliably deterministic and eval-set users already
  tune `retry_attempts`; see open question 3.

It is deliberately not a `LimitExceededError`. Limits mean "stopped early,
still scored, counted as success", which is the opposite of what the issue
asks for.

### 5. Interaction with `retry_refusals`

Without care, the raise would defeat `retry_refusals`, because the first
refused attempt would already raise. So the `_model_generate` retry loop in
`src/inspect_ai/agent/_react.py` (shared by `react()` and `react_no_submit()`)
and `bridge_generate` catch `ModelRefusalError` while retry attempts remain
and re-raise the final one. Net effect: `retry_refusals=N` plus
`fail_on_refusal=True` means "N+1 consecutive refusals in one step fails the
sample". Every other refusal-retry loop in an extension gets the same shape:
catch, retry, re-raise.

Two consequences for implementers:

- `react()` and `react_no_submit()` each have their own outer loop with the
  hardcoded `consecutive_content_filter >= 3` break (around lines 268 and 491
  of `_react.py`). Both become unreachable when the option is on, because the
  refusal raises before the outer loop sees it, and both can stay as-is.
- Defaults differ by agent. `react()` defaults `retry_refusals=None`, so one
  refusal fails the sample. `deepagent()` defaults `retry_refusals=3`
  (`src/inspect_ai/agent/_deepagent/deepagent.py`), so a deepagent step gets
  four consecutive refusals before the sample fails. That is the existing
  retry behaviour of each agent, unchanged by this design; the option only
  decides what happens once retries are exhausted.

### 6. Scope and precedence

The field follows the existing `GenerateConfig` merge order for the active
model; only the role path gets new behaviour. `GenerateConfig.merge()` is
"non-`None` in `other` wins", and the existing composition is:

- `task.config.merge(GenerateConfigArgs(**kwargs))` in
  `src/inspect_ai/_eval/task/run.py`: eval-wide kwargs override the task
  config.
- `Model._resolve_config` in `src/inspect_ai/model/_model.py`: for the active
  model, `self.config.merge(active_config)`, so the task/eval-wide result
  overrides the model's own config (`--model-spec`, `get_model(config=...)`).
  Then `.merge(config)` applies the per-call config last.

So for the active model, from lowest to highest:

| Layer | How | Overridden by |
|---|---|---|
| Model | `--model-spec "{model: ..., fail_on_refusal: true}"`, `get_model(..., config=GenerateConfig(fail_on_refusal=True))` | task, eval-wide, per call |
| Task | `Task(config=GenerateConfig(fail_on_refusal=True))` | eval-wide, per call |
| Eval-wide | `eval(..., fail_on_refusal=True)`, `--fail-on-refusal`, `INSPECT_EVAL_FAIL_ON_REFUSAL` | per call |
| Per call | `model.generate(..., config=GenerateConfig(fail_on_refusal=False))` | nothing (highest) |

Consequences of keeping the existing order:

- Eval-wide is a blanket setting. "Fail everywhere except this one active
  model" is not expressible via `--model-spec` while `--fail-on-refusal` is
  set, because eval-wide overrides model config. To vary the option per model
  in a multi-model eval, leave eval-wide unset and set it in each
  `--model-spec` (each model runs as the active model of its own eval, so the
  model layer then decides).
- This matches how every other `GenerateConfig` field behaves, so users get
  no surprises, and it needs no change to the active-model path.

Role models are the exception, and one change is needed for the task and
eval-wide layers to reach them at all. The config that `_resolve_config`
consults for this is `active_generate_config()`, which is not the eval-wide
config alone: `init_task_context` in `src/inspect_ai/_eval/task/run.py`
receives `task.config.merge(GenerateConfigArgs(**kwargs))`, so it is the
task config with eval-wide kwargs layered on top. Under this proposal
`Task(config=GenerateConfig(fail_on_refusal=True))` therefore flows into
grader and other role models exactly as `--fail-on-refusal` does. A task
author who wants the option only on the agent must set it per role instead.
Today non-active models inherit just a handful of operational fields from
that active config (`max_connections`, `adaptive_connections`,
`max_retries`, `timeout`, `cache`) in the `else` branch of `_resolve_config`.
`fail_on_refusal` joins that inherited set, but with role-wins precedence: it
is copied from the active config only when the role model's own config
leaves it unset. The existing operational fields go the other way (active
config overrides the role), which would make it impossible to say "fail
everywhere except the grader". The `merge()` semantics support this with a
two-line conditional. A role's own config comes
from `--model-role grader="{model: ..., fail_on_refusal: false}"` or
`get_model(..., config=GenerateConfig(fail_on_refusal=False))` in
`model_roles`; when a caller passes a config to `get_model(role=...)`, the
role model's own config already wins over it (`config.merge(model_for_role.config)`
in `get_model`), consistent with role-wins.

Typical configurations this enables:

```bash
# fail any sample where any model refuses
inspect eval task.py --model anthropic/claude-fable-5 --fail-on-refusal

# fail on refusals from the agent, but let a grader refuse normally
inspect eval task.py --fail-on-refusal \
  --model-role grader="{model: openai/gpt-5, fail_on_refusal: false}"

# multi-model eval: fail on refusals for one model only
inspect eval task.py \
  --model-spec "{model: anthropic/claude-fable-5, fail_on_refusal: true}" \
  --model-spec "{model: openai/gpt-5}"
```

### 7. Eval-set identity

The field stays in the task identifier hash (it is not added to
`GENERATE_CONFIG_FIELDS_TO_EXCLUDE` in `src/inspect_ai/_eval/evalset.py`)
because it changes sample outcomes. Flipping it produces a new task rather
than silently reusing logs.

### 8. CLI

`--fail-on-refusal/--no-fail-on-refusal` as a boolean flag pair on
`inspect eval` and `inspect eval-set`, env var `INSPECT_EVAL_FAIL_ON_REFUSAL`.
The pair's click default is `None`, so an omitted flag reaches
`GenerateConfigArgs` as `None` and does not clobber file, task or model
config, `--fail-on-refusal` is `True`, and `--no-fail-on-refusal` is `False`.
That last value matters: because eval-wide config wins over task and model
config (section 6), the negated flag is the only way the CLI can turn the
option off for a run whose `Task` or `--model-spec` config enables it. A
single flag converted like `logprobs` (`False` becomes `None` in
`src/inspect_ai/_util/generate_config_args.py`) was the first draft and was
replaced in review for that reason; `config_from_locals` needs no
special case for this field. The flag's help text and `docs/options.qmd`
entry state that, with the default `fail_on_error`, the first refusal aborts
the eval, and point at `--no-fail-on-error` and `--continue-on-fail` for
per-sample failure.

## Alternatives considered

- **A `react()`-only option** (`on_refusal="error"`). Rejected: does not cover
  custom agents, bridged scaffolds, or scorers, and the issue explicitly wants
  arbitrary tasks and agents.
- **A new sample limit** (`refusal_limit(n)`, `EvalSampleLimit` type
  `"refusal"`). Rejected as the primary mechanism because limits still score
  the sample and count as success. It would be a reasonable follow-up if a
  team wants "stop and score" rather than "stop and error", and nothing here
  precludes it.
- **A generalized `fail_on_stop_reason: list[StopReason]`.** Rejected for
  now: `model_length` and `max_tokens` have in-band recovery paths (overflow
  handling, compaction, truncation) that a raise inside `generate()` would
  break. `content_filter` is the only stop reason with no recovery path. The
  bool name does not block adding a list-valued sibling later.
- **A separate `eval()` argument** mirroring `log_refusals`. Rejected: no
  per-role or per-call granularity without new plumbing.

## Files touched

- `src/inspect_ai/model/_generate_config.py`: field on `GenerateConfigArgs`
  and `GenerateConfig`.
- `src/inspect_ai/model/_model.py`: `ModelRefusalError`, raise at the end of
  the outer `generate()` after the event timing re-emit, role inheritance in
  `_resolve_config`.
- `src/inspect_ai/model/_cache.py`: add the field to
  `_CACHE_KEY_DROPPED_FIELDS`.
- `src/inspect_ai/model/__init__.py`: export the error.
- `src/inspect_ai/agent/_react.py`, `src/inspect_ai/agent/_bridge/util.py`:
  catch while retries remain; `bridge_generate` also applies the predicate to
  filter-produced outputs.
- `src/inspect_ai/agent/_deepagent/agent_tool.py`: re-raise
  `ModelRefusalError` from `_run_background`; `src/inspect_ai/util/_background.py`:
  add it to the `background()` no-log allowlist (both pending open question 4).
- `src/inspect_ai/agent/_bridge/sandbox/types.py`: `request_fail(error)` on
  `SandboxAgentBridge`, generalizing the terminate signal;
  `src/inspect_ai/agent/_bridge/sandbox/bridge.py`: `_monitor_failure` raises
  the stored error; `src/inspect_ai/agent/_bridge/sandbox/service.py`:
  `_forward_provider_errors` takes the bridge, calls `request_fail` on
  `ModelRefusalError`, and still returns the provider error payload without
  the non-provider-error warning.
- `src/inspect_ai/_cli/eval.py`, `src/inspect_ai/_util/generate_config_args.py`:
  flag and env var.
- Docs: `docs/fallbacks.qmd` (the refusals page), `docs/react-agent.qmd`
  (refusals section), `docs/eval-logs.qmd` next to `--log-refusals`,
  `docs/options.qmd`, `docs/handling-errors.qmd`.
- `CHANGELOG.md` entry under Unreleased.
- The `GenerateConfig` change regenerates `inspect-openapi.json` and the
  ts-mono types, so landing follows the `land-ts-mono` skill.

## Test plan

- `tests/model/test_refusal_display.py` (already covers refusal reporting):
  mockllm refusal with `fail_on_refusal=True` yields an errored sample whose
  error message carries the `Model refusal` prefix and category; `ErrorEvent`
  follows the `ModelEvent` and the `ModelEvent` has `completed` and
  `working_time` set; default is off; per-call `False` overrides an eval-wide
  `True`.
- Active-model precedence: eval-wide `True` overrides a model config `False`
  (the existing merge order, asserted so a later change is deliberate).
- Role precedence: eval-wide `True` with a role set to `False` leaves that
  role's generate working; eval-wide unset with a role set to `True` fails
  only on that role; `Task(config=...)` `True` reaches a role the same way
  eval-wide does.
- `tests/model/test_cache.py`: the cache key is identical with the field on
  and off.
- `tests/agent/test_agent_react.py`: `retry_refusals=2` with three refusals
  errors; with two refusals then success it succeeds. Same for
  `react_no_submit()`.
- Bridge equivalent in `tests/agent/`, including a `filter` that returns a
  `content_filter` output.
- `tests/agent/test_bridge_provider_errors.py`: its five existing
  `_forward_provider_errors(fn)` call sites are updated for the new `bridge`
  argument, and a new case checks that a `ModelRefusalError` from the wrapped
  generate still returns a provider error payload (the scaffold gets a
  reply), sets the bridge's failure signal, and does not log the
  non-provider-error warning.
- Sandbox bridge end to end, alongside the existing monitor tests in
  `tests/agent/test_bridge_approval.py` (which import `_monitor_terminate` by
  name and so are updated for the `_monitor_failure` rename): the monitor
  task raises the stored `ModelRefusalError`, and a solver using
  `sandbox_agent_bridge()` with a refusing model produces an errored sample,
  asserting on the sample, not just on the wrapper.
- Deepagent: a synchronous subagent refusal fails the sample; a background
  subagent refusal behaves per the answer to open question 4, and if it
  propagates, no `Background worker error` line is logged for it.
- Default `fail_on_error` aborts the eval on the first refusal;
  `fail_on_error=False` records the sample error but the eval succeeds;
  `score_on_error=True` still scores.
- CLI parsing of `--fail-on-refusal` (`True`), `--no-fail-on-refusal`
  (`False`), the omitted flag (`None`) and the env var.

## Open questions

1. Should task-level and eval-wide `fail_on_refusal` reach grader roles by
   default? Both arrive via `active_generate_config()`, so they cannot be
   told apart in `_resolve_config`; whatever is decided applies to
   `Task(config=...)` and `--fail-on-refusal` alike. The design says yes for
   uniform loudness, with per-role opt-out. The alternative is to inherit
   only into the active model and require roles to opt in.
2. With `num_choices > 1`, should any refused choice trigger, or only the
   first? The design follows `report_refusal` (first choice) for consistency.
3. Should `retry_on_error` skip `ModelRefusalError`, and should `eval_set()`
   stop retrying a task whose only errors are refusals? Both are left as
   ordinary error behaviour for now; the eval-set case matters more because
   the default `retry_attempts` of 10 re-runs the whole task each time.
4. Should a refusal inside a background `deepagent` subagent fail the parent
   sample? The design says yes (re-raise from `_run_background`), since the
   goal is loud failure wherever a refusal occurs. The alternative is to keep
   it as an errored subagent status and rely on `--log-refusals` for
   visibility, which would leave background subagents as a documented gap.
