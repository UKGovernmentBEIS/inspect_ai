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
operations route through, on in-loop scoring and on the default-authority
write of `install_skills()`; the trust model lists the sites. A provider
whose `read_file()`
or `write_file()` cannot take a user raises inside a scope rather than
reading or writing as the default user. The scope and the marker are private
to inspect_ai.

The same calls also use the scope's `cwd`. `exec()` with no `cwd` runs in
it, and every relative path the caller gives resolves against it: a `cwd`
passed to `exec()` or `exec_remote()`, a `read_file()` or `write_file()`
path, and a `sandbox_with()` file lookup. A relative path therefore names the
same file in all of them. Absolute paths are kept, and marked operations are
unaffected.

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
running as a member runs its setup commands with `exec()` and writes its
configuration under the member's home with `write_file()`, then launches its
CLI through `exec_remote()`, which takes the scope's user. If the setup ran
as root, the configuration would be root's files and the member's CLI could
not use it.

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

Each of the three methods runs as:

- an explicit `user`, unchanged, inside a scope as outside;
- the provider's default user when the call names none inside a
  `framework_sandbox_operation()` block;
- otherwise the scope's user inside a scope for that sandbox, and the
  provider's default user outside one or for another sandbox. The sample's
  proxy and the provider behind it count as one sandbox.

The file methods raise instead when the provider cannot take a user (see
[Providers that cannot take a file user](#providers-that-cannot-take-a-file-user)).
The `SandboxEvent` options record the user the proxy passes to the provider,
given or from the scope; a call that runs as the default user records none. Calls a
provider makes on itself do not pass through the proxy, so they are not
defaulted a second time. `SandboxEnvironment`'s abstract methods and provider
implementations are unchanged. `test_operations_take_the_scope_user`,
`test_explicit_user_is_kept_in_a_scope`,
`test_other_sandbox_and_outside_scope_unchanged`,
`test_the_provider_behind_a_sample_proxy_is_the_same_sandbox` and
`test_framework_operation_keeps_the_default_user`
(`tests/util/sandbox/test_sandbox_identity.py`) pin these rules.

## The scope's `cwd` at the boundary

A scope's `cwd` is an absolute directory, typically the member's home or
workspace. On images whose working directory is `/root`, as many eval images
set it, a member cannot enter the provider's default working directory, so
a command run there as the member can fail. Scaffold setup commands running
as the member would otherwise have to pass `cwd` on every call.

After resolving the user, the proxy resolves paths, inside a scope for the
sandbox that has a `cwd` and outside any `framework_sandbox_operation()`:

- `exec()` with no `cwd` runs in the scope's `cwd`.
- A relative `cwd`, or a relative `read_file()` or `write_file()` path,
  resolves against the scope's `cwd`. `SandboxEnvironment.exec()` documents a
  relative `cwd` as relative to the default working directory, and inside
  the scope that directory is the scope's `cwd`.
- An absolute `cwd` or path is kept.

`test_operations_use_the_scope_cwd` pins these rules. The same resolution
applies wherever else a caller gives a relative path inside a scope:

- `exec_remote()` with no `cwd` runs in the scope's `cwd`, and a relative one
  resolves against it, so `exec_remote(cwd="sub")` and `exec(cwd="sub")` run
  in the same directory (`test_identity_scope_resolves_a_relative_cwd` in
  `tests/util/sandbox/test_exec_remote.py`). Inside a marked operation, such
  as an in-loop scorer, a relative `cwd` is kept, as `exec()` keeps it there;
  an omitted one still becomes the scope's `cwd`.
- `sandbox_with(file)` resolves a relative `file` against the scope's `cwd`
  for the scope's sandbox among the candidates before probing it, so
  `sandbox_with("result.txt")` probes the same pathname a member's
  `write_file("result.txt")` wrote. The probe itself is a framework
  operation and runs as the default user, so discovery finds the file only
  when the default user can read that pathname; a file only the member can
  read is not found. A
  lookup whose path resolves differently, as the same relative path does in
  scopes with different `cwd`s or outside any scope, does not reuse an
  earlier result (`test_file_discovery_follows_the_scope_cwd`). Lookups
  that resolve to the same paths share a result whatever scope made them.
  `on_path=True` lookups are unchanged.

These rules do not depend on the user: a call that names `user="root"` and
no `cwd` also runs in the scope's `cwd`, so a relative path names the same
file whoever the call runs as. Marked operations keep the provider's default
directory, as they keep its default user; [`install_skills()`](#install_skills)
says what that means for a relative skills directory. Outside a scope, in a scope without a `cwd`, on
another sandbox and through `as_type()`, nothing changes
(`test_scope_cwd_is_not_used_by_framework_operations_or_elsewhere`). The
`SandboxEvent` records the resolved `cwd` in an exec event's options and the
resolved path in a file event's `file`.

Companion packages tell that the installed inspect_ai applies the scope's
`cwd` at the boundary through the `SANDBOX_OPERATIONS_USE_SCOPE_CWD` flag in
`identity.py`.

### Closed working directories

Docker's own file operations on an absolute path work for a user who cannot
enter the image's default working directory.
`test_member_installs_a_scripted_skill_with_a_closed_workdir`
(`tests/tools/test_skill.py`, which needs Docker) pins this end to end on an
image whose working directory is `/root`, and
`test_read_file_command_preserves_user_and_archive_options` and
`test_write_file_commands_run_from_the_root_directory`
(`tests/util/sandbox/test_docker_read_file.py`) pin it on runtimes that
would not show the failure. The `local` provider runs only as the current
user, so the case does not arise there.

## The framework-operation marker

`framework_sandbox_operation()`, in `_framework_operation.py`, is a private
context manager. Inside the block it wraps, the proxy leaves an omitted user
as the provider's default user. The trust model's
[framework-operation contract](sandbox-trust-model.md#sandbox-identity-scopes)
says which code may use it and where it sits: code acting with the
framework's authority marks the single sandbox call, never model-chosen
work, and in-loop scoring is the one marked block that runs task code. Three
of its sites have reasons specific to this design. The sandbox-tools
transport is marked because, in a sandbox with no usable root, a member
cannot enter the default user's private tools tree
(`test_transport_runs_as_the_tools_user_in_a_scope`). In-loop scoring is
marked so a scorer keeps the default user (see
[Context inheritance](#context-inheritance)). The write of an
explicit-user `install_skills()` is marked so that install keeps its
contract (see [`install_skills()`](#install_skills)).

The tripwire test `test_framework_operation_marker_sites`
(`tests/util/sandbox/test_sandbox_identity.py`) fixes the set of modules
that reference the marker, so marking a call in a new module is a reviewed
change. It does not check which calls route through the marked helpers, and
those helpers run whatever command their caller passes: keeping model-chosen
work out of them rests on review of their callers, companion code included,
not on a test.

The marker affects only the boundary default. For the user, it changes only
calls that pass none: an explicit user is kept, and the model-facing tools
still pass their strictly resolved users. For paths, it suppresses the
scope's `cwd` and relative-path resolution for every call in the block,
including calls that name a user (the `pwd` of an explicit-user
`install_skills()` is one). A misplaced marker can therefore change the user
only of calls that pass none, and the working directory of any call in the block.

### Default identity and root probes

Injection probes the sandbox through marked helpers, so injection first
triggered by a member's tool call inside its scope does not change the
identity that later unscoped tool requests use. With a root tools user they
still run as the sandbox's default identity, and with a rootless tools user
as the tools user; the root and rootless cases of
`test_injection_inside_a_scope_records_the_default_identity`
(`tests/tools/sandbox_tools_utils/test_sandbox_tools_injection.py`) pin
both. Unmarked, the first member to trigger injection would be taken for the
sandbox's default user, and every later unscoped tools request would switch
to that member.

## Context inheritance

Both the scope and the marker are ContextVars, so tasks inherit both.

**The scope, into framework background work.** Tasks started inside a scope
inherit it: sandbox-service polling loops for the bridge, `exec_remote()`
process polling, the MCP server transports, and checkpoints that `react()`
takes. Their sandbox operations keep the framework's identity whatever task
they run in, because each goes through a marked helper. That rests on review
of those paths, not on a test: the tripwire does not check routing.

**The marker, into tasks started inside a marked block.** Each marked block
other than scoring wraps one awaited call to the proxy. A provider may start
its own tasks, but those act on the unwrapped provider and never reach the
proxy again. Code the call itself runs in the marked context, such as the
transcript subscribers its `SandboxEvent` notifies, and tasks that code
starts, do inherit the marker, so their sandbox calls with no user run as the
default user even after the wrapped call returns; that they make no such
calls on a member's behalf rests on review, not a test.

**In-loop scoring is the one marked block that runs task code.** A member's
`react(attempts=...)` and `basic_agent()` call `score()` inside the member's
scope. (The human agent's `task score` also calls `score()`, but a human
agent inside a scope is not a supported shape; see
[Not this design](#not-this-design).) `score()` runs each scorer inside the
marker (`test_react_in_loop_scorer_keeps_the_default_user_in_a_scope` in
`tests/agent/test_agent_react.py`). Unmarked, a scorer that calls
`sandbox().exec()` would run as the member in-loop and as the default user
when the same scorer runs at final scoring, which happens after the solver,
outside every scope; the in-loop verdict could then differ from the final
score, for example when the scorer reads a root-only test file. Marked, a
scorer's userless calls run as the default user of the sandbox they address.
That matches final scoring only when both phases address the same sandbox: a
scope makes its named sandbox the default, and `score()` does not restore
the sample's default selection, so a scorer that calls `sandbox()` inside a
scope for another sandbox addresses that sandbox in-loop and the sample's
default sandbox at final scoring. A scorer that calls a built-in tool still
runs that tool as the member. Tasks the scorer starts inherit the marker.
The scorer is trusted task code, and the marker gives it no authority it
would not have at final scoring.

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
when opened inside `framework_sandbox_operation()`
(`test_scope_cannot_open_inside_a_framework_operation`,
`test_react_in_loop_scorer_cannot_open_a_scope`).

## Providers that cannot take a file user

Inside a scope, an unmarked `read_file()` or `write_file()` with no user
resolves to the scope's user. If the provider's method cannot take a user,
as the trust model's
[File-operation users](sandbox-trust-model.md#file-operation-users) defines
it, the call raises `SandboxUserUnsupportedError` before reaching the
provider. Because the caller passed no user and would not otherwise know
where one came from, the error names the scope's user and sandbox and points
to `exec()` (`test_provider_without_file_user_raises_in_a_scope`).

In inspect_ai, Docker and `local` (current user only) take a file `user`.
Third-party providers whose file methods cannot take one raise `SandboxUserUnsupportedError` for these calls inside a scope; the abstract `SandboxEnvironment.exec()` signature takes `user`, so `exec()` is unaffected. Outside
a scope, and for marked operations, nothing changes on any provider: a
marked call gets no user from the scope, and the checkpoint copier passes
`user="root"` only to a provider that takes a file user, so the copier and the
detector keep working on providers without file users. Built-in tools are unaffected,
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
`user` keeps working for explicit-user installs inside a scope
(`test_install_skills_explicit_user_in_a_scope`).

**Omitted `user`.** The install takes the user a call with no user would
take at the boundary:

- **The member** (inside a scope for the sandbox, outside any marked block):
  every step runs with the member's authority. On a provider whose
  `write_file()` cannot take a user it fails with
  `SandboxUserUnsupportedError` before writing anything. Given an absolute
  `dir`, or a relative one in a scope with a `cwd`, it works on a
  [closed working directory](#closed-working-directories) (see below for a
  relative one in a scope with no `cwd`); companion packages detect that its
  `chmod +x` runs from `/` through the `INSTALL_SKILLS_AS_MEMBER_RUNS_FROM_ROOT`
  flag in `install.py`. It changes no ownership: files it creates belong to the
  member, like every other file the member's scaffold creates, while a file
  it overwrites keeps whatever owner the provider's write leaves (Docker
  keeps the existing owner); it can overwrite only a file the member may
  write. The rule applies whether the caller passes the sample's proxy or the
  provider behind it. `test_install_skills_omitted_user_in_a_scope`,
  `test_install_skills_omitted_user_in_a_scope_relative_dir`,
  `test_install_skills_omitted_user_in_a_scope_without_cwd` and
  `test_install_skills_raw_provider_without_file_user_in_a_scope`
  (`tests/tools/test_skill.py`) and, with Docker,
  `test_member_installs_a_scripted_skill_with_a_closed_workdir` pin this
  branch.
- **`None`** (outside a scope, or inside a marked block such as in-loop
  scoring): the legacy path, a write with the default user's authority and
  no `chown`. An in-loop scorer that installs skills behaves as the same
  scorer does at final scoring
  (`test_install_skills_omitted_user_under_marker_matches_final_scoring`).

A relative `dir`, including the default `skills`, resolves in one of two
ways; the file operations then receive absolute paths. In the member branch,
when the scope has a `cwd`, it resolves against that `cwd`, as the member's own
relative `write_file()` path would (`sandbox_operation_file()`), and no `pwd`
runs. Otherwise it resolves against the working directory of a `pwd` run as
the install's user. That `pwd` is a marked operation, so it runs in the
provider's working directory, not the scope's `cwd`. In a scope with no
`cwd`, the member must therefore be able to enter the provider's working
directory and write the skills directory under it; otherwise the caller
passes an absolute directory. An explicit-user install keeps the provider's
working directory even in a scope with a `cwd`
(`test_install_skills_explicit_user_in_a_scope_relative_dir`): its writes run
with the default user's authority and its `chown` as root, so resolving into
a directory the member controls, typically its home, would let a symbolic
link the member planted there redirect them to a protected file.

## Requirements on companion packages

Packages that install tooling into a scoped sandbox (inspect_swe's agent
installers) meet these requirements before they run inside a scope:

- **Shared artifacts at fixed paths**, such as agent binaries, Node,
  interpreters and source files that several members execute or load, follow
  the trust model's rule for them in
  [Verify before use](sandbox-trust-model.md#verify-before-use), and every
  file that members execute or load, with the directories between it and
  the install directory, is protected from member modification: verifying
  the install directory alone does not protect its contents. Otherwise
  the first member could own a file every later member executes, and run
  code as each peer.
- **Per-user setup** (discovery, per-user installs, configuration under the
  agent's home) runs as the member and resolves that member's home rather
  than an inherited `HOME`. The boundary default supplies the member's
  identity, not its environment: it does not change a command's
  environment, so `HOME` in a defaulted `exec()` is whatever the provider
  sets, not necessarily the member's home. `sandbox_identity_vars()`
  returns the member's home from the passwd database
  (`test_home_lookup_script_reads_the_passwd_database` and the
  `test_vars_*` tests in `tests/util/sandbox/test_sandbox_identity.py`).

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
  user, so a scorer that addresses the same sandbox runs on the same
  identity in-loop and at final scoring (see
  [Context inheritance](#context-inheritance) for sandbox selection).
- 2026-11-04 (decision: Ransom): a scorer cannot open its own scope during
  in-loop scoring; `sandbox_identity()` raises inside a marked block rather
  than ignoring the scope there. No scorer in Inspect or its satellite
  packages opens one, and supporting it would need a scope-aware exemption
  to the marker.
- 2026-11-12 (decision: Ransom): the scope's `cwd` applies at the boundary
  to all three calls, and the same join applies to a relative
  `exec_remote()` `cwd` and to `sandbox_with()` lookups, so a relative path
  names the same file in all of these calls inside a scope. Marked
  operations keep the provider's working directory.

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

**Framework code calls the unwrapped provider** (through `as_type()` or the
provider the proxy wraps). No new mechanism, but it drops the transcript events and output
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
  `user` it installs with the member's authority: skill files it creates are
  owned by the member, and a file it overwrites keeps the owner the
  provider's write leaves (on Docker, its existing owner). For a relative or
  default `dir`, see [`install_skills()`](#install_skills).

## Security

**What reaches the new code.** The user applied at the boundary comes from
the scope, which is host-side configuration chosen by the framework that set
it; the model never supplies it. The commands, paths and file contents
passed to the three operations may be model-chosen, as they always could be.
The default runs them as the framework-selected scope user, which in swarm
user isolation is the member's user rather than the sandbox's default user.
The scope's `cwd` is likewise host configuration. Resolving a model-supplied
relative path against it gives the member no access it lacks when the call
runs as the member, whose own permissions decide what the path reaches. A
call that names a privileged user, such as `user="root"`, keeps that user's
authority while its working directory and relative paths resolve in a
directory the member may control; an intentionally privileged operation
therefore needs a trusted working directory and destination, as the trust
model's [verified-directory](sandbox-trust-model.md#host-verified-directories)
and [verify-before-use](sandbox-trust-model.md#verify-before-use) contracts
require, and an absolute path alone does not make a member-controlled
destination trusted.

**The marker grants the default user.** A marker placed around model-chosen
work would run that work as root. The trust model's
[framework-operation contract](sandbox-trust-model.md#sandbox-identity-scopes)
forbids that, and [the marker section](#the-framework-operation-marker)
says what enforces it and what rests on review. In-loop scoring runs code
the eval author already trusts as the default user at final scoring, but
while other members are active (see
[Context inheritance](#context-inheritance)).

**Shared artifacts.** Without the
[companion requirements](#requirements-on-companion-packages), the default
would let the first member own a binary, interpreter or source file that
every later member executes or loads.

**`install_skills()`.** An explicit-user install keeps its default-authority
write followed by `chown`, inside a scope as outside. Its known exposure, a
destination an agent can redirect through symbolic links, is unchanged and
is tracked in the trust model's
[File-operation users](sandbox-trust-model.md#file-operation-users) section.
An omitted-user install inside a scope writes with the member's authority
and changes no ownership, so it adds no root operation in a directory the
member controls and can overwrite only files the member may write.

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
  still takes the scope's user (its user resolution is not marker-aware), while
  the scorer's `exec()` keeps the default user. No scorer is known to call
  `exec_remote()`.
- **File users in third-party providers.** Kubernetes and other providers
  need `user` on `read_file()` and `write_file()` before custom file
  operations work inside a scope there. That work belongs in each provider's
  repository.
- **`skill()` inside a scope.** It refuses the scope because its shared
  install does not install as a user.
