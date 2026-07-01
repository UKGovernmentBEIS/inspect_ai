"""
Example task demonstrating run_code:

a single outer tool lets the model run allowlisted inner tools from within Python code.
"""

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import model_graded_fact
from inspect_ai.solver import generate, use_tools
from inspect_ai.tool import run_code, tool


@tool
def get_item():
    async def execute(item: str) -> dict:
        """Get the price and quantity of an item as a dictionary {price, quantity}

        Args:
            item: Name of the item.
        """
        items = {
            "widget": {"price": 12.5, "quantity": 4},
            "gadget": {"price": 7.25, "quantity": 10},
        }

        return items.get(item, {"price": 0.0, "quantity": 0})

    return execute


@task
def run_code_task():
    return Task(
        dataset=[
            Sample(
                input=(
                    "Call get_item for the items 'widget' and 'gadget'. "
                    "For each item multiply price by quantity. "
                    "Return only the final sum as result."
                ),
                target="122.5",
            )
        ],
        solver=[
            use_tools(run_code(tools=[get_item()], executor="monty")),
            generate(),
        ],
        scorer=model_graded_fact(),
    )
