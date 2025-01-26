## LangChain Agent

This example demonstrates using a native [LangChain](https://www.langchain.com/) agent with Inspect to perform Q/A using the [Tavili Search API](https://tavily.com/). The example uses the new [`bridge()`](https://github.com/UKGovernmentBEIS/inspect_ai/pull/1181) solver which enables integrating arbitrary 3rd party agent frameworks into Inspect.

The example includes the following source files:

| File            | Description                                                                            |
|------------------|------------------------------------------------------|
| [agent.py](agent.py)      | LangChain agent (this file has no dependencies on Insepct, it is pure LangChain). |
| [task.py](task.py)       | Evaluation task which uses `bridge()` to use the LangChain agent as a solver.          |
| [dataset.json](dataset.json) | Dataset with questions and ideal answers.                                              |

To run the example, first, be sure you have a [Tavili](https://tavily.com/) account and set the `TAVILY_API_KEY` environment variable.

Then, install the following LangChain packages:

``` python
pip install langchain-core langchain-openai langchain-community langgraph
```

Now you should be able to run the example as follows against various models:

``` bash
inspect eval examples/bridge/langchain --model openai/gpt-4 
inspect eval examples/bridge/langchain --model anthropic/claude-3-haiku-20240307
inspect eval examples/bridge/langchain --model google/gemini-1.5-pro
```
