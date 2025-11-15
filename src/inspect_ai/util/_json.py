import types
import typing
from copy import deepcopy
from dataclasses import MISSING, is_dataclass
from datetime import date, datetime, time
from enum import EnumMeta
from typing import (
    Any,
    Dict,
    List,
    Literal,
    Optional,
    Set,
    Tuple,
    Type,
    Union,
    cast,
    get_args,
    get_origin,
    get_type_hints,
    is_typeddict,
)

from pydantic import BaseModel, Field, create_model

JSONType = Literal["string", "integer", "number", "boolean", "array", "object", "null"]
"""Valid types within JSON schema."""


class JSONSchema(BaseModel):
    """JSON Schema for type."""

    type: JSONType | None = Field(default=None)
    """JSON type of tool parameter."""

    format: str | None = Field(default=None)
    """Format of the parameter (e.g. date-time)."""

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
        elif t is datetime:
            return JSONSchema(type="string", format="date-time")
        elif t is date:
            return JSONSchema(type="string", format="date")
        elif t is time:
            return JSONSchema(type="string", format="time")
        elif t is list or t is set:
            return JSONSchema(type="array", items=JSONSchema())
        elif t is dict:
            return JSONSchema(type="object", additionalProperties=JSONSchema())
        elif (
            is_dataclass(t)
            or is_typeddict(t)
            or (isinstance(t, type) and issubclass(t, BaseModel))
        ):
            return cls_json_schema(t)
        elif isinstance(t, EnumMeta):
            return JSONSchema(enum=[item.value for item in t])
        elif t is type(None):
            return JSONSchema(type="null")
        else:
            return JSONSchema()
    elif (
        origin is list
        or origin is List
        or origin is tuple
        or origin is Tuple
        or origin is set
        or origin is Set
    ):
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
            if field.default is MISSING and field.default_factory is MISSING:
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
                    resolved = _resolve_refs(resolved)

                    # Merge in the current object fields, which should take priority
                    # This means that if you have e.g.
                    # {"$ref": "#/$defs/SubType", "description": "subtype of type SubType"},
                    # and SubType resolves to
                    # {"description": "The SubType Class", "parameters": {"param1": {"type": "string"}}},
                    # the final result will be:
                    # {"description": "subtype of type SubType", "parameters": {"param1": {"type": "string"}}}
                    return resolved | {k: o for k, o in obj.items() if k != "$ref"}

            # Process all entries in the dictionary
            return {k: _resolve_refs(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [_resolve_refs(item) for item in obj]
        else:
            return obj

    return cast(dict[str, Any], _resolve_refs(schema))


def set_additional_properties_false(schema: JSONSchema) -> None:
    # Set on top level
    schema.additionalProperties = False

    # Recursively process nested schemas
    if schema.items:
        set_additional_properties_false(schema.items)

    if schema.properties:
        for prop_schema in schema.properties.values():
            set_additional_properties_false(prop_schema)

    if schema.anyOf:
        for any_schema in schema.anyOf:
            set_additional_properties_false(any_schema)


def json_schema_to_base_model(
    schema: JSONSchema | dict[str, Any], model_name: str = "DynamicModel"
) -> type[BaseModel]:
    """Convert JSON schema to Pydantic BaseModel.

    Handles nested objects, arrays, and basic validations.

    Args:
        schema: JSON schema to convert (either JSONSchema object or dict)
        model_name: Name for the generated Pydantic model

    Returns:
        A Pydantic BaseModel class

    Raises:
        ValueError: If the schema is malformed or invalid
    """
    type_map = {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
        "null": type(None),
    }

    if isinstance(schema, JSONSchema):
        schema = schema.model_dump(exclude_none=True)

    # Validate schema structure
    if not isinstance(schema, dict):
        raise ValueError(
            f"Schema must be a dict or JSONSchema object, got {type(schema)}"
        )

    properties = schema.get("properties")
    if properties is None:
        properties = {}
    elif not isinstance(properties, dict):
        raise ValueError(f"Schema 'properties' must be a dict, got {type(properties)}")

    required_fields_list = schema.get("required", [])
    if not isinstance(required_fields_list, list):
        raise ValueError(
            f"Schema 'required' must be a list, got {type(required_fields_list)}"
        )

    required_fields = set(required_fields_list)

    fields: dict[str, Any] = {}

    for prop_name, prop_schema in properties.items():
        field_type = get_type_from_schema(prop_schema, type_map, prop_name, model_name)

        # Determine if required or optional
        is_required = prop_name in required_fields

        # Get default value
        if is_required:
            default = ...
        elif "default" in prop_schema:
            default = prop_schema["default"]
        else:
            # No default specified - make the field Optional
            # Check if it's already Optional/Union with None
            origin = get_origin(field_type)
            if origin is Union:
                args = get_args(field_type)
                if type(None) not in args:
                    field_type = Optional[field_type]
            else:
                field_type = Optional[field_type]
            default = None

        # Create Field with additional validation
        field_kwargs = {}

        # Add constraints from JSON schema
        if "minimum" in prop_schema:
            field_kwargs["ge"] = prop_schema["minimum"]
        if "maximum" in prop_schema:
            field_kwargs["le"] = prop_schema["maximum"]
        if "minLength" in prop_schema:
            field_kwargs["min_length"] = prop_schema["minLength"]
        if "maxLength" in prop_schema:
            field_kwargs["max_length"] = prop_schema["maxLength"]
        if "pattern" in prop_schema:
            field_kwargs["pattern"] = prop_schema["pattern"]
        if "description" in prop_schema:
            field_kwargs["description"] = prop_schema["description"]

        if field_kwargs:
            field_value = (field_type, Field(default, **field_kwargs))
        else:
            field_value = (field_type, default)

        fields[prop_name] = field_value

    return cast(type[BaseModel], create_model(model_name, **fields))


def get_type_from_schema(
    prop_schema: dict[str, Any],
    type_map: dict[str, Any],
    field_name: str | None = None,
    parent_name: str = "Model",
) -> Any:
    """Extract Python type from JSON schema property.

    Returns a type suitable for Pydantic model fields, which can be
    a basic type, generic alias (List[T], Dict[K,V]), or Union type.

    Args:
        prop_schema: JSON schema for the property
        type_map: Mapping from JSON types to Python types
        field_name: Name of the field (for nested model naming)
        parent_name: Name of the parent model (for nested model naming)

    Raises:
        ValueError: If the schema is malformed
    """
    if not isinstance(prop_schema, dict):
        raise ValueError(f"Property schema must be a dict, got {type(prop_schema)}")

    prop_type = prop_schema.get("type")

    # Handle anyOf (union types)
    if "anyOf" in prop_schema:
        any_of_schemas = prop_schema["anyOf"]
        if not isinstance(any_of_schemas, list):
            raise ValueError(f"'anyOf' must be a list, got {type(any_of_schemas)}")
        if not any_of_schemas:
            raise ValueError("'anyOf' cannot be empty")
        any_of_types = [
            get_type_from_schema(schema, type_map, field_name, parent_name)
            for schema in any_of_schemas
        ]
        # Remove duplicates while preserving order
        unique_types = []
        for t in any_of_types:
            if t not in unique_types:
                unique_types.append(t)
        return Union[tuple(unique_types)] if len(unique_types) > 1 else unique_types[0]

    # Handle arrays
    if prop_type == "array":
        items_schema = prop_schema.get("items", {})
        item_type = get_type_from_schema(
            items_schema, type_map, field_name, parent_name
        )
        # Using List with runtime type parameter - mypy doesn't like this but it works at runtime
        return List[item_type]  # type: ignore[valid-type]

    # Handle nested objects
    elif prop_type == "object":
        if "properties" in prop_schema:
            # Create nested model recursively with descriptive name
            if "title" in prop_schema:
                nested_name = prop_schema["title"]
            elif field_name:
                # Use parent name + field name for clarity
                nested_name = f"{parent_name}_{field_name.title().replace('_', '')}"
            else:
                nested_name = f"{parent_name}_NestedObject"
            return json_schema_to_base_model(prop_schema, nested_name)
        return Dict[str, Any]

    # Handle multiple types (JSON schema "type" can be an array)
    elif isinstance(prop_type, list):
        types = [type_map.get(t, Any) for t in prop_type if t != "null"]
        if "null" in prop_type:
            return (
                Optional[Union[tuple(types)]] if len(types) > 1 else Optional[types[0]]
            )
        return Union[tuple(types)] if len(types) > 1 else types[0]

    # Handle enums - use Literal types for better type safety
    elif "enum" in prop_schema:
        enum_values = prop_schema["enum"]
        if enum_values:
            # Use Literal type for enums
            return Literal[tuple(enum_values)]  # type: ignore[valid-type]
        # Fallback to string if empty enum
        return str if prop_type is None else type_map.get(prop_type, str)

    # Standard type
    if prop_type is not None:
        return type_map.get(prop_type, Any)

    # No type specified
    return Any
