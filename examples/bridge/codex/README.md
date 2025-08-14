## Codex CLI Agent

This example demonstrates using the [OpenAI Codex CLI](https://github.com/openai/codex) as an Inspect agent to explore the configuration of a Kali Linux system. The example uses the Inspect [`bridge()`](https://inspect.aisi.org.uk/agent-bridge.html) agent which enables integrating arbitrary 3rd party agent frameworks into Inspect.

The example includes the following source files:

| File | Description |
|-------------------|-----------------------------------------------------|
| [agent.py](agent.py) | Codex agent (invokes the codex CLI within the container). |
| [task.py](task.py) | Evaluation task which uses the `codex_agent()` |
| [dataset.json](dataset.json) | Dataset with questions and answer rubrics. |
| [Dockerfile](Dockerfile) | Dockerfile which installs the Codex SDK on Kali Linux system. |

You can run the example against various models by evaluating the `task.py` file:

``` bash
inspect eval task.py --model openai/gpt-5
inspect eval task.py --model anthropic/claude-3-7-sonnet-latest
inspect eval task.py --model google/gemini-2.5-pro
```