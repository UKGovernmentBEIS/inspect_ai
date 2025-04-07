from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Generator

from inspect_ai.model._model_output import ModelUsage

# Stores the current execution context's leaf _ModelUsageCounterNode.
# The resulting data structure is a tree of _ModelUsageCounterNode nodes which each
# have a pointer to their parent node. Each additional context manager inserts a new
# child node into the tree. The fact that there can be multiple execution contexts is
# what makes this a tree rather than a stack.
leaf_node_ctx_var: ContextVar[ModelUsageCounterNode | None] = ContextVar(
    "counter_leaf_node", default=None
)


@contextmanager
def model_usage_counter(scope: str) -> Generator[None, None, None]:
    """Context manager for scoping model usage counting.

    For example, to scope a counter to a subtask or an agent.

    Args:
      scope: The name of the scope e.g. "sample". Can later be used to query the model
        usage at a particular scope. Does not have to be unique.
    """
    node = ModelUsageCounterNode(scope, leaf_node_ctx_var.get())
    token = leaf_node_ctx_var.set(node)
    try:
        yield
    finally:
        leaf_node_ctx_var.reset(token)


def record_model_usage(model: str, usage: ModelUsage) -> None:
    """Records model usage for the leaf node and its ancestor nodes."""
    get_counter_leaf_node().record(model, usage)


def get_model_usage() -> dict[str, ModelUsage]:
    """Gets the model usage for the leaf (most recently created) node."""
    return get_counter_leaf_node().usage


def get_scoped_model_usage(scope: str) -> dict[str, ModelUsage]:
    """Gets the model usage for the specified scope name (e.g. "sample").

    The search begins at the leaf node and traverses up the tree through each ancestor.

    If multiple scopes with the same name exist, the first one found is returned.
    """
    node: ModelUsageCounterNode | None = get_counter_leaf_node()
    while node is not None:
        if node.scope == scope:
            return node.usage
        node = node.parent
    raise ValueError(f"Scope '{scope}' not found in the tree of model usage.")


def get_counter_leaf_node() -> ModelUsageCounterNode:
    """Gets the current execution context's leaf node."""
    node = leaf_node_ctx_var.get()
    if node is None:
        raise RuntimeError(
            "The model usage counter leaf node is None. At least one "
            "model_usage_counter() context manager must be active within the current "
            "execution context for there to be a leaf node."
        )
    return node


class ModelUsageCounterNode:
    def __init__(self, scope: str, parent: ModelUsageCounterNode | None = None) -> None:
        self.parent = parent
        self.scope = scope
        self.usage: dict[str, ModelUsage] = {}

    def record(self, model: str, usage: ModelUsage) -> None:
        if self.parent is not None:
            self.parent.record(model, usage)
        if model in self.usage:
            self.usage[model] = self.usage[model] + usage
        else:
            self.usage[model] = usage

    def get_total_sum(self) -> int:
        return sum(usage.total_tokens for usage in self.usage.values())

    def __repr__(self) -> str:
        # Useful for debugging.
        result = ""
        if self.parent is not None:
            result += f"{repr(self.parent)}\n~~~\n"
        result += f"{self.scope}: {self.get_total_sum()}"
        return result
