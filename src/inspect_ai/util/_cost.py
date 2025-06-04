import json
import logging
from decimal import getcontext
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

getcontext().prec = 12
logger = logging.getLogger(__name__)


@lru_cache
def _load_cost_file(cost_file: Path) -> dict:
    """
    Read a JSON file of price info.

    Memoized to avoid re-reads of the same file.
    """
    with open(cost_file) as f:
        results = json.load(f)
    # TODO: validate cost format is correct!
    return results


class _CostCalculator:
    def __init__(self, cost_file: Path):
        self._costs = _load_cost_file(cost_file)
        self._cost_file = cost_file

    def get_cost(self, model_name, usage):
        if model_name not in self._costs:
            # Retry after dropping initial slash
            if "/" in model_name:
                model_name = model_name[model_name.index("/") + 1 :]
            if model_name not in self._costs:
                raise ValueError(
                    f"Model {model_name} is missing from cost file {self._cost_file}."
                )

        model_cost = self._costs[model_name]

        cached_input_tokens = usage.input_tokens_cache_read or 0
        uncached_input_tokens = usage.input_tokens - cached_input_tokens
        output_tokens = usage.output_tokens

        return (
            model_cost["input_cost_per_token"] * uncached_input_tokens
            + model_cost["cache_read_input_token_cost"] * cached_input_tokens
            + model_cost["output_cost_per_token"] * output_tokens
        )
