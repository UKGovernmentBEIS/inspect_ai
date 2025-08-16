## AutoGen Agent

This example demonstrates using a native [AutoGen](https://microsoft.github.io/autogen/) agent with Inspect to perform web research using the using the AutoGen [MultiModalWebSurfer](https://microsoft.github.io/autogen/stable//reference/python/autogen_ext.agents.web_surfer.html#autogen_ext.agents.web_surfer.MultimodalWebSurfer). The example uses the Inspect [`agent_bridge()`](https://inspect.aisi.org.uk/agent-bridge.html) agent which enables integrating arbitrary 3rd party agent frameworks into Inspect.

The example includes the following source files:

| File | Description |
|-------------------|-----------------------------------------------------|
| [agent.py](agent.py) | AutoGen agent which uses `agent_bridge()`. |
| [task.py](task.py) | Evaluation task which uses the AutoGen agent. |
| [dataset.json](dataset.json) | Dataset with questions and ideal answers. |
| [requirements.txt](requirements.txt) | Dependencies for AutoGen example. |

To run the example, install the required dependencies then install Playwright:

``` bash
cd examples/bridge/autogen
pip install -r requirements.txt
playwright install
```

Now you should be able to run the example as follows against various models:

``` bash
inspect eval task.py --model openai/gpt-4o
inspect eval task.py --model anthropic/claude-3-7-sonnet-latest
inspect eval task.py --model google/gemini-2.5-pro
```