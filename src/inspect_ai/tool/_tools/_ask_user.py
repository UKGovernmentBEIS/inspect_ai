from typing import Any

from acp.schema import ElicitationSchema
from pydantic import ValidationError

from inspect_ai._util.json import to_json_str_safe
from inspect_ai.input import request_input

from .._tool import Tool, ToolError, tool


@tool
def ask_user() -> Tool:
    """Ask the user a structured question and wait for an answer."""

    async def execute(message: str, schema: dict[str, Any]) -> str:
        """Ask the human operator a structured question and return their answer.

        The operator is shown the question and answers via a console (or UI)
        prompt; their structured response is returned to you as a JSON object.

        ## When to use
        - Information you cannot derive from task context or tools
          (credentials, preferences, missing parameters)
        - The operator should choose between several reasonable branches
          before you commit to one
        - Confirmation before something hard to reverse

        ## When NOT to use
        - You can look it up yourself (read a file, query a tool)
        - You're merely uncertain — pick the most reasonable option
        - You need free-form chat (this is a one-shot structured form)

        ## Schema shape

        Top-level: `{"type": "object", "properties": {...}, "required": [...]}`.
        Each property declares one form field. Use the smallest set that
        answers your question — long forms get abandoned.

        Property types: `"string"`, `"integer"`, `"number"`, `"boolean"`, `"array"`.

        ## Examples

        Simple required string:
          {"type": "object",
           "properties": {"name": {"type": "string", "description": "Your name"}},
           "required": ["name"]}

        Enum choice (string with bounded options):
          {"type": "object",
           "properties": {"color": {"type": "string", "enum": ["red", "green", "blue"]}},
           "required": ["color"]}

        Confirmation (boolean):
          {"type": "object",
           "properties": {"proceed": {"type": "boolean",
                                      "description": "Continue with the operation?"}},
           "required": ["proceed"]}

        Multi-property form with bounded integer:
          {"type": "object",
           "properties": {
             "url": {"type": "string", "description": "API endpoint"},
             "timeout": {"type": "integer", "minimum": 1, "maximum": 300}
           },
           "required": ["url"]}

        Multi-select array (operator picks 1+ items):
          {"type": "object",
           "properties": {"status": {
             "type": "array",
             "items": {"any_of": [
               {"const": "draft", "title": "Draft"},
               {"const": "pub",   "title": "Published"}
             ]},
             "min_items": 1
           }},
           "required": ["status"]}

        ## Constraints per property type
        - string: `enum`, `min_length`, `max_length`, `pattern`, `format`
        - integer / number: `minimum`, `maximum`
        - boolean: no extra constraints
        - array (multi-select): `min_items`, `max_items`; `items.any_of` for titled
          choices (as above) or `items.enum` for bare string choices

        Args:
          message: The prompt to show the operator.
          schema: JSON-Schema-shaped dict describing the answer fields.

        Returns:
          A JSON object string keyed by the schema's property names, with the
          operator's answers as values.

        Raises:
          ToolError: On declined, cancelled, or invalid schema. The error
            message includes pydantic validation details — adjust and retry.
        """
        try:
            validated = ElicitationSchema.model_validate(
                _normalize_schema_types(schema)
            )
        except ValidationError as e:
            raise ToolError(f"Invalid schema: {e}") from None

        result = await request_input(message=message, schema=validated)
        if result.outcome == "accepted":
            return to_json_str_safe(result.content or {})
        if result.outcome == "declined":
            raise ToolError("User declined to answer the question.")
        # cancelled
        raise ToolError("Question was cancelled before the user answered.")

    return execute


def _normalize_schema_types(value: Any) -> Any:
    # Recursively lowercase JSON Schema `type` field values. Some providers
    # (notably Gemini) emit uppercase type names like "OBJECT" / "STRING".
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            if k == "type" and isinstance(v, str):
                out[k] = v.lower()
            else:
                out[k] = _normalize_schema_types(v)
        return out
    if isinstance(value, list):
        return [_normalize_schema_types(v) for v in value]
    return value
