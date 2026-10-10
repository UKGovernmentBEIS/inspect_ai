from typing import (
    TYPE_CHECKING,
    Any,
    Type,
    cast,
)

if TYPE_CHECKING:
    from inspect_ai.event._event import Event
    from inspect_ai.event._store import StoreEvent

import jsonpatch
from pydantic_core import to_jsonable_python

from inspect_ai._util.json import JsonChange, json_changes

# isort: split
# Backward-compatible re-exports of names that moved to inspect_ai.core.
from inspect_ai.core import _store as _core_store
from inspect_ai.core._store import VT as VT
from inspect_ai.core._store import Store as Store
from inspect_ai.core._store import _subtask_store as _subtask_store
from inspect_ai.core._store import init_subtask_store as init_subtask_store

# assigned rather than imported: an imported `store` trips ruff F811 against
# the `store` parameter of store_jsonable()
store = _core_store.store

# End of backward-compatible re-exports.


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
