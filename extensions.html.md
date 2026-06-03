# Extensions – Inspect

Inspect can be extended to integrate with systems and workflows beyond what the core package supports:

|  |  |
|----|----|
| [Model APIs](./extensions-model-api.html.md) | Model hosting services, local inference engines, etc. |
| [Components](./extensions-components.html.md) | Tasks, solvers, scorers, and tools distributed in packages. |
| [Sandboxes](./extensions-sandboxes.html.md) | Local or cloud container runtimes for tool execution. |
| [Approvers](./extensions-approvers.html.md) | Approve, modify, or reject tool calls. |
| [Hooks](./extensions-hooks.html.md) | Logging and monitoring lifecycle hooks. |
| [Filesystems](./extensions-filesystems.html.md) | Storage for datasets, prompts, and evaluation logs. |

Each of the extension types above can be implemented within your own Python package and then used without any special registration—Inspect discovers them automatically through [setuptools entry points](https://setuptools.pypa.io/en/latest/userguide/entry_point.html).
