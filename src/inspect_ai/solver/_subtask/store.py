from contextvars import ContextVar
from copy import deepcopy
from typing import (
    Any,
    ItemsView,
    KeysView,
    TypeVar,
    ValuesView,
    cast,
    overload,
)

from pydantic_core import to_jsonable_python

from inspect_ai._util.json import JsonChange, json_changes

VT = TypeVar("VT")


class Store:
    """The `Store` is used to record state and state changes.

    The `TaskState` for each sample has a `Store` which can be
    used when solvers and/or tools need to coordinate changes
    to shared state. The `Store` can be accessed directly from
    the `TaskState` via `state.store` or can be accessed using
    the `store()` global function.

    Note that changes to the store that occur are automatically
    recorded to transcript as a `StoreEvent`. In order to be
    serialised to the transcript, values and objects must be
    JSON serialisable (you can make objects with several fields
    serialisable using the `@dataclass` decorator or by
    inheriting from Pydantic `BaseModel`)
    """

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    @overload
    def get(self, key: str, default: None = None) -> Any:
        return self._data.get(key, default)

    @overload
    def get(self, key: str, default: VT) -> VT:
        if key not in self._data.keys():
            self._data[key] = default
        return cast(VT, self._data.get(key, default))

    def get(self, key: str, default: VT | None = None) -> VT | Any:
        """Get a value from the store.

        Provide a `default` to automatically initialise a named
        store value with the default when it does not yet exist.

        Args:
           key (str): Name of value to get
           default (VT | None): Default value (defaults to `None`)

        Returns:
           Value if is exists, otherwise default.
        """
        return cast(VT, self._data.get(key, default))

    def set(self, key: str, value: Any) -> None:
        """Set a value into the store.

        Args:
           key (str): Name of value to set
           value (Any): Value to set
        """
        self._data[key] = value

    def delete(self, key: str) -> None:
        """Remove a value from the store.

        Args:
           key (str): Name of value to remove
        """
        del self._data[key]

    def keys(self) -> KeysView[str]:
        """View of keys within the store."""
        return self._data.keys()

    def values(self) -> ValuesView[Any]:
        """View of values within the store."""
        return self._data.values()

    def items(self) -> ItemsView[str, Any]:
        """View of items within the store."""
        return self._data.items()

    def __contains__(self, key: object) -> bool:
        return key in self._data

    def __eq__(self, other: object) -> bool:
        return self._data.__eq__(other)

    def __ne__(self, value: object) -> bool:
        return self._data.__ne__(value)


def store() -> Store:
    """Get the currently active `Store`."""
    return _subtask_store.get()


def init_subtask_store(store: Store) -> None:
    _subtask_store.set(store)


_subtask_store: ContextVar[Store] = ContextVar("subtask_store", default=Store())


def store_changes(
    before: Store | dict[str, Any], after: Store | dict[str, Any]
) -> list[JsonChange] | None:
    if isinstance(before, Store):
        before = store_jsonable(before)
    if isinstance(after, Store):
        after = store_jsonable(after)
    return json_changes(before, after)


def store_jsonable(store: Store) -> dict[str, Any]:
    return deepcopy(dict_jsonable(store._data))


def dict_jsonable(data: dict[str, Any]) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        to_jsonable_python(data, exclude_none=True, fallback=lambda _x: None),
    )
