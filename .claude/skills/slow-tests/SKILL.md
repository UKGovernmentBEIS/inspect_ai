---
name: slow-tests
description: Run the gated test classes that plain `pytest` skips (slow Docker/sandbox tests, live model-provider API tests, flaky tests, trio variants). Use when asked to run slow, live, api, or trio tests, when debugging one, or when a change touches model providers, sandbox or tool code, agents, or async plumbing and needs its gated coverage run.
---

# Running the gated tests

Plain `pytest` (and `make test`) runs the fast suite only. Four classes of
test are gated behind flags defined in `tests/conftest.py`. A gated test
that is not enabled shows as skipped, and the run still exits green. Enable
the class, then read the skip summary at the end of the run (`-ra` is in
`addopts`) to confirm the tests you meant to run actually ran.

PR CI runs almost none of these. A scheduled job in `meridianlabs-ai/actions`
runs `pytest --runslow --runapi` against `main` every couple of hours, so a
gated test that a change breaks fails there, after merge.

| Class | Flag | How a test joins it | What it needs | Does PR CI run it? |
|---|---|---|---|---|
| slow | `--runslow` | `@pytest.mark.slow` | Usually Docker (`@skip_if_no_docker`), sometimes a provider key too | Only `tests/tools/` when tool or sandbox code changed, plus the areas in the `detect-slow` table in `.github/workflows/build.yml` |
| api | `--runapi` | `skip_if_no_<provider>` decorators in `tests/test_helpers/utils.py` add the `api` marker | The provider's key or opt-in variable; the decorator names it | No. CI has no provider keys |
| flaky | `--runflaky` | `@pytest.mark.flaky` | Whatever the underlying test needs (Docker or a key) | No |
| trio | `--runtrio` | Every async test gets a `[trio]` variant automatically | A separate pytest invocation; it runs only the trio variants | No |

Flags combine, except `--runtrio`, which must be its own run.

## Which tests to run for which change

Run the gated tests that cover the code you changed, scoped to the test
directories that exercise it. The whole gated suite is large and spends
provider credit; leave that to the scheduled job.

| You changed | Run |
|---|---|
| `src/inspect_ai/model/_providers/**` or a provider conversion module in `src/inspect_ai/model/` | `pytest --runapi --runslow tests/model/providers/test_<provider>*.py` with that provider's key set. Shared code (`_providers/util/`, `openai_compatible.py`, `providers.py`) is used by many providers; run `tests/model tests/tools tests/agent` with a key for each provider built on it |
| `src/inspect_ai/tool/**` or `src/inspect_sandbox_tools/**` | `pytest --runslow -m slow tests/tools/ -x` with Docker running. Add `--local-inspect-tools` to build the sandbox tools from your working tree instead of using the published binary (see `src/inspect_sandbox_tools/AGENTS.md`) |
| `src/inspect_ai/util/_sandbox/**` or `src/inspect_ai/util/_checkpoint/**` | `pytest --runslow tests/util/ tests/checkpoint/` with Docker running |
| `src/inspect_ai/agent/**` | `pytest --runslow --runapi tests/agent/`. Many of these are ACP and TUI tests that need only time; the rest need Docker or an OpenAI or Anthropic key |
| Async plumbing (task groups, cancellation, anything under `_util/_async.py` or a bridge) | The affected tests once normally and once with `--runtrio` |
| A test marked `flaky`, or the code it covers | That test with `--runflaky` |

## Provider keys

Most providers gate on `<PROVIDER>_API_KEY` (`OPENAI_API_KEY`,
`ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, `GROQ_API_KEY`, and so on). Bedrock
and Vertex authenticate through AWS and gcloud credentials, so their gate is
an opt-in switch: `ENABLE_BEDROCK_TESTS`, `ENABLE_VERTEX_TESTS`. Azure-hosted
OpenAI and Mistral skip on their `AZUREAI_*` variables without the `api`
marker. When unsure, read the decorator on the test.

A provider file's tests often gate on several keys. With only
`OPENAI_API_KEY` set, `test_openai*.py` still reports skips for Together,
Bedrock, vLLM, and reasoning-summary access. Those are expected. A skip
whose reason names the key you set means that test did not run.

## Docker

`@skip_if_no_docker` checks that the `docker` binary exists, not that the
daemon is up. With Docker installed but stopped the tests fail instead of
skipping. Start Docker first.

Local runs set no `--timeout` (CI uses 900s); conftest wraps each async
test attempt in a 5-minute timeout, sync tests get none. If a test hangs,
rerun with `--timeout=<seconds>`; the conftest watchdog then dumps every
thread stack 300 seconds before the kill, or at the threshold in
`INSPECT_TEST_HANG_DUMP_SECONDS` if you set one.

## Reporting a run in a PR

AGENTS.md requires a PR that touches gated-test areas to report its run.
Under "Other information" in the PR description, add a `### Slow tests`
section with:

- the exact command(s) run
- what ran, per class or provider, with the passed and skipped counts from
  the summary
- what you could not run, and why (no key, no Docker, no model access,
  needs a local server)

A test that skipped did not run. Say so rather than counting it. If you ran
nothing, say that, so a maintainer with the keys or Docker runs the tests
before merge.
