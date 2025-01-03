
Another consideration is `max_samples`, which is the maximum number of samples to run concurrently within a task. Larger numbers of concurrent samples will result in higher throughput, but will also result in completed samples being written less frequently to the log file, and consequently less total recovable samples in the case of an interrupted task.

By default, Inspect sets the value of `max_samples` to `max_connections + 1` (note that it would rarely make sense to set it _lower_ than `max_connections`). The default `max_connections` is 10, which will typically result in samples being written to the log frequently. On the other hand, setting a very large `max_connections` (e.g. 100 `max_connections` for a dataset with 100 samples) may result in very few recoverable samples in the case of an interruption. 

{{< include _setting_max_samples.md >}}

