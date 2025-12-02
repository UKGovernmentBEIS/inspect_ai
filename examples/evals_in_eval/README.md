## Evals Inside An Eval

This example demonstrates running Inspect evals (in Docker containers) inside an Inspect eval. The example involves installing Inspect AI itself in a container and instructing [Claude Code](https://docs.anthropic.com/en/docs/claude-code) as an Inspect agent to run evals.

> [!NOTE] The correct way to run an eval in an eval is to shell out a subprocess that has the eval you want to run. That protects many error conditions you would run into if you tried to run an eval in an eval. This is global state, background tasks (e.g. batch jobs), and contention for the UI.

The example includes the following source files:

| File | Description |
|------|-------------|
| [task.py](task.py) | Evaluation task which uses the claude code agent. |
| [file_probe.py](file_probe.py) | Evaluation task which uses the `list_files()` tool. |
| [bash_task.py](bash_task.py) | Evaluation task which uses the `bash()` tool. |
| [claude.py](claude.py) | Claude code agent (invokes the claude CLI within the sandbox). |
| [compose.yaml](compose.yaml) | Docker-in-Docker compose config with dind sidecar. |
| [Dockerfile](Dockerfile) | Dockerfile which installs Docker, Inspect AI, and Claude Code. |

You can run the example by evaluating the `task.py` file:

```bash
inspect eval task.py --model anthropic/claude-3-7-sonnet-latest
```
