# Ask-the-user feature for ACP agents (`ask_user` tool)

## Context

Today, agents running under ACP have two interactive channels: `session/prompt` (operator → agent, one-way) and `session/request_permission` (agent → client, for tool-call approval). There is no first-class way for an agent to **ask the user a structured question and get an answer back** — e.g. "what's the API key?", "which of these three approaches?", "confirm before proceeding".

This design adds a model-callable `ask_user` tool that presents a structured form (matching ACP's Elicitation schema: string / number / integer / boolean / multi-select), plus a fire-and-forget `notify_user` tool that pushes status updates to the operator out of band. Both are user-facing tools; both pair with a single best-effort `notify()` helper that fires Apprise notifications whenever a human-in-the-loop interaction is posted.

## Approach summary

- **Wire protocol on the ACP side:** ACP 0.10.0's `elicitation/create` request (marked UNSTABLE upstream — accepted per [[project_acp_no_installed_clients]]). Capability-gated via `ElicitationCapabilities.form` in the client's `initialize`.
- **Author-facing API:** two model-callable tools, `ask_user` (synchronous request/response form) and `notify_user` (fire-and-forget out-of-band ping). The model picks when to ask or notify; answers come back as structured tool results. No agent-loop changes.
- **Question shape:** structured forms from day one — we use ACP's `ElicitationSchema` and property-schema Pydantic types directly (imported from `acp.schema`) rather than inventing a parallel hierarchy or re-exporting.
- **Built-in dispatch only.** The eval's human channel is one of three surfaces: ACP → Textual panel → console. Selection is deterministic from runtime context (see "Routing policy"). There is no user-supplied custom handler chain — Apprise covers the out-of-band notification surface in a single library, so we don't need a per-service registry.
- **Best-effort out-of-band notification.** A single `inspect_ai.util.notify()` helper fires Apprise notifications when a human-in-the-loop interaction is posted. Called from `request_input()` (for `ask_user`) and from the human approver, so the operator is pinged regardless of which built-in surface (ACP / panel / console) ultimately collects the answer. Bounded by a 5-second timeout and exception-isolated so a misbehaving Apprise backend never blocks or breaks the operator prompt.

## Routing policy

Built-in handler selection is governed by whether the eval has booted an `AcpServer` that is currently accepting external clients (i.e. `--acp-server` is active):

- **`--acp-server` NOT active.** The ACP handler short-circuits with `None` and the dispatcher falls through to the Textual panel and then the console. This is the "stand-alone eval" mode; the operator works at the terminal where the eval runs.

- **`--acp-server` IS active.** `ACP is the human channel.` All `ask_user` and `approver: human` interactions route exclusively through attached ACP clients. The in-proc Textual panel and console handlers are bypassed entirely. If no client is connected when an interaction fires, the eval parks on the registry's attach event until one attaches — *no silent fallback*. The notification-driven workflow depends on this: an operator who reaches the form by clicking a Slack ping (etc.) must not race the panel for the resolution.

This is a one-way commit. There is no per-interaction or per-eval opt-out; the meaning of `--acp-server` is "ACP is the human channel for this eval." If the operator never attaches a client, the eval blocks indefinitely on the first interaction — which is the right semantic for a notification-driven workflow. The operator cancels the sample if they give up.

The mechanism is a module-level `acp_server_accepting_clients()` accessor (`src/inspect_ai/agent/_acp/server.py`) backed by a `ContextVar` that the `acp_server(...)` context manager flips on for the bound-server lifetime and off when the server stops. Routing shims in `src/inspect_ai/util/_input/acp.py` and `src/inspect_ai/approval/_human/acp.py` consult the accessor at their public entry; the inner driver-chain loop unconditionally parks on chain exhaustion regardless of attach history. The flag is deliberately separate from "is the current transport a `LiveAcpTransport`": the Live transport is opened per-sample regardless of `--acp-server` (sub-agent reachability needs the in-process pub/sub plumbing), and nested `acp_session()` blocks install a `NoOp` shadow that would miss-route human-in-the-loop traffic. Both shims also resolve the routing target via `sample_active().acp_transport` (the outermost Live, pinned at sample startup) rather than the ContextVar — sub-agent isolation is for *event publishing*, not human channels.

## Concepts and types

```python
# src/inspect_ai/util/_input/_types.py
from acp.schema import ElicitationSchema  # imported, not re-exported

@dataclass
class InputRequest:
    message: str
    schema: ElicitationSchema

@dataclass
class InputResult:
    outcome: Literal["accepted", "declined", "cancelled"]
    content: dict[str, Any] | None
```

`request_input(message, schema)` returns an `InputResult`. There is no protocol for custom handlers — exactly one built-in surface collects each answer, selected per "Routing policy" above.

## Components and files

### 1. Routing core — `src/inspect_ai/util/_input/`

Mirrors `src/inspect_ai/approval/_human/`. Files:

- **`_types.py`** — `InputRequest` and `InputResult` dataclasses.
- **`request.py`** — `request_input(*, message, schema) -> InputResult`. Orchestrates: (1) fire `notify(message)` (best-effort, bounded), (2) call `_dispatch_builtin(request)` to collect the answer, (3) record an `InputEvent` on the transcript.
- **`builtin.py`** — `_dispatch_builtin(request)` selects exactly one of `acp_handler` / `panel_handler` / `console_handler` based on the routing policy above.
- **`manager.py`** — `HumanQuestionManager` (parallel to `HumanApprovalManager`): in-process queue of pending questions for the Textual panel handler.
- **`panel.py`** — `QuestionInputPanel(InputPanel)`. Renders form fields dynamically from `ElicitationSchema`: Textual `Input` for strings/numbers, `Checkbox` for booleans, `SelectionList` for multi-select. Submit / Decline buttons.
- **`console.py`** — console-fallback handler. Walks schema properties using `input_screen()` (`util/_console.py`) + Rich's `Prompt.ask` / `Confirm.ask` / `IntPrompt.ask`.
- **`acp.py`** — ACP-handler wrapper. Routes via `sample_active().acp_transport.request_elicitation(...)` (the outermost `LiveAcpTransport`, pinned at sample startup — see "Routing policy" for why this is NOT `current_acp_transport()`). Gated on `acp_server_accepting_clients()`: returns `None` when `--acp-server` is not active so the dispatcher falls through to panel / console. When the server IS active, parks until an elicitation-capable client attaches — no silent fallback.

### 2. ACP transport — `src/inspect_ai/agent/_acp/`

Touch points (all parallel to existing approval code):

- **`connection.py`** — `request_elicitation(request) -> ElicitationResponse` next to `request_permission()`. Implementation: `await self._connection.send_request("elicitation/create", params)`. Parses the response action (`accept` / `decline` / `cancel`). Captures `ElicitationCapabilities` from the `initialize` request and stores on `ConnectionState` alongside the existing flags (`client_renders_plan`, `raw_events_subscription`).
- **`transport.py`** — `ElicitationClient` Protocol mirroring `ApproverClient`.
- **`transport_live.py`** — `_ElicitationClientRegistry` modeled on `_ApproverClientRegistry`. Driver-chain-with-fallback: when an attached client disconnects mid-request, retry on the next.

Elicitation lives on the transport, not on `AgentChannel`. The channel carries items *into* the agent loop (operator messages, cancel signals); elicitation is an agent→operator request that flows out via the same low-level path as `session/request_permission`.

### 3. The `ask_user` tool — `src/inspect_ai/tool/_tools/_ask_user.py`

Standard factory pattern:

```python
@tool
def ask_user() -> Tool:
    """Ask the user a structured question and wait for an answer."""

    async def execute(message: str, schema: dict[str, Any]) -> str:
        validated = ElicitationSchema.model_validate(_normalize_schema_types(schema))
        result = await request_input(message=message, schema=validated)
        if result.outcome == "accepted":
            return to_json_str_safe(result.content or {})
        if result.outcome == "declined":
            raise ToolError("User declined to answer the question.")
        raise ToolError("Question was cancelled before the user answered.")

    return execute
```

`ToolError` for declined/cancelled is recoverable so the model can adapt. Registered in `src/inspect_ai/tool/__init__.py`. The `_normalize_schema_types` shim lowercases `type` field values to handle providers (notably Gemini) that emit uppercase JSON Schema type names.

### 4. The `notify_user` tool — `src/inspect_ai/tool/_tools/_notify_user.py`

Parallel to `ask_user` but fire-and-forget — no response collected. Useful for long-running agents to surface "I'm halfway through X" without waiting for a reply.

```python
@tool
def notify_user() -> Tool:
    async def execute(title: str, message: str) -> str:
        if active_apprise() is None:
            return (
                "No notification channels are configured for this eval, so "
                "the message was not delivered out-of-band. If you need the "
                "operator to see this, include it in your response text."
            )
        await notify(message, title=title)
        return "Notification sent."

    return execute
```

`title` is the first arg so the model thinks about a triageable subject line first (matches how humans compose email/Slack notifications). When no Apprise channel is configured the tool returns a hint instructing the model to surface the message in its response text — unlike `ask_user`, there's no in-process surface to fall back to for fire-and-forget pings.

### 5. The `notify()` helper — `src/inspect_ai/util/_notify.py`

Public best-effort notification primitive. Backed by [Apprise](https://github.com/caronc/apprise), which covers Slack, desktop, SMS, email, webhook, and ~90 other services via a single URL DSL.

```python
async def notify(message: str, title: str | None = None) -> None:
    """Send a notification via the active Apprise instance (best-effort).

    No-op when no Apprise instance is installed for the current eval scope.
    Bounded by NOTIFY_TIMEOUT_SECONDS; any exception is logged and swallowed.
    """
```

Default title/body framing (when `title` is omitted) uses the active sample context:

- Inside a sample: title `Inspect Agent: <task>`, body starts with `sample: <sample_id>/<epoch>` followed by the message.
- Outside a sample: title `Inspect Agent`, body is the unmodified message.

`notify()` is best-effort by contract. A misbehaving Apprise backend (slow HTTP, network blackhole, plugin exception) must not delay or break the operator prompt that follows. Dispatch is bounded by `NOTIFY_TIMEOUT_SECONDS` (5s — shorter than any plausible human reaction time, so the latency hit is invisible) via `anyio.move_on_after`. Any exception is caught and logged at warning level. Apprise's sync API runs on a worker thread (`anyio.to_thread.run_sync` with `abandon_on_cancel=True`) so the helper works under both asyncio and trio backends.

Call sites:

- `src/inspect_ai/util/_input/request.py` — fires before `_dispatch_builtin`, so the operator is pinged regardless of which surface collects the answer.
- `src/inspect_ai/approval/_human/approver.py` — fires before the ACP/panel/console approval dispatch chain, same rationale.
- `src/inspect_ai/tool/_tools/_notify_user.py` — fires when the model invokes the tool.
- User code in custom agents / solvers can call `await notify(...)` directly.

### 6. Eval-level configuration

A single `notification: bool | str | None = None` kwarg on `eval()` / `eval_set()` / `eval_retry()` (and the corresponding `--notification` CLI flag). Apprise is an optional dependency: `pip install apprise` when notifications are wanted; the runtime check raises `PrerequisiteError` with a clear message if `notification=` is set but the library is missing.

The API accepts only references, never URL values, because notification URLs frequently carry secrets (Slack tokens, Twilio auth tokens, generic webhook bearer tokens):

- `notification=True` → read URL(s) from the `INSPECT_EVAL_NOTIFICATION` environment variable. The env-var value can be a single Apprise URL, a comma-separated list of URLs, or a path to an Apprise YAML/text config file. Unset/empty env var raises.
- `notification="/path/to/apprise.yml"` → must be an existing file (validated). Strings that aren't existing files (including URL strings) are rejected with a hint pointing at the env var.
- `notification=None` (default) → notifications disabled.

This shape closes four leak vectors that URL-string-acceptance would open: source code, shell history, process listings, and `EvalConfig.notification` in serialized eval logs (which stores only `True` or a file path — never URL contents). See `src/inspect_ai/util/_notify.py:build_apprise` for the validation.

`init_apprise(build_apprise(notification))` is installed in `eval_resolve_tasks` for the eval scope; the `_active_apprise` ContextVar then propagates naturally to every nested scope (sample, agent turn, tool call).

## Public Python API — `src/inspect_ai/util/__init__.py`

```python
from inspect_ai.util import (
    notify,
    request_input,
    InputOutcome,
    InputRequest,
    InputResult,
)
```

ACP schema types (`ElicitationSchema` and the five property schemas) are **not** re-exported — users import them directly from `acp.schema`. They're all available there (confirmed in the installed 0.10.0 package). Reasons: (1) avoid bloating the public surface of `inspect_ai.util`; (2) if upstream renames a field, users see the upstream type directly rather than chasing an Inspect alias.

The model-callable tools live under `inspect_ai.tool`:

```python
from inspect_ai.tool import ask_user, notify_user
```

## Reused utilities (do not reinvent)

- `input_panel()` from `util/_panel.py` — for the Textual tab
- `input_screen()` from `util/_console.py` — console fallback (handles Textual-suspend, Rich live-stop, plain)
- `task_screen()` from `_display/core/active.py` — runtime display detection
- `InputPanel` + `InputPanelHost` (`_display/textual/app.py`) — dynamic tab management
- `HumanApprovalManager` pattern from `approval/_human/manager.py`
- `anyio.move_on_after` + `anyio.to_thread.run_sync` — backend-agnostic timeout and worker-thread dispatch (per [[feedback_acp_asyncio_boundary]])
- ACP Pydantic types from the installed `acp` package — schema/scope/request/response
- Apprise (optional dependency) — multi-service notification dispatch

## Transcript surface

The model's tool call is the primary transcript artifact: it carries the question (in `args`) and the answer (in `result`) and renders correctly in both the eval viewer and the running display. `request_input()` also records an `InputEvent` (`event/_input.py`) carrying the original message, field schema, and final outcome/content — see `_record_input_event()` in `request.py`.

## Out of scope (deliberately deferred)

- **Custom out-of-band reply collection** (Slack-as-handler, email-as-handler). Apprise covers fire-and-forget notifications; reply collection from those channels would need a generalized handler chain, which we deliberately do not ship. Can come back later as a strict extension if real demand surfaces.
- **URL-mode elicitation** (`CreateUrlElicitationRequest`) — useful for auth flows, but not core to "ask a question". Add later.
- **Multi-question batching** — one `ask_user` call carries one question (which may have multiple fields). Sequential questions = sequential tool calls.
- **Question persistence across resumes.**
- **A dedicated `QuestionEvent` in the transcript.** The tool call itself already shows up with both question (args) and answer (result); `InputEvent` carries the schema + outcome. No new event type for v1.
- **Apprise as a packaged extra.** Users install it themselves; we don't bundle.

## Verification

- **Unit tests** in `tests/util/test_notify.py`, `tests/util/test_input.py`, `tests/tools/test_ask_user.py`, `tests/tools/test_notify_user.py`, `tests/approval/test_human_approver_notify.py`:
  - `build_apprise` shape validation (True / path / None / rejected URL strings).
  - `notify()` is best-effort: no-op without config; bounded under a hanging backend; exceptions swallowed.
  - `request_input()` fires `notify()` before dispatch; emits an `InputEvent`.
  - Approver fires `notify()` before the dispatch chain.
  - `notify_user` tool: delivers when configured; returns a fallback hint when not.
- **ACP integration test** in `tests/agent/_acp/test_elicitation.py`:
  - Capability gating (`elicitation.form` advertised vs. not).
  - Accept / decline / cancel response actions map to `InputResult` outcomes.
  - Driver-chain fallback when the active client disconnects mid-request.
- **Manual UI verification:**
  - `inspect eval ... --display full` with an agent that calls `ask_user` → "Question" tab appears and renders form inputs.
  - `--display rich` → console fallback prompts via `input_screen()`.
  - `--acp-server` + Zed (or a stub elicitation-capable ACP client) → form renders client-side.
  - `--notification` set, agent fires `ask_user` → operator gets the configured ping; sample parks on the answer.
- **Lint/type:** `ruff format`, `ruff check --fix`, `mypy --exclude tests/test_package src tests`.

## Risks and notes

- **ACP Elicitation is UNSTABLE.** Fields may rename in a future acp release. Per project convention we track the latest schema directly without compat shims.
- **No high-level `elicitation/create` helper in `acp`.** Dispatch via `connection.send_request(...)` — same low-level path `session/request_permission` already uses.
- **`notify()` is best-effort.** Callers wanting hard-fail semantics must build their own wrapper; the shipped helper logs-and-swallows. This is correct for the human-in-the-loop call sites — a stuck Apprise backend must never delay the operator prompt that follows.
- **Apprise import is non-trivial.** It loads all plugin classes eagerly. Import is deferred to `build_apprise()` / `notify()` so cold-start cost stays in scope only for users who actually use it.
