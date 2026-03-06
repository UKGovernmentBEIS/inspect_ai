## Pydantic AI

This example demonstrates using a native [Pydantic AI](https://ai.pydantic.dev/) agent with Inspect.

The example uses the [`agent_bridge()`](https://inspect.aisi.org.uk/agent-bridge.html) which enables integrating arbitrary 3rd party agent frameworks into Inspect. 

Source files include:


| File            | Description                                                                            |
|------------------|------------------------------------------------------|
| [agent.py](agent.py)      | Pydantic AI agent created using `agent_bridge()`. |
| [task.py](task.py)       | Evaluation task which uses the agent.          |
| [dataset.json](dataset.json) | Dataset with questions and ideal answers.                                              |

To run the example, install the required dependencies as follows:

``` python
pip install pydantic-ai
```

Now you should be able to run the example as follows against various models:

``` bash
inspect eval task.py --model openai/gpt-5
inspect eval task.py --model anthropic/claude-3-7-sonnet-latest
inspect eval task.py --model google/gemini-2.5-pro
```


