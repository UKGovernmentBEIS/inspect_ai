# Sandbox identity at the sandbox-operation boundary

## Overview

Inside a `sandbox_identity(user, ...)` scope, the sample's sandbox proxy
fills in the scope's user for every `exec()`, `read_file()` and
`write_file()` call on the scope's sandbox that names no user. A caller that
names a user keeps it. Custom tools, scaffold code and agent install steps that
run inside a scope therefore act as the scope's user with no change of their
own, as the built-in tools already do.

Inspect's own operations, which use an omitted user to mean "the sandbox's
default user", mark themselves with a private context manager,
`framework_sandbox_operation()`. Inside the marked block the proxy leaves an
omitted user alone. The mark goes on the few low-level helpers that these
operations already route through: the privileged-command helpers, the
framework-directory helper, the sandbox-tools transport and launcher, the
sandbox-file detector, the checkpoint copier, and in-loop scoring. A provider
whose `read_file()` or `write_file()` cannot take a user raises inside a scope
rather than reading or writing as the default user. The scope and the marker
stay private to inspect_ai.

## Why

`sandbox_identity()` exists so that a framework such as inspect_swarm can run
each agent of a shared sandbox as its own Linux user without rebuilding that
agent's tools. Today the scope reaches only the places that resolve a user
explicitly: the built-in model-facing tools, `exec_remote()` and the sandbox
tools' launches. The three sandbox operations themselves ignore it.
[sandbox-trust-model.md](sandbox-trust-model.md#sandbox-identity-scopes)
records the result as a known gap. Inside a scope, a custom tool that calls
`sandbox().exec()`, `read_file()` or `write_file()` without a user runs as the
sandbox's default user, which is root in most images. A model given such a
tool inside an isolated member can therefore read and write every other
member's files.

The same gap affects scaffold code that is not a tool. An inspect_swe agent
running as a member writes its configuration with `write_file()` under the
`$HOME` that `exec(["sh", "-c", "echo $HOME"])` reports. Both calls name no
user, so the file lands in root's home. The agent's CLI is then launched
through `exec_remote()`, which does take the scope's user, so it looks in the
member's home and does not find that configuration (`inspect_swe:
src/inspect_swe/_codex_cli/codex_cli.py:675`,
`_gemini_cli/gemini_cli.py:161-170`, `_opencode/opencode.py:176-209`).

The inspect_swarm isolation design rejected applying the identity inside
`exec()` because Inspect's own commands and scorers also pass no user, to mean
the default user, and `exec()` cannot tell them apart from a custom tool
([swarm-sandbox-isolation.md, Alternatives](https://github.com/meridianlabs-ai/inspect_swarm/blob/main/design/swarm-sandbox-isolation.md#alternatives-considered)).
This design makes them distinguishable. Framework code declares its operations
as framework operations, so every unmarked call can take the scope's user.

## Goals and non-goals

Goals:

- Inside a scope, `exec()`, `read_file()` and `write_file()` on the scope's
  sandbox take the scope's user when the caller passes none. Outside a scope,
  and on any other sandbox, nothing changes.
- Inspect's own sandbox operations keep their current identity inside a
  scope. These include tool injection and its transport, the root-access and
  default-identity probes, sandbox services, checkpoint snapshots and restore,
  and sandbox-file detection. Each is marked where it runs, and a test lists
  the marked modules.
- A provider that cannot perform a file operation as a user fails loudly inside
  a scope instead of quietly using the default user.
- The trust model's "Sandbox identity scopes" and "File-operation users"
  sections describe the new contract.

Non-goals:

- **The scope's `cwd` at the boundary.** Only the user is applied. A
  `read_file()` or `write_file()` call has no `cwd` parameter, so applying
  `cwd` to `exec()` alone would make the same relative path name different
  files in `exec()` and `read_file()`.
- **Strictness at the boundary.** An explicit user is kept, as in
  `exec_remote()`. A caller that names a user, such as `user="root"`, has made
  a choice in code. The model-facing built-in tools stay strict as they are
  today.
- **The provider object behind the proxy.** `sandbox().as_type(Provider)`
  returns the unwrapped provider (`util/_sandbox/events.py:238-245`). Calls on
  that object skip the default, as they already skip transcript events and
  output limits.
- **`connection()`**, which gives host-side login details to a human and runs
  nothing in the sandbox.
- **Making the scope, its helpers or the marker public.** These stay internal,
  as Ransom decided on 2026-10-30. See [Public surface](#public-surface).
- User switching by a tools server that does not run as root, and
  `human_cli()` inside a scope. Both are listed under
  [Not this design](#not-this-design).

## Current behaviour

Paths are relative to `src/inspect_ai/` unless they start with `tests/`,
`design/` or another repository's name.

### The scope and its resolvers

`sandbox_identity(user, cwd=, sandbox=)` (`util/_sandbox/identity.py:26-98`)
stores a `SandboxIdentityScope(user, cwd, sandbox, environment)` in the
`_sandbox_identity` ContextVar (`:233-235`). A ContextVar is copied into each
task when the task starts, so tasks started inside the block inherit the scope
(`tests/util/sandbox/test_sandbox_identity.py::test_tasks_started_inside_inherit_the_scope`).
Nested scopes raise. The block also makes the scope's sandbox the default
sandbox.

`sandbox_identity_user(env, user, *, strict)` (`identity.py:101-131`) returns
`user` unchanged outside a scope for `env`. Inside one it turns `None` into the
scope's user. An explicit different user is kept when `strict=False` and raises
`SandboxIdentityError` when `strict=True`. `_same_sandbox()` (`:220-230`)
unwraps `SandboxEnvironmentProxy` on both sides, so the sample's proxy and the
provider behind it count as one sandbox.

Current callers of the resolver:

| Caller | Mode | Where |
|---|---|---|
| `bash()`, `python()`, `grep()`, `list_files()`, `read_file()` tool | strict, plus scope `cwd` | `tool/_tools/_execute.py:110-114`, `:173-178`, `_grep.py:72-76`, `_list_files.py:44-48`, `_read_file.py:58-62` |
| `bash_session()`, `text_editor()` | strict | `tool/_tools/_bash_session.py:251`, `_text_editor.py:134` |
| Sandbox-tools request `user` param (`exec_remote()`, MCP servers, bridge CLI) | lenient | `util/_sandbox/_cli.py:36-53` |
| `exec_remote()` working directory | scope `cwd` when unset | `util/_sandbox/exec_remote.py:356` |
| `computer()`, `web_browser()`, `skill()` | refuse in a scope | `tool/_tools/_computer/_common.py:357`, `_web_browser/_back_compat.py:102`, `_sandbox_tools_utils/_legacy_helpers.py:40`, `_skill/tool.py:60-61` |

`SandboxEnvironment.exec()`, `read_file()` and `write_file()` do not consult the
scope. `test_exec_is_unchanged_inside_a_scope`
(`tests/util/sandbox/test_sandbox_identity.py:194-198`) pins this:
`sandbox().exec(["true"])` inside `sandbox_identity("w-1")` reaches the
provider with `user=None`. That test passes at the base of this design.

### Every sample sandbox is a proxy

`init_sandbox_environments_sample()` wraps each provider in a
`SandboxEnvironmentProxy` before it publishes the sample's environments
(`util/_sandbox/context.py:288`). `sandbox()`, `sandbox_with()` and injection
all return these proxies. The proxy is already the one host-side place where
every sample-level `exec()`, `read_file()` and `write_file()` call passes
through, unless the caller used `as_type()`. Its methods:

- `exec()` (`util/_sandbox/events.py:41-117`) forwards `user` and records it in
  the `SandboxEvent` options when it is set (`:89`).
- `write_file()` and `read_file()` (`:139-212`) build their keyword arguments
  with `_file_user_params()` (`:220-234`). With no user they forward none. With
  a user, they forward it if the provider's method declares a keyword-capable
  `user` parameter (`environment.py:360-372`), and otherwise raise
  `SandboxUserUnsupportedError`. The resolved parameters are recorded as the
  event's options.
- `no_events()` (`:253-265`, ContextVar at `:279-281`) and `without_sandbox_events()` (`:284-295`)
  suppress events through a ContextVar for the current task and the tasks it
  starts. The marker proposed here follows the same pattern.

Provider internals call their own methods on the unwrapped object. Docker's
`write_file()` calls `self.exec(..., user=user)` (`util/_sandbox/docker/docker.py:482-511`).
Those calls never reach the proxy, so they are unaffected.

### Inspect's own calls that pass no user

The table below covers every call in `src/inspect_ai` that reaches the proxy's
`exec()`, `read_file()` or `write_file()` and can pass `user=None`. It lists
where the call can run and what `None` means there. Calls that always pass an
explicit user, such as the checkpoint commands' `user="root"`, are unaffected
and not listed. `util/_sandbox/self_check.py` runs provider conformance tests
outside any sample and is also omitted.

| Call site | Can run inside a scope? | `None` means |
|---|---|---|
| `privileged_exec()`, `privileged_shell()`, `image_path_lookup()` (`util/_sandbox/_privileged.py:127-254`). Callers include the default-identity probe (`tool/_sandbox_tools_utils/sandbox.py:424-441`), OS detection (`util/_sandbox/recon.py:60`), sandbox services (`util/_sandbox/service.py:849-856`, `:958`), checkpoint restore's `id -u` (`util/_checkpoint/_restore_scope.py:785`), sandbox-file detection (`util/_sandbox/context.py:132`, `:169`) and sample setup (`context.py:384`, `:404`) | Yes. Injection is lazy and runs at a tool's first call, inside the member. Services start inside the bridge. Checkpoints are taken by `react()` | The docstring says "`None` is the sandbox default user. Required so the authority a call carries is explicit at the call site" (`_privileged.py:150-152`) |
| `_run_verified()` (`util/_sandbox/_framework_directory.py:410-454`), behind `ensure_`/`verify_`/`stat_`/`exec_in_`/`write_file_in_framework_directory()` | Yes (injection, services, checkpoints) | The tools user or service user. `None` is the default user of a sandbox without usable root |
| `SandboxJSONRPCTransport._sandbox_exec()` (`util/_sandbox/_json_rpc_transport.py:104-122`) | Yes. Every `bash_session()`, `text_editor()`, `exec_remote()` and MCP request goes through it | The tools user (`exec_remote.py:319-324`: "When root isn't available, this is None (sandbox default user)"). The member's identity travels separately as the request's `user` param |
| `start-server` launch (`tool/_sandbox_tools_utils/sandbox.py:299`) | Yes (lazy injection) | The tools user |
| `_is_file_readable()` fallback `read_file()` (`util/_sandbox/context.py:142`) | Yes (`sandbox_with()` detection, used by `computer()` and `web_browser()` before they refuse) | The default user |
| Checkpoint chunk read (`util/_checkpoint/_copy.py:120`, `:139`) | Yes (`react()` checkpoints inside the member) | `{"user": "root"}` when the provider supports file users, otherwise the default user |
| Sample file copy and setup script (`util/_sandbox/context.py:368`, `:379`, `:393`) | No. They run in `init_sandbox_environments_sample()` before any solver can enter a scope (`context.py:297-302`) | The default user |
| Scorers called by `score()` (`scorer/_score.py:65`), reached from `react(attempts=...)` (`agent/_react.py:347`), `basic_agent()` (`solver/_basic_agent.py:234`) and the human agent's `task score` | Yes, for in-loop scoring inside a member. Final scoring runs after the solver, outside every scope | Scorers are task code written against the default user |
| `human_cli()` install and session-log reads (`agent/_human/install.py:238`, `agent/_human/commands/submit.py:33-48`) | Only if a scope wraps a human agent, which no caller does | The human's configured user |
| `skill()` writes (`tool/_tools/_skill/install.py:246`, `:287`), `computer()` exec (`_computer/_common.py:194`), `web_browser()` legacy exec (`_web_browser/_back_compat.py:40`, `:59`) | No. Each refuses inside a scope for its sandbox before running anything | — |

The model-facing exec tools already pass the strictly resolved user, so the
boundary default leaves them unchanged.

### Providers and `read_file`/`write_file` users

The `user` parameter of `read_file()` and `write_file()` is recent. In
inspect_ai, Docker (`docker.py:467-470`, `:527-540`) and `local`
(`util/_sandbox/local.py:133-170`, current user only) declare it. No
third-party provider checked out next to this repository declares it:
`inspect_k8s_sandbox` (`src/k8s_sandbox/_sandbox_environment.py:313-328`),
`inspect_ec2_sandbox`, `inspect_proxmox_sandbox`, `inspect_vagrant_sandbox`,
inspect_sandboxes' Daytona, E2B and Modal providers, and `inspect-podman`. All
of them do support `exec(user=...)`; for example, Kubernetes accepts it at
`_sandbox_environment.py:280`. `inspect-policy-sandbox` accepts `**kwargs`,
which `_supports_file_user()` deliberately does not treat as support
(`environment.py:363-366`).

### Who sets a scope, and who runs inside one

No package sets a scope yet. inspect_swarm's users isolation, which will set one
for each member, is designed but not built. A grep for `sandbox_identity`
across the satellite checkouts finds only its design document. Inside a
member, the code that calls the three operations with no user is:

- The custom tools and solvers an eval author gives the member.
- inspect_swe's scaffolds, in two groups. **Per-agent configuration** writes
  under the agent's `$HOME` (`inspect_swe: _codex_cli/codex_cli.py:560`,
  `:675`; `_gemini_cli/gemini_cli.py:161-170`; `_opencode/opencode.py:176-209`;
  `_kimi_code/kimi_code.py:266-290`; `_antigravity/antigravity.py:353-437`;
  `acp/_agents/*/`). **Shared installs** write binaries into the fixed
  directory `SANDBOX_INSTALL_DIR = /var/tmp/.5c95f967ca830048`
  (`_util/sandbox.py:14`) and probe or `chmod` them as root
  (`_util/agentbinary.py:367-386`, `_util/agentwheel.py:107`, `:295`,
  `_util/node.py:98`, `:240`, `_util/ripgrep.py:46`,
  `_mini_swe_agent/setup.py:54`). The install is shared: a later agent skips
  the write when the root probe `test -x` succeeds (`agentbinary.py:364-370`).
  inspect_swe also runs an MCP readiness probe with `exec()` and no user
  (`_util/mcp_ready.py:234`). The swarm design wants that probe to run as the
  member.

## Design

### Resolution at the proxy

`SandboxEnvironmentProxy.exec()`, `write_file()` and `read_file()` resolve
`user` before they do anything else:

```python
user = sandbox_operation_user(self, user)
```

The new function in `util/_sandbox/identity.py` is:

```python
def sandbox_operation_user(env: SandboxEnvironment, user: str | None) -> str | None:
    """The user a sandbox operation on `env` runs as.

    Inside a `sandbox_identity()` scope for `env`, an omitted `user` becomes the
    scope's user, unless the call is part of a `framework_sandbox_operation()`.
    An explicit `user` is always kept.
    """
    if user is not None or in_framework_sandbox_operation():
        return user
    return sandbox_identity_user(env, None, strict=False)
```

The proxy imports it inside each method, as it already imports `transcript`,
because `identity.py` imports `events.py`. The resolved user then follows the
existing path. `exec()` forwards it and records it in the event options.
`read_file()` and `write_file()` pass it to `_file_user_params()`, which
forwards it or raises (see
[Providers that cannot take a file user](#providers-that-cannot-take-a-file-user)).
The event options therefore show the user each operation actually ran as.

Only the proxy changes. `SandboxEnvironment`'s abstract methods, provider
implementations and `as_type()` are untouched.

### The framework-operation marker

A new leaf module, `util/_sandbox/_framework_operation.py`, imports nothing but
`contextlib` and `contextvars`, so every helper below can import it without an
import cycle:

```python
_framework_operation: ContextVar[bool] = ContextVar(
    "sandbox_framework_operation", default=False
)


@contextmanager
def framework_sandbox_operation() -> Iterator[None]:
    """Mark sandbox operations in the block as Inspect's own.

    Inside the block, `exec()`, `read_file()` and `write_file()` calls that name
    no user run as the sandbox's default user even inside a `sandbox_identity()`
    scope. Only the boundary default is affected: the scope, injection
    targeting, the sandbox-tools request user and the model-facing tools' strict
    resolution are unchanged.

    Wrap only calls whose `user=None` means the sandbox's default user, and
    never code that runs model-chosen work.
    """
    token = _framework_operation.set(True)
    try:
        yield
    finally:
        _framework_operation.reset(token)


def in_framework_sandbox_operation() -> bool:
    return _framework_operation.get()
```

The marker affects only the boundary default. A model-facing tool called inside
a marked block still passes its strictly resolved user, and a `bash_session()`
or `text_editor()` request still carries the scope's user as its run-as
parameter. A misplaced marker can therefore affect only unmarked calls that
pass no user, the custom-tool case, and never the built-in tools.

### Where the marker goes

The marker wraps the call to the proxy, not a whole operation, so it covers
nothing beyond the operation it marks:

| Site | Change |
|---|---|
| `privileged_exec()`, `privileged_shell()`, `image_path_lookup()` (`util/_sandbox/_privileged.py`) | Wrap the `sandbox.exec(...)` call. These helpers already state that `user` is required and that `None` is the default user, so the marker makes that true inside a scope. This one change covers the default-identity probe, OS detection, services, checkpoint and restore commands, file detection, sample setup, the human agent's listing and `skill()`'s digest. |
| `_run_verified()` (`util/_sandbox/_framework_directory.py`) | Wrap both `sandbox.exec(...)` branches. This covers every framework-directory helper: tools-tree install, verification and `stat`, service queues, checkpoint scratch. |
| `SandboxJSONRPCTransport._sandbox_exec()` (`util/_sandbox/_json_rpc_transport.py`) | Wrap the `self.sandbox.exec(...)` call. The transport runs the tools CLI as the tools user, and the member's identity travels as the request's `user` param. Without the marker, a sandbox without usable root would launch the CLI as the member, who cannot enter the default user's 0700 tools tree. |
| `start-server` launch (`tool/_sandbox_tools_utils/sandbox.py:299`) | Wrap the call. The server runs as the tools user. |
| `_is_file_readable()` fallback (`util/_sandbox/context.py:142`) | Wrap the `read_file()` call. The `test -r` above it already goes through `privileged_exec()`. |
| Checkpoint chunk read (`util/_checkpoint/_copy.py:139`) | Wrap the `read_file()` call. On a provider without file users, the chunk is then still read as the default user, as today. Without the marker, the read would raise. |
| `score()` (`scorer/_score.py:65`) | Wrap `await scorer(state, target)`. See [Context inheritance](#context-inheritance). |

Nothing else in inspect_ai needs the marker. The sample's file copy and setup
script run before any scope can exist. `skill()`, `computer()` and
`web_browser()` refuse inside a scope. The human agent is outside this design.

A tripwire test, written like `test_local_path_is_the_only_file_uri_decoder`,
asserts that `framework_sandbox_operation` appears only in the modules listed
above. Adding a new marked site then requires a deliberate change to the
allowlist, and a reviewer sees it.

### Default identity and root probes

The probes stay correct because of the `_privileged.py` change:

- The **root-access probe** passes `user="root"` (`sandbox.py:366-386`), so it
  is unaffected either way.
- The **default-identity probe** (`_detect_default_user`, `sandbox.py:424-441`)
  calls `privileged_shell(..., user=None)`. With the marker it reports the
  sandbox's default identity even when injection first happens inside a
  member's scope. Without the marker, the first member to trigger injection
  would be recorded as `_tools_default_user` for the sandbox object, and every
  later unscoped tools request would switch to that member
  (`util/_sandbox/_cli.py:50-52`). The swarm design names this hazard.
- **OS detection** (`recon.py:60`) and checkpoint restore's `id -u`
  (`_restore_scope.py:785`) go through the same helpers.

### Context inheritance

Two ContextVars now matter, and tasks inherit both.

**The scope, into framework background work.** Tasks started inside a scope
inherit it. Inspect starts several such tasks: sandbox-service polling loops
for the bridge, `exec_remote()` process polling, the MCP server transports, and
checkpoints that `react()` takes. Every sandbox operation these tasks perform
goes through a marked helper: `privileged_exec()`, `_run_verified()`, the
JSON-RPC transport, or the checkpoint copier. Each therefore keeps its current
identity, whatever task it runs in. The survey above is the evidence for this,
and the tripwire test keeps the set closed.

**The marker, into tasks started inside a marked block.** Each marked block
wraps one awaited call to the proxy. The proxy calls the provider, and a
provider may start its own tasks, but those tasks act on the unwrapped provider
and never reach the proxy again. In practice, then, the marker does not spread
beyond the single call it wraps.

**In-loop scoring is the one marked block that runs task code.** A member's
`react(attempts=...)` calls `score()` inside the member's scope. Without the
marker, a scorer that calls `sandbox().exec()` would run as the member there
and as root when the same scorer runs at the end of the sample. The in-loop
verdict could then differ from the final score, for example when the scorer
reads a root-only test file. Wrapping the scorer call keeps every scorer on the
identity it was written for, which matches what the swarm design specifies for
scorers. A scorer that calls a built-in tool still runs that tool as the
member, as it does today. Tasks the scorer starts inherit the marker. The
scorer is trusted task code, and the marker gives it no authority it would not
have in final scoring. This is Open question 1.

### Providers that cannot take a file user

Inside a scope, `read_file()` or `write_file()` with no user now resolves to the
scope's user. `_file_user_params()` then finds that the provider declares no
`user` parameter and raises `SandboxUserUnsupportedError`. The message names
the scope, because the caller passed no user and would not otherwise know where
one came from:

```
KubernetesSandboxEnvironment.read_file does not support a user, so it cannot
run as 'swarm-w-1' inside the sandbox identity scope for sandbox 'default'.
Update the sandbox provider to support file users, or read the file with exec().
```

The alternative, falling back to a call with no user, would perform the
operation as the default user (root in most images) on a path the member
chose. The trust model already rejects that fallback for the human agent's
session logs, because "falling back to a userless read would let a less
privileged human redirect a log path to a file readable only by the provider's
more privileged reader". The same reasoning applies here, and AGENTS.md's
"Invalid state" rule forbids the silent coercion.

On those providers, then, a custom tool or scaffold that reads or writes files
inside a scope fails at its first call. Built-in tools are unaffected, because
none of them call `read_file()` or `write_file()` inside a scope. Inspect's own
file operations are marked. Outside a scope, nothing changes on any provider.

### Public surface

Ransom decided on 2026-10-30 that the scope and its helpers stay internal.
`sandbox_identity()` is set only by inspect_swarm and read only by inspect_ai's
tools and by inspect_swe, and both of those already import inspect_ai
internals. This design removes the reason the review gave for exporting them:
with the default at the boundary, a custom tool no longer needs
`sandbox_identity_user()` to run as the member. The marker stays private for
the same reason. Its callers are inspect_ai and, through the companion change
below, inspect_swe. The public docstrings of `SandboxEnvironment.exec()`,
`read_file()` and `write_file()` do not mention the private scope. The
`sandbox_identity()` docstring and the trust model do.

### Trust model update

The implementation PR rewrites
[sandbox-trust-model.md](sandbox-trust-model.md#sandbox-identity-scopes) as
follows:

- **Sandbox identity scopes.** A new **Sandbox operations** bullet replaces the
  "Unchanged" bullet. Inside a scope, `SandboxEnvironment.exec()`,
  `read_file()` and `write_file()` on the scope's sandbox run as the scope's
  user when given none, and keep an explicit user. Inspect's own operations,
  listed with their marker sites, keep the default user. In-loop scoring keeps
  the default user. Calls through `as_type()` bypass the default.
- **Custom tools.** The paragraph that calls custom tools "a known gap" is
  replaced. Custom tools inherit the scope's user with no change of their own.
  A custom tool that passes an explicit user, such as `user="root"`, keeps it.
  That is a grant made in code, as with `bash(user="root")` outside a scope.
- **Framework-operation contract.** A new paragraph covers the marker. Code
  that acts with the framework's authority and means "the default user" by
  `user=None` must go through a marked helper. The marker is never placed
  around model-chosen work. The tripwire test lists the marked modules.
- **File-operation users.** The sentence "Root-default evals that confine agent
  tools to another user must supply that user for file operations performed on
  the agent's behalf" gains "outside a sandbox identity scope; inside one the
  scope supplies it". The section also states that providers without file
  users raise inside a scope.

The `sandbox_identity()` docstring's sentence "`SandboxEnvironment.exec()`,
`read_file()` and `write_file()` themselves are unchanged ..." is replaced in
the same way.

## Alternatives considered

**Leave the boundary alone. Custom tools opt in through
`sandbox_identity_user(..., strict=True)` and a public export.** This is the
current state plus an export. It needs no audit and changes no framework code.
But every custom tool and scaffold author must know about the scope, and code
that does not know fails open, as root, which is the gap this task is about.
The swarm can only count such calls after the fact. Rejected: the safe
behaviour should not depend on each author opting in.

**Suspend the whole scope inside framework operations** (set
`_sandbox_identity` to `None`). This needs one ContextVar and no new resolver.
It also turns off injection targeting, the tools request's run-as user and the
strict checks for everything in the block, so a misplaced block would run
built-in tools as root. Rejected in favour of a marker that affects only the
boundary default.

**A sentinel user value** (`user=DEFAULT_USER`) at framework call sites. Each
call would state its identity in its arguments. But `user` is `str | None` on
a public abstract method. Calls made on an unwrapped provider would pass the
sentinel to every third-party provider, and each provider would need to
understand it. Rejected.

**Framework code calls the unwrapped provider** (`env._sandbox.exec()` or
`as_type()`). This bypasses the default with no new mechanism. It also drops
the transcript events and output limits that injection and services rely on,
and it scatters provider unwrapping through framework code. Rejected.

**Apply the default inside each provider**, for example through a
`SandboxEnvironment.__init_subclass__` wrapper. This would cover `as_type()`
too, but it rewrites third-party classes at import time and reaches provider
internals such as Docker's `write_file()` calling `self.exec()`. Rejected; the
proxy is already the sample-level boundary.

**Strict at the boundary** (unmarked calls with another explicit user raise
inside a scope). This would also stop a custom tool that passes
`user="root"`. But scaffold code legitimately passes `user="root"` for its own
installs (`inspect_swe: _util/agentbinary.py:367-386`), and an eval author who
writes `user="root"` has made a grant in code. Rejected for consistency with
`exec_remote()`'s lenient resolution.

**Fall back to the default user on providers without file users.** Rejected
under [Providers that cannot take a file user](#providers-that-cannot-take-a-file-user).

## Compatibility and migration

Outside a scope, nothing changes. The proxy resolves `None` to `None`, and the
marker is a ContextVar that no code reads outside the proxy. Calls on sandboxes
other than the scope's are unchanged too. Since no released package sets a
scope, no existing eval changes behaviour.

Inside a scope:

- **Custom tools, solvers and scaffold code** that pass no user now run as the
  scope's user. This is the intended change.
- **Providers without file users** raise on unmarked `read_file()` and
  `write_file()` calls that pass no user. `exec()` is unaffected, because every
  provider surveyed accepts `exec(user=...)`.
- **Eval logs.** A `SandboxEvent` for a defaulted call now records `user` in
  its options, where it was absent before. `options` is a free-form dict, and
  existing logs read back unchanged. No schema or generated TypeScript type
  changes.
- **inspect_swe** (companion change, required before any scope is set for its
  agents). Its per-agent configuration writes and its MCP readiness probe need
  no change: they start following the member, which fixes the `$HOME` mismatch
  described under [Why](#why). Its shared installs must keep their current
  identity. Otherwise the first member writes the binary into
  `/var/tmp/.5c95f967ca830048` as itself, and later members skip the write and
  execute that member-owned file (see [Security](#security)).
  `ensure_agent_binary_installed()`, `ensure_agent_wheel_installed()`, the
  node, npm-bundle and ripgrep installers, and mini-swe-agent's setup each wrap
  their install body in `framework_sandbox_operation()`. The marker keeps the
  default-user meaning of `None` on every provider. An explicit `user="root"`
  would instead raise on providers without file users.
- **inspect_swarm's design.** Its "What it does not touch", "Custom tools",
  "In-loop scoring", "The harness reads everything" and `foreign_execs` passages
  and its third alternative describe today's boundary. They are updated in that
  repository: custom tools now inherit the member, `foreign_execs` keeps
  counting execs that ran as another user, and harness code inside a member
  scope uses an explicit user or the marker.

## Security

**What reaches the new code.** The user applied at the boundary comes from the
scope, which is host-side configuration chosen by the framework that set it.
The model never supplies it. The commands, paths and file contents passed to
the three operations may be model-chosen, as they are today. The change runs
them with less authority (the member's user instead of the default user, often
root), never with more.

**The marker grants the default user.** A marker placed around model-chosen
work would run that work as root. The design limits this in three ways. The
marker wraps single calls in helpers whose arguments Inspect fixes. It affects
only calls that pass no user, never the model-facing tools' resolved users. And
the tripwire test makes every new site a reviewed allowlist change. The one
block that runs task code, in-loop scoring, runs code the eval author already
trusts as root at final scoring.

**Shared installs (inspect_swe).** Without the companion change, the default
would let the first member own a binary that every later member executes. That
member could replace the binary and so run code as each peer. This is why the
companion change is required before inspect_swe agents run in a scope, and why
it uses the marker rather than letting installs follow the member.

**Providers without file users fail closed.** See
[Providers that cannot take a file user](#providers-that-cannot-take-a-file-user).

**What remains unprotected.** `as_type()` returns an unwrapped provider whose
calls skip the default. That is a provider-specific escape that a custom tool
has to request deliberately. The model cannot choose it. The scope's guarantees
are still bounded by the member/root boundary that
[sandbox-trust-model.md](sandbox-trust-model.md) and the swarm design describe.
This design does not stop a member that obtains root.

## Testing

All tests are host-side with recording fakes unless marked Docker. They follow
the async conventions in AGENTS.md, so they run under asyncio and, with
`--runtrio`, under trio.

`tests/util/sandbox/test_sandbox_identity.py`. The existing fakes are wrapped in
`SandboxEnvironmentProxy`, because the default lives in the proxy:

- Replace `test_exec_is_unchanged_inside_a_scope` with
  `test_operations_take_the_scope_user`: `exec()`, `read_file()` and
  `write_file()` with no user inside a scope reach the provider with the
  scope's user, and the `SandboxEvent` options record it.
- `test_explicit_user_is_kept_in_a_scope`: `exec(user="root")` and
  `read_file(user="root")` reach the provider unchanged.
- `test_other_sandbox_and_outside_scope_unchanged`: these calls reach the
  provider with `user=None`.
- `test_as_type_view_skips_the_default`: calls on the unwrapped provider keep
  `None`, which pins the documented limit.
- `test_framework_operation_keeps_the_default_user`: inside
  `framework_sandbox_operation()` an omitted user stays `None`; after the block
  it resolves again; a task started inside the block inherits the marker, and a
  task started after it does not.
- `test_provider_without_file_user_raises_in_a_scope`: a fake whose
  `read_file()` and `write_file()` declare no `user` raises
  `SandboxUserUnsupportedError` naming the scope, and the same fake works
  outside the scope and inside a marked block.
- `test_framework_operation_marker_sites`: the tripwire. It walks `src/` and
  asserts that `framework_sandbox_operation` appears only in the allowlisted
  modules.

`tests/tools/sandbox_tools_utils/test_sandbox_tools.py`:

- `test_injection_inside_a_scope_records_the_default_identity`: lazy injection
  triggered inside `sandbox_identity("w-1")` on a fake whose `id` output differs
  per user. The test asserts that `_tools_default_user` is the default
  identity, that the transport and `start-server` execs carry the tools user,
  and that framework-directory checks pass `None` or `"root"`, never `"w-1"`.
- `test_rootless_transport_runs_as_the_default_user_in_a_scope`: with root
  unusable, the transport exec for an `exec_remote()` call inside a scope
  passes `user=None`, while the request's `user` param is the scope's user.

Other files:

- `tests/util/sandbox/test_exec_remote.py`: an `exec_remote()` call inside a
  scope is unchanged. Its launch transport exec passes the tools user.
- `tests/checkpoint/test_snapshot_strategy.py` (which already calls
  `copy_out()`): inside a scope, a chunk read passes no user to a provider
  that lacks file users, and passes `"root"` to one that has them.
- `tests/agent/test_agent_react.py` (which already runs `react(attempts=...)`):
  inside a scope, a scorer that calls `sandbox().exec()` reaches the provider
  with `user=None` through `score()`, while a custom tool called by the agent in
  the same scope reaches it with the scope's user.
- Docker slow test beside `test_two_scoped_users_share_one_bash_session` in
  `tests/tools/sandbox_tools_utils/test_sandbox_tools.py`: two users with 0700
  homes. Inside each user's scope, a custom tool's `sandbox().exec(["id",
  "-un"])` reports that user, its `write_file()` into its own home succeeds,
  and its `read_file()` of the other user's home file raises
  `PermissionError`. After both scopes, injection state shows the default
  identity. PR CI runs the slow tests under `tests/tools/`
  (`.github/workflows/build.yml:612`).

No test needs a model provider or network. Apart from the Docker test, all of
them use fakes and run in the ordinary test job.

## Implementation plan

1. **Marker and marked sites (no behaviour change).** Add
   `util/_sandbox/_framework_operation.py`. Wrap the sites in
   [Where the marker goes](#where-the-marker-goes): `_privileged.py`,
   `_framework_directory.py`, `_json_rpc_transport.py`,
   `tool/_sandbox_tools_utils/sandbox.py`, `util/_sandbox/context.py`,
   `util/_checkpoint/_copy.py`, `scorer/_score.py`. Add the tripwire and marker
   tests. Nothing reads the marker yet, so behaviour is unchanged.
2. **The boundary default.** Add `sandbox_operation_user()` to
   `util/_sandbox/identity.py`. Call it from the three
   `SandboxEnvironmentProxy` methods in `util/_sandbox/events.py`, and extend
   `_file_user_params()`'s error for a scope-supplied user. Update the
   `sandbox_identity()` docstring and `design/sandbox-trust-model.md` as in
   [Trust model update](#trust-model-update). Replace
   `test_exec_is_unchanged_inside_a_scope` and add the remaining tests,
   including the Docker test. Steps 1 and 2 may ship as one inspect_ai PR, as
   two commits.
3. **inspect_swe companion.** Wrap the shared install bodies listed under
   [Compatibility](#compatibility-and-migration) in
   `framework_sandbox_operation()`, with a test that an install inside a scope
   writes with `user=None`. This needs step 1, and it must land before
   inspect_swarm sets a scope around inspect_swe agents.
4. **inspect_swarm design.** Update the passages listed under
   [Compatibility](#compatibility-and-migration) in its repository.

## Open questions

1. **Should in-loop scoring keep the sandbox's default user inside a scope?**
   Recommendation: yes. `score()` wraps the scorer call in the marker, so a
   scorer gives the same verdict in-loop and at the end of the sample. This
   matches what the swarm design already specifies for scorers. The
   alternative is to let in-loop scorers run as the member. That would also
   stop a member from learning, through a scorer's report, what it cannot read
   itself, but the same scorer could then return a different verdict in-loop
   than at the end.
   Confidence: high.

## Not this design

- **`human_cli()` inside a scope.** Its `.bashrc` install and session-log reads
  take the human's configured user, while `connection()` logs the human in
  with no scope. Nothing wraps a human agent in a scope today. If something
  does, `human_cli()` should refuse the scope as `computer()` does.
- **User switching without usable root.** A tools server that runs as the
  default user cannot switch to the scope's user, so `bash_session()` and
  `text_editor()` cannot honour a scope there. This predates the scope and is
  unchanged here.
- **Scorers and `exec_remote()`.** Inside a marked in-loop scoring block,
  `exec_remote()` still takes the scope's user (lenient resolution in
  `exec_remote.py` and `_cli.py`), while the scorer's `exec()` keeps the
  default user. This matches the current split, and no scorer is known to call
  `exec_remote()`.
- **File users in third-party providers.** Kubernetes and the other surveyed
  providers need `user` on `read_file()` and `write_file()` before custom file
  operations work inside a scope there. That work belongs in each provider's
  repository.
- **The scope's `cwd` for raw `exec()`**, which raises the relative-path
  question discussed in the review of the scope.
