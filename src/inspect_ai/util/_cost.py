import json
import logging
from decimal import Decimal, getcontext
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

getcontext().prec = 12
logger = logging.getLogger(__name__)

REQUIRED_FIELDS = [
    "input_cost_per_token",
    "output_cost_per_token",
]


class _CostCalculator:
    def __init__(self, cost_file: Path):
        self._costs = self._load_cost_file(cost_file)
        self._cost_file = cost_file

    @staticmethod
    @lru_cache
    def _load_cost_file(cost_file: Path) -> dict:
        """
        Read a JSON file of price info.

        Memoized to avoid re-reads of the same file.
        """
        with open(cost_file) as f:
            results = json.load(f)

        # Validate by ensuring at least one model name
        # contains all the required fields. This allows us to
        # be compatible with litellm format
        for model_name, data in results.items():
            if _CostCalculator._model_data_valid(data):
                return results
        raise ValueError(f"Unexpected data format in {cost_file}")

    @staticmethod
    def _model_data_valid(data):
        return all([x in data for x in REQUIRED_FIELDS])

    def get_cost(self, model_name, usage) -> Decimal:
        if model_name not in self._costs:
            # Retry after dropping initial slash
            if "/" in model_name:
                model_name = model_name[model_name.index("/") + 1 :]
            if model_name not in self._costs:
                raise ValueError(
                    f"Model {model_name} is missing from cost file {self._cost_file}."
                )

        model_cost = self._costs[model_name]
        if not self._model_data_valid(model_cost):
            raise ValueError(
                f"Invalid pricing data for {model_name} in {self._cost_file}"
            )

        # Blank cache implies no cached read discount
        if "cache_read_input_token_cost" not in model_cost:
            model_cost["cache_read_input_token_cost"] = model_cost[
                "input_cost_per_token"
            ]

        cached_input_tokens = usage.input_tokens_cache_read or 0
        uncached_input_tokens = usage.input_tokens - cached_input_tokens
        output_tokens = usage.output_tokens

        return Decimal(
            model_cost["input_cost_per_token"] * uncached_input_tokens
            + model_cost["cache_read_input_token_cost"] * cached_input_tokens
            + model_cost["output_cost_per_token"] * output_tokens
        )
