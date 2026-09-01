

### Max Sandboxes

The `max_sandboxes` option determines how many sandboxes can be executed in parallel. Individual sandbox providers can establish their own default limits (for example, the Docker provider defaults to twice the number of processors available to the eval — which under a container CPU limit such as `docker --cpus` or a Kubernetes `limits.cpu` is the limit rather than the host's processor count). You can modify this option as required, but be aware that container runtimes have resource limits, and pushing up against and beyond them can lead to instability and failed evaluations.

When a `max_sandboxes` is applied, an indicator at the bottom of the task status screen will be shown:

![](images/task-max-sandboxes.png)

Note that when `max_sandboxes` is applied this effectively creates a global `max_samples` limit that is equal to the `max_sandboxes`.

### Max Subprocesses

The `max_subprocesses` option determines how many subprocess calls can run in parallel. By default, this is the number of processors available to the eval (under a container CPU limit, that limit rather than the host's processor count). Depending on the nature of execution done inside sandbox environments, you might benefit from increasing or decreasing `max_subprocesses`.

### Max Samples

{{< include _max_samples.md >}}