# GAIA
This is an Inspect AI implementation of [the GAIA (General AI Assistants)](https://arxiv.org/abs/2311.12983) benchmark, consisting of 450 questions testing tool use on realistic assistant tasks (mostly web browsing).

## Prerequisites

1) **Installation** Install the `inspect_evals` Python package with:

   ```bash
   pip install inspect_ai[inspect_evals]@git+https://github.com/UKGovernmentBEIS/inspect_ai
   ```

2) **Docker Engine** The GAIA task uses [tool calling](https://inspect.ai-safety-institute.org.uk/tools.html) to enable the model to execute bash commands. Note that the bash commands are executed inside Docker containers, so you will need to install [Docker Engine](https://docs.docker.com/engine/install/) in order to run the evaluation.

3) **Hugging Face Dataset** Upon running the GAIA task, it will attempt to download the dataset from the HuggingFace hub. For this to work, you will need to gain access to the dataset (by filling out a form on [the GAIA huggingface repository](https://huggingface.co/datasets/gaia-benchmark/GAIA)), and also [create and set an access token](https://huggingface.co/docs/hub/en/security-tokens). You will need to define the `HF_TOKEN` environment variable to access the dataset:

   ```
   HF_TOKEN=<hf-token>
   ```

4) **Search Provider** The default solver for the GAIA task uses the inspect [web_search()](https://inspect.ai-safety-institute.org.uk/tools.html#sec-web-search) tool. The `web_search()` tool uses [Google Programmable Search Engine](https://programmablesearchengine.google.com/about/). To use it you will therefore need to setup your own Google Programmable Search Engine and also enable the [Programmable Search Element Paid API](https://developers.google.com/custom-search/docs/paid_element). Then, ensure that the following environment variables are defined:

   ```
   GOOGLE_CSE_ID=<google-search-engine-id>
   GOOGLE_CSE_API_KEY=<google-api-key>
   ```


## Usage

After fulfiling the prerequisites, run the GAIA task aginst various models with:

```bash
$ inspect eval inspect_evals/gaia --model openai/gpt-4o
$ inspect eval inspect_evals/gaia --model google/gemini-1.5-pro
```

You might want to limit the number of samples evaluated for initial experimentation:

```bash
$ inspect eval inspect_evals/gaia --model openai/gpt-4o --limit 5
```

## Development

If you want to develop solver for the GAIA task, import the `@task` from the `gaia` module and pass your own solver to it. For example:

```python
from inspect_ai import eval
from inspect_ai.solver import use_tools, generate, system_message, basic_agent
from inspect_ai.tool import bash, web_search

from inspect_evals.gaia import gaia

agent = basic_agent(tools=[bash()])
task = gaia(plan=agent)

eval(task, model="openai/gpt-4o")
```

See the documentation on the Inspect [Agents API](https://inspect.ai-safety-institute.org.uk/agents-api.html) for additional information on developing agents.

### Test Split

You can evaluate against the "test" split with:

```python
agent = basic_agent(tools=[bash()])
task = gaia(plan=agent, split="test")

eval(task, model="openai/gpt-4o")
```

Note that the GAIA "test" split does not come with any solutions so is not scored (rather, solutions are uploaded to the online leaderboard).