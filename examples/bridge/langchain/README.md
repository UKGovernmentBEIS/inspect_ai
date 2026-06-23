## LangChain Agent

This example demonstrates using a native [LangChain](https://www.langchain.com/) agent with Inspect to perform Q/A using the [Tavili Search API](https://tavily.com/). 

The example uses the [`agent_bridge()`](https://inspect.aisi.org.uk/agent-bridge.html) which enables integrating arbitrary 3rd party agent frameworks into Inspect. Source files include:

| File            | Description                                                                            |
|------------------|------------------------------------------------------|
| [agent.py](agent.py)      | LangChain agent created using `agent_bridge()`. |
| [task.py](task.py)       | Evaluation task which uses the agent.          |
| [dataset.json](dataset.json) | Dataset with questions and ideal answers.                                              |
| [requirements.txt](requirements.txt) | Dependencies for LangChain example. |


To run the example, first, be sure you have a [Tavili](https://tavily.com/) account and set the `TAVILY_API_KEY` environment variable.

To run the example, install the required dependencies as follows:

``` python
cd examples/bridge/langchain
pip install -r requirements.txt
```

Now you should be able to run the example as follows against various models:

``` bash
inspect eval task.py --model openai/gpt-4o
inspect eval task.py --model anthropic/claude-3-7-sonnet-latest
inspect eval task.py --model google/gemini-2.5-pro
```
