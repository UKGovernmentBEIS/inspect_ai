## AutoGen Agent

This example demonstrates using a native [AutoGen](https://microsoft.github.io/autogen/) agent with Insepct to perform web research using the using the AutoGen [MultiModalWebSurfer](https://microsoft.github.io/autogen/stable//reference/python/autogen_ext.agents.web_surfer.html#autogen_ext.agents.web_surfer.MultimodalWebSurfer). The example uses the new [`bridge()`](https://github.com/UKGovernmentBEIS/inspect_ai/pull/1181) solver which enables integrating arbitrary 3rd party agent frameworks into Inspect.

The example includes the following source files:

| File            | Description                                                                            |
|------------------|------------------------------------------------------|
| [agent.py](agent.py)      | AutoGen agent (this file has no dependencies on Insepct, it is pure AutoGen). |
| [task.py](task.py)       | Evaluation task which uses `bridge()` to use the AutoGen agent as a solver.          |
| [dataset.json](dataset.json) | Dataset with questions and ideal answers.                                              |


To run the example, install the following Python packages then install Playwright:

```bash
pip install -U playwright autogen-agentchat "autogen-ext[openai,web-surfer]"
playwright install
```

Now you should be able to run the example as follows against various models:

``` bash
inspect eval examples/bridge/autogen --model openai/gpt-4 
inspect eval examples/bridge/autogen --model anthropic/claude-3-haiku-20240307
inspect eval examples/bridge/autogen --model google/gemini-1.5-pro
```







