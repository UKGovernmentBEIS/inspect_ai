from contextvars import ContextVar
from copy import deepcopy
from typing import (
    TYPE_CHECKING,
    Any,
    ItemsView,
    KeysView,
    Type,
    TypeVar,
    ValuesView,
    cast,
    overload,
)

if TYPE_CHECKING:
    from inspect_ai.event._event import Event
    from inspect_ai.event._store import StoreEvent

import jsonpatch
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

    def __init__(self, data: dict[str, Any] | None = None) -> None:
        self._data = deepcopy(data) if data else {}

    @overload
    def get(self, key: str, default: None = None) -> Any: ...

    @overload
    def get(self, key: str, default: VT) -> VT: ...

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
        if default is not None:
            if key not in self._data.keys():
                self._data[key] = default
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
    return dict_jsonable(store._data)


def dict_jsonable(data: dict[str, Any]) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        to_jsonable_python(data, exclude_none=True, fallback=lambda _x: None),
    )


def store_from_events(events: list["Event"]) -> Store:
    """Reconstruct a Store by replaying StoreEvent changes.

    Uses event_tree() to ensure proper ordering of parallel events.
    Only processes StoreEvents from root-level spans (which encompass
    all nested changes) to avoid redundant replay.

    Args:
        events: List of Event objects (typically from EvalSample.events).

    Returns:
        Store: A new Store with reconstructed state.
    """
    from inspect_ai.event._store import StoreEvent
    from inspect_ai.event._tree import EventTreeSpan, event_tree

    tree = event_tree(events)
    data: dict[str, Any] = {}

    # Process only root-level items
    for node in tree:
        if isinstance(node, EventTreeSpan):
            # Find StoreEvents that are direct children (not nested in child spans)
            for child in node.children:
                if isinstance(child, StoreEvent):
                    data = _apply_store_event(data, child)
        elif isinstance(node, StoreEvent):
            # Root-level StoreEvent not in any span
            data = _apply_store_event(data, node)

    return Store(data)


def store_from_events_as(
    events: list["Event"],
    model_cls: Type["SMT"],
    instance: str | None = None,
) -> "SMT":
    """Reconstruct a StoreModel from events.

    Args:
        events: List of Event objects.
        model_cls: Pydantic model type (must derive from StoreModel).
        instance: Optional instance name for namespaced store keys.

    Returns:
        StoreModel: Instance populated with reconstructed data.
    """
    from inspect_ai.util._store_model import SMT as SMT_TypeVar  # noqa: F401

    reconstructed = store_from_events(events)

    # Un-namespace keys (following EvalSample.store_as pattern)
    prefix = f"{model_cls.__name__}:"
    data: dict[str, Any] = {}
    for key, value in reconstructed._data.items():
        if key.startswith(prefix):
            unprefixed = key[len(prefix) :]

            if instance is not None:
                # When instance specified, only include keys with that instance prefix
                if unprefixed.startswith(f"{instance}:"):
                    unprefixed = unprefixed[len(instance) + 1 :]
                else:
                    continue  # Skip keys for other instances or no instance
            else:
                # When no instance specified, skip keys that have any instance prefix
                if ":" in unprefixed:
                    continue  # This key belongs to a specific instance

            data[unprefixed] = value

    data["store"] = Store()  # Detached store
    if instance is not None:
        data["instance"] = instance

    return model_cls.model_validate(data)


# Type variable for store_from_events_as
from inspect_ai.util._store_model import SMT  # noqa: E402


def _json_change_to_patch_op(change: JsonChange) -> dict[str, Any]:
    """Convert a JsonChange to a jsonpatch operation dict with validation.

    Args:
        change: The JsonChange to convert.

    Returns:
        A dict suitable for use with jsonpatch.apply_patch().

    Raises:
        ValueError: If move/copy operation is missing required 'from' field.
    """
    op: dict[str, Any] = {"op": change.op, "path": change.path}

    if change.op in ("add", "replace", "test"):
        # These operations require a value (None is valid for explicit null)
        op["value"] = change.value
    elif change.op in ("move", "copy"):
        if change.from_ is None:
            raise ValueError(
                f"JsonChange operation '{change.op}' requires 'from' field"
            )
        op["from"] = change.from_
    # "remove" doesn't need additional fields

    return op


def _apply_store_event(
    data: dict[str, Any], store_event: "StoreEvent"
) -> dict[str, Any]:
    """Apply a StoreEvent's changes to a data dict.

    Args:
        data: The current state dict to modify.
        store_event: The StoreEvent containing changes to apply.

    Returns:
        The modified data dict.
    """
    patch_ops = [_json_change_to_patch_op(change) for change in store_event.changes]
    result: dict[str, Any] = jsonpatch.apply_patch(
        data,
        patch_ops,  # type: ignore[arg-type]
        in_place=True,
    )
    return result
