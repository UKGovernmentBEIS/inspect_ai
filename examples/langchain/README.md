## LangChain Agent

This example demonstrates creating a custom solver that utilises a LangChain agent to perform Q and A using Wikipedia. The example includes the following source files:

| File                   | Description                                                                                     |
|------------------------|-------------------------------------------------------------------------------------------------|
| `.gitignore`           | Ignore the `.venv` directory and the `.env` file containing environment variables for the eval. |
| `.env.example`         | Prototype of `.env` file (copy this to `.env` and provide your `TAVILY_API_KEY`).               |
| `inspect_langchain.py` | Utilities for creating inspect solvers that use LangChain agents.                               |
| `wikipedia.py`         | Evaluation task and custom solver that uses the search agent.                                   |
| `wikipedia.jsonl`      | Dataset with questions and ideal answers.                                                       |

To run this example, first, be sure you provide a `.env` file that defines a `TAVILY_API_KEY` ([Tavily](https://tavily.com/) is a search API for LLM agents). Note that `.env` files should always be included in `.gitignore` as they often contain secrets!

Next, create a virtual environment and install the required dependencies:

``` bash
$ python3 -m venv .venv
$ source .venv/bin/activate
$ pip install -r requirements.txt
```

Now you should be able to run the example as follows:

``` python
$ inspect eval --model openai/gpt-4 
```

This example will run with any model provider that supports tool use (so Anthropic, Google Gemini, and Mistral will all work as well).

If you want to run in verbose mode (to see the agent's queries printed out), pass the `verbose` task parameter:

``` bash
$ inspect eval --model openai/gpt-4  -T verbose=true --limit 1
```

Note that we specify `--limit 1` so that the verbose output from multiple samples is not intermixed.