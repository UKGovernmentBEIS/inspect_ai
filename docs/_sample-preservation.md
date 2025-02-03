### Sample Preservation {#sec-sample-preservation}

When retrying a log file, Inspect will attempt to re-use completed samples from the original task. This can result in substantial time and cost savings compared to starting over from the beginning.

#### IDs and Shuffling

An important constraint on the ability to re-use completed samples is matching them up correctly with samples in the new task. To do this, Inspect requires stable unique identifiers for each sample. This can be achieved in 1 of 2 ways:

1.  Samples can have an explicit `id` field which contains the unique identifier; or

2.  You can rely on Inspect's assignment of an auto-incrementing `id` for samples, however this *will not work correctly* if your dataset is shuffled. Inspect will log a warning and not re-use samples if it detects that the `dataset.shuffle()` method was called, however if you are shuffling by some other means this automatic safeguard won't be applied.

If dataset shuffling is important to your evaluation and you want to preserve samples for retried tasks, then you should include an explicit `id` field in your dataset.

#### Max Samples

{{< include _max_samples.md >}}
