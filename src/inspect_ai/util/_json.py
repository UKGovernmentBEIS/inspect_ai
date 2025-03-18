import types
import typing
from copy import deepcopy
from dataclasses import is_dataclass
from typing import (
    Any,
    Dict,
    List,
    Literal,
    Optional,
    Tuple,
    Type,
    Union,
    cast,
    get_args,
    get_origin,
    get_type_hints,
    is_typeddict,
)

from pydantic import BaseModel, Field

JSONType = Literal["string", "integer", "number", "boolean", "array", "object", "null"]
"""Valid types within JSON schema."""


class JSONSchema(BaseModel):
    """JSON Schema for type."""

    type: JSONType | None = Field(default=None)
    """JSON type of tool parameter."""

    description: str | None = Field(default=None)
    """Parameter description."""

    default: Any = Field(default=None)
    """Default value for parameter."""

    enum: list[Any] | None = Field(default=None)
    """Valid values for enum parameters."""

    items: Optional["JSONSchema"] = Field(default=None)
    """Valid type for array parameters."""

    properties: dict[str, "JSONSchema"] | None = Field(default=None)
    """Valid fields for object parametrs."""

    additionalProperties: Optional["JSONSchema"] | bool | None = Field(default=None)
    """Are additional properties allowed?"""

    anyOf: list["JSONSchema"] | None = Field(default=None)
    """Valid types for union parameters."""

    required: list[str] | None = Field(default=None)
    """Required fields for object parameters."""


def json_schema(t: Type[Any]) -> JSONSchema:
    """Provide a JSON Schema for the specified type.

    Schemas can be automatically inferred for a wide variety of
    Python class types including Pydantic BaseModel, dataclasses,
    and typed dicts.

    Args:
        t: Python type

    Returns:
        JSON Schema for type.
    """
    origin = get_origin(t)
    args = get_args(t)

    if origin is None:
        if t is int:
            return JSONSchema(type="integer")
        elif t is float:
            return JSONSchema(type="number")
        elif t is str:
            return JSONSchema(type="string")
        elif t is bool:
            return JSONSchema(type="boolean")
        elif t is list:
            return JSONSchema(type="array", items=JSONSchema())
        elif t is dict:
            return JSONSchema(type="object", additionalProperties=JSONSchema())
        elif (
            is_dataclass(t)
            or is_typeddict(t)
            or (isinstance(t, type) and issubclass(t, BaseModel))
        ):
            return cls_json_schema(t)
        elif t is type(None):
            return JSONSchema(type="null")
        else:
            return JSONSchema()
    elif origin is list or origin is List or origin is tuple or origin is Tuple:
        return JSONSchema(
            type="array", items=json_schema(args[0]) if args else JSONSchema()
        )
    elif origin is dict or origin is Dict:
        return JSONSchema(
            type="object",
            additionalProperties=json_schema(args[1])
            if len(args) > 1
            else JSONSchema(),
        )
    elif origin is Union or origin is types.UnionType:
        return JSONSchema(anyOf=[json_schema(arg) for arg in args])
    elif origin is Optional:
        return JSONSchema(
            anyOf=[json_schema(arg) for arg in args] + [JSONSchema(type="null")]
        )
    elif origin is typing.Literal:
        return JSONSchema(enum=list(args))

    return JSONSchema()  # Default case if we can't determine the type


def cls_json_schema(cls: Type[Any]) -> JSONSchema:
    properties: Dict[str, JSONSchema] = {}
    required: List[str] = []

    if is_dataclass(cls):
        fields = cls.__dataclass_fields__  # type: ignore
        for name, field in fields.items():
            properties[name] = json_schema(field.type)  # type: ignore
            if field.default == field.default_factory:
                required.append(name)
    elif isinstance(cls, type) and issubclass(cls, BaseModel):
        schema = cls.model_json_schema()
        schema = resolve_schema_references(schema)
        for name, prop in schema.get("properties", {}).items():
            properties[name] = JSONSchema(**prop)
        required = schema.get("required", [])
    elif is_typeddict(cls):
        annotations = get_type_hints(cls)
        for name, type_hint in annotations.items():
            properties[name] = json_schema(type_hint)
            if name in cls.__required_keys__:
                required.append(name)

    return JSONSchema(
        type="object",
        properties=properties,
        required=required if required else None,
        additionalProperties=False,
    )


def python_type_to_json_type(python_type: str | None) -> JSONType:
    match python_type:
        case "str":
            return "string"
        case "int":
            return "integer"
        case "float":
            return "number"
        case "bool":
            return "boolean"
        case "list":
            return "array"
        case "dict":
            return "object"
        case "None":
            return "null"
        # treat 'unknown' as string as anything can be converted to string
        case None:
            return "string"
        case _:
            raise ValueError(
                f"Unsupported type: {python_type} for Python to JSON conversion."
            )


def resolve_schema_references(schema: dict[str, Any]) -> dict[str, Any]:
    """Resolves all $ref references in a JSON schema by inlining the definitions."""
    schema = deepcopy(schema)
    definitions = schema.pop("$defs", {})

    def _resolve_refs(obj: Any) -> Any:
        if isinstance(obj, dict):
            if "$ref" in obj and obj["$ref"].startswith("#/$defs/"):
                ref_key = obj["$ref"].split("/")[-1]
                if ref_key in definitions:
                    # Replace with a deep copy of the definition
                    resolved = deepcopy(definitions[ref_key])
                    # Process any nested references in the definition
                    return _resolve_refs(resolved)

            # Process all entries in the dictionary
            return {k: _resolve_refs(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [_resolve_refs(item) for item in obj]
        else:
            return obj

    return cast(dict[str, Any], _resolve_refs(schema))
