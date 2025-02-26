::: {.callout-note appearance="simple"}
If your task involves tool calls and/or sandboxes, then you will likely want to set `max_samples` to greater than `max_connections`, as your samples will sometimes be calling the model (using up concurrent connections) and sometimes be executing code in the sandbox (using up concurrent subprocess calls). While running tasks you can see the utilization of connections and subprocesses in realtime and tune your `max_samples` accordingly.
:::
