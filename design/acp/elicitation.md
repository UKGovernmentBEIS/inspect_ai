# Ask-the-user feature for ACP agents (`ask_user` tool)

## Context

Today, agents running under ACP have two interactive channels: `session/prompt` (operator → agent, one-way) and `session/request_permission` (agent → client, but only for tool-call approval). There is no first-class way for an agent to **ask the user a structured question and get an answer back** — e.g. "what's the API key?", "which of these three approaches?", "confirm before proceeding".

This plan adds a model-callable `ask_user` tool that presents a structured form (matching ACP's Elicitation schema: string / number / integer / boolean / multi-select). Delivery is decoupled into two orthogonal extension points:

- **Input handlers** — actually collect the answer. Exactly one is consulted per question. Optional user-supplied custom handler runs first with a timeout; if it returns `None` or times out, the system dispatches to whichever built-in is appropriate at runtime.
- **Input notifiers** — fire-and-forget alerts (Slack, desktop, webhook). Run in parallel with the handler, always. Useful for "ping the user that a question is waiting" out of band.

Both are registry-backed (`@input_handler` / `@input_notifier`), configured at the eval level, and follow the same factory-and-decorator pattern as `@approver` / `@solver`. The Slack-as-full-handler case is the canonical custom-handler use: it posts to Slack, threads the answer back, and the user is responsible for not also configuring a Slack notifier on top.

## Approach summary

- **Wire protocol on the ACP side:** ACP 0.10.0's new `elicitation/create` request (marked UNSTABLE upstream — accepted per [[project_acp_no_installed_clients]]). Capability-gated via `ElicitationCapabilities.form` in the client's `initialize`.
- **Author-facing API:** a model-callable `ask_user` tool. The model picks when to ask; the answer comes back as a structured tool result. No agent-loop changes.
- **Question shape:** structured forms from day one — we use ACP's `ElicitationSchema` and property-schema Pydantic types directly (imported from `acp.schema`) rather than inventing a parallel hierarchy or re-exporting.
- **Handler model:** *not* a generalized chain. At runtime there is at most one custom handler (user-configured) plus one auto-selected built-in. The built-in selection is deterministic from runtime context — see "Routing policy" below.

## Routing policy

Built-in handler selection is governed by whether the eval has booted an `AcpServer` that is currently accepting external clients (i.e. `--acp-server` is active):

- **`--acp-server` NOT active.** The ACP handler short-circuits with `None` and the dispatcher falls through to the Textual panel and then the console — same priority order Phase 4 / Phase 2 established. This is the "stand-alone eval" mode; the operator works at the terminal where the eval runs.

- **`--acp-server` IS active.** `ACP is the human channel.` All `ask_user` and `approver: human` interactions route exclusively through attached ACP clients. The in-proc Textual panel and console handlers are bypassed entirely. If no client is connected when an interaction fires, the eval parks on the registry's attach event until one attaches — *no silent fallback*. The notification-driven workflow depends on this: an operator who reaches the form by clicking a Slack ping (etc.) must not race the panel for the resolution.

This is a one-way commit. There is no per-interaction or per-eval opt-out; the meaning of `--acp-server` is "ACP is the human channel for this eval." If the operator never attaches a client, the eval blocks indefinitely on the first interaction — which is the right semantic for a notification-driven workflow. The operator cancels the sample if they give up.

The mechanism is a module-level `acp_server_accepting_clients()` accessor (`src/inspect_ai/agent/_acp/server.py`) backed by a `ContextVar` that the `acp_server(...)` context manager flips on for the bound-server lifetime and off when the server stops. Routing shims in `src/inspect_ai/input/acp.py` and `src/inspect_ai/approval/_human/acp.py` consult the accessor at their public entry; the inner driver-chain loop unconditionally parks on chain exhaustion regardless of attach history. The flag is deliberately separate from "is the current transport a `LiveAcpTransport`": the Live transport is opened per-sample regardless of `--acp-server` (sub-agent reachability needs the in-process pub/sub plumbing), and nested `acp_session()` blocks install a `NoOp` shadow that would mis-route human-in-the-loop traffic. Both shims also resolve the routing target via `sample_active().acp_transport` (the outermost Live, pinned at sample startup) rather than the ContextVar — sub-agent isolation is for *event publishing*, not human channels.

## Concepts and types

```python
# src/inspect_ai/input/_types.py
from acp.schema import ElicitationSchema  # imported, not re-exported

@dataclass
class InputResult:
    outcome: Literal["accepted", "declined", "cancelled"]
    content: dict[str, Any] | None

@dataclass
class InputNotification:
    event: Literal["posted", "answered", "cancelled"]
    message: str
    schema: ElicitationSchema
    sample_id: str
    task_name: str
    metadata: dict[str, Any] | None  # passthrough for handler↔notifier correlation

# Protocols
InputHandler = Callable[[str, ElicitationSchema], Awaitable[InputResult | None]]
InputNotifier = Callable[[InputNotification], Awaitable[None]]
```

A handler returns `None` to mean "I can't / won't handle this — fall through". Any other return value (accepted / declined / cancelled) ends the request. Notifiers always return `None`; per-notifier exceptions are swallowed via `coro_log_exceptions` (see "Async + error isolation" below) so a misbehaving notifier never breaks the agent loop.

## Components and files

### 1. Routing core — new module `src/inspect_ai/input/`

Mirrors `src/inspect_ai/approval/_human/`. Files:

- **`_types.py`** — the dataclasses and Callable type aliases shown above.
- **`request.py`** — `request_input(message, schema, *, metadata=None) -> InputResult`. Orchestrates: (1) fan-out notifiers in parallel via `anyio.create_task_group()` with each notifier wrapped in `coro_log_exceptions`, (2) run custom handler (if configured) with timeout, (3) on `None`/timeout, dispatch to built-in selection. See the "Async + error isolation" section below for why `tg_collect()` isn't the right primitive.
- **`builtin.py`** — `_dispatch_builtin(message, schema)` — selects exactly one of `acp_handler` / `panel_handler` / `console_handler` based on availability. Today's approval code does this implicitly via `NotImplementedError` fallthrough; here we make it explicit.
- **`manager.py`** — `HumanQuestionManager` (parallel to `HumanApprovalManager` at `approval/_human/manager.py:28-92`): in-process queue of pending questions for the Textual panel handler.
- **`panel.py`** — `QuestionInputPanel(InputPanel)` (parallel to `ApprovalInputPanel` at `approval/_human/panel.py:52-103`). Renders form fields dynamically from `ElicitationSchema`: Textual `Input` for strings/numbers, `Checkbox` for booleans, `SelectionList` for multi-select. Submit / Decline buttons.
- **`console.py`** — console-fallback handler. Walks schema properties using `input_screen()` (`util/_console.py:13-41`) + Rich's `Prompt.ask` / `Confirm.ask` / `IntPrompt.ask`.
- **`acp.py`** — ACP-handler wrapper. Routes via `sample_active().acp_transport.request_elicitation(...)` (the outermost `LiveAcpTransport`, pinned at sample startup — see "Routing policy" for why this is NOT `current_acp_transport()`). Gated on `acp_server_accepting_clients()`: returns `None` when `--acp-server` is not active so the dispatcher falls through to panel / console. When the server IS active, parks until an elicitation-capable client attaches — no silent fallback.
- **`registry.py`** — `@input_handler` and `@input_notifier` decorators. Follow the existing `@approver` pattern (registry name + factory function returning the actual callable).

`request.py` looks roughly like:

```python
import anyio
from inspect_ai._util._async import coro_log_exceptions

async def request_input(message, schema, *, metadata=None) -> InputResult:
    cfg = active_input_config()
    notification = InputNotification(event="posted", message=message, ..., metadata=metadata)

    result: InputResult | None = None

    async def run_handler() -> None:
        nonlocal result
        # Custom handler first (if any), with timeout
        if cfg.input_handler is not None:
            with anyio.move_on_after(cfg.input_handler_timeout):
                r = await cfg.input_handler(message, schema)
                if r is not None:
                    result = r
                    return
        # Fall through to built-in selection (acp | panel | console — exactly one at runtime)
        result = await _dispatch_builtin(message, schema)

    # Fan-out notifiers in parallel WITH the handler. Each notifier is wrapped so its
    # exceptions are logged-and-swallowed; the agent loop never sees a notifier error.
    async with anyio.create_task_group() as tg:
        for n in cfg.input_notifiers:
            tg.start_soon(
                coro_log_exceptions, logger, "input notifier",
                _notify_with_timeout, n, notification, cfg.notifier_timeout,
            )
        tg.start_soon(run_handler)

    assert result is not None
    return result
```

## Async + error isolation

Everything is **anyio**, no asyncio (per CLAUDE.md / [[feedback_acp_asyncio_boundary]] is the exception only inside the ACP transport itself). Specifics:

- **`tg_collect()` is not the right primitive for notifier fan-out.** Its default mode raises the first exception; `exception_group=True` raises an `ExceptionGroup`. Neither returns partial successes. For fan-out where we want to ignore per-notifier failures, use an `anyio.create_task_group()` and wrap each notifier in `coro_log_exceptions(logger, "input notifier", notifier, notification)` (`_util/_async.py:90-99`) — that helper already does the catch-and-log we need.
- **Per-notifier timeout:** `anyio.move_on_after(cfg.notifier_timeout)` inside each notifier wrapper. Default e.g. 30s — much shorter than the handler timeout.
- **Custom-handler timeout:** `anyio.move_on_after(cfg.input_handler_timeout)` — generous default (e.g. 600s) since human turnaround can exceed five minutes.
- **Cancellation:** if the agent turn is cancelled, the surrounding task group cancels both the handler and any in-flight notifiers cleanly via anyio's structured concurrency.

### 2. ACP transport — extend `src/inspect_ai/agent/_acp/`

Touch points (all parallel to existing approval code):

- **`connection.py`** — add `request_elicitation(request: CreateFormElicitationRequest) -> ElicitationResponse` next to `request_permission()` (~`connection.py:889-955`). Implementation: `await self._connection.send_request("elicitation/create", params)`. Parse the response action (`accept` / `decline` / `cancel`). Also: capture `ElicitationCapabilities` out of the `initialize` request and store on `ConnectionState` alongside the existing flags (`client_renders_plan`, `raw_events_subscription`).
- **`transport.py`** — add `ElicitationClient` protocol mirroring `ApproverClient` at `transport.py:69-115`.
- **`transport_live.py`** — add `_ElicitationClientRegistry` modeled on `_ApproverClientRegistry` (`transport_live.py:437-`). Same driver-chain-with-fallback semantics: when an attached client disconnects mid-request, retry on the next.
- The ACP-handler in `_input/acp.py` (above) gates on `acp_server_accepting_clients()` and routes via `sample_active().acp_transport`'s elicitation driver chain. Under exclusive routing it parks on `subscribe_elicitation_attach` when the chain is empty rather than bailing — see "Routing policy".

Elicitation lives on the transport, not on `AgentChannel`. The channel carries items *into* the agent loop (operator messages, cancel signals); elicitation is an agent→operator request that flows out via the same low-level path as `session/request_permission`. The two pieces of plumbing exist independently on the transport — the channel substrate is orthogonal to this design.

### 3. The `ask_user` tool — `src/inspect_ai/tool/_tools/_ask_user.py`

Standard factory pattern (cf. `tool/_tools/_think.py:7-38`):

```python
@tool
def ask_user(title: str | None = None) -> Tool:
    """Ask the user a structured question and wait for an answer."""

    async def execute(message: str, schema: dict[str, Any]) -> ToolResult:
        """Ask the human user a question.

        Args:
          message: Prompt shown to the user.
          schema: JSON schema (object) describing the answer fields.
        """
        elicitation_schema = ElicitationSchema.model_validate(schema)
        result = await request_input(message, elicitation_schema)
        if result.outcome == "accepted":
            return json.dumps(result.content)
        elif result.outcome == "declined":
            raise ToolError("User declined to answer.")
        else:
            raise ToolError("User cancelled the question.")

    return ToolDef(execute, name="ask_user", ...).as_tool()
```

`ToolError` is correct here per `tool/_tool.py:50-78`: declined/cancelled are recoverable, so the model can adapt. Register in `src/inspect_ai/tool/__init__.py`.

### 4. Eval-level configuration

Add to the `eval()` / `Task` config (the same place approval policies are configured — see `approval/_policy.py` for the pattern). New optional parameters:

```python
eval(
    task,
    input_handler="slack_handler",                # registry name or callable
    input_handler_args={"channel": "#agents"},     # passed to the factory
    input_handler_timeout=300,                     # seconds; default e.g. 600
    input_notifiers=[                               # registry names or callables
        ("slack_notifier", {"channel": "#agents"}),
        "desktop_notifier",
    ],
)
```

Resolved config is stashed in a context-var (`_active_input_config`) similarly to how approval state is propagated today, so `request_input()` can read it from anywhere.

### 5. Registry decorators — `src/inspect_ai/input/registry.py`

Same factory shape as `@approver` (see `approval/_approver.py`):

```python
@input_handler(name="slack_handler")
def slack_handler_factory(channel: str, bot_token: str | None = None) -> InputHandler:
    async def handle(message: str, schema: ElicitationSchema) -> InputResult | None:
        # post to Slack, await threaded reply, parse against schema, return
        ...
    return handle

@input_notifier(name="slack_notifier")
def slack_notifier_factory(channel: str) -> InputNotifier:
    async def notify(event: InputNotification) -> None:
        ...
    return notify
```

Registry names are referenceable from YAML/CLI eval config strings, mirroring how `approver: "human"` works today.

## Public Python API — `src/inspect_ai/util/__init__.py`

```python
from inspect_ai.util import (
    request_input,
    InputResult,
    InputNotification,
    InputHandler,
    InputNotifier,
    input_handler,    # registry decorator
    input_notifier,    # registry decorator
)
```

ACP schema types (`ElicitationSchema` and the five property schemas) are **not** re-exported — users import them directly from `acp.schema`. They're all available there (confirmed in the installed 0.10.0 package). Reasons: (1) avoid bloating the public surface of `inspect_ai.util`; (2) if upstream renames a field, users see the upstream type directly rather than chasing an Inspect alias.

## Reused utilities (do not reinvent)

- `input_panel()` from `util/_panel.py:81-115` — for the Textual tab
- `input_screen()` from `util/_console.py:13-41` — console fallback (handles Textual-suspend, Rich live-stop, plain)
- `task_screen()` from `_display/core/active.py` — runtime display detection
- `InputPanel` + `InputPanelHost` (`_display/textual/app.py:457-491`) — dynamic tab management
- `HumanApprovalManager` pattern from `approval/_human/manager.py`
- `tg_collect()` from `inspect_ai._util._async` — notifier fan-out
- ACP Pydantic types from the installed `acp` package — schema/scope/request/response

## Transcript surface

The model's tool call is the primary transcript artifact: it carries the question (in `args`) and the answer (in `result`) and renders correctly in both the eval viewer and the running display. No new event type is needed.

`InputEvent` (`event/_input.py`) already exists with `input` and `input_ansi` fields and is recorded automatically by `input_screen()` (called from `_display/textual/app.py:539` and `_display/rich/display.py:242`). That means:

- **Console-fallback handler:** records an `InputEvent` for free, because the user types the answer through `input_screen()`. No extra plumbing.
- **Panel and ACP handlers:** do *not* synthesize an `InputEvent` — there's no raw console input to record, and the tool call already captures the answer.

We deliberately don't extend `InputEvent` or invent a new event type in v1 — the tool-call surface is enough. If we later want richer transcript rendering for ask-user (e.g. showing the schema fields and the user's response as a structured block), that's a follow-on.

## Out of scope (deliberately deferred)

- **URL-mode elicitation** (`CreateUrlElicitationRequest`) — useful for auth flows, but not core to "ask a question". Add later.
- **Multi-question batching** — one `ask_user` call carries one question (which may have multiple fields). Sequential questions = sequential tool calls.
- **Question persistence across resumes.**
- **A dedicated `QuestionEvent` in the transcript.** The tool call itself already shows up with both question (args) and answer (result). No new event type for v1.
- **`suppresses_notifications` handler capability.** Decided against per user direction: notifiers always fire; handler authors avoid double-notifying by not configuring duplicate notifiers (e.g. a Slack-handler user wouldn't also wire a Slack-notifier).
- **Bundled built-in notifiers** (Slack, desktop, etc.). The registry mechanism is in core; concrete notifier implementations ship as user code or future contrib packages.

## Verification

- **Unit tests** in `tests/input/test_input.py`:
  - schema validation; accept/decline/cancel mapping
  - custom-handler-then-builtin fallthrough on `None` and on timeout
  - notifier fan-out runs in parallel and survives per-notifier exceptions
  - registry decorator name lookup
- **ACP integration test** in `tests/agent/_acp/test_elicitation.py` (extending the harness that already exercises `session/request_permission`):
  - mock a client advertising `ElicitationCapabilities.form`
  - send a question, return each of accept/decline/cancel, verify result mapping
  - mock a client that drops mid-request, verify driver-chain fallback in `_ElicitationClientRegistry`
- **Manual UI verification:**
  1. `inspect eval ... --display full` with an agent that calls `ask_user` → confirm "Question" tab appears and renders form inputs
  2. `--display rich` → confirm console fallback prompts via `input_screen()`
  3. Connect Zed (or a stub elicitation-capable ACP client) → confirm the form renders client-side
  4. Eval with a custom Slack-stub handler that delays 2s → confirm notifiers fire immediately and the handler answer wins
  5. Same Slack stub but never answers → confirm `input_handler_timeout` falls through to console
- **Lint/type:** `ruff format`, `ruff check --fix`, `mypy --exclude tests/test_package src tests`.

## Risks and notes

- **ACP Elicitation is UNSTABLE.** Fields may rename in a future acp release. Per project convention we track the latest schema directly without compat shims.
- **No high-level `elicitation/create` helper in `acp`.** Dispatch via `connection.send_request(...)` — same low-level path `session/request_permission` already uses.
- **Custom handler timeout default.** Picked as a deliberate config knob; suggest a generous default (e.g. 600s) since Slack-style human turnaround can easily exceed five minutes. Users wanting "no timeout" pass `None` or a very large value.
- **Notifier failure isolation.** Each notifier runs inside its own task with exceptions captured and logged — one misbehaving notifier never blocks the question or the agent.
- **Handler↔notifier correlation.** A `metadata` passthrough on `request_input()` flows into both the handler call and the `InputNotification`, so e.g. a Slack notifier can post a thread id that a Slack handler later reads. v1 keeps this generic; we can formalize correlation IDs later if needed.

## Implementation

### Guidelines

1. **One phase at a time.** Create a dedicated plan for each phase. Do not exit plan mode or start implementation until the user has approved that phase's plan. Implement, test, and verify each phase before moving to the next.
2. **Review before commit.** After tests pass, pause and review the code together before committing. Do not auto-commit.
3. **Tests at each step.** Every phase produces implementation + tests.
4. **Update this document.** After completing a phase but before committing, replace that phase's overview below with a summary of what actually landed — files created/modified, key design decisions made during implementation, and test coverage. Same pattern as `agent-acp.md`.

### Phase ordering rationale

Phases are ordered so the feature reaches **end-to-end usability at Phase 3** (console-only delivery) and each subsequent phase is a strict enhancement that can be skipped without breaking earlier value. This mirrors `agent-acp.md`'s discipline of delivering an in-process foundation before transport: Phases 1–4 land everything that works without ACP; Phases 5–6 add ACP transport and routing; Phase 7 is optional polish.

Independent testability is the second constraint. Phase 1 ships protocols and the orchestrator testable with mock handlers. Each subsequent handler (console, panel, ACP) is testable in isolation against its own surface, then wired into `_dispatch_builtin` selection.

### Phase 1: Foundation — types, registry, `request_input` orchestrator

Lands the in-process plumbing with mock handlers in tests; no real handler bodies, no tool, no ACP touch points yet.

**Files created:**
- `src/inspect_ai/input/__init__.py` — package re-exports.
- `src/inspect_ai/input/_types.py` — `InputResult`, `InputNotification` dataclasses; `InputHandler` / `InputNotifier` Callable type aliases.
- `src/inspect_ai/input/_config.py` — `InputConfig` dataclass + `_active_input_config` ContextVar + `active_input_config()` accessor.
- `src/inspect_ai/input/registry.py` — `@input_handler` / `@input_notifier` decorators (factory pattern mirroring `@approver`).
- `src/inspect_ai/input/request.py` — `request_input()` orchestrator (anyio task group; per-notifier `coro_log_exceptions` + `move_on_after`; custom handler with timeout falling through to a `_dispatch_builtin` stub that raises `NotImplementedError`).
- `tests/input/test_input.py` — orchestrator tests against mock handlers.

**What lands:**
- Types and the ContextVar-backed config (defaults: no custom handler, no notifiers, handler timeout 600s, notifier timeout 30s).
- Registry: name lookup, factory args passthrough — same shape as `@approver`.
- Orchestrator: notifier fan-out parallel with handler inside one `anyio.create_task_group`; per-notifier isolation via `coro_log_exceptions`; custom handler wrapped in `anyio.move_on_after(input_handler_timeout)`.
- `_dispatch_builtin` is a stub that raises — Phases 2/4/5 fill in console/panel/ACP one at a time.
- **`active_input_config()` works outside any eval scope.** When the ContextVar is unset (REPL, ad-hoc scripts, unit tests calling `request_input()` directly), the accessor returns a default-constructed `InputConfig` rather than raising — so `request_input()` is always callable. The defaults mean: no notifiers, no custom handler, built-in selection only. This matters for custom tools and solvers that may run in non-eval contexts.

**Tests (~12):**
- Construct `InputResult` / `InputNotification`; serialization roundtrip.
- `@input_handler(name=...)` / `@input_notifier(name=...)` register and look up by name; factory args pass through.
- `request_input` with no custom handler and no notifiers → calls `_dispatch_builtin` (asserts the raise).
- Custom handler returns `InputResult` → that result is returned; `_dispatch_builtin` not called.
- Custom handler returns `None` → falls through.
- Custom handler hangs past timeout → falls through.
- Notifier fan-out: three notifiers called concurrently with the handler.
- One notifier raises → logged and swallowed; handler result still returned; other notifiers complete.
- One notifier hangs past `notifier_timeout` → cancelled; others still complete; handler result returned.
- `metadata=` passthrough reaches both notifiers and the custom handler.
- ContextVar isolation between concurrent `request_input` calls in overlapping scopes.
- All tests pass under both asyncio and trio (the anyio backends).

Verification: `pytest tests/input/test_input.py -v`; `mypy --exclude tests/test_package src/inspect_ai/input tests/input/test_input.py` clean; `ruff format` / `ruff check --fix` clean.

### Phase 2: Console-fallback handler

Lands the simplest concrete handler — walks an `ElicitationSchema` via `input_screen()` + Rich prompts. After Phase 2 `_dispatch_builtin` always picks console.

**Files created:**
- `src/inspect_ai/input/console.py` — `console_handler(message, schema) -> InputResult`. Renders each schema property via the appropriate Rich helper (`Prompt.ask` / `Confirm.ask` / `IntPrompt.ask` / `FloatPrompt.ask`; multi-select via numbered list + comma-input). Treats `KeyboardInterrupt` → `cancelled`; user enters `:decline` → `declined`. All input inside one `input_screen()` so `InputEvent` records automatically.
- `src/inspect_ai/input/builtin.py` — `_dispatch_builtin(message, schema)` selects console (only tier available so far).

**Files modified:**
- `src/inspect_ai/input/request.py` — uses the real `_dispatch_builtin`.

**Tests:**
- Each `ElicitationSchema` property type (string / number / integer / boolean / multi-select) parsed correctly from user input.
- `required` enforcement: missing required field re-prompts.
- Accept path returns `accepted` + structured `content` matching schema.
- `:decline` token returns `declined` with `content=None`.
- `KeyboardInterrupt` returns `cancelled`.
- `InputEvent` recorded on the transcript (capture via `transcript()._event` monkeypatch — [[feedback_warnings_testing]]).

Verification: `pytest tests/input/test_input.py tests/input/test_input_console.py`; manual smoke: run an eval with `--display rich` and an agent that synthesizes an `ask_user` call.

### Phase 3: `ask_user` tool + eval-level config + public API

Wires the user-visible surface. **After Phase 3 the feature is end-to-end usable in console mode.**

**Files created:**
- `src/inspect_ai/tool/_tools/_ask_user.py` — `@tool def ask_user(...)` factory. `execute(message, schema)` validates the schema via `ElicitationSchema.model_validate`, calls `request_input`, maps outcomes (accepted → `json.dumps(content)`, declined/cancelled → `ToolError`).
- `tests/tool/test_ask_user.py` — tool-level tests.
- `tests/agent/test_react_ask_user.py` — mock-model react test where the model invokes `ask_user`.

**Files modified:**
- `src/inspect_ai/tool/__init__.py` — register and export `ask_user`.
- `src/inspect_ai/util/__init__.py` — export `request_input`, `InputResult`, `InputNotification`, `InputHandler`, `InputNotifier`, `input_handler`, `input_notifier`.
- `src/inspect_ai/_eval/task/task.py` (or wherever the existing approval-policy params are defined — discover during implementation) — new `Task` / `eval()` kwargs: `input_handler`, `input_handler_args`, `input_handler_timeout`, `input_notifiers`.
- `src/inspect_ai/_eval/run.py` — resolves the new params (registry name → factory → callable) and installs the `_active_input_config` ContextVar for the eval scope.
- `src/inspect_ai/_cli/eval.py` — corresponding CLI flags.

**Tests:**
- Tool: well-formed schema accepted → returns JSON content. Malformed schema → `ToolError` with pydantic error.
- Tool: declined and cancelled outcomes → `ToolError`.
- Eval-config: registry-name resolution; direct-callable acceptance; `input_handler_args` passthrough.
- Eval-config: ContextVar threads through to a tool call inside a sample.
- Mock-model react: model emits `ask_user` tool call; mock handler answers; model continues the turn.

Verification: `pytest tests/tool/test_ask_user.py tests/agent/test_react_ask_user.py`; manual smoke: a small eval with `inspect eval ... --display rich` and a hand-written `ask_user` task, plus the same with a custom registry-named handler passed via CLI.

### Phase 4: Textual panel handler

Adds the rich in-process UX: a dynamic "Question" tab on the full Textual display.

**Files created:**
- `src/inspect_ai/input/manager.py` — `HumanQuestionManager` (parallel to `HumanApprovalManager` at `approval/_human/manager.py:28-92`): pending-question queue, future-based completion, withdrawal on cancel.
- `src/inspect_ai/input/panel.py` — `QuestionInputPanel(InputPanel)`. Renders form fields dynamically from `ElicitationSchema` (Textual `Input` for strings/numbers, `Checkbox` for booleans, `SelectionList` for multi-select). Submit / Decline buttons.
- `tests/input/test_input_panel.py` — Textual headless harness tests.

**Files modified:**
- `src/inspect_ai/input/builtin.py` — `_dispatch_builtin` now tries panel first; falls through to console on `NotImplementedError` (matches today's approval pattern at `approval/_human/approver.py:25-52`).

**Tests:**
- Per-field-type rendering on the panel.
- Submit button collects values → `accepted` with content matching schema.
- Decline button → `declined`.
- Withdraw (sample cancellation while waiting) → `cancelled`.
- `_dispatch_builtin` selects panel when Textual display is active; falls to console under rich/plain.

Verification: `pytest tests/input/test_input_panel.py`; manual smoke: `inspect eval ... --display full` and confirm the Question tab appears and the answer round-trips.

### Phase 5: ACP elicitation transport — capability, connection method, registry

The ACP wire surface. No selection wiring yet — Phase 6 adds `_input/acp.py`.

**Files created:**
- `tests/agent/test_acp/test_elicitation.py` — transport tests with mock ACP clients.

**Files modified:**
- `src/inspect_ai/agent/_acp/transport.py` — `ElicitationClient` Protocol mirroring `ApproverClient` (`transport.py:69-115`).
- `src/inspect_ai/agent/_acp/transport_live.py` — `_ElicitationClientRegistry` modeled on `_ApproverClientRegistry`: attach / has / driver_chain / mark_active / clear-on-exit. Driver-chain semantics: single driver tried first; transport failure falls through to next attached client (no broadcast — same lesson as Phase 14 of `agent-acp.md`).
- `src/inspect_ai/agent/_acp/connection.py` — capture `client_capabilities.elicitation` from the `initialize` request into `ConnectionState` (alongside `client_renders_plan`, `raw_events_subscription`). Implement `ConnectionHandler.request_elicitation(request) -> ElicitationResponse` via `conn.send_request("elicitation/create", payload)`. Self-register on the transport's elicitation registry in `Forwarders.start` when the capability is present; deregister in `Forwarders.stop`. `mark_active_elicitation_client(self)` on each successful `session/prompt` forward (same hook the approver driver uses).

**Tests:**
- Capability gating: client without `elicitation.form` → not added to registry.
- Capability gating: client with `elicitation.form` → added; `has_elicitation_clients()` True.
- `request_elicitation` dispatches `elicitation/create` with correct payload (assert via mock connection).
- Accept / decline / cancel response actions map to corresponding `InputResult` outcomes.
- Driver-chain fallback: first client raises → next is tried; all raise → `request_elicitation` re-raises.
- Disconnect mid-request: send raises → driver chain advances.
- `mark_active` after `session/prompt` promotes the prompting client to driver.

Verification: `pytest tests/agent/test_acp/test_elicitation.py`; `mypy --exclude tests/test_package src/inspect_ai/agent/_acp` clean.

### Phase 6: ACP handler in built-in selection — end-to-end over a socket

Plugs Phase 5's transport into Phase 1's orchestrator via a new built-in handler.

**Files created:**
- `src/inspect_ai/input/acp.py` — `acp_handler(request) -> InputResult | None`. Gates on `acp_server_accepting_clients()` (the `acp_server(...)` context manager's ContextVar flag); when off, returns `None` so the dispatcher falls through. When on, resolves the routing target via `sample_active().acp_transport` (the outermost `LiveAcpTransport`, NOT `current_acp_transport()` — see "Routing policy"), builds an `ElicitationRequest` (message + session_id + requestedSchema), dispatches through the transport's elicitation driver chain, parks on `subscribe_elicitation_attach` if no client is attached, and maps the response to `InputResult`.
- `tests/agent/test_acp/test_elicitation_e2e.py` — end-to-end over a real AF_UNIX socket with a stub elicitation-capable client (pattern: see existing `test_approval.py` E2E test).

**Files modified:**
- `src/inspect_ai/input/builtin.py` — `_dispatch_builtin` order now: ACP → panel → console. ACP handler returns `None` when `--acp-server` is not active (no `AcpServer` accepting external clients), falling through to panel → `NotImplementedError` (no Textual) → console. When `--acp-server` IS active the handler routes exclusively via ACP — no fallthrough on missing clients; the shim parks until one attaches.

**Tests:**
- `--acp-server` active + client attached → selection picks ACP, panel/console not invoked.
- `--acp-server` active + no client attached → shim parks on attach event (no fallthrough — regression of the notification-driven race).
- `--acp-server` not active → handler returns `None`, dispatcher falls through to panel or console per display.
- ACP attached but client lacks `elicitation.form` capability → request skipped over in the driver chain.
- End-to-end over socket: agent calls `ask_user`, stub client receives `elicitation/create`, returns accept → tool result reaches the model.
- End-to-end attach-after-fire: `ask_user` fires BEFORE any client attaches; result still routes via ACP once the client connects.

Verification: `pytest tests/agent/test_acp/test_elicitation*`; manual smoke against Zed (or a stub) via `inspect acp --stdio` confirming the form renders client-side and the answer round-trips.

### Phase 7 (optional): Worked Slack example + doc polish + Zed smoke

Documentation, an example of a third-party handler/notifier, and the final live verification.

**Files created/modified:**
- `examples/input_handlers/slack/` — a worked-example handler + notifier (not bundled in core; demonstrates the registry pattern). Posts via Slack SDK; threads the answer back.
- `docs/agents.qmd` (or wherever ACP user docs live — discover during implementation) — section on `ask_user`, eval-level config, handler/notifier extension.
- `design/acp/elicitation.md` — final post-Phase-N summaries replacing each phase's overview.

**Verification:**
- Run the Slack example end-to-end against a real Slack workspace.
- Run `inspect eval ... --acp-server` with Zed; confirm form rendering and submit flow.
- `pytest tests/agent/test_acp/ tests/input/test_input* tests/tool/test_ask_user.py` — full suite green.

### Phase risk and dependency table

| Phase | Depends on | Risk | Notes |
|---|---|---|---|
| 1 | — | low | Pure plumbing; anyio idioms are well-trodden |
| 2 | 1 | low | `input_screen` is established; `InputEvent` records for free |
| 3 | 1, 2 | medium | Eval-config wiring touches `Task` / `eval()` / CLI; discover surface during implementation |
| 4 | 1, 2 | medium | Dynamic form rendering on Textual — schema-to-widget mapping is new |
| 5 | — (parallelizable with 4) | medium-high | ACP Elicitation is UNSTABLE upstream; capability gating, driver-chain mirror approval |
| 6 | 1, 5 (and ideally 4) | medium | E2E over socket; pattern exists in approval tests |
| 7 | 1–6 | low | Polish + manual smoke |

Phases 4 and 5 can run in parallel (independent surfaces). Phases 2 → 3 → 6 are the critical path to a feature-complete ACP-capable release.
