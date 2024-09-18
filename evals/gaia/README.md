# GAIA
This is an inspect-native implementation of [the GAIA (General AI Assistants)](https://arxiv.org/abs/2311.12983) benchmark, consisting of 450 questions testing tool use on realistic assistant tasks (mostly web browsing).

## Installation

1) **Install requirements.** As well as the requirements provided by inspect, this benchmark has its own dependencies. You can install them in your virtual environment by running ```pip install -r requirements.txt```
2) **Download the dataset.** Upon loading gaia.py file, it will attempt to download the dataset from the HuggingFace hub. For this to work, you will need to gain access to the dataset (by filling out a form on [the GAIA huggingface repository](https://huggingface.co/datasets/gaia-benchmark/GAIA)), and also [create and set an access token](https://huggingface.co/docs/hub/en/security-tokens).

## Usage
After install, the GAIA benchmark can be used in the following way:

```python
from inspect_ai import eval
from inspect_ai.solver import use_tools, generate, system_message, basic_agent
from inspect_ai.tool import bash, web_search
from gaia import gaia

# Create a task to attempt to solve GAIA with a basic agent.
agent = basic_agent(tools=[bash()])
task = gaia(split="validation", plan=agent)

# For the demonstration, we will select only the first 5 tasks.
eval(task, model="openai/gpt-4o", limit=5)
```

Note that the GAIA test split does not come with any solutions - they must be uploaded to the online leaderboard.