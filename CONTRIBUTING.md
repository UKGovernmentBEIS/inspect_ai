# Contributing to Inspect AI

Thanks for your interest in contributing to Inspect! We regularly accept contributions from the community and we're glad you want to help.

## Quick Reference
For returning contributors:
- Find issue → Comment to claim → Branch → Code → `make check` → `make test` → PR
- Setup: `pip install -e ".[dev]"` and `make hooks`

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

## Working on your issue
After you’ve claimed an issue, you can start working on it. If this is your first contribution, you’ll need to clone the repository and install the development dependencies:

```
git clone https://github.com/UKGovernmentBEIS/inspect_ai.git
cd inspect_ai
pip install -e ".[dev]"
```

Create a branch with a short, descriptive name, then start working on the issue. You may find it helpful to install the pre-commit hooks:

```
make hooks
```

Once you’ve fixed the issue, run the linter, formatter, and unit tests by running the following commands:

```
make check    # Run linter (ruff) and formatter
make test     # Run pytest suite
```

If any tests are failing, fix the code and run both commands again to verify. Once all the tests are passing, push your branch to GitHub.

## Creating a pull request
After you’ve fixed your issue and the checks and tests are passing, go ahead and create a pull request. In order to help us better review your code, we’ll need you to fill in the blanks in the pull request template. Once you’ve done that, submit your pull request and we’ll review it as soon as we can. You don’t need to request a review or mention anyone; we regularly review open pull requests.

We may make comments or request changes on your pull request. We’ll try to be clear about what updates are needed, if any, but feel free to ask for clarification if our comments don’t make sense.

## Thanks so much!
We look forward to your contribution!