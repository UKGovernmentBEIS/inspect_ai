from inspect_ai._util.file import filesystem

from .._dataset import Dataset


def resolve_sample_files(dataset: Dataset) -> None:
    """Resolve relative file paths to absolute (using the input file path)"""
    # bail if the dataset has no location
    if not dataset.location:
        return

    # filesystem and parent for resolving paths
    fs = filesystem(dataset.location)
    parent_dir = fs.sep.join(dataset.location.split(fs.sep)[:-1])

    # for each sample that has files
    for sample in dataset:
        if sample.files is not None:
            for path in sample.files.keys():
                # try/except (and ignore) to tolerate 'paths' that are actually
                # file contents (so will trip OS name too long constraints)
                try:
                    target_file = f"{parent_dir}{fs.sep}{sample.files[path]}"
                    if fs.exists(target_file):
                        sample.files[path] = target_file
                except OSError:
                    pass
