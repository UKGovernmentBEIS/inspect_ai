## HTTP Proxy Interception

This example demonstrates how to intercept, modify, and control HTTP requests made by an agent running inside a container. This example involves installing [mitmproxy](https://mitmproxy.org/) in a container and instructing [Claude Code](https://docs.anthropic.com/en/docs/claude-code) to integrate a non-existent AI model API ("FutureModel") into a codebase.

The example includes the following source files:

| File | Description |
|------|-------------|
| [task.py](task.py) | Evaluation task which uses the Claude Code agent. |
| [claude.py](claude.py) | Claude Code agent (invokes the Claude CLI within the sandbox). |
| [compose.yaml](compose.yaml) | Compose config with mitmproxy for HTTP interception. |
| [Dockerfile](Dockerfile) | Dockerfile which installs Claude Code and mitmproxy. |
| [entrypoint.sh](entrypoint.sh) | Starts mitmproxy and installs its CA cert. |
| [remap.py](remap.py) | mitmproxy addon that remaps and blocks requests. |

You can run the example against various models by evaluating the `task.py` file:

```bash
inspect eval task.py --model openai/gpt-5
inspect eval task.py --model anthropic/claude-3-7-sonnet-latest
inspect eval task.py --model google/gemini-2.5-pro
```
