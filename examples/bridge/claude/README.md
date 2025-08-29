## Claude Code Agent

This example demonstrates using the [Claude Code](https://docs.anthropic.com/en/docs/claude-code) as an Inspect agent to explore the configuration of a Kali Linux system. The example uses the Inspect [`sandbox_agent_bridge()`](https://inspect.aisi.org.uk/agent-bridge.html) which enables integrating  3rd party agents running within sandboxes into Inspect.

The example includes the following source files:

| File | Description |
|-------------------|-----------------------------------------------------|
| [task.py](task.py) | Evaluation task which uses the claude code agent. |
| [claude.py](claude.py) | Claude code agent (invokes the claude CLI within the sandbox). |
| [dataset.json](dataset.json) | Dataset with questions and answer rubrics. |
| [Dockerfile](Dockerfile) | Dockerfile which installs the Claude Code on a Kali Linux system. |

You can run the example against various models by evaluating the `task.py` file:

``` bash
inspect eval task.py --model openai/gpt-5
inspect eval task.py --model anthropic/claude-3-7-sonnet-latest
inspect eval task.py --model google/gemini-2.5-pro
```