# Sandbox identity at the sandbox-operation boundary

## Overview

Inside a `sandbox_identity(user, ...)` scope, the sample's sandbox proxy
fills in the scope's user for every `exec()`, `read_file()` and
`write_file()` call on the scope's sandbox that names no user. A caller that
names a user keeps it. Custom tools, scaffold code and per-user install
steps that run inside a scope therefore act as the scope's user with no
change of their own, as the built-in tools do.

Inspect's own operations, which use an omitted user to mean "the sandbox's
default user", mark themselves with a private context manager,
`framework_sandbox_operation()`. Inside the marked block the proxy leaves an
omitted user alone. The mark sits on the few low-level helpers these
operations route through: the privileged-command helpers, the
framework-directory helper, the sandbox-tools transport and launcher, the
sandbox-file detector, the checkpoint copier, in-loop scoring, and the
default-authority write of `install_skills()`. A provider whose `read_file()`
or `write_file()` cannot take a user raises inside a scope rather than
reading or writing as the default user. The scope and the marker are private
to inspect_ai.

The same calls also use the scope's `cwd`. `exec()` with no `cwd` runs in
it, and every relative path the caller gives resolves against it: a `cwd`
passed to `exec()` or `exec_remote()`, a `read_file()` or `write_file()`
path, and a `sandbox_with()` file lookup. A relative path therefore names the
same file in all of them. Absolute paths are kept, and marked operations are
unaffected; `install_skills()` resolves a relative skills directory through
such a marked operation, so it uses the provider's working directory. Docker runs the commands behind its file operations from `/`, so
an absolute path works for a user who cannot enter the image's working
directory.

Companion packages that install tooling into a scoped sandbox provision
shared artifacts inside the marker and verify them before a member uses
them, and run per-user setup as the member in that member's home.

The code is in
[`util/_sandbox/identity.py`](../src/inspect_ai/util/_sandbox/identity.py),
[`util/_sandbox/_framework_operation.py`](../src/inspect_ai/util/_sandbox/_framework_operation.py)
and the proxy in
[`util/_sandbox/events.py`](../src/inspect_ai/util/_sandbox/events.py). The
security contract it implements is the trust model's
[Sandbox identity scopes](sandbox-trust-model.md#sandbox-identity-scopes) and
[File-operation users](sandbox-trust-model.md#file-operation-users).

## Why

`sandbox_identity()` lets a framework such as inspect_swarm run each agent of
a shared sandbox as its own Linux user without rebuilding that agent's tools.
The built-in model-facing tools, `exec_remote()` and the sandbox tools'
launches resolve the user explicitly. A scope that reached only those would
leave every other sandbox call running as the sandbox's default user, which
is root in most images: a custom tool that calls `sandbox().exec()`,
`read_file()` or `write_file()` without a user would let a model in one
isolated member read and write every other member's files.

Scaffold code that is not a tool has the same problem. An inspect_swe agent
running as a member writes its configuration with `write_file()` under the
`$HOME` that `exec(["sh", "-c", "echo $HOME"])` reports, and then launches
its CLI through `exec_remote()`, which takes the scope's user. If the first
two calls ran as root, the configuration would land in root's home and the
member's CLI would not find it.

Inspect's own commands and scorers also pass no user, to mean the default
user. Without a framework-operation marker, `exec()` cannot distinguish
those calls from a custom tool's when both omit a user. The marker makes
them distinguishable: framework code declares its operations, so every
unmarked call can take the scope's user. (The
[inspect_swarm isolation design](https://github.com/meridianlabs-ai/inspect_swarm/blob/main/design/swarm-sandbox-isolation.md)
sets the scopes this applies to.)

## Scope

Covered:

- `exec()`, `read_file()` and `write_file()` on the sample's sandbox proxy,
  for the scope's sandbox.
- The scope's `cwd` for those calls, for `exec_remote()` and for
  `sandbox_with()` lookups.
- The public `install_skills()`, which scaffolds call inside a member.

Not covered:

- **The provider object behind the proxy.** `sandbox().as_type(Provider)`
  returns the unwrapped provider. Calls on it skip the default, as they
  already skip transcript events and output limits.
- **`connection()`**, which gives host-side login details to a human and
  runs nothing in the sandbox.
- **Strictness.** The boundary keeps an explicit user, as `exec_remote()`
  does. The model-facing built-in tools stay strict and raise for a
  configured user other than the scope's.
- **A public scope or marker** (see [Decisions](#decisions)).

## The user at the boundary

Every sample sandbox is a `SandboxEnvironmentProxy`:
`init_sandbox_environments_sample()` wraps each provider before it publishes
the sample's environments, and `sandbox()`, `sandbox_with()` and injection
return these proxies. The proxy is therefore the one host-side place every
sample-level `exec()`, `read_file()` and `write_file()` passes through,
unless the caller used `as_type()`.

Each of the three methods resolves its user first, with
`sandbox_operation_user(env, user)`:

- An explicit `user` is returned unchanged.
- Inside a `framework_sandbox_operation()` block, `None` is returned
  unchanged.
- Otherwise the result is `sandbox_identity_user(env, None, strict=False)`:
  the scope's user inside a scope for `env`, `None` outside one or for
  another sandbox. Sandboxes are compared after unwrapping proxies, so the
  sample's proxy and the provider behind it count as one sandbox.

`exec()` forwards the resolved user to the provider. The file methods build
their keyword arguments with `sandbox_file_user_params()`, which resolves the
same way and then forwards the user if the provider's method declares a
keyword-capable `user` parameter, or raises (see
[Providers that cannot take a file user](#providers-that-cannot-take-a-file-user)).
The `SandboxEvent` options record the resolved user, so the transcript shows
the user each operation ran as. Provider internals that call their own
methods (Docker's `write_file()` runs `self.exec(...)`) act on the unwrapped
object and never reach the proxy again. `SandboxEnvironment`'s abstract
methods and provider implementations are unchanged.

## The scope's `cwd` at the boundary

A scope's `cwd` is an absolute directory, typically the member's home or
workspace. On images whose working directory is `/root` (Docker's default,
and many eval images), a member cannot enter the provider's default working
directory: some runc versions refuse to start a command there, and others
start it but fail anything that uses `.` or a relative path. Scaffold setup
commands running as the member would otherwise have to pass `cwd` on every
call.

After resolving the user, the proxy resolves paths, inside a scope for the
sandbox that has a `cwd` and outside any `framework_sandbox_operation()`:

- `exec()` with no `cwd` runs in the scope's `cwd`
  (`sandbox_operation_cwd()`).
- A relative `cwd`, or a relative `read_file()` or `write_file()` path, is
  joined to the scope's `cwd` (`sandbox_operation_cwd()`,
  `sandbox_operation_file()`). `SandboxEnvironment.exec()` documents a
  relative `cwd` as relative to the default working directory, and inside
  the scope that directory is the scope's `cwd`.
- An absolute `cwd` or path is kept.

The same join applies wherever else a caller gives a relative path inside a
scope:

- `exec_remote()` resolves its `cwd` with `sandbox_identity_cwd()`: no `cwd`
  becomes the scope's `cwd`, and a relative one is joined to it, so
  `exec_remote(cwd="sub")` and `exec(cwd="sub")` run in the same directory.
  Inside a marked operation, such as an in-loop scorer, a relative `cwd` is
  kept, as `exec()` keeps it there; an omitted one still becomes the scope's
  `cwd`.
- `sandbox_with(file)` resolves a relative `file` with
  `sandbox_operation_file()` for each candidate sandbox before probing it, so
  a file a member wrote with `write_file("result.txt")` is found by
  `sandbox_with("result.txt")`. The probe itself is a framework operation and
  runs as the default user. The discovery cache key holds the path each
  sandbox was probed with, so a lookup made in one scope, or outside any, is
  not reused in another. `on_path=True` lookups are unchanged.

These rules do not depend on the user: a call that names `user="root"` and
no `cwd` also runs in the scope's `cwd`, so a relative path names the same
file whoever the call runs as. Marked operations keep the provider's default
directory, as they keep its default user. A marked command that runs as the
member needs a directory the member can enter: `install_skills()`'s
`chmod +x` names `/`, but its `pwd` for a relative skills directory names
none, so it runs in the provider's working directory (see
[`install_skills()`](#install_skills)). Outside a scope, in a scope without a `cwd`, on
another sandbox and through `as_type()`, nothing changes. The `SandboxEvent`
records the resolved `cwd` in an exec event's options and the resolved path
in a file event's `file`.

`identity.py` exports `SANDBOX_OPERATIONS_USE_SCOPE_CWD = True` so companion
packages can tell that the installed inspect_ai applies the scope's `cwd` at
the boundary.

A provider's own commands must also work for a user who cannot enter the
default working directory. Docker's `read_file()` runs `tar` with `--workdir
/`, and its `write_file()` runs `mkdir -p`, `tee` and the `ls` of its
permission-denied diagnostic from `/` on the already-absolute path; the
diagnostic lists the destination's parent rather than `.`. The `local`
provider runs only as the current user and writes with Python I/O, so it has
no such command.

## The framework-operation marker

`_framework_operation.py` is a leaf module that imports only the standard
library, so every helper below can import it without a cycle. It holds a
`ContextVar[bool]`, the context manager `framework_sandbox_operation()` that
sets it for the block, and `in_framework_sandbox_operation()`, which reads
it.

The marker affects only the boundary default for user and `cwd`. The scope,
injection targeting, the sandbox-tools request user and the model-facing
tools' strict resolution are unchanged inside a marked block: a built-in
tool called there still passes its strictly resolved user, and a
`bash_session()` or `text_editor()` request still carries the scope's user
as its run-as parameter. A misplaced marker can therefore affect only
unmarked calls that pass no user, and never the built-in tools.

**Contract.** Code that acts with the framework's authority and means "the
sandbox's default user" by `user=None` goes through a marked helper. The
marker wraps the single call to the proxy, not a whole operation. It is
never placed around model-chosen work; in-loop scoring, which runs trusted
task code, is the one marked block that runs code Inspect does not fix. The
trust model states this as its
[framework-operation contract](sandbox-trust-model.md#sandbox-identity-scopes).

### Marked sites

| Site | What it covers |
|---|---|
| `privileged_exec()`, `privileged_shell()`, `image_path_lookup()` ([`_privileged.py`](../src/inspect_ai/util/_sandbox/_privileged.py)) | Every command Inspect issues with the framework's authority: the default-identity probe, OS detection, sandbox services, checkpoint and restore commands, the passwd home lookup, file detection's `test -r`, sample setup, skill digests and ownership changes. These helpers already require `user` and document `None` as the default user; the marker keeps that true inside a scope. |
| `_run_verified()` ([`_framework_directory.py`](../src/inspect_ai/util/_sandbox/_framework_directory.py)) | Every framework-directory helper: tools-tree install, verification and `stat`, service queues, checkpoint scratch. |
| `SandboxJSONRPCTransport` ([`_json_rpc_transport.py`](../src/inspect_ai/util/_sandbox/_json_rpc_transport.py)) | The tools CLI runs as the tools user; the member's identity travels as the request's `user` param. Without the marker, a sandbox with no usable root would launch the CLI as the member, who cannot enter the default user's 0700 tools tree. |
| `start-server` launch ([`tool/_sandbox_tools_utils/sandbox.py`](../src/inspect_ai/tool/_sandbox_tools_utils/sandbox.py)) | The server runs as the tools user. |
| `_is_file_readable()` fallback read ([`context.py`](../src/inspect_ai/util/_sandbox/context.py)) | The `sandbox_with()` detector's `read_file()` runs as the default user. |
| Checkpoint chunk read ([`util/_checkpoint/_copy.py`](../src/inspect_ai/util/_checkpoint/_copy.py)) | The chunk is read as `root` on a provider with file users and as the default user otherwise, inside a scope as outside. |
| `score()` ([`scorer/_score.py`](../src/inspect_ai/scorer/_score.py)) | In-loop scoring; see [Context inheritance](#context-inheritance). |
| `install_skills()`'s default-authority write ([`tool/_tools/_skill/install.py`](../src/inspect_ai/tool/_tools/_skill/install.py)) | See [`install_skills()`](#install_skills). |

`identity.py` reads the marker. Nothing else in inspect_ai needs it. The
sample's file copy and setup script run in
`init_sandbox_environments_sample()`, before any solver can open a scope.
`skill()` and `computer()` refuse inside a scope for their sandbox before
running anything, so `skill()`'s shared install is not reached there.

A tripwire test, `test_framework_operation_marker_sites` in
`tests/util/sandbox/test_sandbox_identity.py`, asserts that the set of
modules referencing the marker module is exactly the modules in this table
plus `identity.py`. A marker use in a new module is therefore a deliberate
change to its allowlist, which a reviewer sees. The test does not see a new
marker use inside a module already on the list, or a sandbox call that
bypasses the marked helpers; review of those modules covers both.

### Default identity and root probes

The probes injection runs stay correct through the `_privileged.py` sites.
The root-access probe passes `user="root"`. The default-identity probe
(`_detect_default_user()`) passes `user=None` through `privileged_shell()`,
so it reports the sandbox's default identity even when injection first
happens lazily, at a tool's first call inside a member's scope. Unmarked, the
first member to trigger injection would be recorded as the sandbox's
`_tools_default_user`, and every later unscoped tools request would switch
to that member. OS detection and checkpoint restore's `id -u` go through the
same helpers.

## Context inheritance

Both the scope and the marker are ContextVars, so tasks inherit both.

**The scope, into framework background work.** Tasks started inside a scope
inherit it: sandbox-service polling loops for the bridge, `exec_remote()`
process polling, the MCP server transports, and checkpoints that `react()`
takes. Every sandbox operation these tasks perform goes through a marked
helper (the privileged helpers, the framework-directory helper, the JSON-RPC
transport or the checkpoint copier), so each keeps its identity whatever
task it runs in. This holds by construction of those paths; the tripwire
limits which modules can use the marker but does not check that background
work routes through it.

**The marker, into tasks started inside a marked block.** Each marked block
other than scoring wraps one awaited call to the proxy. A provider may start
its own tasks, but those act on the unwrapped provider and never reach the
proxy again, so the marker does not spread beyond the call it wraps.

**In-loop scoring is the one marked block that runs task code.** A member's
`react(attempts=...)` and `basic_agent()` call `score()` inside the member's
scope. (The human agent's `task score` also calls `score()`, but a human
agent inside a scope is not a supported shape; see
[Not this design](#not-this-design).) `score()` wraps each
`await scorer(state, target)` in the marker. Unmarked, a scorer that calls
`sandbox().exec()` would run as the member in-loop and as the default user
when the same scorer runs at final scoring, which happens after the solver,
outside every scope; the in-loop verdict could then differ from the final
score, for example when the scorer reads a root-only test file. Marked, every
scorer runs on the identity it was written for. A scorer that calls a
built-in tool still runs that tool as the member. Tasks the scorer starts
inherit the marker. The scorer is trusted task code, and the marker gives it
no authority it would not have at final scoring.

The cost is timing. A scorer can execute submitted code (SWE-bench runs the
modified repository's tests; Frontier-CS runs the submitted program).
In-loop, it does so as the default user while other members are still
running, so member user isolation does not protect peers from that scorer.
Final scoring runs the same code only after every member has finished. An
in-loop scorer's report can also tell a member about files the member cannot
read, as final scoring's report can.

**A scope cannot open inside a marked block.** Inside the block a scope's
user would not reach the scorer's userless calls, while the same scorer
opening the same scope at final scoring, which is unmarked, would run them
as that user. `sandbox_identity()` therefore raises `SandboxIdentityError`
when opened inside `framework_sandbox_operation()`.

## Providers that cannot take a file user

Inside a scope, an unmarked `read_file()` or `write_file()` with no user
resolves to the scope's user. If the provider's method declares no
keyword-capable `user` parameter (a `**kwargs` catch-all does not count),
`sandbox_file_user_params()` raises `SandboxUserUnsupportedError`. Because
the caller passed no user and would not otherwise know where one came from,
the message names the scope:

```
KubernetesSandboxEnvironment.read_file does not support a user, so it cannot
run as 'swarm-w-1' inside the sandbox identity scope for sandbox 'default'.
Update the sandbox provider to support file users, or read the file with exec().
```

In inspect_ai, Docker and `local` (current user only) declare a file
`user`. Third-party providers that do not declare a keyword-capable file
`user` raise `SandboxUserUnsupportedError` for these calls inside a scope; all of them accept `exec(user=...)`, so `exec()` is unaffected. Outside
a scope, and for marked operations, nothing changes on any provider: a
marked call passes no user, so the checkpoint copier and the detector keep
working on providers without file users. Built-in tools are unaffected,
because none calls `read_file()` or `write_file()` inside a scope.

## `install_skills()`

`install_skills(skills, sandbox, user, dir)` is public, and scaffolds call it
directly (not through `skill()`) inside the agent they set up, so inside a
member it runs in the member's scope and does not refuse it. Its long-standing
contract is a write with the default user's authority, then, when `user` is
given, a `chown` to `user` (as root, or as `user` where root is unavailable)
and a `chmod +x` for scripts as `user`. It handles the two ways of calling it
separately.

**Explicit `user`.** The contract is unchanged inside a scope. The write is
marked, so it runs with the default user's authority, and the ownership and
mode changes follow. Unmarked, `install_skills(..., user="root",
dir="/root/skills")` inside a member's scope would write as the member and
fail with `PermissionError` before it could hand the files to root. Because
the marked write passes no user, a provider whose `write_file()` takes no
`user` keeps working for explicit-user installs inside a scope.

**Omitted `user`.** `install_skills()` calls `sandbox_operation_user(sbox,
None)` once and applies the answer to every step:

- **The member** (inside a scope for the sandbox, outside any marked block):
  the install runs as the member. It first checks that the provider's
  `write_file()` can take a user, and raises `SandboxUserUnsupportedError`
  before writing anything if not. The member is then named on every step:
  `pwd` for a relative `dir`, each `write_file(..., user=member)` and each
  `chmod +x`. No `chown` runs, because the writer owns the files. `chmod +x`
  runs from `/`, because the member may not be able to enter the provider's
  working directory; `install.py` exports
  `INSTALL_SKILLS_AS_MEMBER_RUNS_FROM_ROOT = True` so companion packages can
  detect this. The skills land owned by the member, like every other write
  the member's scaffold makes. The rule applies whether the caller passes the
  sample's proxy or the provider behind it, since the scope is matched after
  unwrapping.
- **`None`** (outside a scope, or inside a marked block such as in-loop
  scoring): the legacy path, a write with the default user's authority and
  no `chown`. An in-loop scorer that installs skills behaves as the same
  scorer does at final scoring.

A relative `dir`, including the default `skills`, resolves against the
provider's working directory, not the scope's `cwd`, because its `pwd` runs
through the marked `privileged_exec()` with no `cwd`; the resulting absolute
paths are what the file operations receive. Inside a scope with no `user`,
the member must therefore be able to enter the provider's working directory
(for `pwd`) and write the skills directory under it; otherwise the caller
passes an absolute directory.

## Requirements on companion packages

Packages that install tooling into a scoped sandbox (inspect_swe's agent
installers) meet these requirements before they run inside a scope:

- **Shared artifacts at fixed paths**, such as agent binaries, Node,
  interpreters and source files that several members execute or load, are
  provisioned inside the marker with `user=None` and satisfy the trust
  model's [verified-directory](sandbox-trust-model.md#host-verified-directories)
  and [verify-before-use](sandbox-trust-model.md#verify-before-use)
  contracts. The location is created or adopted with
  `ensure_framework_directory()` before any privileged step writes or
  executes there, those steps run through `exec_in_framework_directory()`
  rather than a pathname, and every executed or loaded file and the
  directories between it and the install directory are protected from member
  modification. Otherwise the first member could own a file every later
  member executes, and run code as each peer.
- **Per-user setup** (discovery, per-user installs, configuration under the
  agent's home) runs as the member and resolves that member's home rather
  than an inherited `HOME`. The boundary default supplies the member's
  identity, not its environment: Docker's `exec()` adds `--user` and leaves
  the image's `HOME` in place, whereas the sandbox-tools job launcher sets
  `HOME` to the switched user's home unless the caller sets it.
  `sandbox_identity_vars()` returns the member's home from the passwd
  database.

## Decisions

- 2026-10-30 (decision: Ransom): the scope, its helpers and the marker stay
  private to inspect_ai. Their callers outside inspect_ai, inspect_swarm
  (which sets the scope) and inspect_swe (which reads it), already import
  inspect_ai internals, and with the default at the boundary a custom tool
  needs no helper to run as the scope's user. The public docstrings of
  `SandboxEnvironment.exec()`, `read_file()` and `write_file()` do not
  mention the scope; the `sandbox_identity()` docstring and the trust model
  do.
- 2026-11-02 (decision: Ransom): in-loop scoring keeps the sandbox's default
  user, so a scorer runs on the same identity in-loop and at final scoring.
- 2026-11-04 (decision: Ransom): a scorer cannot open its own scope during
  in-loop scoring; `sandbox_identity()` raises inside a marked block rather
  than ignoring the scope there. No scorer in Inspect or its satellite
  packages opens one, and supporting it would need a scope-aware exemption
  to the marker.
- 2026-11-12 (decision: Ransom): the scope's `cwd` applies at the boundary
  to all three calls, and the same join applies to a relative
  `exec_remote()` `cwd` and to `sandbox_with()` lookups, so a relative path
  names the same file in all of these calls inside a scope. Marked
  operations, and so `install_skills()`'s relative skills directory, keep
  the provider's working directory.

## Alternatives considered

**Leave the boundary alone; custom tools opt in** through
`sandbox_identity_user(..., strict=True)` and a public export. No audit and
no framework change, but every custom tool and scaffold author must know
about the scope, and code that does not know fails open, as root. Rejected:
the safe behaviour should not depend on each author opting in.

**Suspend the whole scope inside framework operations** (set the scope
ContextVar to `None`). One ContextVar and no new resolver, but it also turns
off injection targeting, the tools request's run-as user and the strict
checks for everything in the block, so a misplaced block would run built-in
tools as root. Rejected in favour of a marker that affects only the boundary
default.

**A sentinel user value** (`user=DEFAULT_USER`) at framework call sites.
Each call would state its identity in its arguments, but `user` is
`str | None` on a public abstract method: calls on an unwrapped provider
would pass the sentinel to every third-party provider, and each would need
to understand it. Rejected.

**Framework code calls the unwrapped provider** (`as_type()` or the proxy's
`_sandbox`). No new mechanism, but it drops the transcript events and output
limits that injection and services rely on, and scatters provider unwrapping
through framework code. Rejected.

**Apply the default inside each provider**, for example through a
`SandboxEnvironment.__init_subclass__` wrapper. It would cover `as_type()`
too, but it rewrites third-party classes at import time and reaches provider
internals such as Docker's `write_file()` calling `self.exec()`. Rejected;
the proxy is already the sample-level boundary.

**Strict at the boundary** (an unmarked call naming another user raises
inside a scope). It would also stop a custom tool that passes
`user="root"`, but scaffold code legitimately passes `user="root"` for its
own installs, and an eval author who writes `user="root"` has made a grant in
code. Rejected for consistency with `exec_remote()`'s lenient resolution.

**Fall back to the default user on providers without file users.** The
operation would then run as the default user (root in most images) on a path
the member chose. The trust model already rejects that fallback for the
human agent's session logs, and AGENTS.md's "Invalid state" rule forbids the
silent coercion. Rejected.

**Apply the scope's `cwd` to `exec()` only.** `read_file()` and
`write_file()` take no `cwd`, so the same relative path would name different
files in `exec()` and in the file calls. Rejected in favour of joining
relative file paths too (see [Decisions](#decisions)).

**`install_skills()` with an omitted user keeps the legacy root write inside
a scope.** That would put root-owned files into a directory the member
controls, typically its home, with no ownership change after it, and a
member could redirect the root write through a symbolic link it plants
there. Rejected: the install runs as the member.

## Compatibility

Outside a scope nothing changes: the proxy resolves `None` to `None`, the
`cwd` and paths are untouched, and no code outside the proxy and
`identity.py` reads the marker. Calls on sandboxes other than the scope's are
unchanged too. Inside a scope:

- **Custom tools, solvers and scaffold code** that pass no user run as the
  scope's user. Code that needs the default user names it, as
  `user="root"` for example.
- **Working directory.** Inside a scope with a `cwd`, an `exec()` with no
  `cwd` runs there, and relative `cwd`s, file paths and `sandbox_with()`
  lookups resolve against it. Code that relies on the provider's default
  directory passes an absolute `cwd` or path.
- **Providers without file users** raise on unmarked `read_file()` and
  `write_file()` calls that pass no user. `exec()` is unaffected.
- **Eval logs.** A `SandboxEvent` for a defaulted call records `user` in its
  options, and inside a scope with a `cwd` an exec event records the `cwd`
  it ran in and a file event the resolved path. `options` is a free-form
  dict; there is no schema or generated TypeScript type change, and existing
  logs read back unchanged.
- **`install_skills()`** with a `user` behaves as outside a scope. With no
  `user` it installs as the member and the skills are owned by the member;
  a relative or default `dir` resolves in the provider's working directory,
  which the member must be able to enter and write under.

## Security

**What reaches the new code.** The user applied at the boundary comes from
the scope, which is host-side configuration chosen by the framework that set
it; the model never supplies it. The commands, paths and file contents
passed to the three operations may be model-chosen, as they always could be.
The default runs them as the framework-selected scope user, which in swarm
user isolation is the member's user rather than the sandbox's default user.
The scope's `cwd` is likewise host configuration, and a relative path a
model supplies is joined to it with `posixpath.join`, which gives the member
no access it lacks: the member's own permissions decide what the path
reaches.

**The marker grants the default user.** A marker placed around model-chosen
work would run that work as root. Three things limit this: the marker wraps
single calls in helpers whose arguments Inspect fixes; it affects only calls
that pass no user, never the model-facing tools' resolved users; and the
tripwire test makes a marker use in a new module a reviewed allowlist
change (uses inside already listed modules rely on review). The one
block that runs task code, in-loop scoring, runs code the eval author
already trusts as the default user at final scoring, but while other members
are active (see [Context inheritance](#context-inheritance)).

**Shared artifacts.** Without the
[companion requirements](#requirements-on-companion-packages), the default
would let the first member own a binary, interpreter or source file that
every later member executes or loads.

**`install_skills()`.** An explicit-user install keeps its default-authority
write followed by `chown`, inside a scope as outside. Its known exposure, a
destination an agent can redirect through symbolic links, is unchanged and
is tracked in the trust model's
[File-operation users](sandbox-trust-model.md#file-operation-users) section.
An omitted-user install inside a scope writes as the member and runs no
privileged `chown`, so it adds no root operation in a directory the member
controls.

**Providers without file users fail closed** (see
[above](#providers-that-cannot-take-a-file-user)).

**What remains unprotected.** `as_type()` returns an unwrapped provider whose
calls skip the default; a custom tool has to request it deliberately, and
the model cannot choose it. The scope's guarantees are bounded by the
member/root boundary that [sandbox-trust-model.md](sandbox-trust-model.md)
and the swarm design describe; nothing here stops a member that obtains
root.

## Not this design

- **`human_cli()` inside a scope.** Its `.bashrc` install and session-log
  reads take the human's configured user, while `connection()` logs the
  human in with no scope. A human agent inside a scope is not a supported
  shape; if one is needed, `human_cli()` should refuse the scope as
  `computer()` does until it is designed.
- **User switching without usable root.** A tools server that runs as the
  default user cannot switch to the scope's user, so `bash_session()` and
  `text_editor()` cannot honour a scope there.
- **Scorers and `exec_remote()`.** Inside in-loop scoring, `exec_remote()`
  still takes the scope's user (its resolution is not marker-aware), while
  the scorer's `exec()` keeps the default user. No scorer is known to call
  `exec_remote()`.
- **File users in third-party providers.** Kubernetes and other providers
  need `user` on `read_file()` and `write_file()` before custom file
  operations work inside a scope there. That work belongs in each provider's
  repository.
- **`skill()` inside a scope.** It refuses the scope because its shared
  install does not install as a user.
