# Making `inspect ctl` discoverable to agents (without a skill teaching it)

Design for [meridianlabs-ai/inspect_ai#128](https://github.com/meridianlabs-ai/inspect_ai/issues/128).
Companion to [`control-channel.md`](control-channel.md), which designs the `ctl`
surface itself; this doc covers how an agent that has never read our docs or a
skill *finds* that surface.

## Problem

An LLM agent never reads our skill, so discovery has to live in surfaces the
agent already touches, ranked by how much context the agent holds at that
moment. The highest-leverage moment is **launch**: an agent running
`inspect eval` holds the exact object `ctl` operates on, the control server is
default-on (`resolve_ctl_server` at `src/inspect_ai/_eval/eval.py:966`), and
yet a plain interactive run prints nothing about `ctl` at any point — the only
console pointers are the keep-alive park notices (standalone:
`src/inspect_ai/_eval/eval.py:1132`; eval-set:
`src/inspect_ai/_eval/evalset.py:942`), which fire only when keep-alive was
requested (`--ctl-server=keep` or a runtime `inspect ctl process keep` /
`POST /keep` — itself requiring prior knowledge of `ctl`) and only *after*
the eval finishes.

The `ctl` reorg (noun groups, agent output contract — see control-channel.md
"CLI command hierarchy") already did most of the help-text and structured-output
work. What remains is concentrated at the launch moment plus a few output
details. Issue #128 proposed seven items in three tiers; two of the seven have
since shipped in full. This doc records the status of each and designs the
rest.

## Status of the issue's items

| # | Item | Status |
|---|------|--------|
| 1a | Launch-time "observe from another shell" pointer | **Open** — designed below |
| 1b | `inspect eval --json` startup output with a `control` block | **Shipped** — nothing to do |
| 1c | Observe command in `--ctl-server` flag help | **Open** (help names `inspect ctl` and the release command but no observe command) — designed below |
| 2a | `eval` / `eval-set` help cross-link to `ctl` | **Open** — designed below |
| 2b | Worked examples in hot `ctl` subcommand help | **Open** — designed below |
| 3a | Structured `--json` error envelope with branchable fields | **Shipped** — nothing to do |
| 3b | Positive-path footer hints in human output | **Partially shipped** — one gap designed below |

*Update (2026-07): the open items — 1a, 1c, 2a, 2b, and the 3b remainder —
are implemented alongside this doc (same PR), following the designs below.*

### Already shipped (verified against the code, 2026-07)

**1b — `inspect eval --json` (and beyond).** Shipped as the "launch handoff"
slice described in control-channel.md ("The launch handoff is load-bearing"):
`--json` on `eval` / `eval-set` / `eval-retry` (`src/inspect_ai/_cli/eval.py:933`,
`:1235`, `:2315`) emits a `launch` record once the control server is bound —
`run_id` / `pid` / `log_dir` / `control.socket_path`, with `control: null` when
the surface is definitively absent — plus a `done` record on exit. Stdout is
owned at the file-descriptor level, pre-flight errors re-render to stderr, and
`--detach` builds the fire-and-monitor launch on top. This deletes the
sleep-and-retry heuristic the issue targeted; no further work.

**3a — structured error envelope.** Shipped as issue #44 (control-channel.md
"Structure the error path too"): any terminal failure of a `--json` invocation
emits `{"error": {kind, exception, message, status}}` on stdout, with `kind`
drawn from a closed vocabulary (`busy`, `connect_timeout`, `read_timeout`,
`connect_error`, `not_found`, `ambiguous`, `http_error`, `invalid_request`,
`invalid_response`, `internal`) and `exception` carrying the package-qualified
class (`httpx.ReadTimeout`). The event-loop starvation the issue wanted
diagnosable without scraping tracebacks gets an even stronger signal than the
`exception` field it asked for: a dedicated `read_timeout` kind. The envelope
is advertised in `inspect ctl --help`
(`src/inspect_ai/_cli/ctl.py:286`). The issue's `suggestion` field was not
included; `message` is required to be self-contained (e.g. the ambiguity error
folds candidate ids in) and the group-level unknown-command hints (`_NounGroup.hint`)
cover the teach-through-the-error cases. We don't add `suggestion` now — no
observed failure mode needs a fourth field — but the envelope is extensible if
one appears.

**3b (mostly) — footer hints.** Human output already signposts next steps in
several places: the `task list` keep-alive footer suggests
`inspect ctl process keep` when keep-alive is off (`ctl.py:_print_keep_alive_footer`),
the empty-state message suggests `--ctl-server=keep` (`_echo_no_running_evals`),
capped listings print a truncation footer (`_echo_truncation_footer`), and each
noun group corrects unknown-command mistakes with the right invocation. The one
gap from the issue — `task list` showing errored samples without pointing at
the triage command — is designed below.

## Design

### 1a. Launch-time observe pointer (the real gap)

When the control server binds, print one line to **stderr**:

```
Monitor from another shell: inspect ctl task list   (inspect ctl --help)
```

**Where.** The bind site in `_eval/eval.py`, immediately after the
`control_server(...)` context manager yields and alongside
`emit_launch_handoff` (`src/inspect_ai/_eval/eval.py:994-1010`) — a site
that knows the server actually bound, before any task work begins.
Not the task startup panel (`src/inspect_ai/_display/core/panel.py:109`'s
`Log:` line): the panel renders per-task, so an eval-set would repeat the
pointer for every task; the panel also has two implementations (rich and
plain) that would each need the change, and under rich the panel repaints —
a one-shot notice doesn't belong in a repainting region. Under the rich and
plain renderers — which includes the primary audience, since an agent's
non-TTY run always resolves to `RichDisplay` — a stderr write at the bind
site precedes the live display taking the screen, so it cannot be garbled by
or garble the renderer.

**Except under the textual display, where the pointer is gated off.** The
default interactive display — `--display full` on a TTY outside Jupyter —
is the full-screen textual app (`src/inspect_ai/_display/core/active.py:24-34`),
and its `run_task_app` starts the app *before* `eval_async` runs: the bind
happens inside the running app, and a stderr write races app startup. Landing
before capture begins (`begin_capture_print` in `on_mount`) it goes to the
alternate screen and is lost; landing after, it is routed to the Console tab
and replayed only once the app exits — when "monitor from another shell" is
stale advice. Neither outcome is useful, and the textual user isn't
shortchanged: the app itself is the monitoring surface the pointer exists to
advertise. So the gate below checks the active display *implementation*, not
TTY-ness — the textual display is itself TTY-selected, but the distinction
matters because the no-TTY-detection stance below is about never suppressing
the agent's non-TTY case, which this gate cannot touch.

**Also the eval-set park bind.** There is a second bind site: the eval-set
keep-alive park (`_keep_alive_park`, `src/inspect_ai/_eval/evalset.py:919`)
binds a fresh server after the run — and when every task was reused, no eval
ran, so the park's is the *only* bind, yet its control surface is queryable
(`inspect ctl task list` shows the reused EvalStates registered by
`_register_reused_logs`). The park should call the same print helper: the
once-per-process latch makes it a no-op for a normal eval-set (the run's
earlier bind already printed), and in the all-reused case it closes the same
hole the park already closes for `--json` consumers by emitting the launch
handoff itself (the `launch_handoff_emitted()` guard). The park notice alone
doesn't substitute — it names only `process release`, and 1c exists precisely
because release-only mentions don't teach observation. The textual gate
applies at the park bind too (the resolved display implementation is
process-wide, even after the app exits or when it never ran): acceptable,
because the suppressed case is an interactive human who already gets the
park notice, while the agent's non-TTY park resolves to `RichDisplay` and
prints normally.

**Once per process.** Guard with a module-level latch (same pattern as the
keep-alive intent latch in `_control/server.py`). The standalone bind fires
once, but an eval-set with `--no-retry-immediate` re-binds per batch retry
and would otherwise repeat the line.

**Gating.** Print only when *all* hold:

- the control server actually bound (`_ctl_server is not None` and
  `socket_path is not None`) — a disabled or bind-failed server has nothing
  to observe;
- display is not `none` (this also covers `--json` and `--detach`, both of
  which force `--display none`; under `--json` the `launch` record's
  `control` block already carries strictly more information, so the pointer
  would be redundant noise);
- not quiet (`--display none` is how quiet is spelled for eval runs — no
  separate flag needed);
- the active display is not the textual full-screen app (see "Except under
  the textual display" above);
- the process was entered via the CLI (see below).

**Python-API callers are out of scope.** The bind site is shared with the
programmatic `eval()` API, whose display defaults to `full` — so display-mode
gating alone would print the pointer from every notebook, script, and pytest
suite that calls `eval()` directly. Like the launch handoff, the pointer is a
launch concern of the CLI process, not part of the public `eval()` surface
(see the module docstring of `src/inspect_ai/_eval/handoff.py`), and it uses
the same mechanism: a process-wide arm set by the CLI entry points
(`eval`/`eval-set`/`eval-retry` in `_cli/eval.py`) before they call into
`eval()` — mirroring `set_launch_handoff_listener` — rather than a parameter
threaded through `eval()`. A bare `eval()` call never prints it.

**Deliberately no TTY detection.** The issue's caveat suggests non-TTY
suppression, but the primary audience — an agent driving `inspect eval`
through a Bash tool — is *always* non-TTY; suppressing there would defeat
the item's purpose. Display-mode gating is the suppression mechanism:
a consumer who wants silence passes `--display none` (or `--json`, whose
stdout stays clean regardless since the pointer is on stderr).

This stance is about *hint suppression*, not TTY detection per se: `ctl`'s
terse mutation lines (see "Terse per-mutation lines when repeated" in
`control-channel.md`) do key their default off TTY-ness, precisely because
there the non-TTY consumer is who the compact form serves — nothing is
suppressed that `--no-terse`/`--json` doesn't restore.

**Exact text.** As above — the runnable command first, the help entry point
second, no styling/markup (plain stderr write, agent- and pipe-safe). The
line names `task list` rather than the bare `inspect ctl` because a runnable
command that produces useful output on first invocation teaches more than a
help pointer alone; `inspect ctl --help` rides along for the surface map.

### 1c. Observe command in `--ctl-server` help

The flag help (`src/inspect_ai/_cli/eval.py:444-453`) names the `inspect ctl`
CLI and `inspect ctl process release` but never the observe command. Append
one sentence to the shared `eval`/`eval-set` option and to the `eval-retry`
copy (`:2483-2493`):

> Observe the run from another shell with `inspect ctl task list`.

### 2a. `eval` / `eval-set` / `eval-retry` help cross-link

The command docstrings — which click renders as the `--help` header, the first
thing an agent reads — don't mention monitoring at all (`eval_command` is just
"Evaluate tasks.", `src/inspect_ai/_cli/eval.py:952`). Add one line to each of
`eval_command`, `eval_set_command`, and `eval_retry_command`:

> Monitor a running eval from another shell with `inspect ctl`
> (see `inspect ctl --help`).

The option help for `--json` / `--ctl-server` already mentions `ctl`, but an
agent skimming `--help` output reads the header and stops when the option list
looks conventional — the header line is the discovery surface.

### 2b. Worked examples in the hot `ctl` subcommands

The `ctl` subcommand docstrings (`src/inspect_ai/_cli/ctl.py`) explain
selectors and JSON shapes but carry no `Example:` lines; agents
pattern-match from examples. Add one line each, at the end of the docstring:

- `task_list_command`: `Example: inspect ctl task list --json`
- `sample_list_command`: `Example: inspect ctl sample list my-task --json`
- `sample_events_command`: `Example: inspect ctl sample events my-task sample-1 --tail 20`
- `config_command`: `Example: inspect ctl config --max-connections 20 --dry-run`

The examples show the flags an agent most needs to see composed (`--json` on
the list commands; `--tail` on events because the unseeded default is a
recent tail; `--dry-run` on the one mutation, reinforcing the
check-before-acting shape).
Other subcommands keep their current docstrings — these four are the hot
entry points, and blanket examples dilute the signal.

### 3b (remainder). Errored-samples footer on `task list`

When the human (non-`--json`) `task list` table contains rows with errored
samples, append one footer line (sibling of the keep-alive footer, same
placement and tone):

```
N samples errored — see `inspect ctl sample errors`
```

`N` sums `samples.errored` across rows. Note that `N` is deliberately
narrower than the triage view it points at: `samples.errored` counts
latest-attempt errors only (`_build_summary` in `_control/state.py` — a
sample that errored on attempt 1 and succeeded on attempt 2 doesn't count),
while `inspect ctl sample errors` also lists retried samples. So the view may
show more rows than `N`, never fewer — the footer cannot fire spuriously —
and the implementer should *not* "fix" the count to match the view's row
count. `--json` output is unchanged (the
counts are already in the envelope; hints in JSON are noise the agent contract
forbids). No other reads grow footers now: `sample list` already prints a
truncation footer when capped, and `sample errors` *is* the follow-up.

## Governing constraint

Every embedded hint is **one line**, on **stderr** for launch-time surfaces /
appended to the human table for `ctl` reads, and **absent from `--json`
stdout** in all cases. Suppression is via display mode (`--display none`,
`--json`) or display implementation (the textual app), not TTY detection
(see 1a). If a pointer can't satisfy all three,
it doesn't ship — hints that become noise teach agents and humans to ignore
all of them.

## Implementation notes

- 1a spans `_eval/eval.py` (the bind-site print and latch),
  `_eval/evalset.py` (the same print at the park bind), and `_cli/eval.py`
  (the process-wide arm set by the `eval`/`eval-set`/`eval-retry` entry
  points, likely alongside `set_launch_handoff_listener` in
  `_eval/handoff.py`); 1c/2a touch only help text in `_cli/eval.py`; 2b/3b
  touch only `_cli/ctl.py`. All are independent and can land as one small PR.
- Tests: extend `tests/_control/test_ctl.py` for the 3b footer (assert
  presence with errored rows, absence without, absence under `--json`);
  extend `tests/_cli/test_ctl_server_flag.py` (or a sibling) for 1a's gating
  (printed once on a plain CLI run; printed exactly once for an eval-set,
  including the all-reused case where only the park binds; absent under
  `--display none` and `--json`; absent from a direct `eval()` call, which
  never arms the pointer). Those cases all run non-TTY and so never select
  the textual display; the textual gate needs its own test that exercises
  the gate predicate directly (e.g. against a forced `TextualDisplay`)
  rather than a real TTY run.
  Help-text items (1c/2a/2b) are covered by `--help` snapshot-style assertions
  only if such tests already exist — otherwise not worth pinning prose.
- CHANGELOG: one line, e.g. "`inspect eval` now prints a pointer to
  `inspect ctl` monitoring at launch, and eval/ctl help text cross-links the
  two surfaces."
