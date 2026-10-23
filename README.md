[<img width="295" src="https://inspect.aisi.org.uk/images/aisi-logo.svg" />](https://aisi.gov.uk/)

Welcome to Inspect, a framework for large language model evaluations created by the [UK AI Security Institute](https://aisi.gov.uk/).

Inspect provides many built-in components, including facilities for prompt engineering, tool usage, multi-turn dialog, and model graded evaluations. Extensions to Inspect (e.g. to support new elicitation and scoring techniques) can be provided by other Python packages.

To get started with Inspect, please see the documentation at <https://inspect.aisi.org.uk/>.

Inspect also includes a collection of over 200 pre-built evaluations ready to run on any model (learn more at <https://inspect.aisi.org.uk/evals/>).

> Coding agents: a structured index of the docs is published at <https://inspect.aisi.org.uk/llms.txt>. The user guide is concatenated as Markdown at <https://inspect.aisi.org.uk/llms-guide.txt>, and <https://inspect.aisi.org.uk/llms-full.txt> additionally bundles the API and CLI reference. Individual pages are available as Markdown by appending `.md` to the `.html` path (e.g. `/extensions/index.html.md`).

***

To work on development of Inspect, install [uv](https://docs.astral.sh/uv/) (0.11.8 or later), clone the repository, and sync the development environment from the checked-in lockfile:

```bash
git clone https://github.com/UKGovernmentBEIS/inspect_ai.git
cd inspect_ai
uv sync
```

This installs Inspect in editable mode with its development dependencies at the versions recorded in `uv.lock`. Project dependencies are declared in `requirements*.txt` and exposed through `pyproject.toml`. When changing dependencies, update the appropriate requirements file and run `uv lock` rather than relying on `uv add`. uv only resolves releases that are at least seven days old, except for model provider SDKs and Inspect's own packages; see [CONTRIBUTING.md](CONTRIBUTING.md#working-on-your-issue) for how to adopt a newer release.

Optionally install pre-commit hooks via

```bash
make hooks
```

Run linting, formatting, and tests via

```bash
make check
make test
```

Prefix those commands with `uv run` (for example, `uv run make check`), or activate the environment in `.venv` first.

If you use VS Code, you should be sure to have installed the recommended extensions (Python, Ruff, and MyPy). Note that you'll be prompted to install these when you open the project in VS Code.

### Frontend development (TypeScript)

The web UI lives in a git submodule at `src/inspect_ai/_view/ts-mono/`. **These steps are only needed if you plan to work on the TypeScript/React frontend** — Python-only contributors can skip this entirely.

Initialize the submodule and install dependencies — see the [one-time setup guide](https://github.com/meridianlabs-ai/ts-mono/blob/main/docs/submodule-guide.md#one-time-setup).

### Documentation

To work on the Inspect documentation, sync the optional `doc` dependencies and build the docs:

```
uv sync --extra doc
cd docs
uv run quarto render # or 'uv run quarto preview'
```

If you intend to work on the docs iteratively, you'll want to install the Quarto extension in VS Code.
