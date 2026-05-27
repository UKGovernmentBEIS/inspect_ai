"""Demo eval for the `ask_user` Textual question panel.

Run this directly with Python to see the Phase 4 "Question" tab in action:

    python examples/ask_user/demo.py

The script wires a `mockllm` model that emits two tool calls:
1. `ask_user` with a kitchen-sink schema (string + enum string + integer +
   number + boolean + multi-select).
2. `submit` echoing back whatever fields the user entered.

When the agent fires the first call, Inspect mounts the Question tab on
the Textual display and waits for you to fill out the form and press
Submit (or Decline). The form's answer flows back into the model, which
then submits via the second tool call and the eval completes.
"""

from acp.schema import (
    ElicitationBooleanPropertySchema,
    ElicitationIntegerPropertySchema,
    ElicitationMultiSelectPropertySchema,
    ElicitationNumberPropertySchema,
    ElicitationSchema,
    ElicitationStringPropertySchema,
    EnumOption,
    TitledMultiSelectItems,
)

from inspect_ai import Task, eval
from inspect_ai.agent._react import react
from inspect_ai.agent._types import AgentSubmit
from inspect_ai.dataset import Sample
from inspect_ai.model import ModelOutput, get_model
from inspect_ai.scorer import includes
from inspect_ai.tool import ask_user


def _kitchen_sink_schema() -> dict:
    # Per the ACP RFD and MCP elicitation spec, the conversational ask lives on
    # the request's `message` field (see `main()` below); schema-level `title`
    # and `description` are reserved for cases where the form itself has an
    # identity worth labelling (multi-section dialogs etc.) and are normally
    # omitted. Per-property `title`/`description` carry the field labels.
    return ElicitationSchema(
        properties={
            "name": ElicitationStringPropertySchema(
                type="string",
                title="Your name",
                description="Free-form text, min 2 characters.",
                min_length=2,
            ),
            "color": ElicitationStringPropertySchema(
                type="string",
                title="Favourite color",
                description="Pick one (renders as a Select).",
                one_of=[
                    EnumOption(const="red", title="Red"),
                    EnumOption(const="green", title="Green"),
                    EnumOption(const="blue", title="Blue"),
                ],
            ),
            "count": ElicitationIntegerPropertySchema(
                type="integer",
                title="Quantity",
                description="Between 1 and 100.",
                minimum=1,
                maximum=100,
            ),
            "ratio": ElicitationNumberPropertySchema(
                type="number",
                title="Discount (optional)",
                description="Decimal — leave blank for none.",
            ),
            "confirm": ElicitationBooleanPropertySchema(
                type="boolean",
                title="Confirm",
                description="Tick to confirm the order.",
            ),
            "tags": ElicitationMultiSelectPropertySchema(
                type="array",
                title="Tags",
                description="Pick one or more.",
                items=TitledMultiSelectItems(
                    any_of=[
                        EnumOption(const="rush", title="Rush delivery"),
                        EnumOption(const="gift", title="Gift wrap"),
                        EnumOption(const="signed", title="Signature required"),
                    ]
                ),
                min_items=1,
            ),
        },
        required=["name", "color", "count", "confirm", "tags"],
    ).model_dump(mode="json")


def main() -> None:
    task = Task(
        dataset=[
            Sample(
                input=(
                    "Use the ask_user tool to collect order details from the "
                    "operator, then submit the order summary."
                ),
                target=["ok"],
            )
        ],
        solver=react(
            tools=[ask_user()],
            submit=AgentSubmit(
                name="submit",
                description="Submit the final summary once the form is filled.",
            ),
        ),
        scorer=includes(),
        message_limit=10,
    )

    model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="ask_user",
                tool_arguments={
                    "message": "Please fill out your order details.",
                    "schema": _kitchen_sink_schema(),
                },
            ),
            # Whatever the operator entered, submit "ok" so the scorer passes.
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="submit",
                tool_arguments={"answer": "ok"},
            ),
        ],
    )

    eval(task, model=model, display="full")


if __name__ == "__main__":
    main()
