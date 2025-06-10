from __future__ import annotations

import json
import logging
from decimal import Decimal, getcontext
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypedDict, TypeGuard

if TYPE_CHECKING:
    from inspect_ai.model import ModelUsage

getcontext().prec = 10

logger = logging.getLogger(__name__)


class ModelCostEntry(TypedDict, total=False):
    """Model cost entries must have these fields"""

    input_cost_per_token: Decimal
    output_cost_per_token: Decimal
    cache_read_input_token_cost: Decimal  # optional; we’ll default it if missing


# TypeGuard so mypy knows when a dict is a ModelCostEntry
REQUIRED_FIELDS = ("input_cost_per_token", "output_cost_per_token")


def is_model_cost_entry(obj: Any) -> TypeGuard[ModelCostEntry]:
    if not isinstance(obj, dict):
        return False
    return all(field in obj for field in REQUIRED_FIELDS)


class _CostCalculator:
    def __init__(self, cost_file: Path):
        self._cost_file = cost_file
        self._costs = self._load_cost_file(cost_file)

    @staticmethod
    @lru_cache
    def _load_cost_file(cost_file: Path) -> dict[str, ModelCostEntry]:
        # 4) Tell json.load to use Decimal for all JSON floats
        with open(cost_file) as f:
            raw = json.load(f, parse_float=Decimal)

        if not isinstance(raw, dict):
            raise ValueError(f"Top-level JSON must be an object in {cost_file!r}")

        filtered: dict[str, ModelCostEntry] = {}
        for name, entry in raw.items():
            if is_model_cost_entry(entry):
                # mypy now knows entry is ModelCostEntry
                filtered[name] = entry

        if not filtered:
            raise ValueError(f"No valid models in {cost_file!r}")

        return filtered

    def get_cost(self, model_name: str, usage: ModelUsage) -> Decimal:
        entry = self._costs.get(model_name)
        if entry is None and "/" in model_name:
            # retry without prefix
            model_name = model_name.split("/", 1)[1]
            entry = self._costs.get(model_name)
        if entry is None:
            raise ValueError(f"Model {model_name!r} missing from {self._cost_file}")

        # If no cost for cached reads, just use cost of uncached read
        cache_cost: Decimal = entry.get(
            "cache_read_input_token_cost",
            entry["input_cost_per_token"],
        )

        return Decimal(
            entry["input_cost_per_token"] * usage.input_tokens
            + entry["output_cost_per_token"] * usage.output_tokens
            + cache_cost * (usage.input_tokens_cache_read or 0)
        )
