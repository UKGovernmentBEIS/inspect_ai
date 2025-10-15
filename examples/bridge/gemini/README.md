## Gemini CLI Agent

This example demonstrates using the [Google Gemini CLI](https://github.com/google-gemini/gemini-cli) as an Inspect agent to explore the configuration of a Kali Linux system. The example uses the Inspect [`sandbox_agent_bridge()`](https://inspect.aisi.org.uk/agent-bridge.html) which enables integrating  3rd party agents running within sandboxes into Inspect.

Note that this example relies features that are available only in the development version of Inspect. To install the development version from GitHub:

``` bash
pip install git+https://github.com/UKGovernmentBEIS/inspect_ai
```

> [!NOTE] This example is intended as a demonstration of the basic mechanics of using the sandbox agent bridge. For a more feature-rich implementation of a Gemini CLI agent for Inspect see <https://meridianlabs-ai.github.io/inspect_swe/>.

The example includes the following source files:

| File | Description |
|-------------------|-----------------------------------------------------|
| [task.py](task.py) | Evaluation task which uses the gemini agent. |
| [gemini.py](gemini.py) | Gemini agent (invokes the gemini CLI within the sandbox). |
| [dataset.json](dataset.json) | Dataset with questions and answer rubrics. |
| [Dockerfile](Dockerfile) | Dockerfile which installs the Gemini CLI on a Kali Linux system. |

You can run the example against various models by evaluating the `task.py` file:

``` bash
inspect eval task.py --model openai/gpt-5
inspect eval task.py --model anthropic/claude-3-7-sonnet-latest
inspect eval task.py --model google/gemini-2.5-pro
```
