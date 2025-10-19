# inspect_ai.dataset


## Readers

### csv_dataset

Read dataset from CSV file.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/81d8689032370a3b30a10fe8e8ac0be5efae8788/src/inspect_ai/dataset/_sources/csv.py#L21)

``` python
def csv_dataset(
    csv_file: str,
    sample_fields: FieldSpec | RecordToSample | None = None,
    auto_id: bool = False,
    shuffle: bool = False,
    seed: int | None = None,
    shuffle_choices: bool | int | None = None,
    limit: int | None = None,
    dialect: str = "unix",
    encoding: str = "utf-8",
    name: str | None = None,
    fs_options: dict[str, Any] | None = None,
    fieldnames: list[str] | None = None,
    delimiter: str = ",",
) -> Dataset
```

`csv_file` str  
Path to CSV file. Can be a local filesystem path, a path to an S3 bucket
(e.g. “s3://my-bucket”), or an HTTPS URL. Use `fs_options` to pass
arguments through to the `S3FileSystem` constructor.

`sample_fields` [FieldSpec](inspect_ai.dataset.qmd#fieldspec) \| [RecordToSample](inspect_ai.dataset.qmd#recordtosample) \| None  
Method of mapping underlying fields in the data source to Sample
objects. Pass `None` if the data is already stored in `Sample` form
(i.e. has “input” and “target” columns.); Pass a `FieldSpec` to specify
mapping fields by name; Pass a `RecordToSample` to handle mapping with a
custom function that returns one or more samples.

`auto_id` bool  
Assign an auto-incrementing ID for each sample.

`shuffle` bool  
Randomly shuffle the dataset order.

`seed` int \| None  
Seed used for random shuffle.

`shuffle_choices` bool \| int \| None  
Whether to shuffle the choices. If an int is passed, this will be used
as the seed when shuffling.

`limit` int \| None  
Limit the number of records to read.

`dialect` str  
CSV dialect (“unix”, “excel” or”excel-tab”). Defaults to “unix”. See
<https://docs.python.org/3/library/csv.html#dialects-and-formatting-parameters>
for more details

`encoding` str  
Text encoding for file (defaults to “utf-8”).

`name` str \| None  
Optional name for dataset (for logging). If not specified, defaults to
the stem of the filename

`fs_options` dict\[str, Any\] \| None  
Optional. Additional arguments to pass through to the filesystem
provider (e.g. `S3FileSystem`). Use `{"anon": True }` if you are
accessing a public S3 bucket with no credentials.

`fieldnames` list\[str\] \| None  
Optional. A list of fieldnames to use for the CSV. If None, the values
in the first row of the file will be used as the fieldnames. Useful for
files without a header.

`delimiter` str  
Optional. The delimiter to use when parsing the file. Defaults to “,”.

### json_dataset

Read dataset from a JSON file.

Read a dataset from a JSON file containing an array of objects, or from
a JSON Lines file containing one object per line. These objects may
already be formatted as `Sample` instances, or may require some mapping
using the `sample_fields` argument.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/81d8689032370a3b30a10fe8e8ac0be5efae8788/src/inspect_ai/dataset/_sources/json.py#L23)

``` python
def json_dataset(
    json_file: str,
    sample_fields: FieldSpec | RecordToSample | None = None,
    auto_id: bool = False,
    shuffle: bool = False,
    seed: int | None = None,
    shuffle_choices: bool | int | None = None,
    limit: int | None = None,
    encoding: str = "utf-8",
    name: str | None = None,
    fs_options: dict[str, Any] | None = None,
) -> Dataset
```

`json_file` str  
Path to JSON file. Can be a local filesystem path or a path to an S3
bucket (e.g. “s3://my-bucket”). Use `fs_options` to pass arguments
through to the `S3FileSystem` constructor.

`sample_fields` [FieldSpec](inspect_ai.dataset.qmd#fieldspec) \| [RecordToSample](inspect_ai.dataset.qmd#recordtosample) \| None  
Method of mapping underlying fields in the data source to `Sample`
objects. Pass `None` if the data is already stored in `Sample` form
(i.e. object with “input” and “target” fields); Pass a `FieldSpec` to
specify mapping fields by name; Pass a `RecordToSample` to handle
mapping with a custom function that returns one or more samples.

`auto_id` bool  
Assign an auto-incrementing ID for each sample.

`shuffle` bool  
Randomly shuffle the dataset order.

`seed` int \| None  
Seed used for random shuffle.

`shuffle_choices` bool \| int \| None  
Whether to shuffle the choices. If an int is passed, this will be used
as the seed when shuffling.

`limit` int \| None  
Limit the number of records to read.

`encoding` str  
Text encoding for file (defaults to “utf-8”).

`name` str \| None  
Optional name for dataset (for logging). If not specified, defaults to
the stem of the filename.

`fs_options` dict\[str, Any\] \| None  
Optional. Additional arguments to pass through to the filesystem
provider (e.g. `S3FileSystem`). Use `{"anon": True }` if you are
accessing a public S3 bucket with no credentials.

### hf_dataset

Datasets read using the Hugging Face `datasets` package.

The `hf_dataset` function supports reading datasets using the Hugging
Face `datasets` package, including remote datasets on Hugging Face Hub.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/81d8689032370a3b30a10fe8e8ac0be5efae8788/src/inspect_ai/dataset/_sources/hf.py#L22)

``` python
def hf_dataset(
    path: str,
    split: str,
    name: str | None = None,
    data_dir: str | None = None,
    revision: str | None = None,
    sample_fields: FieldSpec | RecordToSample | None = None,
    auto_id: bool = False,
    shuffle: bool = False,
    seed: int | None = None,
    shuffle_choices: bool | int | None = None,
    limit: int | None = None,
    trust: bool = False,
    cached: bool = True,
    **kwargs: Any,
) -> Dataset
```

`path` str  
Path or name of the dataset. Depending on path, the dataset builder that
is used comes from a generic dataset script (JSON, CSV, Parquet, text
etc.) or from the dataset script (a python file) inside the dataset
directory.

`split` str  
Which split of the data to load.

`name` str \| None  
Name of the dataset configuration.

`data_dir` str \| None  
data_dir of the dataset configuration to read data from.

`revision` str \| None  
Specific revision to load (e.g. “main”, a branch name, or a specific
commit SHA). When using `revision` the `cached` option is ignored and
datasets are revalidated on Hugging Face before loading.

`sample_fields` [FieldSpec](inspect_ai.dataset.qmd#fieldspec) \| [RecordToSample](inspect_ai.dataset.qmd#recordtosample) \| None  
Method of mapping underlying fields in the data source to Sample
objects. Pass `None` if the data is already stored in `Sample` form
(i.e. has “input” and “target” columns.); Pass a `FieldSpec` to specify
mapping fields by name; Pass a `RecordToSample` to handle mapping with a
custom function that returns one or more samples.

`auto_id` bool  
Assign an auto-incrementing ID for each sample.

`shuffle` bool  
Randomly shuffle the dataset order.

`seed` int \| None  
Seed used for random shuffle.

`shuffle_choices` bool \| int \| None  
Whether to shuffle the choices. If an int is passed, this will be used
as the seed when shuffling.

`limit` int \| None  
Limit the number of records to read.

`trust` bool  
Whether or not to allow for datasets defined on the Hub using a dataset
script. This option should only be set to True for repositories you
trust and in which you have read the code, as it will execute code
present on the Hub on your local machine.

`cached` bool  
By default, datasets are read once from HuggingFace Hub and then cached
for future reads. Pass `cached=False` to force re-reading the dataset
from Hugging Face. Ignored when the `revision` option is specified.

`**kwargs` Any  
Additional arguments to pass through to the `load_dataset` function of
the `datasets` package.

## Types

### Sample

Sample for an evaluation task.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/81d8689032370a3b30a10fe8e8ac0be5efae8788/src/inspect_ai/dataset/_dataset.py#L28)

``` python
class Sample(BaseModel)
```

#### Attributes

`input` str \| list\[[ChatMessage](inspect_ai.model.qmd#chatmessage)\]  
The input to be submitted to the model.

`choices` list\[str\] \| None  
List of available answer choices (used only for multiple-choice evals).

`target` str \| list\[str\]  
Ideal target output. May be a literal value or narrative text to be used
by a model grader.

`id` int \| str \| None  
Unique identifier for sample.

`metadata` dict\[str, Any\] \| None  
Arbitrary metadata associated with the sample.

`sandbox` SandboxEnvironmentSpec \| None  
Sandbox environment type and optional config file.

`files` dict\[str, str\] \| None  
Files that go along with the sample (copied to SandboxEnvironment)

`setup` str \| None  
Setup script to run for sample (run within default SandboxEnvironment).

#### Methods

\_\_init\_\_  
Create a Sample.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/81d8689032370a3b30a10fe8e8ac0be5efae8788/src/inspect_ai/dataset/_dataset.py#L31)

``` python
def __init__(
    self,
    input: str | list[ChatMessage],
    choices: list[str] | None = None,
    target: str | list[str] = "",
    id: int | str | None = None,
    metadata: dict[str, Any] | None = None,
    sandbox: SandboxEnvironmentType | None = None,
    files: dict[str, str] | None = None,
    setup: str | None = None,
) -> None
```

`input` str \| list\[[ChatMessage](inspect_ai.model.qmd#chatmessage)\]  
The input to be submitted to the model.

`choices` list\[str\] \| None  
Optional. List of available answer choices (used only for
multiple-choice evals).

`target` str \| list\[str\]  
Optional. Ideal target output. May be a literal value or narrative text
to be used by a model grader.

`id` int \| str \| None  
Optional. Unique identifier for sample.

`metadata` dict\[str, Any\] \| None  
Optional. Arbitrary metadata associated with the sample.

`sandbox` SandboxEnvironmentType \| None  
Optional. Sandbox specification for this sample.

`files` dict\[str, str\] \| None  
Optional. Files that go along with the sample (copied to
SandboxEnvironment). Files can be paths, inline text, or inline binary
(base64 encoded data URL).

`setup` str \| None  
Optional. Setup script to run for sample (run within default
SandboxEnvironment).

metadata_as  
Metadata as a Pydantic model.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/81d8689032370a3b30a10fe8e8ac0be5efae8788/src/inspect_ai/dataset/_dataset.py#L84)

``` python
def metadata_as(self, metadata_cls: Type[MT]) -> MT
```

`metadata_cls` Type\[MT\]  
BaseModel derived class.

### FieldSpec

Specification for mapping data source fields to sample fields.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/81d8689032370a3b30a10fe8e8ac0be5efae8788/src/inspect_ai/dataset/_dataset.py#L207)

``` python
@dataclass
class FieldSpec
```

#### Attributes

`input` str  
Name of the field containing the sample input.

`target` str  
Name of the field containing the sample target.

`choices` str  
Name of field containing the list of answer choices.

`id` str  
Unique identifier for the sample.

`metadata` list\[str\] \| Type\[BaseModel\] \| None  
List of additional field names that should be read as metadata.

`sandbox` str  
Sandbox type along with optional config file.

`files` str  
Files that go along wtih the sample.

`setup` str  
Setup script to run for sample (run within default SandboxEnvironment).

### RecordToSample

Callable that maps raw dictionary record to a Sample.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/81d8689032370a3b30a10fe8e8ac0be5efae8788/src/inspect_ai/dataset/_dataset.py#L236)

``` python
RecordToSample = Callable[[DatasetRecord], Sample | list[Sample]]
```

### Dataset

A sequence of Sample objects.

Datasets provide sequential access (via conventional indexes or slicing)
to a collection of Sample objects.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/81d8689032370a3b30a10fe8e8ac0be5efae8788/src/inspect_ai/dataset/_dataset.py#L128)

``` python
class Dataset(Sequence[Sample], abc.ABC)
```

#### Methods

sort  
Sort the dataset (in place) in ascending order and return None.

If a key function is given, apply it once to each list item and sort
them, ascending or descending, according to their function values.

The key function defaults to measuring the length of the sample’s input
field.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/81d8689032370a3b30a10fe8e8ac0be5efae8788/src/inspect_ai/dataset/_dataset.py#L159)

``` python
@abc.abstractmethod
def sort(
    self,
    reverse: bool = False,
    key: Callable[[Sample], "SupportsRichComparison"] = sample_input_len,
) -> None
```

`reverse` bool  
If `Treu`, sort in descending order. Defaults to False.

`key` Callable\[\[[Sample](inspect_ai.dataset.qmd#sample)\], SupportsRichComparison\]  
a callable mapping each item to a numeric value (optional, defaults to
sample_input_len).

filter  
Filter the dataset using a predicate.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/81d8689032370a3b30a10fe8e8ac0be5efae8788/src/inspect_ai/dataset/_dataset.py#L176)

``` python
@abc.abstractmethod
def filter(
    self, predicate: Callable[[Sample], bool], name: str | None = None
) -> "Dataset"
```

`predicate` Callable\[\[[Sample](inspect_ai.dataset.qmd#sample)\], bool\]  
Filtering function.

`name` str \| None  
Name for filtered dataset (optional).

shuffle  
Shuffle the order of the dataset (in place).

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/81d8689032370a3b30a10fe8e8ac0be5efae8788/src/inspect_ai/dataset/_dataset.py#L190)

``` python
@abc.abstractmethod
def shuffle(self, seed: int | None = None) -> None
```

`seed` int \| None  
Random seed for shuffling (optional).

shuffle_choices  
Shuffle the order of the choices with each sample.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/81d8689032370a3b30a10fe8e8ac0be5efae8788/src/inspect_ai/dataset/_dataset.py#L198)

``` python
@abc.abstractmethod
def shuffle_choices(self, seed: int | None = None) -> None
```

`seed` int \| None  
Random seed for shuffling (optional).

### MemoryDataset

A Dataset stored in memory.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/81d8689032370a3b30a10fe8e8ac0be5efae8788/src/inspect_ai/dataset/_dataset.py#L240)

``` python
class MemoryDataset(Dataset)
```

#### Attributes

`name` str \| None  
Dataset name.

`location` str \| None  
Dataset location.

`shuffled` bool  
Was the dataset shuffled.

#### Methods

\_\_init\_\_  
A dataset of samples held in an in-memory list.

Datasets provide sequential access (via conventional indexes or slicing)
to a collection of Sample objects. The ListDataset is explicitly
initialized with a list that is held in memory.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/81d8689032370a3b30a10fe8e8ac0be5efae8788/src/inspect_ai/dataset/_dataset.py#L243)

``` python
def __init__(
    self,
    samples: list[Sample],
    name: str | None = None,
    location: str | None = None,
    shuffled: bool = False,
) -> None
```

`samples` list\[[Sample](inspect_ai.dataset.qmd#sample)\]  
The list of sample objects.

`name` str \| None  
Optional name for dataset.

`location` str \| None  
Optional location for dataset.

`shuffled` bool  
Was the dataset shuffled after reading.
