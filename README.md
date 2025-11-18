[<img width="295" src="https://inspect.aisi.org.uk/images/aisi-logo.svg" />](https://aisi.gov.uk/)

Welcome to Inspect, a framework for large language model evaluations created by the [UK AI Security Institute](https://aisi.gov.uk/).

Inspect provides many built-in components, including facilities for prompt engineering, tool usage, multi-turn dialog, and model graded evaluations. Extensions to Inspect (e.g. to support new elicitation and scoring techniques) can be provided by other Python packages.

To get started with Inspect, please see the documentation at <https://inspect.aisi.org.uk/>.

***

To work on development of Inspect, clone the repository and install with the `-e` flag and `[dev]` optional dependencies:

```bash
git clone https://github.com/UKGovernmentBEIS/inspect_ai.git
cd inspect_ai
pip install -e ".[dev]"
```

Optionally install pre-commit hooks via

```bash
make hooks
```

Run linting, formatting, and tests via

```bash
make check
make test
```

If you use VS Code, you should be sure to have installed the recommended extensions (Python, Ruff, and MyPy). Note that you'll be prompted to install these when you open the project in VS Code.

## Contributing to Documentation

The documentation for Inspect is built using [Quarto](https://quarto.org/) and is located in the `docs/` directory. All documentation files use the `.qmd` format (Quarto Markdown).

### Setting up documentation development

To work on documentation for Inspect, install with the `-e` flag and `.[doc]` optional dependencies:

```bash
pip install -e ".[doc]"
```

### Install the Quarto VS Code Extension

For developers using VS Code, we recommend installing the [Quarto VS Code Extension](https://marketplace.visualstudio.com/items?itemName=quarto.quarto)

### Previewing documentation changes

To start a local development server that watches for changes and automatically rebuilds the documentation:

```bash
quarto preview docs
```

This will serve the documentation at <http://localhost:4200> and automatically reload when you make changes to any `.qmd` files.

### Building documentation

To build the documentation without starting a preview server:

```bash
quarto render docs
```