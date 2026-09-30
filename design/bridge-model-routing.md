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
utility model names. With the pass-through default each such call is served
by whatever Inspect model its name implies, on the host's credentials: a
model the eval author never chose, on another provider when the eval's model
is not on the scaffold's native API (an eval on `openai/gpt-5` whose Claude
Code haiku calls go to Anthropic), and otherwise another model on the same
provider (an eval on `anthropic/claude-fable-5` paying for haiku calls
outside the eval model's configuration). Eval-internal model roles (graders,
monitors) are also reachable by name from inside the sandbox
(util.py:678-679). The log records which model served each call and its
usage (`_model.py:1964-1975`, `2976-2977`) and the viewer shows it, but not
the name the scaffold asked for or why the bridge chose that model; the
response echoes the served model's name too (`completions.py:69,115`). A
redirect therefore cannot be told from a call the scaffold made by name.

### Who is untrusted

Everything inside the sandbox: the scaffold, and the model under evaluation
driving it with tool access. The model name in a request is a string that
side chooses, delivered through the proxy in the JSON body or, for Google,
parsed from the URL path (proxy.py:2044-2047). Today the resolver ends by
handing that string to `get_model()`. The eval author's decisions live on
the host: `model=`, `model_aliases`, `model_resolver`, and the eval's own
model and roles. The design's rule is that only host-side configuration
decides which model serves a request.

### What that allows today, and what the design closes

- **Use of the host's credentials as a confused deputy.** Sandboxed code
  names any `provider/model` and the host instantiates that provider with
  its own API keys and makes the call. A sandbox with no network egress of
  its own still gains use of every provider the host has keys for: a spend
  channel, and an outbound channel through the host. Under the new default
  the untrusted string never reaches `get_model()` or provider construction;
  it is compared against author-configured aliases and the eval's model, and
  otherwise dropped in favour of the eval's model.
- **Reaching eval-internal models.** A grader or monitor role is a host-side
  trust boundary: a different model, prompt or configuration the evaluated
  agent is not supposed to talk to. Today `grader` or `inspect/grader` from
  inside the sandbox resolves to that role's model (util.py:678-679), so the
  agent can query, probe or spend on its own grader. Roles become
  unreachable by name unless the author aliases one in.
- **Eval integrity by model substitution.** An agent evaluated on a weak
  model can send its hard sub-steps to `inspect/<the strongest model the
  host has a key for>` and report the results as its own. Unrecognised
  names go to the eval's model, so measured capability is the evaluated
  model's.
- **Data handling.** Conversation content that must stay on an approved
  provider or deployment (an Azure tenant, say) can today be sent to public
  OpenAI or Anthropic by naming them. The default keeps it on the model the
  author chose.
- **No provenance.** The served model and its usage are already recorded
  and shown (`_model.py:1964-1975`, `2976-2977`, the viewer's
  `ModelEventView`), so an operator can see that `anthropic/claude-haiku-4-5`
  was called. What the log lacks is the client-requested name and the
  routing that led there, so a call the scaffold made by name and a redirect
  look the same. The `requested_model` field and the once-per-name warning
  supply that provenance for every redirect and every alias hit.

What the design deliberately leaves alone: provider-side tools
(`web_search`, `code_execution`, remote MCP) are a separate, already
withheld channel; `model_resolver` still receives the untrusted
string, but that is author code; the in-process bridge gets no mitigation
because its scaffold already holds the host's credentials; and nothing here
constrains what the sandbox sends *to* the eval's model.

### The documented and implemented defaults disagree


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

The rule the design enforces is the same from either angle, routing and
cost or the trust boundary above: the bridge serves the model the eval
author chose unless the author says otherwise, and the log shows when it
had to decide.

## Goals and non-goals

Goals:

1. By default, every request name that is not an alias, a resolver result,
   `"inspect"`, or the eval's active model routes to the eval's active model.
   A scaffold's sub-agent and side calls keep working, on the main model.
   No other model, on any provider, and no model role is reached unless the
   author says so.
2. Multi-model scaffolds route through the existing mechanisms:
   `model_aliases` for exact names (the inspect_swe pattern),
   `model_resolver` for routing by policy. The sandbox bridge gains no new
   routing parameter (see Alternatives for the pass-through opt-in that was
   considered and left out).
3. Redirects are visible: one warning per redirected name pointing at
   `model_aliases`, and the client-requested name recorded in a new
   `requested_model` field on the `ModelEvent`.
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
the body (proxy.py:2044-2047) with a pattern that stops at the next slash
(`models/([^/:]+)`, proxy.py:2032), so a prefixed Google name such as
`inspect/mockllm/other` reaches the host as `inspect`. Each host dialect
reads the name and calls the resolver with the bridge's options and the
endpoint's provider; the Google dialect substitutes `"inspect"` when the
body has no `model` (google_api_impl.py:76):

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

The Google patch differs from the other three. It extracts a name from the
SDK URL path only to decide interception (`_google_api_model_name`,
bridge.py:578-581, the same slash-stopping pattern; used at 527-528) and
then forwards the SDK's `request_dict`, which carries no `model`, so the
Google dialect resolves its default `"inspect"` (google_api_impl.py:76). An
in-process Google request for `inspect/mockllm/other` is therefore served by
the active model today, and the dialect never sees the requested name
(verified with a `google.genai` client under `agent_bridge()`, 2026-09-16).

### Where a record of the requested name would go

`ModelEvent` (`src/inspect_ai/event/_model.py:85-137`) records the model
that served the call (`model`, `role`) but has no field for the name the
client asked for; it is built in `Model._record_model_interaction`
(`src/inspect_ai/model/_model.py:1964-1975`) from the `Model` alone.
`BaseEvent.metadata` (`src/inspect_ai/event/_base.py:29-30`) is a free-form
dict that neither the viewer nor the events dataframe reads. The bridge calls
`model.generate()` from `bridge_generate()` inside two context managers
(`bridge_model_generate()` and `use_model_event_sink()`, util.py:562), so a
third context manager is the established shape. Installing a sink to stamp
events is not an option: a sink disables partial-progress publishing
(`_model.py:1401`).

### inspect_swe today

Every inspect_swe agent built on `sandbox_agent_bridge()` pins `model=`,
except the two ACP agents noted last. "Bridge options" is what the agent
passes to `sandbox_agent_bridge()` for the two routing parameters: `model=`
(the pin; each agent has its own `model: str | None` argument, defaulting to
the task's main model, and builds `"inspect/<model>"` from it or `"inspect"`
when unset) and `model_aliases=`. "Under today's code" is the resolver step
that ends up serving the scaffold's requests: "alias, else pin" means the
names the agent aliased hit step 1 and every other name is captured by the
pin at step 4; "pin" means no aliases are needed because the pin captures
everything.

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
- **pass-through**: today's `model=None` routing, where a name the bridge
  does not recognise resolves to the role or model it names. Kept for the
  in-process bridge only, through `allow_client_model_names=True` (below).
- **redirect**: a request served by a model the requested name does not
  denote, by the default rule or by a pin.

### Resolution order

```
resolve_bridge_model(requested, *, model_aliases, model_resolver, model,
                     allow_client_model_names, provider) -> BridgeModelResolution

 1. requested in model_aliases              -> alias target            route="alias"
 2. qualified = provider-qualify(requested)    (unchanged rule)
 3. model_resolver(qualified) is not None   -> that                    route="resolver"
 4. requested == "inspect"                  -> get_model()             route="inspect"
 5. pin set                                 -> D                       route="model"
 6. allow_client_model_names and the
    stripped name is in model_roles()       -> get_model(role=name)    route="role"
 7. qualified (inspect/ stripped) or requested
    names the active model                  -> active instance         route="active"
 8. allow_client_model_names                -> get_model(name)         route="passthrough"
 9. otherwise                               -> get_model()             route="default"
```

What changes relative to today: step 4 no longer depends on how the pin is
spelled; steps 6 and 8 run only for the in-process bridge; step 9 is new. Every other
precedence is today's: alias and resolver beat the pin (util.py:639-663
run before 669), the pin beats roles and the active-model match (669-672
before 678 and 700), a role beats the active-model match (678-679 before
700-705), and the active-model match beats `get_model(name)`. Under
pass-through the order is therefore exactly today's `model=None` order,
which is what keeps the in-process bridge unchanged. Step 7 keeps both of
today's comparisons (full name or short name after stripping, and the raw
pre-qualification name against the short name), so a client on the OpenAI
endpoint naming `gpt-4o` still gets an `azureai/gpt-4o` active model. Step
9 calls `get_model()` exactly as `"inspect"` does, so outside an eval it
falls back to `INSPECT_EVAL_MODEL` and otherwise raises the same "No model
specified" error a bare `"inspect"` request raises today.

Role before active matters when the active model's short name is also a
role name (active `mockllm/grader`, role `grader` bound to another model).
Today `grader` and `inspect/grader` both return the role (verified
2026-09-15 at the base commit), and under pass-through they still do. Under
the default, where roles are not reachable, they resolve to the active
model without a warning, because the name denotes the active model.

### What `model=` means (the matrix)

Active model `A`; role `grader`; pin target `D`. "warn" means the redirect
warning below fires once per requested name; the warning is new wherever it
appears, so the last column lists routing changes only. The matrix is the
sandbox bridge's routing; the in-process bridge keeps today's `model=None`
routing (pass-through, below).

| requested name | default (`model=None` or `"inspect"`) | pinned (`model="inspect/<spec>"` or `"<spec>"`) | change from today: example, previous behaviour, who is affected |
|---|---|---|---|
| a name listed in `model_aliases` | the model it maps to | the model it maps to | none |
| a name the `model_resolver` returns a model for | the resolver's model | the resolver's model | none |
| `inspect` | `A` | `A` (**change**) | Only for a pin spelled without `inspect/`. Example: `model="openai/gpt-4o"` and the scaffold sends `inspect`: today `openai/gpt-4o`, now `A`. Affects bridges pinned without the prefix whose scaffold sends `inspect`: none in this repo or inspect_swe (ACP Gemini pins that way, but Gemini CLI never sends `inspect`). |
| `A`'s full name, or its short name (bare, any endpoint) | `A` instance, no warning | `D`, warn (pin wins) | none in routing |
| `inspect/<A's spec>` | `A` instance | `D`, warn | none in routing |
| `grader` (a role) | `A`, warn (**change**) | `D`, warn | Unpinned bridges only. Example: `eval(..., model_roles={"grader": "openai/gpt-4o-mini"})`, `sandbox_agent_bridge(state)`, scaffold sends `grader`: today the grader model, now `A`. Affects unpinned bridges whose scaffold names a role: none found (inspect_swe's unpinned ACP agents send provider model ids). Fix: `model_aliases={"grader": get_model(role="grader")}`. |
| `inspect/grader` | `A`, warn (**change**) | `D`, warn | As the row above; the alias key is `"inspect/grader"`. |
| `grader` when `A`'s short name is also `grader` | `A` instance, no warning (**change**) | `D`, warn | Default only: today the role wins over the active-model match; now roles are not reachable by default, so the name resolves as `A`'s own. Same population and fix as the `grader` row. |
| `inspect/grader` when `A`'s short name is also `grader` | `A` instance, no warning (**change**) | `D`, warn | As the row above. |
| `inspect/openai/gpt-4o-mini` | `A`, warn (**change**) | `D`, warn | Unpinned bridges only. Example: `sandbox_agent_bridge(state)`, scaffold sends `inspect/openai/gpt-4o-mini`: today Inspect's OpenAI provider on the host's `OPENAI_API_KEY`, now `A`. Affects unpinned sandbox bridges whose scaffold uses the `inspect/` form for another model: none in this repo (the docs example is in-process, unchanged). Fix: `model_aliases={"inspect/openai/gpt-4o-mini": "openai/gpt-4o-mini"}`. |
| `gpt-4o-mini` on the OpenAI endpoint (any bare native name) | `A`, warn (**change**) | `D`, warn | Unpinned bridges only; the case this design exists for. Example: eval on `openai/gpt-5`, `sandbox_agent_bridge(state)`, Claude Code's background call sends `claude-haiku-4-5` on the Anthropic endpoint: today Inspect's Anthropic provider on the host's `ANTHROPIC_API_KEY`, now `A`. Affects inspect_swe's ACP Claude Code and Codex agents (`model=None`) and any direct `sandbox_agent_bridge()` caller without `model=`. Fix: alias the tier, or pin. |
| `unknown-model` with no endpoint provider | `A`, warn (**change**) | `D`, warn | Resolver level only: every bridge dialect passes a provider, so no bridged request reaches this row. Direct callers of `resolve_inspect_model()` without a provider or pin: none (Kimi pins). |
| pinned spec names `A` | n/a | `A` instance | none |

### Pass-through stays in-process only

`AgentBridge.__init__` (types.py) gains one capability keyword next to
`allow_remote_mcp` and `allow_remote_media`:

```python
allow_client_model_names: bool = False
```

It enables steps 6 and 8 of the resolution order: a name the bridge does
not otherwise recognise reaches the role or model it names. It defaults
closed for the same reason `allow_remote_media` does (types.py:60-62): a
bridge subclass cannot reopen the channel by accident. The in-process
`agent_bridge()` constructs its `AgentBridge` with
`allow_client_model_names=True` (bridge.py:180-190), as it passes
`allow_remote_media=True` and `default_grant=True` for web search
(bridge.py:168-174): the scaffold already runs with the host's credentials
and can call any provider directly, so redirecting `inspect/<spec>` buys
nothing and would break the documented LangChain example. Its behaviour is
unchanged.

`SandboxAgentBridge` and `sandbox_agent_bridge()` do not take or pass it, so
every sandbox bridge routes by the matrix above. A sandbox author who wants
another model reached names it in `model_aliases`, whose keys are the exact
strings the scaffold sends (the warning and `ModelEvent.requested_model`
show them), or routes by policy with `model_resolver`. There is no public
opt-in that restores open-ended pass-through; see Alternatives. The pin and
the capability do not conflict: no caller sets both, and if one did the pin
would win at step 5, as it wins over roles and the active match today.

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
> to route it to a model of your choice.

For the pinned route the second sentence is "Add ... to model_aliases to
route it elsewhere; it was pinned by model='inspect/openai/gpt-4o'." When
the requested name is a model role the hint is specific: "'grader' is a
model role; expose it with model_aliases={'grader': get_model(role='grader')}".

The warning fires under an explicit pin too, including for scaffolds whose
model selection this design leaves unchanged (inspect_swe's Gemini CLI and
OpenCode agents warn once about their presented name). The pin collapses
names the author may not know the scaffold sends, and one line per name per
process is cheap; an agent that wants silence aliases its presented name, as
inspect_swe's Claude Code agent already does. Decision: Ransom, 2026-09-25.

Dedupe is a module-level `set[str]` of requested names in util.py (not
`warn_once`, whose list membership is linear in distinct messages), capped
at `_MAX_REDIRECT_WARNINGS = 64` names; on reaching the cap one final
warning says further redirects are not reported and points at
`ModelEvent.requested_model`. The requested name is `repr()`-escaped and
truncated to 200 characters in the message.

### Recording the requested name on the `ModelEvent`

A new optional field on the event, set through a small context-variable
hook in the model layer, used once by the bridge.

`src/inspect_ai/event/_model.py`, after `role` (94-95):

```python
requested_model: str | None = Field(default=None)
"""Model name the client requested, for calls made through an agent bridge
(`None` for direct calls). Differs from `model` when the bridge routed the
request elsewhere: an alias, a resolver, a pin, or the default of serving
an unrecognised name with the eval's model. For the Google dialect through
the sandbox proxy this is the name as the proxy read it from the URL, which
truncates an `inspect/`-prefixed name at its first slash."""
```

`src/inspect_ai/model/_model.py`:

```python
_requested_model: ContextVar[str | None] = ContextVar(
    "_requested_model", default=None
)

@contextmanager
def requested_model(name: str) -> Iterator[None]:
    """Record `name` as `ModelEvent.requested_model` for every generation
    in the block. Not part of the public API."""
    token = _requested_model.set(name)
    try:
        yield
    finally:
        _requested_model.reset(token)
```

`_record_model_interaction` passes `requested_model=_requested_model.get()`
to `ModelEvent(...)` (1964-1975). Cache reads, retries and sink routing are
untouched: they all go through this one constructor.

The `finally` reset is what makes this state safe: a generation that is
cancelled or raises unwinds through it, so the next generation in the same
task sees no stale name. A `ContextVar` is per task and anyio copies the
context when a task starts, so two bridged requests in flight in different
tasks never see each other's name. Both properties are tested (see Testing).
A context variable rather than a `generate()` parameter because a
`GenerateFilter` may call `model.generate()` itself (below); a parameter
would miss that event unless every filter author remembered to pass it.

`bridge_generate()` gains a keyword-only `routing: BridgeModelResolution |
None = None`. Inside its retry loop, the block that runs the filter and the
default generation (util.py:532-579) is enclosed in a fresh
`requested_model(...)` context on every attempt:

```python
def _routing_context(routing: BridgeModelResolution | None) -> AbstractContextManager[None]:
    return requested_model(routing.requested) if routing else nullcontext()

while True:
    input_messages, tools, tool_choice, config = ...   # reset per attempt
    with _routing_context(routing):
        output: ModelOutput | None = None
        if bridge.filter:
            ...                                        # a filter may generate itself
        if output is None:
            with bridge_model_generate(), use_model_event_sink(bridge.model_event_sink):
                output = await model.generate(...)
    ...                                                # compaction bookkeeping, approval
```

A `@contextmanager` object is single-use, hence the helper that returns a
new one per attempt. The filter runs inside the block because a
`GenerateFilter` may call `model.generate()` itself and return the output
(util.py:543-555): that `ModelEvent` is the client's request served through
the filter and must carry the requested name too. Compaction
(`compact.compact_input` at 510-512, `record_output` at 583-584) and tool
approval (600) stay outside: a summarisation or approver call is not the
client's request and must not be labelled as one.

Every bridged call records the field, not only redirects: an alias hit is
also a name-to-model mapping worth seeing in the log, and one rule is
simpler to test than a conditional one. A filter that returns a
`ModelOutput` without generating produces no `ModelEvent` and so nothing to
record. The route is not logged: it stays on `BridgeModelResolution` for
the warning and the tests, and a reader sees a redirect as `requested_model`
differing from `model` while knowing their own aliases.

**Google.** On both Google paths the routing input is not the client's name
today (see Current behaviour), so the requested name has to reach the
recording path independently of it. `inspect_google_api_request()` and its
`_impl` gain a keyword-only `requested_model: str | None = None`; the
dialect records `requested_model` when given and the routing name otherwise.
In-process, `patched_async_request` (bridge.py:518-537) extracts the whole
model segment with a new helper `_google_api_requested_model(path)` and
passes it as `requested_model`. The helper anchors on the terminal operation
rather than on the first colon, because a model name may itself contain
colons (Inspect accepts tagged specs such as `ollama/llama3:8b`,
`src/inspect_ai/model/_providers/ollama.py:10-25`, and the SDK path for
`inspect/ollama/llama3:8b` ends in `:8b:generateContent`): pattern
`models/(.+):generateContent(?:\?.*)?$`, so `inspect`,
`inspect/mockllm/other`, `inspect/ollama/llama3:8b` and
`inspect/ollama/llama3:70b` are each recovered exactly. The interception
test and the routing input
(`_google_api_model_name` and the unmodified `request_dict`) are untouched,
so in-process Google routing stays exactly as it is today, defect included.
In the sandbox the proxy writes the slash-truncated segment into `model`
(proxy.py:2032, 2044-2047) and this design does not change the proxy binary,
so that path records the name as the proxy delivered it. For bare Gemini ids,
the only Google names a known scaffold sends (Gemini CLI's `gemini-2.5-pro`
and its utility names), that is the full client name; for an
`inspect/`-prefixed Google name sent through the sandbox the field holds the
first segment. The field's docstring says so, and the proxy fix is listed
under Not this design with the routing defect.

Because it is a typed field, the name is a first-class part of the log: in
`.eval` files, through `read_eval_log()`, as a new
`model_event_requested_model` column in the events dataframe
(`ModelEventColumns`, `src/inspect_ai/analysis/_dataframe/events/columns.py:62-75`),
and in the viewer's generated TypeScript types, so the viewer can show it
(a separate small change; see Not this design). The first draft recorded
the name in `BaseEvent.metadata` instead; see Alternatives for why the
field won (decision: Ransom, 2026-09-16).

### Code changes

`src/inspect_ai/agent/_bridge/util.py`

```python
BridgeModelRoute = Literal[
    "alias", "resolver", "inspect", "model", "active", "role", "passthrough", "default"
]  # "role" and "passthrough" only with allow_client_model_names

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
    allow_client_model_names: bool,
    provider: str = "",
) -> BridgeModelResolution: ...

def resolve_inspect_model(
    model_name: str,
    model_aliases: dict[str, str | Model] | None = None,
    fallback_model: str | None = None,
    *,
    model_resolver: ModelResolver | None = None,
    provider: str = "",
) -> Model:
    """Compatibility wrapper: `resolve_bridge_model(...,
    allow_client_model_names=False).model`."""
```

`resolve_inspect_model` stays because inspect_swe imports it
(`_kimi_code/kimi_code.py:18, 525`); Kimi always passes a pin, so its result
is unchanged. Its signature is unchanged too; tests of the in-process
routing call `resolve_bridge_model` directly.

`bridge_generate()` gains the `routing` keyword and fires the warning. A
NamedTuple rather than a bare tuple per the repo's typed-returns rule.

The four dialect functions (call sites in the table above) call
`resolve_bridge_model(...)` with `bridge.model`, `bridge.model_aliases`,
`bridge.model_resolver`, `bridge.allow_client_model_names` and their provider,
use `.model` where they used the `Model`, and pass `routing=` to
`bridge_generate`.

`src/inspect_ai/agent/_bridge/types.py`: `allow_client_model_names`
parameter and attribute, with the capability comment extended to cover it;
the `model` attribute docstring rewritten to the semantics in the matrix.

`src/inspect_ai/agent/_bridge/sandbox/bridge.py`: no new parameter; the
`model` docstring rewritten:

> Pin every request the bridge does not otherwise recognise to this model
> (e.g. `"inspect/openai/gpt-4o"`; the `inspect/` prefix is optional).
> Aliases, resolver results and the name `"inspect"` are not pinned.
> Defaults to `None`, which routes unrecognised names to the eval's active
> model (`"inspect"` means the same); map other names with `model_aliases`.

`src/inspect_ai/agent/_bridge/bridge.py`: pass `allow_client_model_names=True`;
add `_google_api_requested_model(path)` and pass its result as
`requested_model=` from `patched_async_request`.

`src/inspect_ai/agent/_bridge/google_api.py` and `google_api_impl.py`: the
keyword-only `requested_model` parameter, used for recording only.

`src/inspect_ai/event/_model.py`: the `requested_model` field.

`src/inspect_ai/model/_model.py`: the `requested_model()` context manager
and the constructor change.

`src/inspect_ai/analysis/_dataframe/events/columns.py`: the
`model_event_requested_model` column in `ModelEventColumns`.

Generated schema and types: the OpenAPI spec and the viewer's TypeScript
types are regenerated per `design/type-generation-pipeline.md` and landed
with the ts-mono pointer bump (`.agents/skills/land-ts-mono/SKILL.md`).

`docs/agent-bridge.qmd`: the "Models" section (196-204) is rewritten to
state the default, show the alias pattern for a scaffold's sub-agent tiers,
and move the `inspect/<provider>/<model>` example under the in-process
bridge with a note that the sandbox bridge serves such a name with the
eval's model unless it is aliased. The migration paragraph says: map each
name the scaffold sends that should reach another model; keys are the exact
requested strings, which the warning and `requested_model` show; names for
the eval's own model need no alias (the active-model match serves them with
the eval's config, which an alias to a spec string would not):

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
name on the `ModelEvent`; map names to other models with `model_aliases`."

## Alternatives considered

**Refuse unrecognised names with a 400.** Correct in the sense that nothing
is silently substituted, but it breaks the calls the design exists to keep
working: OpenCode's title generation, Claude Code's haiku background calls
and Gemini CLI's utility-model calls would fail, and a scaffold that treats
a model error as fatal loses the sample. The proxy cannot make this decision
either, since aliases and roles live on the host. Substitution plus a
visible record is the behaviour inspect_swe already chose for every agent.

**Keep pass-through as the default and add an allowlist parameter.** The
default would still serve unlisted names with whatever model they imply,
billed to the host, for every scaffold whose author did not enumerate its
names, and enumerating them is the hard part: the
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
warning and the log record.

**Honour `inspect/`-prefixed names by default and redirect only bare
names.** The prefix is the scaffold's spelling, not the eval author's
intent, and it keeps roles reachable via `inspect/grader`. It is the right
behaviour for the in-process bridge, where it stays.

**A public pass-through opt-in (`forward_model_names=True`).** Earlier
revisions added this flag to `sandbox_agent_bridge()` to restore today's
routing for a faithful proxy, where the client's model name is
authoritative. Left out because no known caller needs it: the unpinned
bridges this design affects (inspect_swe's ACP Claude Code and Codex
agents) want their side calls on the eval model, and a scaffold that should
reach specific other models names them in `model_aliases`. The flag also
needed a rule against combining it with a pin. Adding it later breaks
nothing; removing it would. Open-ended pass-through on the sandbox bridge is
therefore unsupported. A `model_resolver` can approximate it, but the
resolver receives the provider-qualified name before the `"inspect"`,
`inspect/`-prefix, role and active-model steps, so `lambda name:
get_model(name)` is not equivalent: it raises on `"inspect"`,
`inspect/<spec>` and role names, and returns a separate instance for the
eval's own model without the eval's config. Decision: Ransom, 2026-09-25,
after review.

**Record the requested name in `ModelEvent.metadata`.** The first draft of
this design. No schema, OpenAPI or TypeScript change and old logs untouched,
but the keys are untyped strings nobody validates, the viewer and the events
dataframe never see them, and discoverability is by convention. An explicit
optional field costs one regenerated-types landing and gives a real
contract. Decision: Ransom, 2026-09-16.

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
the eval's active model, with a warning and the requested name on the
event. When such an
agent runs a model other than the eval's active model and wants unknown
names to collapse onto *its* model, it pins `model=str(model)` as the ACP
Gemini agent already does (`acp/_agents/gemini_cli/gemini_cli.py:70-76`).
That is a one-line follow-up in inspect_swe, not a prerequisite. Anyone else
who relied on a name reaching its own model aliases that name; the warning
names each one. The CHANGELOG entry and the docs section carry the change.

**Model roles.** Unreachable by name from a sandbox by default. To expose
one: `model_aliases={"grader": get_model(role="grader")}`.
Pinned bridges already had this behaviour (table row `grader` /
`fallback_model="inspect"`).

**`model=` with bare `"inspect"`.** A pin spelled without the `inspect/`
prefix (`model="openai/gpt-4o"`) no longer captures a request for
`"inspect"`; that request goes to the eval's active model, as it does for a
pin spelled `inspect/openai/gpt-4o` today. One caller spells a pin this way:
inspect_swe's ACP Gemini agent (`acp/_agents/gemini_cli/gemini_cli.py:75`,
`model=str(model)`). Its normal traffic is Gemini model ids
(`gemini-2.5-pro` and the CLI's internal utility names), which the pin
captures today and under this design alike. Only a literal `"inspect"`
request would route differently, and Gemini CLI never sends one (it sends
the `--model` id); when the agent's model is the eval's model the two
targets coincide anyway.

**Precedence with `model_aliases` and the active-model match.** Unchanged:
aliases first, then resolver, then pin, then active match. The active match
still runs before the new default rule, so a client naming the eval's model
gets the active instance (and its eval config) without a warning.

**`resolve_inspect_model()`.** Signature unchanged; its default now
follows the new routing. Its only external caller (Kimi)
pins and is unaffected. Its tests in `tests/agent/test_bridge_model_aliases.py`
and `test_bridge_model_resolver.py` change where they asserted pass-through
(`test_resolve_inspect_model_prefixed`,
`test_no_resolver_no_fallback_resolves_via_get_model_with_provider`,
`test_other_model_does_not_get_the_eval_config` in
`test_bridge_generate_config_propagation.py`); each keeps its pass-through
expectation as an in-process variant that calls `resolve_bridge_model` with
`allow_client_model_names=True`.

**In-process `agent_bridge()`.** Shares the resolver and the dialect
functions; constructed with `allow_client_model_names=True`, so its routing is unchanged
and the LangChain `inspect/google/...` example keeps working. Its
`ModelEvent`s gain `requested_model` (`"inspect"` or the `inspect/` name),
on the Google path taken from the SDK URL rather than the body (see
Recording); in-process Google routing is unchanged, including the
pre-existing loss of a prefixed name described under Not this design.

**Stored formats and the viewer.** `ModelEvent` is a persisted public
model, so the field is a public-contract change and its consumers are
named here. Log readers: the field is optional with default `None`, so logs
written before the change read unchanged, and logs written after it read
on older `inspect_ai` versions too (neither `BaseEvent` nor `ModelEvent`
sets a pydantic `extra` policy, so the default `ignore` applies). Events
dataframe: one new column. Viewer: the JSON schema, OpenAPI spec and
generated TypeScript change; they are regenerated per
`design/type-generation-pipeline.md` and landed with a ts-mono pointer bump,
which the `check-schema-and-types` CI job enforces. `str | None` is not
required in TypeScript under the pipeline's Noneability rule, so existing
viewer code compiles unchanged. ACP event mapping
(`src/inspect_ai/agent/_acp/event_mapping.py`) reads the event fields it
names and is unaffected. inspect_scout consumes `ModelEvent` through
`inspect_ai`'s own models (`src/inspect_scout/_transcript/messages.py:322-324`)
and gains an optional attribute it can ignore. The `inspect_sandbox_tools`
binaries are untouched. Round-trip coverage is under Testing.

**Public API.** `sandbox_agent_bridge()` and `SandboxAgentBridge` keep
their signatures. `AgentBridge` gains `allow_client_model_names`, a
capability keyword beside `allow_remote_mcp` and `allow_remote_media`,
closed by default and set only by `agent_bridge()`. Code that constructs
`AgentBridge` directly gets the sandbox routing unless it passes the
keyword; outside `agent_bridge()` and `SandboxAgentBridge` there is no
such constructor in this repo, inspect_swe or inspect_evals (the
`PatchConfig` default at bridge.py:217-219 is used only while the patch is
disabled). `ModelResolver`
is unchanged. `ModelEvent` gains one optional field. The `requested_model()`
context manager and `resolve_bridge_model` are internal.

## Security

Untrusted input reaching the new code is the request's model name: a string
chosen by the sandboxed scaffold, delivered through the proxy in the JSON
body or, for Google, parsed from the URL path (proxy.py:2044-2047). Today it
reaches `get_model()` and so provider construction. Under the new default it
reaches only: an exact-match dictionary lookup, string concatenation for
provider qualification, the author's `model_resolver` (which already
receives it today), string comparison against the active model's names, the
warning message (escaped with `repr()`, truncated, deduped with a capped
set) and `ModelEvent.requested_model` (stored verbatim, as the rest of the
request body already is in the bridge's tracked messages). `get_model()`,
`model_roles()` and provider construction see it only on the in-process
bridge (`allow_client_model_names=True`), whose scaffold already holds the
host's credentials; no sandbox bridge option reopens that path. Nothing in the design executes, formats into a template, or opens a
file based on the name.

## Testing

Unit, `tests/agent/test_bridge_model_resolver.py` (existing file; the
matrix replaces the ad-hoc default-route tests):

- `test_routing_matrix`: `@pytest.mark.parametrize` over the rows of the
  matrix above, each row `(requested, provider, model, expected)` where
  `expected` is one of `active`, `alias`, `resolver`, `pin`, plus the
  expected `route` and `redirected`. Active model and role set with `init_active_model` /
  `init_model_roles` under the `_isolate_active_model` fixture pattern from
  `tests/agent/test_bridge_generate_config_propagation.py:35-53`. Pins and
  alias targets use `mockllm/...` specs so no provider key is needed.
- `test_in_process_routing_unchanged`: the same names with
  `allow_client_model_names=True` resolve as today (role, `get_model(name)`
  on a `mockllm/...` spec, active instance), covering steps 6 and 8.
- The existing regressions stay as named tests:
  `test_bare_name_matches_active_model_under_different_provider`,
  `test_fallback_model_wins_over_active_model_raw_name_match`, alias before
  resolver, resolver `None` defers.
- `test_pin_spec_naming_active_model_returns_active_instance`.
- `test_client_model_names_closed_by_default`: `AgentBridge` and
  `SandboxAgentBridge` default to `allow_client_model_names=False`;
  `agent_bridge()` sets it.

Warning, same file, with `caplog`:

- `test_redirect_warns_once_per_name`: two requests for the same name and
  one for another across two bridge instances produce exactly two warnings,
  each naming `model_aliases`; the pinned variant names the pin.
- `test_redirect_warning_cap`: past 64 names, one final warning and then
  silence.
- `test_active_and_alias_hits_do_not_warn`.

Model layer, `tests/model/test_model_event_requested_model.py` (new file:
no existing model test covers a context manager's cancellation and task
isolation; `test_model_event_timing.py` is about snapshot timing):

- `test_requested_model_stamps_event`: a `mockllm` generate inside the block
  yields an event with `requested_model` set; a nested block wins; no block
  means `requested_model is None`.
- `test_requested_model_reset_after_cancel`: a stub `ModelAPI` registered
  with `@modelapi` (as `tests/agent/test_bridge_provider_errors.py` does
  around line 254) whose `generate` sets an `anyio.Event` (started) and then
  awaits a second event that is never set. The test awaits started, cancels
  the enclosing `anyio.CancelScope`, then generates again with `mockllm`
  outside any block and asserts `requested_model is None`. No sleeps.
- `test_requested_model_reset_after_failure`: the same with a stub whose
  `generate` raises; the next event carries no stale name.
- `test_requested_model_isolated_between_tasks`: two tasks under
  `tg_collect`, each in its own block with a different name, each awaiting a
  shared "both started" `anyio.Event` before generating so they are in
  flight together; each task's event carries only its own name.

All four are plain `async def` tests, so the conftest hook runs them on both
backends; the PR runs them with `--runtrio` as well as the default.

Log and dataframe: a round-trip test in `tests/log/test_eval_log.py`
(existing file) writes an eval log whose `ModelEvent` has `requested_model`
set, reads it back with `read_eval_log()` and asserts the value, and reads
an existing fixture log written before the field to assert `None`. No test
under `tests/analysis/` names `ModelEventColumns`, so one small test is
added there asserting the `model_event_requested_model` column of the
events dataframe for a log with a bridged call. The `check-schema-and-types`
CI job fails until the OpenAPI spec and TypeScript types are regenerated.

End to end without Docker, `tests/agent/test_agent_bridge.py` (existing
file, `eval()` with `mockllm`): a solver builds `SandboxAgentBridge(...)` by
hand (pattern: `tests/agent/test_bridge_provider_errors.py:110-119`) and
calls `inspect_completions_api_request({"model": "gpt-4o-mini", ...}, None,
bridge)` directly. The dialect functions do not touch the sandbox, so this
covers dialect → resolver → `bridge_generate` → `ModelEvent`. Asserts: the
response came from `mockllm/model`, and the log's `ModelEvent` has
`model == "mockllm/model"` and `requested_model == "gpt-4o-mini"`; a second
test builds `AgentBridge(..., allow_client_model_names=True)`, as
`agent_bridge()` does, and sends `"model": "inspect/mockllm/other"`, served
by `mockllm/other` with `requested_model == "inspect/mockllm/other"`. Repeat
one redirected case for the Anthropic and Google dialect functions.
`test_bridge_filter_generated_event_records_requested_name`: the bridge has
a `GenerateFilter` that calls `model.generate()` itself and returns that
output; the resulting `ModelEvent` (the only one) carries
`requested_model`, which is the filter-path case the context block exists
to cover.
`test_google_sdk_request_records_full_requested_model`, next to
`test_google_bridge_returns_logprobs_to_client` (line 686), parametrized
over `inspect`, `inspect/mockllm/other`, `inspect/ollama/llama3:8b` and
`inspect/ollama/llama3:70b`: under `agent_bridge()` with a `mockllm` active
model, a `google.genai` client calls `generate_content(model=<name>, ...)`
with the dialect's generate stubbed so no provider is constructed; the
resulting `ModelEvent` has `requested_model` equal to the exact string
requested and `model` equal to the active model (today's routing,
unchanged). The two tagged names must record as distinct strings, which is
the case a first-colon pattern gets wrong. Invoking the dialect directly
with a supplied `model` cannot catch any of this, because the SDK path never
supplies one. Skipped with `pytest.importorskip("google.genai")` when the
SDK is not installed.

End to end with Docker, `tests/tools/test_tools_bridge.py` (existing
`@skip_if_no_docker` file whose slow tests PR CI runs):
`test_sandbox_bridge_redirects_unknown_model_to_eval_model`, modelled on
`test_sandbox_bridge_rejection_hides_the_call_from_the_agent` (552-600):
`post_completions` with `"model": "claude-haiku-4-5"` through the real proxy,
assert the reply and `requested_model` on the `ModelEvent`.

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

One PR, with a companion ts-mono PR for the regenerated types, in commits
an implementer can land in order:

1. **Field and hook.** `requested_model` on `ModelEvent`
   (`src/inspect_ai/event/_model.py`); the `requested_model()` context
   manager and the `_record_model_interaction` change in
   `src/inspect_ai/model/_model.py`; the four tests in
   `tests/model/test_model_event_requested_model.py` (stamping, reset after
   cancel, reset after failure, task isolation) and the log round-trip
   test. Independent of the bridge.
2. **Schema, types and dataframe.** Regenerate the OpenAPI spec and the
   viewer's TypeScript types and land them with the ts-mono pointer bump per
   `.agents/skills/land-ts-mono/SKILL.md`; add `model_event_requested_model`
   to `ModelEventColumns` with its test. This step is what makes the PR a
   coordinated ts-mono landing rather than a Python-only change.
3. **Resolver.** `BridgeModelRoute`, `BridgeModelResolution`,
   `resolve_bridge_model`, the wrapper and the warning in
   `src/inspect_ai/agent/_bridge/util.py`; `allow_client_model_names` on
   `AgentBridge` (`types.py`); `agent_bridge()` passes `True`
   (`bridge.py`). Rewrite `tests/agent/test_bridge_model_resolver.py` with
   the matrix and warning tests; adjust the three pass-through assertions
   named under Compatibility.
4. **Dialects.** `completions.py`, `responses_impl.py`,
   `anthropic_api_impl.py`, `google_api_impl.py` call `resolve_bridge_model`
   and pass `routing=` to `bridge_generate`; `bridge_generate` sets the
   requested name. Add the no-Docker end-to-end tests to
   `tests/agent/test_agent_bridge.py`.
5. **Sandbox surface and Docker test.** `sandbox_agent_bridge()`
   docstrings (`sandbox/bridge.py`); the Docker test in
   `tests/tools/test_tools_bridge.py`.
6. **Docs and CHANGELOG.** `docs/agent-bridge.qmd` Models section and the
   alias example; the `## Unreleased` entry.

Follow-up outside this repo (not blocking): inspect_swe's ACP Claude Code
and Codex agents pin `model=str(model)` when the agent's model may differ
from the eval's, matching its ACP Gemini agent.

## Open questions

None. The warning under a pin (kept) and the pass-through opt-in (dropped)
were decided on 2026-09-25; see The redirect warning and Alternatives.

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
- Showing `requested_model` in the viewer's `ModelEventView`. The field
  and its TypeScript type land with this design; rendering it next to the
  served model is a small ts-mono change on its own.
- Logging the resolution route on the event. `BridgeModelResolution.route`
  exists for the warning and the tests; a second field would record a
  distinction (alias versus redirect) the author already knows from their
  own configuration.
- The in-process bridge exposing `model=`, `model_aliases` or
  `model_resolver`.
- Google routing loses a prefixed name on both paths: `_google_api_model_name`
  (bridge.py:578-581) and the proxy's `_extract_model_from_google_path`
  (proxy.py:2032) stop at the first slash, and the in-process patch forwards
  no `model` at all, so `inspect/mockllm/other` through the Google dialect
  is served by the active model rather than the named spec. Fixing it is a
  routing change and, for the sandbox, a proxy binary rebuild, separate from
  recording the requested name accurately.
