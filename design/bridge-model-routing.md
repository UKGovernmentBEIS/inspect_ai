# Sandbox agent bridge: route unknown model names to the eval model

> **Status: proposed**, 2026-09-15. No tracking issue. Author: agent
> (Claude), reviewed by Codex; see the PR. Line references are to
> `ba590d5128` (`main` when this branch was cut). References into
> `inspect_swe` are to `meridianlabs-ai/inspect_swe` at `b2c1bf0`
> (2026-09-10), cited as precedent only.

## Why

A scaffold running in a sandbox reaches the model through the in-container
proxy. Each request names a model in the scaffold's own dialect
(`"model": "claude-haiku-4-5"`, `models/gemini-2.5-pro:generateContent`), and
the host resolves that string with `resolve_inspect_model()`
(`src/inspect_ai/agent/_bridge/util.py:631-707`). When nothing else claims
the name, the final step is `get_model(model_name)` (util.py:707): the string
the scaffold sent is instantiated as a provider, using whatever credentials
the host process has.

Scaffolds legitimately use several models. Claude Code has opus, sonnet,
haiku and subagent tiers and makes background calls on haiku; OpenCode
generates session titles with a side call; Gemini CLI hard-codes internal
utility model names. With the pass-through default those calls silently run
on other providers and bill the host's credentials for models the eval author
never chose, and eval-internal model roles (graders, monitors) are reachable
by name from inside the sandbox (util.py:678-679). None of this is visible in
the log: the `ModelEvent` records the model that served the call, not the
name the scaffold asked for, and the response echoes the served model's name
too (`completions.py:69,115`).

The documented default and the implemented default disagree:

- The `sandbox_agent_bridge()` docstring says `model` "defaults to
  'inspect'" (`src/inspect_ai/agent/_bridge/sandbox/bridge.py:83-85`), which
  would route every non-alias name to the eval's active model.
- The signature default is `None` (bridge.py:53; `AgentBridge.__init__`,
  `src/inspect_ai/agent/_bridge/types.py:50`), and the attribute docstring
  says "`None` means no fallback (the request model name is used as-is)"
  (types.py:139-143). That is what the code does.
- The same docstring says the fallback applies to "requests that don't use
  'inspect' or an 'inspect/' prefixed model", as does the CHANGELOG entry
  that introduced it (line 1739, #2885), but the code replaces `inspect/...`
  names as well (util.py:669-672; verified in the table below).

inspect_swe's Claude Code agent already shows the intended pattern. It pins
the bridge (`model="inspect"` or `"inspect/<model>"`) and registers one
alias per name Claude Code is told to present, so each presented tier routes
where the author said and anything else collapses onto the main model
(`src/inspect_swe/_claude_code/model.py:75-119`, used at
`claude_code.py:342-346`). This design makes that behaviour the default for
every sandbox bridge.

This is a routing-correctness and cost-control change: the bridge should
serve the model the eval author chose unless the author says otherwise.

## Goals and non-goals

Goals:

1. By default, every request name that is not an alias, a resolver result,
   `"inspect"`, or the eval's active model routes to the eval's active model.
   A scaffold's sub-agent and side calls keep working, on the main model.
   Nothing reaches another provider or a model role unless the author says
   so.
2. Multi-model scaffolds route through the existing mechanisms:
   `model_aliases` for exact names (the inspect_swe pattern),
   `model_resolver` for routing by policy, plus one explicit opt-in that
   restores today's pass-through for the faithful-proxy case.
3. Redirects are visible: one warning per redirected name pointing at
   `model_aliases`, and the client-requested name recorded on the
   `ModelEvent`.
4. `model=` has one documented meaning for direct names, bare `"inspect"`,
   `inspect/` names, aliases, roles and the active-model match, backed by a
   table-driven test.

Non-goals:

- Changing which provider-side tools the bridge withholds or grants
  (`web_search`, `code_execution`, remote MCP). Unchanged.
- Request provenance (attributing a call to a scaffold component). A
  separate design.
- Changing the in-container proxy. Routing is host-side; no
  `inspect_sandbox_tools` rebuild.
- Changing what the in-process `agent_bridge()` intercepts or how it routes
  (see Compatibility).

## Current behaviour

### Where names come from

The in-container proxy
(`src/inspect_sandbox_tools/src/inspect_sandbox_tools/_agent_bridge/proxy.py`)
forwards the request body to the host service. A missing or empty `model` is
rejected with a 400 before forwarding (proxy.py:701-702, 1427-1428,
1649-1650); for Google the name is parsed from the URL path and written into
the body (proxy.py:2044-2047). Each host dialect reads it and calls the
resolver with the bridge's options and the endpoint's provider:

| Dialect | Call site | `provider` |
|---|---|---|
| OpenAI Completions | `src/inspect_ai/agent/_bridge/completions.py:61-68` | `openai` |
| OpenAI Responses | `src/inspect_ai/agent/_bridge/responses_impl.py:216-223` | `openai` |
| Anthropic | `src/inspect_ai/agent/_bridge/anthropic_api_impl.py:114-121` | `anthropic` |
| Google | `src/inspect_ai/agent/_bridge/google_api_impl.py:76-83` | `google` |

All four pass `bridge.model_aliases`, `bridge.model` (as `fallback_model`)
and `bridge.model_resolver`, then call `bridge_generate()` (util.py:482-613)
with the resolved `Model`.

### Resolution order today (`util.py:631-707`)

1. `model_aliases` exact match on the raw name → `get_model(alias_value)`
   (639-640).
2. A bare name on a provider endpoint is qualified (`gpt-4o` →
   `openai/gpt-4o`) unless it is `"inspect"` or a role name (650-656). Added
   by #4897 (CHANGELOG line 17).
3. `model_resolver(qualified_name)` → its result when not `None` (660-663).
4. `fallback_model` (the `model=` option), when set, replaces the name:
   every name except bare `"inspect"`, and `"inspect"` too unless the
   fallback itself starts with `inspect/` (669-672).
5. `"inspect"` → `get_model()`, the active model (674-675).
6. The `inspect/` prefix is stripped (677); a role name →
   `get_model(role=name)` (678-679).
7. A name equal to the active model's full or short name, or a bare
   pre-qualification name equal to its short name when no fallback applied
   → the active `Model` instance, so eval-level config applies (700-705).
8. Otherwise `get_model(name)` (707): the provider the client named is
   instantiated.

Verified by calling `resolve_inspect_model()` at the base commit with active
model `mockllm/active` and role `grader` bound to `mockllm/grader` (probe
run 2026-09-15, provider keys unset):

| requested | `fallback_model` | `provider` | result |
|---|---|---|---|
| `inspect/mockllm/other` | `inspect/mockllm/fallback` | | `mockllm/fallback` (the fallback replaces an `inspect/` name) |
| `inspect` | `inspect/mockllm/fallback` | | active |
| `inspect` | `mockllm/fallback` | | `mockllm/fallback` (fallback without `inspect/` prefix replaces `"inspect"`) |
| `grader` | `inspect` | | active (role unreachable when pinned) |
| `grader` | None | `anthropic` | role `grader` |
| `inspect/grader` | None | | role `grader` |
| `active` | None | `anthropic` | active instance (raw short-name match) |
| `mockllm/active` | `inspect/mockllm/other` | | `mockllm/other` (fallback beats the active match) |
| `gpt-4o-mini` | None | `openai` | `get_model("openai/gpt-4o-mini")`: the OpenAI provider is constructed (failed in the probe only because no `OPENAI_API_KEY` was set) |
| `inspect/openai/gpt-4o-mini` | None | | same |
| `unknown-model` | None | `""` | `ValueError` from `get_model` (unqualified name) |
| alias key | `inspect` | | alias target |
| resolver hit / resolver returns `None` | `inspect` | | resolver target / active |

### The in-process bridge

`agent_bridge()` (`src/inspect_ai/agent/_bridge/bridge.py:100-112`) has no
`model`, `model_aliases` or `model_resolver` parameter and constructs
`AgentBridge` with `model=None` (bridge.py:180-190). Its client patches
intercept only requests whose model matches `^inspect/?`
(`targets_inspect_model`, bridge.py:584-586; used at 340, 473, 528, 568).
Every other name goes to the real SDK client untouched, with the scaffold's
own credentials. Intercepted requests go through the same four dialect
functions and so the same resolver, where `inspect/<spec>` resolves to a
role or `get_model(spec)`. The documented
`ChatOpenAI(model="inspect/google/gemini-1.5-pro")` example
(`docs/agent-bridge.qmd:196-204`) is this path.

### Where a record of the requested name would go

`ModelEvent` is built in `Model._record_model_interaction`
(`src/inspect_ai/model/_model.py:1964-1975`) without metadata, but
`BaseEvent.metadata: dict[str, Any] | None` exists
(`src/inspect_ai/event/_base.py:29-30`) and is serialised with every event,
so a natural field exists and no schema change is needed. The bridge calls
`model.generate()` from `bridge_generate()` inside two context managers
(`bridge_model_generate()` and `use_model_event_sink()`, util.py:562), so a
third context manager is the established shape. Installing a sink to stamp
events is not an option: a sink disables partial-progress publishing
(`_model.py:1401`).

### inspect_swe today

Every inspect_swe agent built on `sandbox_agent_bridge()` pins `model=`,
except the two ACP agents noted last:

| Agent | Name the scaffold sends | Bridge options | Under today's code |
|---|---|---|---|
| Claude Code (`_claude_code/claude_code.py:342-346`, `model.py:75-119`) | the presented id passed via `--model` (claude_code.py:379) and the `ANTHROPIC_*` tier env vars; each is an alias key | `model="inspect"` or `"inspect/<model>"`, `model_aliases` per presented name | alias, else pin |
| Codex CLI (`_codex_cli/codex_cli.py:272, 371-377, 546-547`) | the aligned Codex slug from `resolve_codex_model()` (833-867) on the Responses endpoint; the guardian slug is aliased (`model_catalog.py:135-158`) | `model="inspect"` or `"inspect/<model>"` | alias, else pin |
| Gemini CLI (`_gemini_cli/gemini_cli.py:110, 124-127, 185-186`) | `gemini_model` (default `gemini-2.5-pro`) on the Google endpoint, plus internal utility names | `model="inspect"` or `"inspect/<model>"` | pin |
| OpenCode (`_opencode/opencode.py:109, 130-133, 211-212`) | the id part of `opencode_model` (default `anthropic/claude-sonnet-4-5`) on that provider's endpoint | `model="inspect"` or `"inspect/<model>"` | pin |
| Kimi Code (`_kimi_code/kimi_code.py:184-185, 235-236`) | the configured model | pin; also calls `resolve_inspect_model()` directly (520-525) | pin |
| Antigravity (`_antigravity/antigravity.py:314, 322-323`), mini-swe-agent (`_mini_swe_agent/mini_swe_agent.py:119, 132-137`) | fixed SDK name / `inspect/<model>` | pin (+ alias) | pin / alias |
| ACP Claude Code (`acp/_agents/claude_code/claude_code.py:120-123`), ACP Codex (`acp/_agents/codex_cli/codex_cli.py:89-98`) | canonical model name (aliased) plus whatever else the scaffold emits | `model=None`, `model_aliases=self.model_map` | alias, else **pass-through to `get_model(name)`** |
| ACP Gemini (`acp/_agents/gemini_cli/gemini_cli.py:70-76`) | as Gemini CLI | `model=str(model)` "for any model name not covered by model_aliases" | pin |

## Design

### Terms

- **requested name**: the string the client sent.
- **qualified name**: the requested name with the endpoint's provider
  prefixed when it is bare (today's rule, unchanged: skipped for
  `"inspect"` and for role names).
- **pin**: `model=` set to a value other than `None` or `"inspect"`. Its
  target `D` is resolved from the spec with the `inspect/` prefix stripped:
  a role name → `get_model(role=spec)`; a spec naming the active model →
  the active `Model` instance (today's rule at util.py:700-705, applied to
  the pin); otherwise `get_model(spec)`. `model="inspect"` is identical to
  `model=None`.
- **pass-through**: `forward_model_names=True`.
- **redirect**: a request served by a model the requested name does not
  denote, by the default rule or by a pin.

### Resolution order

```
resolve_bridge_model(requested, *, model_aliases, model_resolver, model,
                     forward_model_names, provider) -> BridgeModelResolution

 1. requested in model_aliases              -> alias target            route="alias"
 2. qualified = provider-qualify(requested)    (unchanged rule)
 3. model_resolver(qualified) is not None   -> that                    route="resolver"
 4. requested == "inspect"                  -> get_model()             route="inspect"
 5. pin set                                 -> D                       route="model"
 6. qualified (inspect/ stripped) or requested
    names the active model                  -> active instance         route="active"
 7. forward_model_names:
      stripped name in model_roles()        -> get_model(role=name)    route="role"
      else                                  -> get_model(name)         route="passthrough"
 8. otherwise                               -> get_model()             route="default"
```

What changes relative to today: step 4 no longer depends on how the pin is
spelled; step 7 runs only on opt-in; step 8 is new. Steps 1 to 3, 5 and 6
keep today's precedence: alias and resolver beat the pin, the pin beats the
active-model match, the active-model match beats pass-through. Step 6 keeps
both of today's comparisons (full name or short name after stripping, and
the raw pre-qualification name against the short name), so a client on the
OpenAI endpoint naming `gpt-4o` still gets an `azureai/gpt-4o` active model.
Step 8 calls `get_model()` exactly as `"inspect"` does, so outside an eval
it falls back to `INSPECT_EVAL_MODEL` and otherwise raises the same
"No model specified" error a bare `"inspect"` request raises today.

### What `model=` means (the matrix)

Active model `A`; role `grader`; pin target `D`.

| requested name | default (`model=None` or `"inspect"`) | pinned (`model="inspect/<spec>"` or `"<spec>"`) | pass-through (`forward_model_names=True`, no pin) |
|---|---|---|---|
| alias key | alias target | alias target | alias target |
| resolver returns a model | resolver result | resolver result | resolver result |
| `inspect` | `A` | `A` (**change**: today replaced by a pin spelled without `inspect/`) | `A` |
| `A`'s full name, or its short name (bare, any endpoint) | `A` instance, no warning | `D`, warn (unchanged: pin wins) | `A` instance |
| `inspect/<A's spec>` | `A` instance | `D`, warn | `A` instance |
| `grader` (role) | `A`, warn (**change**) | `D`, warn (unchanged) | role `grader` |
| `inspect/grader` | `A`, warn (**change**) | `D`, warn (unchanged) | role `grader` |
| `inspect/openai/gpt-4o-mini` | `A`, warn (**change**) | `D`, warn (unchanged) | `get_model("openai/gpt-4o-mini")` |
| `gpt-4o-mini` on the OpenAI endpoint | `A`, warn (**change**) | `D`, warn (unchanged) | `get_model("openai/gpt-4o-mini")` |
| `unknown-model` with no endpoint provider | `A`, warn (**change**: today `ValueError`) | `D`, warn | `ValueError` from `get_model` (unchanged) |
| pinned spec names `A` | n/a | `A` instance | n/a |
| `forward_model_names=True` with a pin | n/a | `ValueError` at construction | n/a |

"warn" means the redirect warning below fires once per requested name.

### The opt-in: `forward_model_names`

```python
forward_model_names: bool = False
```

on `AgentBridge.__init__` (types.py), `SandboxAgentBridge.__init__`
(`sandbox/types.py`) and `sandbox_agent_bridge()` (sandbox/bridge.py),
documented next to `forward_generation_config`:

> Honour the client's model name. Defaults to `False`: a name the bridge
> does not recognise (not an alias, resolver result, `"inspect"`, or the
> eval's model) is served by the eval's model, so a scaffold's sub-agent and
> side calls stay on the model under evaluation. Set `True` for
> faithful-proxy behaviour where the client's model name is authoritative:
> an `inspect/<provider>/<model>` or bare name is resolved with
> `get_model()` on the host's credentials and a model role name reaches
> that role. Cannot be combined with `model=`.

`AgentBridge.__init__` raises `ValueError("forward_model_names=True cannot
be combined with model=...: the pin routes every unrecognised name to one
model, pass-through routes each to the model it names")` when both are set.
The two options describe contradictory routing, and silently letting one
win would be exactly the kind of masked configuration this design removes.

The in-process `agent_bridge()` constructs its `AgentBridge` with
`forward_model_names=True` (bridge.py:180-190) and does not expose the
option. Same reasoning as its `default_grant=True` for web search
(bridge.py:168-174): the scaffold already runs with the host's credentials
and can call any provider directly, so redirecting `inspect/<spec>` buys
nothing and would break the documented LangChain example. Its behaviour is
unchanged.

Spelling: `forward_model_names` parallels `forward_generation_config`, the
option it accompanies in the faithful-proxy configuration
(`forward_generation_config=True, forward_model_names=True`). Alternatives
considered: `model_passthrough` (reads well but the repo's bridge flags are
verb-first), `route_unknown_models="passthrough"` (a string enum for a
two-way choice).

### The redirect warning

Fired from `bridge_generate()` when `routing.redirected` is true, once per
requested name per process. `redirected` is computed in
`resolve_bridge_model`: `route == "default"`, or `route == "model"` and
neither the stripped qualified name nor the raw name is `str(D)` or
`ModelName(D).name` (so Kimi's `requested == pinned spec` is not a
redirect).

Message for the default route:

> Agent bridge routed a request for model 'claude-haiku-4-5' to the eval
> model 'anthropic/claude-fable-5'. Add 'claude-haiku-4-5' to model_aliases
> to route it to a model of your choice, or pass forward_model_names=True to
> honour client model names.

For the pinned route the second sentence is "Add ... to model_aliases to
route it elsewhere; it was pinned by model='inspect/openai/gpt-4o'."

Dedupe is a module-level `set[str]` of requested names in util.py (not
`warn_once`, whose list membership is linear in distinct messages), capped
at `_MAX_REDIRECT_WARNINGS = 64` names; on reaching the cap one final
warning says further redirects are not reported and points at the
`ModelEvent` metadata. The requested name is `repr()`-escaped and truncated
to 200 characters in the message.

### Recording the requested name on the `ModelEvent`

A small generic hook in the model layer, then one use in the bridge.

`src/inspect_ai/model/_model.py`:

```python
_model_event_metadata: ContextVar[dict[str, Any] | None] = ContextVar(
    "_model_event_metadata", default=None
)

@contextmanager
def model_event_metadata(metadata: dict[str, Any]) -> Iterator[None]:
    """Merge `metadata` into every ModelEvent recorded within the block.

    Nested blocks merge, inner keys winning. Not part of the public API.
    """
```

`_record_model_interaction` passes `metadata=dict(current) if current else
None` to `ModelEvent(...)` (1964-1975). Cache reads, retries and sink
routing are untouched: they all go through this one constructor.

`bridge_generate()` gains a keyword-only `routing: BridgeModelResolution |
None = None` and wraps the generate call:

```python
with (
    bridge_model_generate(),
    use_model_event_sink(bridge.model_event_sink),
    model_event_metadata(
        {"bridge_requested_model": routing.requested, "bridge_route": routing.route}
    ) if routing else nullcontext(),
):
    output = await model.generate(...)
```

Every bridged call records both keys, not only redirects: an alias hit is
also a name-to-model mapping worth seeing in the log, and one rule is
simpler to test than a conditional one. A filter that returns a
`ModelOutput` without generating produces no `ModelEvent` and so nothing to
stamp. The keys appear under `metadata` on the event in the log and in the
viewer's event metadata; no viewer change is needed to see them.

### Code changes

`src/inspect_ai/agent/_bridge/util.py`

```python
BridgeModelRoute = Literal[
    "alias", "resolver", "inspect", "model", "active", "role", "passthrough", "default"
]

class BridgeModelResolution(NamedTuple):
    model: Model
    route: BridgeModelRoute
    requested: str
    redirected: bool

def resolve_bridge_model(
    requested: str,
    *,
    model_aliases: dict[str, str | Model] | None,
    model_resolver: ModelResolver | None,
    model: str | None,
    forward_model_names: bool,
    provider: str = "",
) -> BridgeModelResolution: ...

def resolve_inspect_model(
    model_name: str,
    model_aliases: dict[str, str | Model] | None = None,
    fallback_model: str | None = None,
    *,
    model_resolver: ModelResolver | None = None,
    provider: str = "",
    forward_model_names: bool = False,
) -> Model:
    """Compatibility wrapper: `resolve_bridge_model(...).model`."""
```

`resolve_inspect_model` stays because inspect_swe imports it
(`_kimi_code/kimi_code.py:18, 525`); Kimi always passes a pin, so its result
is unchanged.

`bridge_generate()` gains the `routing` keyword and fires the warning. A
NamedTuple rather than a bare tuple per the repo's typed-returns rule.

The four dialect functions (call sites in the table above) call
`resolve_bridge_model(...)` with `bridge.model`, `bridge.model_aliases`,
`bridge.model_resolver`, `bridge.forward_model_names` and their provider,
use `.model` where they used the `Model`, and pass `routing=` to
`bridge_generate`.

`src/inspect_ai/agent/_bridge/types.py`: `forward_model_names` parameter,
attribute and docstring; the `ValueError` above; the `model` attribute
docstring rewritten to the semantics in the matrix.

`src/inspect_ai/agent/_bridge/sandbox/types.py`: thread
`forward_model_names` through `SandboxAgentBridge.__init__`.

`src/inspect_ai/agent/_bridge/sandbox/bridge.py`: new parameter; `model`
docstring rewritten:

> Pin every request the bridge does not otherwise recognise to this model
> (e.g. `"inspect/openai/gpt-4o"`; the `inspect/` prefix is optional).
> Aliases, resolver results and the name `"inspect"` are not pinned.
> Defaults to `None`, which routes unrecognised names to the eval's active
> model (`"inspect"` means the same). Cannot be combined with
> `forward_model_names=True`.

`src/inspect_ai/agent/_bridge/bridge.py`: pass `forward_model_names=True`.

`src/inspect_ai/model/_model.py`: `model_event_metadata` and the
constructor change.

`docs/agent-bridge.qmd`: the "Models" section (196-204) is rewritten to
state the default, show the alias pattern for a scaffold's sub-agent tiers,
and move the `inspect/<provider>/<model>` example under the in-process
bridge with a note that the sandbox bridge needs `forward_model_names=True`
for it:

```python
async with sandbox_agent_bridge(
    state,
    model_aliases={
        "claude-haiku-4-5": get_model("anthropic/claude-haiku-4-5"),
        "grader": get_model(role="grader"),
    },
) as bridge:
    ...
```

`CHANGELOG.md`, under `## Unreleased`: "Agent Bridge: `sandbox_agent_bridge()`
now serves requests for model names it does not recognise with the eval's
model instead of the provider the name implies, and records the requested
name on the `ModelEvent`; pass `forward_model_names=True` to restore
pass-through, or map names with `model_aliases`."

## Alternatives considered

**Refuse unrecognised names with a 400.** Correct in the sense that nothing
is silently substituted, but it breaks the calls the design exists to keep
working: OpenCode's title generation, Claude Code's haiku background calls
and Gemini CLI's utility-model calls would fail, and a scaffold that treats
a model error as fatal loses the sample. The proxy cannot make this decision
either, since aliases and roles live on the host. Substitution plus a
visible record is the behaviour inspect_swe already chose for every agent.

**Keep pass-through as the default and add an allowlist parameter.** The
default would still bill other providers for every scaffold whose author
did not enumerate its names, and enumerating them is the hard part: the
author has to know every id the scaffold emits. `model_aliases` is already
an allowlist that also says where each name goes; an allowlist that maps a
name to itself would be a second spelling of the same thing.

**Per-provider allow policies (`allowed_providers={"anthropic"}`).** Too
coarse for cost control: the eval author chose a model, not a provider, and
a haiku call on the same provider is still a model they did not choose. A
policy like this is expressible today with `model_resolver` for anyone who
wants it.

**Fix the signature to `model="inspect"` and stop there.** This is the
routing part of the chosen design, spelled differently: under the new
semantics `model="inspect"` and `model=None` are the same. Keeping `None` as
the signature default keeps "not pinned" distinguishable in the code and
docs, and the design adds what a bare default change would not: the
pass-through opt-in, the warning and the log record.

**Honour `inspect/`-prefixed names by default and redirect only bare
names.** The prefix is the scaffold's spelling, not the eval author's
intent, and it keeps roles reachable via `inspect/grader`. It is the right
behaviour for the in-process bridge, where it stays.

**Warn per bridge instance instead of per process.** One warning per sample
per name is hundreds of identical lines in a large eval. The per-call
record lives on the `ModelEvent`; the warning only needs to be noticed
once.

## Compatibility and migration

**Who relies on pass-through today.** Any sandbox bridge with `model=None`
whose scaffold names a model other than the eval's. In this repo: none
(`tests/tools/test_tools_bridge.py` and
`tests/agent/test_sandbox_agent_bridge_media.py` send `"inspect"`).
inspect_evals has no `sandbox_agent_bridge()` caller. In inspect_swe, the
non-ACP agents all pin and are unchanged; the ACP Claude Code and Codex
agents pass `model=None` with aliases (table above), so a name outside
their alias map moves from `get_model(name)` on the host's credentials to
the eval's active model, with a warning and a metadata record. When such an
agent runs a model other than the eval's active model and wants unknown
names to collapse onto *its* model, it pins `model=str(model)` as the ACP
Gemini agent already does (`acp/_agents/gemini_cli/gemini_cli.py:70-76`).
That is a one-line follow-up in inspect_swe, not a prerequisite. Anyone else
who wants the old behaviour passes `forward_model_names=True`. The
CHANGELOG entry and the docs section carry the change.

**Model roles.** Unreachable by name from a sandbox by default. To expose
one: `model_aliases={"grader": get_model(role="grader")}`, or pass-through.
Pinned bridges already had this behaviour (table row `grader` /
`fallback_model="inspect"`).

**`model=` with bare `"inspect"`.** A pin spelled without the `inspect/`
prefix (`model="openai/gpt-4o"`) no longer captures a request for
`"inspect"`; that request goes to the active model, as it does for a pin
spelled `inspect/openai/gpt-4o` today. No caller in this repo or inspect_swe
spells a pin without the prefix.

**Precedence with `model_aliases` and the active-model match.** Unchanged:
aliases first, then resolver, then pin, then active match. The active match
still runs before the new default rule, so a client naming the eval's model
gets the active instance (and its eval config) without a warning.

**`resolve_inspect_model()`.** Signature preserved with one added keyword;
its default now follows the new routing. Its only external caller (Kimi)
pins and is unaffected. Its tests in `tests/agent/test_bridge_model_aliases.py`
and `test_bridge_model_resolver.py` change where they asserted pass-through
(`test_resolve_inspect_model_prefixed`,
`test_no_resolver_no_fallback_resolves_via_get_model_with_provider`,
`test_other_model_does_not_get_the_eval_config` in
`test_bridge_generate_config_propagation.py`); each gains a pass-through
variant.

**In-process `agent_bridge()`.** Shares the resolver and the dialect
functions; constructed with pass-through on, so its routing is unchanged
and the LangChain `inspect/google/...` example keeps working. Its
`ModelEvent`s gain the two metadata keys.

**Stored formats and the viewer.** `ModelEvent.metadata` is an existing
optional field; the two keys are plain strings inside it. No JSON schema,
OpenAPI or generated TypeScript change; old logs read unchanged; the
`inspect_sandbox_tools` binaries are untouched.

**Public API.** `sandbox_agent_bridge()`, `AgentBridge` and
`SandboxAgentBridge` gain one keyword argument with a default. `ModelResolver`
is unchanged. `model_event_metadata` and `resolve_bridge_model` are
internal.

## Security

Untrusted input reaching the new code is the request's model name: a string
chosen by the sandboxed scaffold, delivered through the proxy in the JSON
body or, for Google, parsed from the URL path (proxy.py:2044-2047). Today it
reaches `get_model()` and so provider construction. Under the new default it
reaches only: an exact-match dictionary lookup, string concatenation for
provider qualification, the author's `model_resolver` (which already
receives it today), string comparison against the active model's names, the
warning message (escaped with `repr()`, truncated, deduped with a capped
set) and the `ModelEvent` metadata (stored verbatim, as the rest of the
request body already is in the bridge's tracked messages). `get_model()`,
`model_roles()` and provider construction see it only under
`forward_model_names=True`, which restores today's exposure by explicit
choice. Nothing in the design executes, formats into a template, or opens a
file based on the name.

## Testing

Unit, `tests/agent/test_bridge_model_resolver.py` (existing file; the
matrix replaces the ad-hoc default-route tests):

- `test_routing_matrix`: `@pytest.mark.parametrize` over the rows of the
  matrix above, each row `(requested, provider, model, forward_model_names,
  expected)` where `expected` is one of `active`, `alias`, `resolver`,
  `role:grader`, `pin`, `spec:<name>`, `error`, plus the expected `route`
  and `redirected`. Active model and role set with `init_active_model` /
  `init_model_roles` under the `_isolate_active_model` fixture pattern from
  `tests/agent/test_bridge_generate_config_propagation.py:35-53`. Pins and
  pass-through targets use `mockllm/...` specs so no provider key is
  needed.
- The existing regressions stay as named tests:
  `test_bare_name_matches_active_model_under_different_provider`,
  `test_fallback_model_wins_over_active_model_raw_name_match`, alias before
  resolver, resolver `None` defers.
- `test_pin_spec_naming_active_model_returns_active_instance`.
- `test_forward_model_names_with_pin_raises` (construction of
  `AgentBridge` and of `SandboxAgentBridge`).

Warning, same file, with `caplog`:

- `test_redirect_warns_once_per_name`: two requests for the same name and
  one for another across two bridge instances produce exactly two warnings,
  each naming `model_aliases`; the pinned variant names the pin.
- `test_redirect_warning_cap`: past 64 names, one final warning and then
  silence.
- `test_active_and_alias_hits_do_not_warn`.

Model layer, `tests/model/test_model_event_timing.py` (existing file that
runs a `mockllm` generate and inspects the resulting `ModelEvent`):

- `test_model_event_metadata_context_stamps_event`: nested blocks merge,
  inner key wins, no block means `metadata is None`.

End to end without Docker, `tests/agent/test_agent_bridge.py` (existing
file, `eval()` with `mockllm`): a solver builds `SandboxAgentBridge(...)` by
hand (pattern: `tests/agent/test_bridge_provider_errors.py:110-119`) and
calls `inspect_completions_api_request({"model": "gpt-4o-mini", ...}, None,
bridge)` directly. The dialect functions do not touch the sandbox, so this
covers dialect → resolver → `bridge_generate` → `ModelEvent`. Asserts: the
response came from `mockllm/model`, the log's `ModelEvent.metadata` is
`{"bridge_requested_model": "gpt-4o-mini", "bridge_route": "default"}`, and
a second test with `forward_model_names=True` and `"model": "mockllm/other"`
records `route == "passthrough"`. Repeat one redirected case for the
Anthropic and Google dialect functions.

End to end with Docker, `tests/tools/test_tools_bridge.py` (existing
`@skip_if_no_docker` file whose slow tests PR CI runs):
`test_sandbox_bridge_redirects_unknown_model_to_eval_model`, modelled on
`test_sandbox_bridge_rejection_hides_the_call_from_the_agent` (552-600):
`post_completions` with `"model": "claude-haiku-4-5"` through the real proxy,
assert the reply and the `ModelEvent` metadata.

Trio: the bridge is async plumbing, so the touched async tests run once
normally and once with `--runtrio` before the PR opens, per
`.agents/skills/slow-tests/SKILL.md`; the Docker test runs with
`--runslow`. Neither needs a provider key. The PR description reports both
under "Slow tests".

Docs: no test executes `docs/agent-bridge.qmd`
(`tests/agent/test_agent_docs.py` covers other agent pages), so the new
example is reviewed by eye; it names real models and is not meant to run
under `mockllm`.

## Implementation plan

One PR, in commits an implementer can land in order:

1. **Model-layer hook.** `model_event_metadata()` and the
   `_record_model_interaction` change in `src/inspect_ai/model/_model.py`;
   test in `tests/model/test_model_event_timing.py`. Independent of the
   bridge and safe alone.
2. **Resolver.** `BridgeModelRoute`, `BridgeModelResolution`,
   `resolve_bridge_model`, the wrapper and the warning in
   `src/inspect_ai/agent/_bridge/util.py`; `forward_model_names` on
   `AgentBridge` (`types.py`) with the `ValueError`; `SandboxAgentBridge`
   threading (`sandbox/types.py`); `agent_bridge()` passes `True`
   (`bridge.py`). Rewrite `tests/agent/test_bridge_model_resolver.py` with
   the matrix and warning tests; adjust the three pass-through assertions
   named under Compatibility.
3. **Dialects.** `completions.py`, `responses_impl.py`,
   `anthropic_api_impl.py`, `google_api_impl.py` call `resolve_bridge_model`
   and pass `routing=` to `bridge_generate`; `bridge_generate` stamps the
   metadata. Add the no-Docker end-to-end tests to
   `tests/agent/test_agent_bridge.py`.
4. **Sandbox surface and Docker test.** `sandbox_agent_bridge()` parameter
   and docstrings (`sandbox/bridge.py`); the Docker test in
   `tests/tools/test_tools_bridge.py`.
5. **Docs and CHANGELOG.** `docs/agent-bridge.qmd` Models section and the
   alias example; the `## Unreleased` entry.

Follow-up outside this repo (not blocking): inspect_swe's ACP Claude Code
and Codex agents pin `model=str(model)` when the agent's model may differ
from the eval's, matching its ACP Gemini agent.

## Open questions

1. **Warning under a pin.** The design warns once per redirected name for
   pinned bridges too, since the requested name is still information the
   author did not choose to collapse. If that is noise for inspect_swe users
   (every Gemini CLI run warns once about `gemini-2.5-pro`), drop the
   warning for `route == "model"` and rely on the `ModelEvent` record.
   Recommendation: keep it; it is one line per process per name and
   inspect_swe can alias the presented name to silence it, as Claude Code
   does.
2. **Flag spelling.** `forward_model_names` as proposed, or
   `model_passthrough`. Recommendation: `forward_model_names`, for the
   pairing with `forward_generation_config`.

## Not this design

- Provider-side tool withholding (`web_search`, `code_execution`, remote
  MCP) is unchanged and not revisited.
- Request provenance: which scaffold component (main agent, sub-agent, title
  generator) made a bridged call. The `ModelEvent` record here carries the
  requested name only.
- The response's `model` field echoes the served model's short name
  (`completions.py:115`, `responses_impl.py:337`). Whether it should echo the
  requested name for scaffolds that compare it is a separate question.
- `warn_once()` in `src/inspect_ai/_util/logger.py:277-283` keeps its
  history in a list with linear membership; fine for its fixed messages,
  worth a set if it is ever used with per-input messages.
- A public API for attaching metadata to `ModelEvent`s
  (`model_event_metadata` stays private until a second consumer appears).
- The in-process bridge exposing `model=`, `model_aliases` or
  `model_resolver`.
