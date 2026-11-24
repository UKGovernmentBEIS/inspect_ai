
Another consideration is `max_samples`, which is the maximum number of samples to run concurrently within a task. Larger numbers of concurrent samples will result in higher throughput, but will also result in completed samples being written less frequently to the log file, and consequently less total recoverable samples in the case of an interrupted task.

By default, `max_samples` tracks the model's current connection limit: with adaptive connections (the default) it follows the controller, and with static concurrency it is set to `max_connections` (note that it would rarely make sense to set it _lower_ than `max_connections`). A small limit will typically result in samples being written to the log frequently. On the other hand, setting a very large limit (e.g. 100 `max_connections` for a dataset with 100 samples) may result in very few recoverable samples in the case of an interruption.

{{< include _setting_max_samples.md >}}

