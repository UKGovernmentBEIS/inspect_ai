from openai.types.responses import ResponseComputerToolCall, ResponseFunctionToolCall

# TODO: OpenAI publishes both ResponseComputerToolCall and
# ResponseComputerToolCallParam. The first is a pydantic model. The second is
# a TypedDict. Structurally, they are identical.
#
# They seem to follow that same pattern for all of their tool call types.
# We store the pydantic models in our ToolCall.internal field. We're currently
# relying on this situation to just cast the result of .model_dump() to the
# TypedDict version. This is a bit of a hack.

ResponseToolCallInternal = (
    ResponseFunctionToolCall | ResponseComputerToolCall
    # | ResponseFileSearchToolCall
    # | ResponseFunctionToolCall
    # | ResponseFunctionWebSearch
)
