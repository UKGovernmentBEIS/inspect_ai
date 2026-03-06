[<img width="295" src="https://inspect.aisi.org.uk/images/aisi-logo.svg" />](https://aisi.gov.uk/)

Welcome to Inspect, a framework for large language model evaluations created by the [UK AI Security Institute](https://aisi.gov.uk/).

Inspect provides many built-in components, including facilities for prompt engineering, tool usage, multi-turn dialog, and model graded evaluations. Extensions to Inspect (e.g. to support new elicitation and scoring techniques) can be provided by other Python packages.

To get started with Inspect, please see the documentation at <https://inspect.aisi.org.uk/>.

Inspect also includes a collection of over 100 pre-built evaluations ready to run on any model (learn more at [Inspect Evals](https://ukgovernmentbeis.github.io/inspect_evals/))

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

***

To work on the Inspect documentation, install the optional `[doc]` dependencies with the `-e` flag and build the docs:

```
pip install -e ".[doc]"
cd docs
quarto render # or 'quarto preview'
```

If you intend to work on the docs iteratively, you'll want to install the Quarto extension in VS Code.