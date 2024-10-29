from inspect_ai.dataset._dataset import Dataset


def dataset_with_ids(
    dataset: Dataset,
    limit: int | tuple[int, int] | None,
) -> Dataset:
    # apply limit to dataset
    dataset_limit = (
        slice(0, len(dataset))
        if limit is None
        else (slice(*limit) if isinstance(limit, tuple) else slice(0, limit))
    )
    dataset = dataset[dataset_limit]

    # add sample ids to dataset if they aren't there (start at 1 not 0)
    for id, sample in zip(range(dataset_limit.start, dataset_limit.stop), dataset):
        if sample.id is None:
            sample.id = id + 1

    return dataset
