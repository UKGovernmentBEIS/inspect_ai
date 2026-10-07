# Bridged host tools under Codex code mode

Status: accepted (Ransom, 2026-10-07) and implemented in the same PR. Issue:
https://github.com/UKGovernmentBEIS/inspect_ai/issues/5687. Author: agent
(Claude), reviewed by Codex; see the PR.

All `path:line` references are to `main` at `aa20052a6` unless another tree
is named. Codex references are to `openai/codex` at tag `rust-v0.160.1`
unless another tag is named.

## Why

Since #5428, `sandbox_agent_bridge(bridged_tools=...)` runs a bridged host
tool only for a call the model proposed in a bridged generation, once per
proposal. The bridge finds the proposal by matching the declaration the
scaffold made to the model against the description the bridge served in
`tools/list`.

Codex CLI has a tool mode in which the model never proposes an MCP tool call
as a tool call. Its catalog marks models `tool_mode: "code_mode_only"`; those
models are given a freeform `exec` tool (JavaScript run inside Codex's
process in the sandbox) and `wait`, and call every MCP tool from the script
they write: `await tools.mcp__<server>__<tool>({...})`. The bridge sees only
the `exec` proposal, mints no grant for the nested call, and denies it. The
issue reports this for Codex 0.153.1 with `gpt-5.6-sol`: every bridged call
was denied, and the same task completed once the server set
`BridgedToolsSpec(require_proposal=False)`.

This affects most current Codex models, not an edge case. In the Codex
0.160.1 catalog (`codex-rs/models-manager/models.json`, as cached by
inspect_swe), `gpt-6-astra`, `gpt-6.1-sol`, `gpt-6-sol`, `gpt-6-luna`,
`gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna`, both `gpt-daybreak-*`
entries and `codex-auto-review` are `code_mode_only`; only `gpt-5.5` has no
tool mode. An eval that runs inspect_swe's `codex_cli` with bridged tools and
one of these models today runs with every host tool denied (the request
captures under "Current behaviour" are from the CLI's configuration).
inspect_swe's ACP Codex agent drives Codex through the same bridge, but it
installs a separately released `codex-acp` package and passes the model name
without the CLI's catalog resolution, so whether its runtime selects code
mode has not been established. The denial reaches the model as a tool error.
The eval author sees two warnings, each also recorded as a `LoggerEvent` in
the sample transcript: the bridge's `warn_once`, once per tool
(`src/inspect_ai/agent/_bridge/sandbox/service.py:268-273`), and the sandbox
service's warning for each failed RPC
(`src/inspect_ai/util/_sandbox/service.py:562-568`). Neither says why the
call was denied or what to do, and the sample runs to completion on a
different trajectory than intended.

The issue asks for a documented statement that code-mode scaffolds are
outside the proposal check and must opt out, or a bridge-side detection of a
code-mode declaration that fails with that message. A maintainer asked on
the issue whether to document the limitation and improve the error, or to
support nested calls while preserving the check. This design answers both.

## Goals and non-goals

Goals:

- An eval author whose agent calls host tools from model-written code learns,
  from the documentation and from the denial they hit, that the proposal
  check cannot hold for that agent and that `require_proposal=False` is the
  remedy, with its consequence stated.
- The proposal check itself is unchanged: an `exec` proposal grants nothing
  for the calls its script makes, and a regression test holds that.

Non-goals:

- Supporting nested calls while keeping the proposal check (see
  "Alternatives considered": no design found does it soundly).
- Changing what the model or the scaffold sees on a denial. The model-facing
  error text and the denial itself stay as they are, so no trajectory
  changes.
- Detecting Codex's tool mode in inspect_swe. That check is exact and
  belongs there; it is listed under "Not this design" and as an open
  question.
- Transcript events for denials (the proposed
  `design/bridge-host-tool-events.md` covers them).

## Current behaviour

**Grant registration.** `bridge_generate` approves a response and then calls
`bridge.register_tool_execution_grants(calls, declarations)` with the tools
the scaffold declared for that attempt, including declarations carried in the
input (`src/inspect_ai/agent/_bridge/util.py:763-770`). For each call,
`_proposed_call` looks up the call's declaration by name and resolves it to
bridged tools by served content (`_resolve_by_served_content`, exact
description or a truncation of one), falling back to Antigravity's
`call_mcp_tool` dispatcher shape (`_dispatched_call`)
(`src/inspect_ai/agent/_bridge/sandbox/types.py:292-321`, `:324-354`,
`:387-422`). A call that resolves to nothing mints no grant
(`types.py:150-182`).

**Denial.** The service's `call_tool` rejects an unknown server or tool with
`ValueError` (`service.py:257-261`), then, unless the server is in
`proposal_exempt_servers`, consumes a grant matching (server, tool,
arguments) or denies: it logs once per distinct message

```
Denied host tool call '<server>/<tool>': the model did not propose it in a
bridged generation (or its proposal has already executed).
```

and raises `PermissionError("Host tool call '<server>/<tool>' was not
proposed by the model in a bridged generation (a bridged host tool runs once
per proposed call)")`, which the scaffold returns to the model as the tool
result (`service.py:264-278`). `warn_once` keys on the message text
(`src/inspect_ai/_util/logger.py:277-283`), so the line appears once per
(server, tool) per process. The sandbox service dispatcher then logs the
failed RPC as `Error calling sandbox service method call_tool: ...` with the
exception, for every denial (`src/inspect_ai/util/_sandbox/service.py:562-568`).
Both are `WARNING` records, at or above the default transcript level, so
`LogHandler` also records each as a `LoggerEvent` in the sample transcript
(`src/inspect_ai/_util/logger.py:118-127`, `:270-274`), where the viewer
shows it. A denial has no `ToolEvent`.

**Opt-out.** `BridgedToolsSpec.require_proposal=False` adds the server to
`proposal_exempt_servers` (`types.py:116-124`): its tools run for any
`tools/call`, and no grants are stored for it (`types.py:163-164`). The
docstrings (`src/inspect_ai/tool/_mcp/_tools_bridge/bridge.py:16-23`,
`:51-58`; `src/inspect_ai/agent/_bridge/sandbox/bridge.py:141-147`) and the
docs (`docs/agent-bridge.qmd:200-217`, `docs/approval.qmd:197`) describe the
opt-out for "an agent that calls a host tool programmatically outside a model
turn". None mentions code mode.

**Approval.** `apply_bridge_tool_approval` reviews each proposed call as
itself, or as its dispatched target for `call_mcp_tool`
(`src/inspect_ai/agent/_bridge/_approval.py:149-152`). An `exec` call is
reviewed as `exec`: a policy keyed on a bridged tool's name never sees a call
made from inside the script. With the server opted out, nothing reviews the
nested host call.

**What the bridge sees of a code-mode scaffold.** Codex sends code-mode
declarations in an `additional_tools` input item, which the Responses bridge
merges into the declared tools (`src/inspect_ai/agent/_bridge/responses_impl.py:250-257`);
`exec` is a custom tool, converted to a `ToolInfo` whose description is the
`exec` description (`responses_impl.py:718-731`). Whether that description
contains the bridged tools depends on Codex's configuration:

- Codex renders the `exec` description from its template plus a section per
  *enabled* nested tool (`### \`<name>\``, the tool's description, a
  TypeScript declaration). Deferred nested tools are not rendered; the
  description says only that "Some deferred nested tools may be omitted from
  this description. They are still available on the global `tools` object
  and listed in `ALL_TOOLS`" (`codex-rs/code-mode-protocol/src/description.rs:16-17`,
  `:269-362`).
- MCP tools are registered `Deferred` whenever the tool search is enabled
  (`codex-rs/core/src/mcp_tool_exposure.rs:85-89`, the same in
  `rust-v0.153.1`), which is the case when the model's catalog entry has
  `supports_search_tool` and the provider supports namespace tools
  (`codex-rs/core/src/tools/spec_plan.rs:653-655`). Every `code_mode_only`
  model in the catalog has `supports_search_tool: true`, and a configured
  provider such as inspect_swe's `openai-proxy` inherits
  `namespace_tools: true` (`codex-rs/model-provider/src/provider.rs:60-69`,
  `:461-473`).

Verified by running Codex 0.154.0 and 0.160.1 (linux-arm64 packages from
inspect_swe's download cache) in Docker against a local Responses endpoint
that recorded the request, with one stdio MCP server `agent-c-mcp` serving
`shell_exec` and inspect_swe's provider settings. For `gpt-5.6-sol` the
request had no top-level tools; its `additional_tools` item declared `exec`,
`wait`, `request_user_input` and the collaboration tools, and neither
`shell_exec`, its description, nor the server name appeared anywhere in the
request. For `gpt-5.5` the request declared `tool_search`, whose description
named `agent-c-mcp` as a source. So the inline catalog the issue observed
(`exec` carrying a `### \`mcp__agent_c_mcp__<tool>\`` section per tool) is
not what current Codex sends in inspect_swe's default configuration; it
appears only when the tool search is off. Which setting differed in the
issue's run is not known.

The denial itself was reproduced in-process: a `SandboxAgentBridge` with
`shell_exec` on `agent-c-mcp`, an `exec` declaration embedding its served
description, and an `exec` call whose script calls it registers no grant;
`call_tool` then denies `agent-c-mcp/shell_exec`, and runs it once the server
is registered with `require_proposal=False`.

## Design

Two changes, neither altering what the model, the scaffold or the grant logic
does: the documentation states the limitation, and the denial log line names
the cause and the remedy. A regression test pins the security property that
an `exec` proposal grants nothing.

### Documentation

**`BridgedToolsSpec` class docstring**
(`src/inspect_ai/tool/_mcp/_tools_bridge/bridge.py`). After the paragraph
ending "Set `require_proposal=False` for an agent that legitimately calls a
host tool outside a model turn.", add:

> An agent that calls MCP tools from code the model writes, rather than
> handing the model each tool to call, is outside this check: the model
> proposes only the code-running call, so no host tool call it makes can
> match a proposal and every one is denied. Codex CLI does this for models
> whose catalog entry sets `tool_mode = "code_mode_only"` (its code mode: the
> model calls `tools.mcp__<server>__<tool>(...)` from an `exec` script). Set
> `require_proposal=False` on the servers such an agent uses.

**`require_proposal` attribute docstring**, same file. Replace the last
sentence with: "Use it for an agent that calls a host tool programmatically
outside a model turn, or from code the model writes (Codex CLI's code mode).
Approval policies then review only the calls the model proposed (for Codex
code mode, the `exec` call carrying the script), never the host tool call
made from inside it."

**`sandbox_agent_bridge` `bridged_tools` argument**
(`src/inspect_ai/agent/_bridge/sandbox/bridge.py:141-147`). After "unless its
spec sets `require_proposal=False` (see `BridgedToolsSpec`)", add "; an agent
that calls host tools from model-written code, such as Codex CLI in code
mode, needs that opt-out".

**`docs/agent-bridge.qmd`, Execution Contract.** After the
`require_proposal=False` example, add a paragraph:

> Some agents call MCP tools from code the model writes instead of offering
> each tool to the model. Codex CLI does this for models its catalog marks
> `code_mode_only` (most current GPT models): the model writes JavaScript for
> an `exec` tool, and the script calls `tools.mcp__<server>__<tool>(...)`.
> The model's only proposal is the `exec` call, so the bridge has nothing to
> match those calls against and denies all of them. Such an agent needs
> `require_proposal=False` on every bridged server it uses. The bridge cannot
> tell these calls from any other unproposed call: it neither detects code
> mode nor fails the sample, and logs the opt-out guidance once per server
> and tool per process. With the opt-out, approval policies review the
> `exec` call that carries the script, not the host tool calls made from it.

Also amend the opening sentence of "Matching a Proposal", where it lists
Codex CLI's naming ("Codex CLI the bare name inside a Responses API
namespace"), to read "Codex CLI the bare name inside a Responses API
namespace (outside code mode; see above)".

**`docs/approval.qmd:197`.** Append: "Under Codex CLI's code mode the model
proposes only the `exec` call that runs its script, so policies review that
call and the host tool calls the script makes are reviewed by no policy (and
need `require_proposal=False` to run at all)."

### Denial warning

In `call_tool` (`service.py:268-273`), extend the `warn_once` message; the
`PermissionError` text the model sees is unchanged:

```python
warn_once(
    logger,
    f"Denied host tool call '{server}/{tool}': the model did not "
    "propose it in a bridged generation (or its proposal has "
    "already executed). An agent that calls host tools from code "
    "the model writes (Codex CLI in code mode) can never match a "
    "proposal; set require_proposal=False on the existing "
    f"BridgedToolsSpec for server '{server}' for such an agent.",
)
```

The remedy names an edit to the author's existing spec rather than a
constructor call: `BridgedToolsSpec` requires `tools`
(`src/inspect_ai/tool/_mcp/_tools_bridge/bridge.py:48`), so a copied
`BridgedToolsSpec(name=..., require_proposal=False)` would raise `TypeError`.

`server` and `tool` have already been checked against the registry
(`service.py:257-261`), so the message carries only registered names. The
dedupe key stays one line per (server, tool) per process.

The wording is conditional because the bridge cannot know the cause: a
scaffold retrying a consumed proposal and a model-written script calling the
MCP endpoint produce the same denial.

### What is deliberately not added

No detection of code mode, no new state on `SandboxAgentBridge`, no sample
failure, no change to `register_tool_execution_grants` or `_proposed_call`.
The reasons are under "Alternatives considered" (3 to 5).

### Regression test for the grant boundary

The issue's first "obvious fix" (grant nested calls from the `exec`
proposal) would quietly undo #5428 for every code-mode scaffold. A test pins
that it is not done: an `exec` custom declaration whose description embeds a
bridged tool's served description (the inline-catalog shape the issue
measured), plus an `exec` call whose script names that tool with literal
arguments, registers no grant, and `call_tool` denies the tool with those
arguments.

## Alternatives considered

1. **Grant the nested calls from the `exec` proposal.** An `exec` script can
   call any tool any number of times with arguments computed at run time
   inside the sandbox (from files, command output, `ALL_TOOLS` lookups). A
   grant scoped to "tools this script may call" authorizes whatever the
   sandbox makes of the script, so it does not restore the correspondence
   between a proposal and an execution; it only appears to.

2. **Grant literal calls extracted from the script.** Parse the `exec`
   input, find `tools.<name>({...literal...})` calls, map each name to a
   bridged tool, and grant those exact arguments. Sound for what it grants,
   since the text is the model's own output, but: it needs a JavaScript
   parser in the bridge; the names are Codex's normalized identifiers
   (`mcp__agent_c_mcp__shell_exec`), which reintroduces the name-based
   matching #5428 removed; a call inside a loop executes several times on
   one literal; and arguments built from variables, which code mode exists
   to allow, stay denied. A partial grant that works for some scripts and not
   others is harder to reason about than a documented opt-out.

3. **Detect a code-mode declaration by embedded served descriptions** (the
   issue's suggestion): treat a declaration that resolves to no bridged tool
   but whose description contains a bridged tool's served description as a
   code-mode dispatcher, and fail with the opt-out message. The signal comes
   from the scaffold, not the model, so it would not misfire on a
   model-written probe. But it does not fire in the configuration that
   matters: Codex 0.154.0 and 0.160.1 defer MCP tools in code mode and the
   `exec` declaration carries no served description (see "Current
   behaviour"). It would only cover configurations with the tool search
   off, which inspect_swe does not use, at the cost of a substring scan of
   every declaration per generation and new bridge state. If such a
   configuration turns out to be common it can be added later without
   changing this design.

4. **Detect Codex code mode by its `exec` template text** ("Run JavaScript
   code to orchestrate/compose tool calls", `ALL_TOOLS`). Codex-specific, and
   the template is replaceable per model through the catalog's `messages`
   (`description.rs:283-286`), so it can change without a Codex release.

5. **Fail the sample on a denial the bridge cannot explain** (for example,
   a denied call to a tool or server that has never been granted). Code-mode
   nested calls are indistinguishable at the bridge from a model-written
   script or shell command calling the MCP endpoint directly: both are model
   output executed in the sandbox. Today such a probe is denied and the
   sample continues; failing it would change the result of evals that rely
   on the denial, and the error would recommend `require_proposal=False` to
   an author who should not set it. Changing an eval's outcome needs a
   reliable signal, and the bridge has none.

6. **Opt out automatically when code mode is detected.** Drops the guarantee
   without the author asking, for exactly the agents where nothing reviews
   the nested call. Rejected for the same reason the issue rejects it.

7. **Codex's `features.code_mode.direct_only_tool_namespaces`.** Makes the
   listed namespaces direct tools again, so their calls are proposals and
   are granted (`spec_plan.rs:236-244`). It changes the tool surface the
   model is evaluated with, away from what Codex gives the model outside the
   eval, so the documentation does not recommend it.

8. **Fail fast in inspect_swe from the catalog's `tool_mode`.** inspect_swe
   resolves the Codex catalog entry for the model before launch, so it can
   raise a clear error before the sample starts when the entry is
   `code_mode_only` and a bridged spec keeps `require_proposal=True`. This is
   exact and cheap, and is the check the issue's "clear error" wants for the
   agents Inspect ships, but it is a change to inspect_swe. It complements
   this design rather than replacing it, since other consumers drive Codex
   through the bridge too; see "Not this design".

## Compatibility and migration

No migration required.

- **Behaviour.** Unchanged: the same calls are granted and denied, the model
  sees the same error text, and no sample that completes today fails.
- **Public API.** No signature, default or type changes. `BridgedToolsSpec`,
  `sandbox_agent_bridge` and `SandboxAgentBridge` keep their interfaces.
- **Logs and schemas.** The text of the bridge's denial warning changes, in
  Python logs and in the `LoggerEvent` each sample records for it (the
  textual and web transcript views show the longer string). Event and log
  schemas, generated viewer types, and the model-facing error are
  unchanged, and old logs read as before. Nothing in inspect_ai or
  inspect_swe matches on the warning text (the denial tests match the
  `PermissionError` text, `tests/agent/test_bridge_approval.py:709`, `:730`
  and others).
- **CHANGELOG.** None: the change is documentation and a log message.

## Security

- **Untrusted input.** The change reads no new input. The warning
  interpolates `server` and `tool` from the scaffold's `tools/call`, but only
  after both have been checked against the bridge's registry
  (`service.py:257-261`), so it carries registered names only.
- **Grant boundary.** Unchanged, and now pinned by a test: an `exec`
  proposal mints no grant for calls its script makes, whatever the script's
  text says. The script is model output, but what it executes is determined
  in the sandbox, so its text cannot stand for a proposal (Alternatives 1
  and 2).
- **The opt-out.** The documentation change makes the consequence of
  `require_proposal=False` explicit for code mode: anything in the sandbox
  can call that server's tools with any arguments, and approval policies
  review only the `exec` call. Authors should expose only tools they would
  accept being called that way. This is today's behaviour, stated.
- **Not failing on denials.** Keeping a denial a denial means a model
  probing the MCP endpoint from the sandbox gets a contained error rather
  than ending the sample (Alternative 5).

## Testing

All in `tests/agent/test_bridge_approval.py`, next to the existing grant and
denial tests (`:703-848`, `:1440-1530`), using its helpers
(`sandbox_bridge_with_tool`, `sandbox_bridge_with_servers`, `declare`,
`run_bridge`, `call_host_tool`). They run in the default `pytest` job: no
network, Docker or provider.

1. `test_denial_warning_names_the_opt_out`: an unproposed call to
   `host/read_file` raises `PermissionError` with the unchanged text, and the
   captured `WARNING` record contains "set require_proposal=False on the
   existing BridgedToolsSpec for server 'host'". `warn_once` dedupes on a module-level list, so the test
   isolates it with `monkeypatch.setattr(inspect_ai._util.logger, "_warned",
   [])`.
2. `test_code_mode_exec_call_grants_no_nested_tool`: declare `exec` as a
   `ToolInfo` whose description is a Codex-shaped catalog (template line,
   `### \`mcp__host__read_file\``, the served description, a TypeScript
   declaration) plus `wait`; run a response carrying
   `ToolCall(function="exec", arguments={"input": "await
   tools.mcp__host__read_file({\"path\": \"notes.txt\"})"})` through
   `run_bridge`; assert no grant was stored and that `call_host_tool(bridge)
   ("host", "read_file", {"path": "notes.txt"})` raises `PermissionError`
   with the tool not awaited.
3. `test_code_mode_exec_call_runs_nested_tool_when_opted_out`: the same with
   `require_proposal=False`, asserting the call runs once. This documents the
   remedy the docs give.

The `--runtrio` variants of these async tests run as for the rest of the
file.

**Manual check, reported in the PR's `### Slow tests` section.** inspect_swe
`codex_cli` with `gpt-5.6-sol` (OpenAI key) in a Docker sandbox, one bridged
`BridgedToolsSpec`: with `require_proposal=True` the new warning appears and
the tool never runs; with `require_proposal=False` the task completes. CI
cannot run this (provider key, Docker, a second repo); if it is not run, the
PR says so.

PR CI validates rendering when `docs/**` changes (the `docs` job,
`.github/workflows/build.yml:162-174`, runs `quarto render docs`, reusing a
previous successful render for identical inputs). Read the rendered pages to
check the guidance itself.

## Implementation plan

One PR, in three commits:

1. **Denial warning and tests.** `src/inspect_ai/agent/_bridge/sandbox/service.py`
   (the `warn_once` text); `tests/agent/test_bridge_approval.py` (tests 1-3).
2. **Docstrings.** `src/inspect_ai/tool/_mcp/_tools_bridge/bridge.py`
   (`BridgedToolsSpec` and `require_proposal`),
   `src/inspect_ai/agent/_bridge/sandbox/bridge.py` (`bridged_tools`
   argument).
3. **Docs.** `docs/agent-bridge.qmd` (Execution Contract paragraph, Matching
   a Proposal parenthesis), `docs/approval.qmd` (one sentence).

Run `make check` and the focused file
(`pytest tests/agent/test_bridge_approval.py -v`, then with `--runtrio`).

## Open questions

1. **inspect_swe fail-fast.** Should inspect_swe's `codex_cli` (and the ACP
   Codex agent) raise before launch when the resolved Codex catalog entry is
   `code_mode_only` and any `BridgedToolsSpec` keeps
   `require_proposal=True`? Recommendation: yes, raise with the opt-out
   message, never opt out on the author's behalf; file it as an inspect_swe
   issue. It is the only place the cause is known exactly. The check should
   use each adapter's effective tool configuration, not the catalog alone:
   the ACP agent does not share the CLI's catalog resolution, and namespaces
   an author makes direct with `features.code_mode.direct_only_tool_namespaces`
   are proposed as ordinary tool calls and need no opt-out.

## Not this design

- **inspect_swe fail-fast check** (Alternative 8, Open question 1).
- **Denials as tool events.** A denial appears in the transcript only as
  `LoggerEvent` warnings and has no `ToolEvent`;
  `design/bridge-host-tool-events.md` (proposed) records denied host tool
  calls as `ToolEvent`s.
- **Whether inspect_swe's ACP Codex agent selects code mode.** Capturing the
  pinned `codex-acp` package's request would settle it (see "Why").
- **Code mode with a non-OpenAI eval model.** The Responses bridge drops
  custom tools for non-OpenAI models (`responses_impl.py:266-267`), and
  `exec` is a custom tool. If inspect_swe aligns a non-OpenAI model to a
  `code_mode_only` catalog profile, Codex would declare `exec` and the model
  would never see it. Not verified end to end; worth checking in inspect_swe.
