# Filesystems – Inspect

## Filesystems with fsspec

Datasets, prompt templates, and evaluation logs can be stored using either the local filesystem or a remote filesystem. Inspect uses the [fsspec](https://filesystem-spec.readthedocs.io/en/latest/) package to read and write files, which provides support for a wide variety of filesystems, including:

- [Amazon S3](https://aws.amazon.com/pm/serv-s3)
- [Hugging Face Storage Buckets](https://huggingface.co/docs/hub/storage-buckets)
- [Google Cloud Storage](https://gcsfs.readthedocs.io/en/latest/)
- [Azure Blob Storage](https://github.com/fsspec/adlfs)
- [Azure Data Lake Storage](https://github.com/fsspec/adlfs)
- [DVC](https://dvc.org/doc/api-reference/dvcfilesystem)

Support for [Amazon S3](./eval-logs.html.md#sec-amazon-s3) is built in to Inspect via the [s3fs](https://pypi.org/project/s3fs/) package. [Hugging Face Storage Buckets](./eval-logs.html.md#sec-hugging-face-storage-buckets) are supported via the optional [huggingface_hub](https://pypi.org/project/huggingface-hub/) filesystem integration. Other filesystems may require installation of additional packages. See the list of [built in filesystems](https://filesystem-spec.readthedocs.io/en/latest/api.html#built-in-implementations) and [other known implementations](https://filesystem-spec.readthedocs.io/en/latest/api.html#other-known-implementations) for all supported storage back ends.

See [Custom Filesystems](#sec-custom-filesystems) below for details on implementing your own fsspec compatible filesystem as a storage back-end.

## Filesystem Functions

The following Inspect API functions use **fsspec**:

- [resource()](./reference/inspect_ai.util.html.md#resource) for reading prompt templates and other supporting files.

- [csv_dataset()](./reference/inspect_ai.dataset.html.md#csv_dataset) and [json_dataset()](./reference/inspect_ai.dataset.html.md#json_dataset) for reading datasets (note that `files` referenced within samples can also use fsspec filesystem references).

- [list_eval_logs()](./reference/inspect_ai.log.html.md#list_eval_logs) , [read_eval_log()](./reference/inspect_ai.log.html.md#read_eval_log), [write_eval_log()](./reference/inspect_ai.log.html.md#write_eval_log), and [retryable_eval_logs()](./reference/inspect_ai.log.html.md#retryable_eval_logs).

For example, to use S3 you would prefix your paths with `s3://`:

``` python
# read a prompt template from s3
prompt_template("s3://inspect-prompts/ctf.txt")

# read a dataset from S3
csv_dataset("s3://inspect-datasets/ctf-12.csv")

# read eval logs from S3
list_eval_logs("s3://my-s3-inspect-log-bucket")

# read eval logs from a Hugging Face Storage Bucket
list_eval_logs("hf://buckets/my-org/inspect-logs")
```

## Custom Filesystems

See the fsspec [developer documentation](https://filesystem-spec.readthedocs.io/en/latest/developer.html) for details on implementing a custom filesystem. Note that if your implementation is *only* for use with Inspect, you need to implement only the subset of the fsspec API used by Inspect. The properties and methods used by Inspect include:

- `sep`
- `open()`
- `makedirs()`
- `info()`
- `created()`
- `exists()`
- `ls()`
- `walk()`
- `unstrip_protocol()`
- `invalidate_cache()`

As with Model APIs and Sandbox Environments, fsspec filesystems should be registered using a [setuptools entry point](https://setuptools.pypa.io/en/latest/userguide/entry_point.html). For example, if your package is named `evaltools` and you have implemented a `myfs://` filesystem using the `MyFs` class exported from the root of the package, you would register it like this in `pyproject.toml`:

``` toml
[project.entry-points."fsspec.specs"]
myfs = "evaltools:MyFs"
```

``` toml
[project.entry-points."fsspec.specs"]
myfs = "evaltools:MyFs"
```

``` toml
[tool.poetry.plugins."fsspec.specs"]
myfs = "evaltools:MyFs"
```

Once this package is installed, you’ll be able to use `myfs://` with Inspect without any further registration.
