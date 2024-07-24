### Sample Preservation {#sec-sample-preservation}

When retrying a log file, Inspect will attempt to re-use completed samples from the original task. This can result in substantial time and cost savings compared to starting over from the beginning.

#### IDs and Shuffling

An important constraint on the ability to re-use completed samples is matching them up correctly with samples in the new task. To do this, Inspect requires stable unique identifiers for each sample. This can be achieved in 1 of 2 ways:

1.  Samples can have an explicit `id` field which contains the unique identifier; or

2.  You can rely on Inspect's assignment of an auto-incrementing `id` for samples, however this *will not work correctly* if your dataset is shuffled. Inspect will log a warning and not re-use samples if it detects that the `dataset.shuffle()` method was called, however if you are shuffling by some other means this automatic safeguard won't be applied.

If dataset shuffling is important to your evaluation and you want to preserve samples for retried tasks, then you should include an explicit `id` field in your dataset.

#### Max Samples

Another consideration is `max_samples`, which is the maximum number of samples to run concurrently within a task. Larger numbers of concurrent samples will result in higher throughput, but will also result in completed samples being written less frequently to the log file, and consequently less total recovable samples in the case of an interrupted task.

By default, Inspect sets the value of `max_samples` to `max_connections + 1`, ensuring that the model API is always fully saturated (note that it would rarely make sense to set it _lower_ than `max_connections`). The default `max_connections` is 10, which will typically result in samples being written to the log frequently. On the other hand, setting a very large `max_connections` (e.g. 100 `max_connections` for a dataset with 100 samples) may result in very few recoverable samples in the case of an interruption. 

