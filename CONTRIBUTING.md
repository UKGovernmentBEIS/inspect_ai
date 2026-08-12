# Contributing to Inspect AI

Thanks for your interest in contributing to Inspect! We regularly accept contributions from the community and we're glad you want to help. To keep review capacity focused on work the project has agreed it wants, contributions follow a tiered policy. Please read this section first.

## How contributions work

Your path depends on your history with the project:

- **Qualified contributors**: maintainers and individuals recorded (by
  account id) in [`.github/qualified.yml`](.github/qualified.yml) — may open
  PRs directly.

- **Established contributors**: anyone with at least one merged non-trivial
  PR in this repository (trivial documentation fixes don't count toward this)
  — may open PRs directly, subject to a limit of 4 open PRs at a time.
  One caveat: an issue you filed yourself doesn't establish demand. A PR
  addressing your own issue needs that issue labeled `accepted` first, just
  as for new contributors — self-reported problems get maintainer sign-off
  before code, self-*discovered* fixes for problems others have reported
  don't need it.
- **New contributors**: if you haven't had a PR merged here yet, start from an
  issue a maintainer has labeled `accepted` before writing code. PRs from new
  contributors that aren't linked to an accepted issue are closed
  automatically, with a comment explaining the available paths.
  **Exception:** trivial documentation fixes (typos, broken links) are always
  welcome directly.

Whatever your tier, a non-draft PR inactive for 60 days is closed with an
invitation to reopen. And whatever your tier, check for an existing open PR
addressing the same problem before opening yours: duplicates are closed in
favor of the earlier PR unless a maintainer has asked for an alternative.

Issues a maintainer has labeled `deferred` are decisions not to prioritize
that work right now. PRs against a deferred issue are closed automatically,
whatever your tier — comment on the issue with new evidence or demand if you
think it should be revisited.

**Why:** like most open-source projects, we now receive a large volume of
unrequested, often agent-generated PRs. Reviewing a PR is time-consuming;
agreeing on a direction in an issue first is much easier. This policy spends
our review time on work we've agreed we want and spares you writing code we
can't merge.

## Proposing work (new contributors)

1. **Search existing issues and open PRs** to avoid duplicates.
2. **Open an issue** describing the problem, the motivation, and (optionally)
   whether you'd like to implement it. Concrete evidence — a reproduction, a
   failing test — makes acceptance much more likely.
3. **Maintainers triage frequently** and aim to decide within 7 days: the issue
   is labeled `accepted`, closed as "not planned", or redirected to the
   extension ecosystem (see below).
4. Once your issue is `accepted`, comment to claim it, then open a PR that
   references it (`Fixes #NNN`).

## Consider an extension first

Much of what contributors want to add such as model providers, tools, scorers,
metrics, storage backends, example evals doesn't need to live in Inspect
core. Inspect has first-class extension APIs and an
[extensions listing](https://inspect.aisi.org.uk/extensions.html) in the
documentation. Publishing your own package means you own it, you ship on your
own schedule, and there's no review queue; a one-line PR adds it to the
listing.

## Using AI tools

AI-assisted contributions are welcome from every tier — we use these tools
ourselves. The requirements:

- You must understand, and be able to explain and defend, every line you
  submit. If you can't, don't submit it.
- Note the tooling you used in the PR description.
- Use your tools to review your changes, not just implement them — we find
  multiple review passes (each in a fresh context) before opening a PR catch
  a lot — and summarize what
  they found in the PR description (agents: see the `Agent review` format in
  [`AGENTS.md`](AGENTS.md)). We'd prefer review passes use a strong
  (frontier-class) model: small fast-tier models rarely surface real issues,
  and maintainers weight a disclosed review by the model used and the number
  of passes.

If you are a coding agent, read [`AGENTS.md`](AGENTS.md) before opening a PR.

## Reporting Bugs
Found a bug to report? Please [open an issue](https://github.com/UKGovernmentBEIS/inspect_ai/issues/new) with:
- A clear description of the problem
- Steps to reproduce
- Expected vs actual behavior
- Your environment (OS, Python version, Inspect version)

Before opening a new issue, please search [existing issues](https://github.com/UKGovernmentBEIS/inspect_ai/issues) to avoid duplicates.

## Finding an issue to work on
We use GitHub Issues to track open issues for Inspect. You can view all open issues on the project’s [Issues](https://github.com/UKGovernmentBEIS/inspect_ai/issues) tab on GitHub. We use the “good first issue” label to mark issues that might be easier for a first-time contributor to address. You can see issues marked “good first issue” by [filtering the Issues tab](https://github.com/UKGovernmentBEIS/inspect_ai/issues?q=is%3Aissue%20state%3Aopen%20label%3A%22good%20first%20issue%22).

Once you’ve found an issue you’d like to work on, add a comment to the issue saying you’d like to work on it. This will let others know you’re working on it so there’s no duplicate effort. We value your time, and we don’t want you to invest your time fixing an issue, only to find that when you finish, someone else has already created a pull request that fixes the same issue, rendering your work meaningless.

After you’ve claimed an issue, we’ll let you work on it for up to 7 days. At this point, if you haven’t checked in or created a pull request, we’ll allow someone else to claim it and work on it.

If there’s something you’d like to work on but no GitHub issue for it, start by creating an issue. We’ll weigh in there so you’ll know whether it’s something we think others might benefit from, and if so, you’ll be able to claim the issue.

Note that `good first issue` implies `accepted` — you can open a PR for one directly.

## Working on your issue
After you’ve claimed an issue, you can start working on it. If this is your first contribution, you’ll need to clone the repository and install the development dependencies:

```
git clone https://github.com/UKGovernmentBEIS/inspect_ai.git
cd inspect_ai
pip install -e ".[dev]"
```

If you prefer [uv](https://docs.astral.sh/uv/), you can instead sync the development environment from the lockfile:

```
uv sync --extra dev
```

The uv workflow is optional. Inspect's dependencies are declared in the `requirements*.txt` files and exposed through `pyproject.toml`; `uv.lock` captures a reproducible development resolution. If you are changing dependencies, update the relevant requirements file and refresh the lockfile rather than using `uv add` as the source of truth.

Create a branch with a short, descriptive name, then start working on the issue. You may find it helpful to install the pre-commit hooks:

```
make hooks
```

Once you’ve fixed the issue, run the linter, formatter, and unit tests by running the following commands:

```
make check    # Run linter (ruff) and formatter
make test     # Run pytest suite
```

In a uv-managed environment, run these as `uv run make check` and `uv run make test`.

If any tests are failing, fix the code and run both commands again to verify. Once all the tests are passing, push your branch to GitHub.

## Creating a pull request

Fill in the PR template and reference the issue your PR resolves
(`Fixes #NNN`). Run `make check` and `make test` before pushing.

**Review expectations:** we aim to review every PR, given time. A PR that goes
inactive for 60 days is closed by the stale bot with an invitation to reopen —
that isn't a judgment of you or your work.

## Becoming a qualified contributor

Qualified status is earned through a sustained record. As a rule of thumb, being added to the qualified list requires several
months of PRs that mostly merge (~75%+) as well as responsive engagement in review.
Maintainers periodically add such contributors to our list of qualified contributors.

## Thanks so much!

We look forward to your contribution!
