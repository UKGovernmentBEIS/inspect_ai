import abc
import random
from typing import Any, Callable, Iterator, Sequence, Union, overload

from pydantic import BaseModel, Field
from typing_extensions import override

from inspect_ai.model import ChatMessage


class Sample(BaseModel):
    r"""Sample to be used in an evaluation task.

    Args:
        input (str | list[ChatMessage]): The input to be submitted to the model.
        choices (list[str] | None): Optional. List of available answer choices
           (used only for multiple-choice evals).
        target (str | list[str] | None): Optional. Ideal target output. May be a literal value
            or narrative text to be used by a model grader.
        id (int | str | None): Optional. Unique identifier for sample.
        metadata (dict | None): Optional. Arbitrary metadata associated with the sample.
    """

    input: str | list[ChatMessage]
    """The input to be submitted to the model."""

    choices: list[str] | None = Field(default=None)
    """List of available answer choices (used only for multiple-choice evals)."""

    target: str | list[str] = Field(default="")
    """Ideal target output. May be a literal value or narrative text to be used by a model grader."""

    id: int | str | None = Field(default=None)
    """Unique identifier for sample."""

    metadata: dict[str, Any] | None = Field(default=None)
    """Arbitrary metadata associated with the sample."""


DatasetRecord = dict[str, Any]

DatasetReader = Iterator[DatasetRecord]


class Dataset(Sequence[Sample], abc.ABC):
    r"""A sequence of Sample objects.

    Datasets provide sequential access (via conventional indexes or slicing)
    to a collection of Sample objects.
    """

    @abc.abstractproperty
    def name(self) -> str | None:
        ...

    @abc.abstractproperty
    def location(self) -> str | None:
        ...

    @overload
    def __getitem__(self, index: int) -> Sample:
        ...

    @overload
    def __getitem__(self, index: slice) -> "Dataset":
        ...

    @abc.abstractmethod
    def __getitem__(self, index: Union[int, slice]) -> Union[Sample, "Dataset"]:
        ...

    @abc.abstractmethod
    def __len__(self) -> int:
        ...

    @abc.abstractmethod
    def shuffle(self, seed: int | None = None) -> None:
        """Shuffle the order of the dataset (in place).

        Args:
           seed: (int | None): Random seed for shuffling (optional).
        """

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
        return MemoryDataset(
            name=name or self.name,
            location=self.location,
            samples=[sample for sample in self if predicate(sample)],
        )


class FieldSpec(BaseModel):
    r"""Specification for mapping data source fields to sample fields.

    Args:
        input (str): Name of the field containing the sample input.
        target (str): Name of the field containing the sample target.
        choices (str): Optional. Name of field containing the list of answer choices.
        id (str): Optional. Unique identifier for the sample.
        metadata (list[str] | None): List of additional field names that should be read as metadata.
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


RecordToSample = Callable[[DatasetRecord], Sample]
r"""Callable that maps raw dictionary record to a Sample."""


class MemoryDataset(Dataset):
    r"""A Dataset stored in memory."""

    def __init__(
        self,
        samples: list[Sample],
        name: str | None = None,
        location: str | None = None,
    ) -> None:
        r"""A dataset of samples held in an in-memory list.

        Datasets provide sequential access (via conventional indexes or slicing)
        to a collection of Sample objects. The ListDataset is explicitly
        initialized with a list that is held in memory.

        Args:
            samples (list[Sample]): The list of sample objects.
            name (str | None): Optional name for dataset.
            location (str | None): Optional location for dataset.
        """
        self.samples = samples
        self._name = name
        self._location = location

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

    @overload
    def __getitem__(self, index: int) -> Sample:
        ...

    @overload
    def __getitem__(self, index: slice) -> Dataset:
        ...

    @override
    def __getitem__(self, index: Union[int, slice]) -> Union[Sample, Dataset]:
        if isinstance(index, int):
            return self.samples[index]
        else:
            return MemoryDataset(
                samples=self.samples[index], name=self.name, location=self.location
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
