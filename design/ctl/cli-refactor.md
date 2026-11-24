# ctl CLI refactor: split `_cli/ctl.py` into a package

> **Status: implemented** (see "Implementation notes" at the end for the
> deltas between this design and what landed). Originating issue:
> meridianlabs-ai/inspect_ai#220.
> Companion to [`control-channel.md`](control-channel.md), which owns the
> control-channel architecture and the CLI command hierarchy this module
> implements; this doc owns only the *code organization* of the client. It
> proposes no behavior, surface, or JSON-shape changes — a pure move.

`src/inspect_ai/_cli/ctl.py` is 6,229 lines — every `inspect ctl` command,
its runner, the HTTP/discovery client, the `--json` error envelope, and all
human-output rendering in one module. It is the largest file in the package
by a wide margin, and each new directive (requeue, pause/resume, config
knobs) grows it further. The internal structure is already disciplined —
layered sections, most of them banner-marked — so the refactor is mostly
mechanical: promote the existing sections to modules in a `_cli/ctl/`
package. The exceptions are called out below: the client and rendering
sections have no markers, and a handful of helpers sit in the "wrong"
section for the module boundaries, so their placement is decided here
from the call graph rather than by section membership.

## Current structure

The file is organized by layer. Banner comments mark the sections through
`command runners` (line ~1831); the client (~4100) and rendering (~5400)
boundaries below are unmarked — inferred from where `_process_scope_note`
ends and `_knob_label` begins — so the `_http` / `_fetch` / `_render`
extractions need more care than the marked noun sections:

| Lines (approx) | Section |
|---|---|
| 1–420 | Module docstring, imports, tuning constants, knob tables, click param types, `_NounGroup` / option-mirroring infrastructure, root `ctl` group, shared echo/exit helpers |
| 420–1430 | Noun command groups (thin click wrappers): `task`, `sample`, `config`, `process`, `model` |
| 1430–1600 | Hidden deprecated aliases (the old flat spellings) |
| 1600–1830 | `--json` error envelope: `_CtlFailure`, `_fail`, `_classify`, `_structured_failures`, `_envelope_failures` |
| 1830–4100 | Command runners (shared by canonical commands and aliases): listings, show/events/messages, mutations, config compose/scope resolution |
| 4100–5400 | Server discovery + HTTP client: `_resolve_target_server`, `_ServerUnreachable`/`_ServerBusy`, busy narration, retry budgets, `_request_json`, per-resource fetches, version gates, `_exec_limits` |
| 5400–6230 | Rendering: every `_print_*` / `_format_*` helper, tables, footers, summaries |

Dependencies mostly flow one way: click commands → runners → client →
envelope, with rendering shared broadly. But a single module cannot have
import cycles — they appear exactly when boundaries are drawn — so the
layering below is derived from the actual call graph, not from section
order, and a handful of helpers are placed away from their current
section specifically to keep it acyclic (see the placement notes).

## Constraints

- **Import path stability.** `inspect_ai._cli.main` does
  `from .ctl import ctl_command`; prose in `_control/{__init__,server,discovery}.py`
  and several `design/ctl/*.md` docs reference `inspect_ai._cli.ctl`.
  Converting the module to a *package* of the same name keeps every
  `inspect_ai._cli.ctl` reference valid.
- **Test coupling.** `tests/_control/test_ctl.py` (5,616 lines) plus
  `test_limits.py`, `test_server.py`, `test_buffer.py`, and
  `test_eval_set_integration.py` import 40 private symbols (plus
  `ctl_command`) from `inspect_ai._cli.ctl`. String patch targets live in
  `test_ctl.py` alone: 109 of its 112 `monkeypatch.setattr` calls target
  `"inspect_ai._cli.ctl.<name>"` (the other 3 patch the `discovery` and
  `process` module objects directly and need no migration); the other four
  files only import. Both imports and patch targets must be migrated
  mechanically and must fail loudly (not silently patch a dead alias) if a
  target goes stale.
- **Import-lightness.** The CLI deliberately avoids importing the core
  package (`TYPE_CHECKING` guard on `inspect_ai.log._samples`, see the
  comment at the guard). The split must not add eager heavy imports.
- **Behavior freeze.** No CLI surface, output, exit-code, or JSON-shape
  change. The agent output contract (see "Agent output contract" in
  [`control-channel.md`](control-channel.md)) and the discoverability
  docstrings ([`agent-discoverability.md`](agent-discoverability.md)) move
  verbatim.

## Proposed layout

`src/inspect_ai/_cli/ctl.py` becomes the package `src/inspect_ai/_cli/ctl/`.
Module boundaries follow the existing sections (banner-marked or inferred
per the caveat above); the two oversized
sections (runners, client) split along lines the code already draws — the
runners by resource noun, the client into transport vs. per-resource
fetches. Approximate sizes are from today's section extents, plus per-module
import boilerplate:

| Module | Contents | ~lines |
|---|---|---|
| `__init__.py` | Imports every command module for registration side effects; `__all__ = ["ctl_command"]`. Carries the current module docstring (the noun-group overview). | 80 |
| `_group.py` | Root `ctl` click group; `_NounGroup`, `_forward_group_options`, `_mirror_list_options`, `_json_option`, `_IntOrClearType`, `_deprecation_note`; shared echo/exit helpers (`_echo_no_running_evals`, `_busy_note`, `_busy_pids_label`, `_anomalies_pointer`, `_exit_all_busy`). | 355 |
| `_knobs.py` | The knob/version tables and their parity contract: `_KNOB_SCOPE`, `_KNOB_SINCE`, `_PROVENANCE_SINCE`. Pure data, no imports — read from both the config and rendering sides (see placement notes). | 70 |
| `_failure.py` | The `--json` error envelope section: `_ErrorKind`, `_CtlFailure`, `_fail`, `_classify`, `_structured_failures`, `_envelope_failures`. | 230 |
| `_http.py` | Transport + targeting: `_resolve_target_server`, `_ServerUnreachable`/`_ServerBusy`, `_BusyNarrator`, retry budgets (`_REQUEST_ATTEMPTS`, `_DEGRADED_READ_ATTEMPTS`, `_MAX_CONCURRENT_READS`, timeouts), `_get_with_retry_async`, `_request_json`, `_handler_404`, `_run_async`, `_collect_reads`, `_exit_busy`, `_unreachable_failure`, error-detail helpers (`_error_body`, `_error_detail_from_response`, `_unreachable_detail`, and `_error_detail` — see placement notes). | 820 |
| `_fetch.py` | Per-resource reads/writes over `_http`: `_fetch_summaries`, `_read_task_rows` / `_read_all_task_rows`, `_fetch_samples*`, `_fetch_sample_detail` / `_fetch_sample_events` / `_fetch_sample_messages`, `_post_flush`; target-eval resolution (`_resolve_target_eval`, `_match_by_task_name`, `_exit_ambiguous`). | 650 |
| `_mutate.py` | Directive machinery used by more than one noun: scope targeting (`_resolve_scope`, `_DirectiveScope`, `_is_active`, `_active_siblings`), the uniform `--json` mutation envelope (`_mutation_envelope`), and the cross-noun missing-route text (`_CANCEL_ROUTE_MISSING`, `_PAUSE_ROUTE_MISSING`). | 220 |
| `_task.py` | `task` group commands + their runners: `_run_task_list`, `_run_task_cancel`, `_run_task_pause_resume`, `_run_log_flush`, `_still_held_note`. | 560 |
| `_sample.py` | `sample` group commands (list/errors/show/events/messages/cancel/requeue) + the mutation runners (`_run_sample_mutation`, `_run_sample_cancel`, `_run_sample_requeue`, `_REQUEUE_ROUTE_MISSING`). | 800 |
| `_sample_read.py` | Sample read runners: `_list_sample_rows`, `_read_all_eval_samples`, `_run_sample_list` / `_run_sample_errors` / `_run_sample_listing`, `_run_sample_show`, `_run_sample_events`, `_run_sample_messages`, idle/truncation footers, their tuning constants (`_DEFAULT_EVENTS_TAIL`, `_DEFAULT_MESSAGES_TAIL`, `_IDLE_POINTER_MIN_SECONDS`), and the option-validation helpers (`_validate_cursor`, `_validate_from_start`, `_normalized_types`, `_exit_removed_since`, `_looks_like_timestamp` — see placement notes). | 900 |
| `_config.py` | `config` command + everything config-specific: `_run_config`, `_compose_config`, `_applied_knob_names`, `_process_scope_note`, `_gate_knob_support` / `_gate_provenance_support` / `_default_provenance_author`, `_exec_limits`, `_ConfigResult`. | 740 |
| `_process.py` | `process` group commands + runners: `_run_process_list`, `_run_keep_alive`, `_run_process_pause_resume`, `_run_process_anomalies` (+ `_trace_file_for_pid`, `_PidAnomalies` — the `_cli/trace.py` integration). | 500 |
| `_model.py` | `model` group commands + `_run_model_pause_resume` and its single-noun `_MODEL_PAUSE_ROUTE_MISSING`. | 160 |
| `_aliases.py` | The hidden deprecated flat spellings, unchanged thin delegations to the runners. | 190 |
| `_render.py` | The rendering section: `_print_*`, `_format_*`, `_render_table`, `_task_header`, `_short_id` / `_SHORT_ID_LEN`, `_truncate`, `_PER_TASK_PLACEHOLDER`, event/message summaries; plus `_paused_sources` (see placement notes). Excludes `_error_detail`, which goes to `_http.py`. | 880 |

Notes on placement judgment calls:

- **Runners live with their noun's commands** (not in a separate `runners`
  layer) — a runner has exactly one canonical command plus at most one
  hidden alias as callers, so co-location is where a reader looks first.
  The exception is `sample`, whose read runners are large enough to warrant
  the `_sample.py` / `_sample_read.py` split (commands + mutations vs. read
  runners); if implementation finds the seam awkward, collapsing them into
  one ~1,700-line `_sample.py` is acceptable — still a 3.5× reduction and
  the noun boundary is the one that must hold.
- **`_render.py` stays one module.** The formatters are small, uniform, and
  heavily shared across nouns (the samples table serves `sample list`,
  `task list` footers, and the errors table); splitting them per-noun would
  force either duplication or a shared-formatters module that recreates
  today's grab-bag.
- **`_mutate.py` holds only what more than one noun uses.** Membership is
  decided by caller count, in both directions. In: `_resolve_scope` (called
  by three `_task` runners at ctl.py:2701, 2770, 2899 and by `_run_config`
  at 3647 — its docstring calls it "the one resolution rule for directives
  with an optional `TASK`"), `_mutation_envelope` (task, process, model,
  and sample callers), and the two route-missing strings each shared by two
  nouns (`_CANCEL_ROUTE_MISSING`: task cancel 2799 + sample cancel 3247;
  `_PAUSE_ROUTE_MISSING`: task pause/resume 2921 + process pause/resume
  2995). Out, despite reading as mutation machinery: `_run_sample_mutation`
  (callers only in `_sample` — 3241, 3284) and `_still_held_note` (only
  `_run_task_pause_resume` — 2965, 2974), which go to their noun modules,
  as do the single-noun route strings `_REQUEUE_ROUTE_MISSING` and
  `_MODEL_PAUSE_ROUTE_MISSING`. Keeping the shared pieces below the noun
  tier is what leaves only the two intra-tier edges drawn under "Dependency
  layering": no noun module imports another for a route constant or for
  scope resolution.
- **`_unreachable_failure` moves to `_http.py`, not `_failure.py`**, even
  though today it sits in the envelope section: it runtime-dispatches on
  `isinstance(exc, _ServerBusy)`, so keeping it beside `_CtlFailure` would
  make `_failure` import `_http`. Its natural home is next to the exception
  types it translates.
- **`_error_detail` moves to `_http.py`, not `_render.py`**, even though
  today it sits in the rendering section (ctl.py:5787) — and it needs a
  definite home because `tests/_control/test_server.py` imports it. It
  calls `_error_body` and is called from `_request_json` and
  `_unreachable_detail`, all `_http.py`; landing it in `_render.py` would
  make `_http` and `_render` import each other.
- **The knob tables go to a `_knobs.py` leaf, not `_config.py`.**
  `_KNOB_SCOPE` is read from both sides of the config/rendering boundary:
  the `config` option help tags and `_exec_limits`'s key-set parity
  assertion (ctl.py:5320) on one, `_knob_label` and `_print_config` on the
  other — and `_run_config` calls `_print_config`, so assigning it to
  `_config.py` would make `_config` and `_render` import each other.
  `_KNOB_SINCE` and `_PROVENANCE_SINCE` are config-only and could live in
  `_config.py`, but the `_KNOB_SCOPE`/`_KNOB_SINCE` key-set parity contract
  (asserted at ctl.py:5320, and documented by the comment pair at
  ctl.py:111–151) reads best with the tables adjacent, so all three move
  together. A dedicated data leaf also keeps `_group.py` about click
  plumbing rather than "whatever was in the header region", and spares
  `_render.py` an import of the module that defines the root group.
  `_PER_TASK_PLACEHOLDER` needs no leaf at all: its only readers are
  `_print_config`'s three call sites (ctl.py:5435, 5561, 5570), so it goes
  to `_render.py`.
- **`_exec_limits`, the version gates, and `_ConfigResult` go to
  `_config.py`**, though the structure table puts them in the client
  section (ctl.py:5154–5370). Each has exactly one caller — `_run_config`
  (`_gate_knob_support` at 3677, `_gate_provenance_support` at 3686,
  `_exec_limits` at 3702) — and `_default_provenance_author` is called only
  by the provenance gate, so nothing else in the client section is
  config-aware. This matters for the seam list below: `_exec_limits` is
  patched at 9 sites, and its canonical target becomes
  `inspect_ai._cli.ctl._config._exec_limits`, not `._http.`.
- **The sample option validators move to `_sample_read.py`, not
  `_sample.py`.** `_run_sample_events` (a `_sample_read` runner) calls
  `_validate_from_start`, `_validate_cursor`, and `_normalized_types`
  (ctl.py:2399–2403), while `_sample`'s `sample events` command calls
  `_run_sample_events` — validators in `_sample.py` would close a
  `_sample`/`_sample_read` cycle. `_looks_like_timestamp` and
  `_exit_removed_since` ride along (`_validate_cursor` and
  `_exit_removed_since` both use the former); `_sample`'s remaining use of
  `_exit_removed_since` (ctl.py:826) points the already-required
  `_sample → _sample_read` direction.
- **`_paused_sources` moves to `_render.py`, not `_mutate.py`**, despite
  reading as mutation machinery. Its callers are the task pause/resume
  runners (`_task`) and the paused-state formatters `_format_paused` and
  `_print_keep_alive_footer` (ctl.py:5881, 5917). Leaving it in `_mutate.py`
  would give `_render → _mutate` against the `_mutate → _render` edge that
  `_resolve_scope` already creates (it builds its scope header with
  `_task_header`, ctl.py:3996, 4019) — a direct cycle. As a pure normalizer
  with no dependencies it sits naturally beside the formatters that consume
  it.
- **Root group in `_group.py`, not `__init__.py`.** Noun modules attach via
  `@task_group.command(...)` decorators at import time, so they need the
  parent group importable without importing the package `__init__`
  (avoiding an import cycle). `__init__.py` then imports the noun modules
  purely for their registration side effects and re-exports `ctl_command`.

### Dependency layering

One-way, derived by assigning every top-level symbol in `ctl.py` to its
module per the table above and resolving each reference in its body
(leaf → top):

```
_failure                              (leaf)
_knobs                                (leaf: pure data, no imports)
_group  → _failure                    (shared exit helpers raise _CtlFailure)
_render → _knobs                      (_KNOB_SCOPE scope labels)
_http   → _group, _failure            (busy exits use _anomalies_pointer)
_fetch  → _http, _render, _group, _failure
                                      (_exit_ambiguous renders the match
                                       table; busy notes/exits from _group)
_mutate → _fetch, _render, _failure   (_resolve_scope resolves the target
                                       eval and builds its header)
noun modules (_task, _sample, _sample_read,
  _config, _process, _model)
        → _mutate, _fetch, _http, _render, _group, _failure
                                      (not every noun uses every layer:
                                       _model skips _fetch/_render,
                                       _sample_read skips _mutate, and
                                       _config alone also reads _knobs)
_aliases → _task, _sample_read, _process, _config, _group
__init__ → _group + every command module (registration)
```

The noun tier is *not* flat — two sets of intra-tier edges are real and
load-bearing for the extraction order:

- `_sample → _sample_read`. The sample commands invoke the read runners and
  the option validators directly (8 references, including
  `_exit_removed_since` and the two tail defaults).
- `_aliases →` the four runner modules. The aliases are thin delegations, so
  each one calls a runner: `_run_task_list` (ctl.py:1444) and `_run_log_flush`
  (1537) in `_task`; `_run_sample_list` (1454), `_run_sample_errors` (1463),
  `_run_sample_events` (1491) in `_sample_read`; `_run_keep_alive` (1516,
  1526) in `_process`; `_run_config` (1553, 1589) in `_config`. Nine calls,
  all one-way — `_aliases.py` is a pure sink nothing imports.

No other noun-to-noun edge survives the `_mutate.py` membership rule above:
scope resolution and the shared route constants live below the tier, so
`_task` does not import `_config` and the cancel/pause nouns do not import
each other. The whole graph is acyclic (leaf-first topological order:
`_failure`, `_knobs`, `_group`, `_http`, `_render`, `_fetch`, `_mutate`,
then the nouns, `_aliases` last).

Note this is *not* today's section order: rendering is mid-stack, not a leaf
(`_fetch`, `_mutate`, and the runners all call into it), and `_mutate` sits
*above* `_fetch` rather than beside it — which is exactly why the placement
calls above are made from the call graph. A cycle would be an implementation
bug; the extraction order below makes one impossible to introduce silently
(each extracted module must import cleanly before the next extraction
starts).

### Patchable seams: import modules, not names

`monkeypatch.setattr` only affects lookups through the patched namespace, so
after the split a test patching `inspect_ai._cli.ctl._fetch.` +
`_fetch_samples_async` must actually intercept the runner's call. The rule
that keeps every existing patch site a one-line mechanical rewrite:

**Cross-module references to functions that tests patch go through the
module object** — `from inspect_ai._cli.ctl import _fetch` then
`_fetch._fetch_samples_async(...)` — never `from ._fetch import
_fetch_samples_async`. Each seam then has exactly one canonical patch target
(its defining module) that intercepts *every* consumer. Types, constants,
and never-patched helpers may be imported by name as usual. The seams tests
patch today:

- `_request_json` — the most-patched target in the suite (34 sites),
  called from what become `_task`, `_sample`, `_process`, `_model`,
  `_fetch`, and `_config`. This is the seam that most needs the rule: a
  `from ._http import _request_json` in any consumer would silently
  defeat all 34 patches.
- `_fetch_sample_detail` / `_fetch_sample_events` /
  `_fetch_sample_messages` and `_post_flush` — defined in `_fetch.py`,
  called from the `_sample_read.py` runners and `_run_log_flush` in
  `_task.py` respectively.
- `_fetch._fetch_samples` / `_fetch._fetch_samples_async` /
  `_fetch._fetch_summaries`; `_http._get_with_retry_async` (transport, so it
  stays in `_http.py` even though both its callers — `_read_task_rows` and
  `_fetch_samples_async` — are in `_fetch.py`); `_config._exec_limits`
  (9 sites; a client-section symbol that lands in `_config.py`, see the
  placement note above).
- `list_discovered_servers`, `pid_alive`, and `inspect_trace_dir` — names
  imported *into* ctl from elsewhere and patched on the ctl module.
  `pid_alive` and `inspect_trace_dir` are only called from what becomes
  `_process.py`, so their targets become
  `inspect_ai._cli.ctl._process.<name>`. `list_discovered_servers`
  (31 sites) is called from five future modules (`_task`, `_process`,
  `_config`, `_http`, `_fetch`), so like `_request_json` it gets one
  canonical home: `_http.py` imports it, every other module calls
  `_http.list_discovered_servers`.

The `httpx` client classes are the exception that needs *no* canonical home.
`monkeypatch.setattr("inspect_ai._cli.ctl.httpx.Client", ...)` resolves the
`httpx` *module object* and mutates `httpx.Client` on it, so the patch
intercepts every consumer whichever submodule the path traverses — any
module that imports `httpx` works as the rewritten target. Funnelling
`httpx` through `_http.py` isn't possible anyway: `_classify` dispatches on
`httpx` exception types (ctl.py:1723–1730), so `_failure.py` imports `httpx`
directly, as do `_fetch.py` and `_http.py`.

Not seams, despite appearing patch-adjacent: `read_trace_file` and the
retry-budget constants (`_REQUEST_ATTEMPTS`, `_DEGRADED_READ_ATTEMPTS`,
`_MAX_CONCURRENT_READS`) are imported by name in tests but never
`setattr`-patched, so by this rule they need no indirection.

A short comment at each module-object import notes it is a patch
seam, so a later cleanup doesn't "simplify" it back into a name import.

Symbol names are **kept verbatim** (leading underscores included) even
though module-level privacy now also comes from the path. Renaming would
turn a `sed`-able migration into a semantic one and break the
grep-discoverability of every symbol cited in `design/ctl/*.md`. A
follow-up may drop underscores; not this refactor.

### `__init__.py` re-exports nothing private

Only `ctl_command` is exported. Test imports and patch targets are updated
to the defining modules rather than served by a compatibility facade: a
facade would keep stale patch targets *importable* while making them
silently ineffective (patching the facade's alias, not the name the runner
looks up) — the worst failure mode, a test that passes for the wrong
reason. With no facade, any missed migration fails loudly at import or
`setattr` time.

## Test migration

Mechanical, in the same commit as each extraction (the suite stays green at
every commit):

1. **Imports** — rewrite `from inspect_ai._cli.ctl import X` to the
   defining module per the table above (40 private symbols plus
   `ctl_command` across 5 test files, both the top-of-file blocks and the
   in-test lazy imports).
2. **Patch targets** — rewrite `"inspect_ai._cli.ctl.<name>"` to
   `"inspect_ai._cli.ctl.<module>.<name>"` (109 sites, all in
   `test_ctl.py`; its 3 remaining `setattr`s patch the `discovery` and
   `process` module objects and are unaffected). The module-object seam
   rule above guarantees the canonical module is always the correct
   target.
3. **No assertion changes.** Any test whose *assertions* need touching is a
   red flag that the move changed behavior.

`tests/_control/test_ctl.py` itself (5,616 lines) is out of scope here; a
natural follow-up splits it along the same noun/module lines once the
source layout settles.

## Migration plan

One PR, reviewable commit by commit, suite green after each:

1. `git mv src/inspect_ai/_cli/ctl.py src/inspect_ai/_cli/ctl/__init__.py`
   — a pure rename commit (100% similarity), preserving history through the
   package conversion.
2. Extract leaves first, per the layering above: `_failure.py`, `_knobs.py`,
   `_group.py`, then `_render.py` (which imports `_knobs`).
3. Extract `_http.py`, `_fetch.py`, `_mutate.py` (in that order — each
   imports the one before it).
4. Extract noun modules. The only ordering constraints inside the tier are
   `_sample_read.py` before `_sample.py` and `_aliases.py` last (it calls
   into four of the others): `_sample_read.py`, `_sample.py`, `_task.py`,
   `_config.py`, `_process.py`, `_model.py`, then `_aliases.py`.
5. Shrink `__init__.py` to registration + docstring; update the file-path
   references in `design/ctl/*.md` (`agent-discoverability.md`,
   `config-log-persistence.md`, `sample-requeue.md`, `pause-resume.md`)
   to the new module paths.

Each extraction commit moves code verbatim (plus the import block), moves
the section's tests' imports/patch targets, and nothing else. Reviewers can
verify move-only commits with `git diff --color-moved=dimmed-zebra`.

Verification gate per commit: `pytest tests/_control tests/_cli`, then
`ruff check` and `mypy` over `src/inspect_ai/_cli/ctl/` at the end. The
5,616-line ctl test suite is the behavioral safety net — it exercises every
command's human and `--json` output, the retry/busy paths, and the version
gates.

## Risks

- **Silent behavior drift during a move.** Mitigated by move-only commits,
  `--color-moved` review, the no-assertion-changes rule, and the breadth of
  the existing suite.
- **Missed patch-target migration.** Fails loudly by design (no facade;
  `monkeypatch.setattr` raises on a missing attribute).
- **Import cycles.** A single file cannot have them — they appear exactly
  when boundaries are drawn. The known ones are avoided by the call-graph
  placements above (`_unreachable_failure`, `_error_detail`, the knob
  tables, the sample validators, `_paused_sources`, and `_mutate.py`'s
  shared-only membership); leaf-first extraction order surfaces any
  remaining inversion immediately as an `ImportError`.
- **`git log --follow` across the split.** History for extracted modules
  needs `git log --follow` from the extraction commit back through
  `__init__.py` to `ctl.py`; the rename-first commit keeps that chain
  intact for the file bulk. Accepted cost, standard for any split.

## Non-goals

- No CLI surface, output, exit-code, or JSON-shape changes.
- No symbol renames (see above) and no de-underscoring.
- No restructuring of `tests/_control/test_ctl.py` (follow-up).
- No changes to the deprecated-alias transition policy — aliases move as-is
  and retire on their own schedule.

## Implementation notes

Implemented 2026-08-18 (issue meridianlabs-ai/inspect_ai#220). The design
above was written against an older revision of `ctl.py` (6,229 lines; 7,336
at implementation time), and the code had moved under it. Deltas from the
proposal, all derived by re-running the call-graph analysis at
implementation time:

- **No `_aliases.py`.** The hidden deprecated flat spellings were removed
  upstream before the refactor landed, so the module (and the
  `_aliases → runners` edges) doesn't exist. The nouns register directly on
  the `ctl` group and nothing imports them.
- **`_knobs.py` holds `_STRICT_SINCE`, not `_KNOB_SINCE`.** Issue #67
  retired the per-knob version table in favor of the strict-mutations floor,
  and `_gate_knob_support` became `_gate_strict_floor` (in `_config.py`, as
  designed for its predecessor).
- **`_failure` is not a leaf, and everything emits through `_render`.** The
  envelope helpers (and every other layer) now emit through the sanitizing
  `_echo` / `_echo_raw` wrappers, so `_failure → _render`,
  `_group → _render`, and `_http → _render` are real edges the diagram above
  lacks, and `_model` no longer skips `_render` (it sanitizes reason lines).
  `_render` and `_knobs` are the leaves. The graph stays acyclic — `_render`
  imports only `_knobs`.
- **Symbols added since the design** were placed by the same caller-count
  rule: the requeue machinery (`_requeue_pairs`, bulk/errored runners) in
  `_sample.py`; the terse-mode helpers (`_terse_option`, `_use_terse`,
  `_terse_line`) in `_group.py`; the shared pause-confirmation prose
  (`_pause_prefix`, `_pause_confirmation`, `_HELD_CAVEAT`,
  `_terse_held_suffix` — task/process/model callers) in `_mutate.py`; the
  output sanitizers (`_sanitize_control` and friends) in `_render.py`; and
  `_get_response_with_retry`(`_async`) — a patched seam — in `_http.py`.
- **One test changed beyond imports/patch targets.** The structural
  click-echo scan (`test_no_direct_click_echo_outside_the_wrappers`) read
  the single module's source via `inspect.getsource`; after the split that
  would have scanned only the docstring-and-registration `__init__.py` and
  passed vacuously, so it now walks every `*.py` file in the package (and
  asserts the package is actually split). The `_echo` / `_echo_raw`
  exemption is scoped to `_render.py`, where the wrappers live — in the
  monolith a shadowing same-named function was impossible, in a package a
  per-module shadow would otherwise pass the scan. Its assertions are
  unchanged.
- **Two commits, not per-module commits.** A pure-rename commit
  (`ctl.py → ctl/__init__.py`, 100% similarity) followed by one split
  commit. Move-fidelity was verified mechanically instead of per-commit
  review: every top-level symbol in the new modules was checked
  AST-identical to the original (217 symbols), modulo only the intended
  seam rewrites (bare `name(...)` → `_module.name(...)`).
- `list_discovered_servers` is re-exported from `_http.py` with the
  `import ... as ...` idiom — mypy's no-implicit-reexport would otherwise
  reject the `_http.list_discovered_servers` seam accesses.
