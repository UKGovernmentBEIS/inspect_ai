## HTTP Proxy Interception

This example demonstrates how to intercept and remap HTTP requests made by an agent running inside a container. It installs [mitmproxy](https://mitmproxy.org/) in the container and instructs [Claude Code](https://docs.anthropic.com/en/docs/claude-code) to integrate a non-existent AI model API ("FutureModel") into a codebase.

The Docker sandbox network policy is the containment control: `network_mode: none` disables ordinary container egress, so the agent cannot bypass the proxy by ignoring or unsetting the proxy environment variables. At runtime, the agent has no direct internet access. This is an intentional security boundary, but it may limit agent performance on tasks that benefit from downloading packages or consulting online resources. The loopback interface remains available for the in-container data path:

1. Compatible HTTP clients send the FutureModel request to mitmproxy on `localhost:8080` using `HTTP_PROXY` or `HTTPS_PROXY`.
2. mitmproxy intercepts the request and remaps the non-existent API host to the `sandbox_agent_bridge` model proxy on `localhost:13131`.
3. The sandbox agent bridge routes the model request to Inspect on the host.

mitmproxy provides request interception and remapping, not the egress boundary. Its addon also returns a `403` response for non-FutureModel requests that reach the proxy.

The example includes the following source files:

| File | Description |
|------|-------------|
| [task.py](task.py) | Evaluation task which uses the Claude Code agent. |
| [claude.py](claude.py) | Claude Code agent (invokes the Claude CLI within the sandbox). |
| [compose.yaml](compose.yaml) | Compose config that disables network egress and directs compatible HTTP clients to mitmproxy. |
| [Dockerfile](Dockerfile) | Dockerfile which installs Claude Code and mitmproxy. |
| [entrypoint.sh](entrypoint.sh) | Starts mitmproxy and installs its CA cert. |
| [remap.py](remap.py) | mitmproxy addon that remaps and blocks requests. |

You can run the example against various models by evaluating the `task.py` file:

```bash
inspect eval task.py --model openai/gpt-5
inspect eval task.py --model anthropic/claude-3-7-sonnet-latest
inspect eval task.py --model google/gemini-2.5-pro
```
