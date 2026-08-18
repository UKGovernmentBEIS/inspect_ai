from typing import Any, cast

_AGENT_MESSAGE_FIELDS = {"type", "author", "recipient", "role", "content"}
_AGENT_MESSAGE_PART_FIELDS = {
    "input_text": {"type", "text"},
    "encrypted_content": {"type", "encrypted_content"},
}


def validate_agent_message(value: Any) -> dict[str, Any]:
    """Validate an opaque OpenAI Responses agent-message replay item.

    Agent messages bypass ordinary typed content serialization so encrypted
    inter-agent content can be replayed to OpenAI. Keep that native path
    fail-closed: only the current scalar envelope and non-media content parts
    may be forwarded verbatim.
    """
    if not isinstance(value, dict) or value.get("type") != "agent_message":
        raise ValueError("Invalid agent_message replay item.")

    unexpected_fields = set(value) - _AGENT_MESSAGE_FIELDS
    if unexpected_fields:
        fields = ", ".join(sorted(unexpected_fields))
        raise ValueError(f"agent_message contains unsupported fields: {fields}.")

    for field in ("author", "recipient", "role"):
        if (
            field in value
            and value[field] is not None
            and not isinstance(value[field], str)
        ):
            raise ValueError(f"agent_message field '{field}' must be a string or null.")

    parts = value.get("content", [])
    if not isinstance(parts, list):
        raise ValueError("agent_message content must be a list.")

    for part in parts:
        if not isinstance(part, dict) or not isinstance(part.get("type"), str):
            raise ValueError("agent_message content parts must declare a type.")
        part_type = part["type"]
        allowed_fields = _AGENT_MESSAGE_PART_FIELDS.get(part_type)
        if allowed_fields is None:
            raise ValueError(
                f"agent_message content type '{part_type}' cannot be replayed."
            )
        unexpected_part_fields = set(part) - allowed_fields
        if unexpected_part_fields:
            fields = ", ".join(sorted(unexpected_part_fields))
            raise ValueError(
                f"agent_message {part_type} content contains unsupported fields: "
                f"{fields}."
            )
        value_field = "text" if part_type == "input_text" else "encrypted_content"
        if not isinstance(part.get(value_field), str):
            raise ValueError(
                f"agent_message {part_type} content field '{value_field}' "
                "must be a string."
            )

    return cast(dict[str, Any], value)
