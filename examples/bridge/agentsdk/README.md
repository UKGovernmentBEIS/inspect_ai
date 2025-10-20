## OpenAI Agents SDK

This example demonstrates using a native [OpenAI Agents SDK](https://openai.github.io/openai-agents-python/) agent with Inspect.

The example uses the [`agent_bridge()`](https://inspect.aisi.org.uk/agent-bridge.html) which enables integrating arbitrary 3rd party agent frameworks into Inspect. 

Source files include:


| File            | Description                                                                            |
|------------------|------------------------------------------------------|
| [agent.py](agent.py)      | Agent SDK agent created using `agent_bridge()`. |
| [task.py](task.py)       | Evaluation task which uses the agent.          |
| [dataset.json](dataset.json) | Dataset with questions and ideal answers.                                              |

To run the example, install the required dependencies as follows:

``` python
pip install openai-agents
pip install --upgrade openai
```

Now you should be able to run the example as follows against various models:

``` bash
inspect eval task.py --model openai/gpt-5
inspect eval task.py --model anthropic/claude-3-7-sonnet-latest
inspect eval task.py --model google/gemini-2.5-pro
```


