## LangChain Agent

This example demonstrates using a native [LangChain](https://www.langchain.com/) agent with Inspect to perform Q/A using the [Tavili Search API](https://tavily.com/). The example uses new [`bridge()`](https://inspect.aisi.org.uk/agent-bridge.html) agent which enables integrating arbitrary 3rd party agent frameworks into Inspect.

The example includes the following source files:

| File            | Description                                                                            |
|------------------|------------------------------------------------------|
| [agent.py](agent.py)      | LangChain agent (this file has no dependencies on Inspect, it is pure LangChain). |
| [task.py](task.py)       | Evaluation task which uses `bridge()` to use the LangChain agent as an Inspect agent.          |
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
inspect eval task.py --model openai/gpt-4 
inspect eval task.py --model anthropic/claude-3-haiku-20240307
inspect eval task.py --model google/gemini-1.5-pro
```
