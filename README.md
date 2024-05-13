[<img width="295" src="https://ukgovernmentbeis.github.io/inspect_ai/images/aisi-logo.png" />](https://www.gov.uk/government/organisations/ai-safety-institute)

Welcome to Inspect, a framework for large language model evaluations created by the [UK AI Safety Institute](https://www.gov.uk/government/organisations/ai-safety-institute).

Inspect provides many built-in components, including facilities for prompt engineering, tool usage, multi-turn dialog, and model graded evaluations. Extensions to Inspect (e.g. to support new elicitation and scoring techniques) can be provided by other Python packages.

To get started with Inspect, please see the documentation at <https://UKGovernmentBEIS.github.io/inspect_ai/>.

***

#### Development

To work on development of Inspect, clone the repository and install with the `-e` flag and `[dev]` optional dependencies:

```         
$ git clone https://github.com/UKGovernmentBEIS/inspect_ai.git
$ cd inspect_ai
$ pip install -e ".[dev]"
```

If you use VS Code, you should be sure to have installed the recommended extensions (Python, Ruff, and MyPy). Note that you'll be prompted to install these when you open the project in VS Code.
