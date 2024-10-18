import abc
import random
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Iterator,
    Sequence,
    Union,
    overload,
)

from pydantic import BaseModel, Field
from typing_extensions import override

from inspect_ai.model import ChatMessage
from inspect_ai.util import SandboxEnvironmentSpec, SandboxEnvironmentType
from inspect_ai.util._sandbox.environment import resolve_sandbox_environment

if TYPE_CHECKING:
    from _typeshed import SupportsRichComparison


class Sample(BaseModel):
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
    ) -> None:
        r"""Sample to be used in an evaluation task.

        Args:
            input (str | list[ChatMessage]): The input to be submitted to the model.
            choices (list[str] | None): Optional. List of available answer choices
            (used only for multiple-choice evals).
            target (str | list[str]): Optional. Ideal target output. May be a literal value
                or narrative text to be used by a model grader.
            id (int | str | None): Optional. Unique identifier for sample.
            metadata (dict[str,Any] | None): Optional. Arbitrary metadata associated with the sample.
            sandbox (SandboxEnvironmentType | None): Sandbox environment type
            (or optionally a str or tuple with a shorthand spec)
            files (dict[str, str] | None): Optional. Files that go along with the sample (copied to
            SandboxEnvironment). Files can be paths, inline text, or inline binary (base64 encoded data URL).
            setup (str | None): Optional. Setup script to run for sample (run
            within default SandboxEnvironment).
        """
        super().__init__(
            input=input,
            choices=choices,
            target=target,
            id=id,
            metadata=metadata,
            sandbox=resolve_sandbox_environment(sandbox),
            files=files,
            setup=setup,
        )

    input: str | list[ChatMessage]
    """The input to be submitted to the model."""

    choices: list[str] | None = Field(default=None)
    """List of available answer choices (used only for multiple-choice evals)."""

    target: str | list[str] = Field(default_factory=str)
    """Ideal target output. May be a literal value or narrative text to be used by a model grader."""

    id: int | str | None = Field(default=None)
    """Unique identifier for sample."""

    metadata: dict[str, Any] | None = Field(default=None)
    """Arbitrary metadata associated with the sample."""

    sandbox: SandboxEnvironmentSpec | None = Field(default=None)
    """Sandbox environment type and optional config file."""

    files: dict[str, str] | None = Field(default=None)
    """Files that go along with the sample (copied to SandboxEnvironment)"""

    setup: str | None = Field(default=None)
    """Setup script to run for sample (run within default SandboxEnvironment)."""


def sample_input_len(sample: Sample) -> int:
    """Measures the length of a samples `input` field.

    The default length function use in `Dataset.sort()`.

    Args:
        sample (Sample): A Sample to be used in an evaluation task.
    """
    return (
        len(sample.input)
        if isinstance(sample.input, str)
        else sum(len(inp.text) for inp in sample.input)
    )


DatasetRecord = dict[str, Any]

DatasetReader = Iterator[DatasetRecord]


class Dataset(Sequence[Sample], abc.ABC):
    r"""A sequence of Sample objects.

    Datasets provide sequential access (via conventional indexes or slicing)
    to a collection of Sample objects.
    """

    @property
    @abc.abstractmethod
    def name(self) -> str | None: ...

    @property
    @abc.abstractmethod
    def location(self) -> str | None: ...

    @property
    @abc.abstractmethod
    def shuffled(self) -> bool: ...

    @overload
    def __getitem__(self, index: int) -> Sample: ...

    @overload
    def __getitem__(self, index: slice) -> "Dataset": ...

    @abc.abstractmethod
    def __getitem__(self, index: Union[int, slice]) -> Union[Sample, "Dataset"]: ...

    @abc.abstractmethod
    def __len__(self) -> int: ...

    @abc.abstractmethod
    def shuffle(self, seed: int | None = None) -> None:
        """Shuffle the order of the dataset (in place).

        Args:
           seed: (int | None): Random seed for shuffling (optional).
        """

    @abc.abstractmethod
    def sort(
        self,
        reverse: bool = False,
        key: Callable[[Sample], "SupportsRichComparison"] = sample_input_len,
    ) -> None:
        """Sort the dataset (in place) in ascending order and return None.

        If a key function is given, apply it once to each list item and sort them, ascending or descending, according to their function values.

        The key function defaults to measuring the length of the sample's input field.

        Args:
            reverse (bool): if true, sort in descending order. Defaults to False.
            key (Callable[[Any], Any]): a callable mapping each item to a numeric value (optional, defaults to sample_input_len).
        """

    @abc.abstractmethod
    def filter(
        self, predicate: Callable[[Sample], bool], name: str | None = None
    ) -> "Dataset":
        """Filter the dataset using a predicate.

        Args:
          predicate (Callable[[Sample], bool]): Filtering function.
          name (str | None): Name for filtered dataset (optional).

        Returns:
          Filtered dataset.
        """


class FieldSpec(BaseModel):
    r"""Specification for mapping data source fields to sample fields.

    Args:
        input (str): Name of the field containing the sample input.
        target (str): Name of the field containing the sample target.
        choices (str): Optional. Name of field containing the list of answer choices.
        id (str): Optional. Unique identifier for the sample.
        metadata (list[str] | None): List of additional field names that should be read as metadata.
        sandbox (str): Optional. Sandbox type along with optional config file
        files (str): Optional. Files that go along with the sample.
        setup (str): Optional. Setup script to run for sample .
    """

    input: str = Field(default="input")
    """Name of the field containing the sample input."""

    target: str = Field(default="target")
    """Name of the field containing the sample target."""

    choices: str = Field(default="choices")
    """Name of field containing the list of answer choices."""

    id: str = Field(default="id")
    """ Unique identifier for the sample."""

    metadata: list[str] | None = Field(default=None)
    """List of additional field names that should be read as metadata."""

    sandbox: str = Field(default="sandbox")
    """Sandbox type along with optional config file."""

    files: str = Field(default="files")
    """Files that go along wtih the sample."""

    setup: str = Field(default="setup")
    """Setup script to run for sample (run within default SandboxEnvironment)."""


RecordToSample = Callable[[DatasetRecord], Sample | list[Sample]]
r"""Callable that maps raw dictionary record to a Sample."""


class MemoryDataset(Dataset):
    r"""A Dataset stored in memory."""

    def __init__(
        self,
        samples: list[Sample],
        name: str | None = None,
        location: str | None = None,
        shuffled: bool = False,
    ) -> None:
        r"""A dataset of samples held in an in-memory list.

        Datasets provide sequential access (via conventional indexes or slicing)
        to a collection of Sample objects. The ListDataset is explicitly
        initialized with a list that is held in memory.

        Args:
            samples (list[Sample]): The list of sample objects.
            name (str | None): Optional name for dataset.
            location (str | None): Optional location for dataset.
            shuffled (bool): Was the dataset shuffled after reading.
        """
        self.samples = samples
        self._name = name
        self._location = location
        self._shuffled = shuffled

    @override
    @property
    def name(self) -> str | None:
        """Dataset name."""
        return self._name

    @override
    @property
    def location(self) -> str | None:
        """Dataset location."""
        return self._location

    @override
    @property
    def shuffled(self) -> bool:
        """Was the dataset shuffled."""
        return self._shuffled

    @overload
    def __getitem__(self, index: int) -> Sample: ...

    @overload
    def __getitem__(self, index: slice) -> Dataset: ...

    @override
    def __getitem__(self, index: Union[int, slice]) -> Union[Sample, Dataset]:
        if isinstance(index, int):
            return self.samples[index]
        else:
            return MemoryDataset(
                samples=self.samples[index],
                name=self.name,
                location=self.location,
                shuffled=self.shuffled,
            )

    @override
    def __len__(self) -> int:
        return len(self.samples)

    @override
    def shuffle(self, seed: int | None = None) -> None:
        if seed:
            random.Random(seed).shuffle(self.samples)
        else:
            random.shuffle(self.samples)
        self._shuffled = True

    @override
    def sort(
        self,
        reverse: bool = False,
        key: Callable[[Sample], "SupportsRichComparison"] = sample_input_len,
    ) -> None:
        self.samples.sort(reverse=reverse, key=key)

    @override
    def filter(
        self, predicate: Callable[[Sample], bool], name: str | None = None
    ) -> "MemoryDataset":
        return MemoryDataset(
            name=name or self.name,
            location=self.location,
            samples=[sample for sample in self if predicate(sample)],
            shuffled=self.shuffled,
        )
