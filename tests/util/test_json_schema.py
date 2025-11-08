"""Tests for json_schema_to_base_model function."""

import pytest
from pydantic import BaseModel, ValidationError

from inspect_ai.util._json import JSONSchema, json_schema_to_base_model


def test_basic_string_type():
    """Test basic string type conversion."""
    schema = {"type": "object", "properties": {"name": {"type": "string"}}}
    Model = json_schema_to_base_model(schema, "TestModel")

    instance = Model(name="test")
    assert instance.name == "test"


def test_basic_integer_type():
    """Test basic integer type conversion."""
    schema = {"type": "object", "properties": {"age": {"type": "integer"}}}
    Model = json_schema_to_base_model(schema, "TestModel")

    instance = Model(age=25)
    assert instance.age == 25


def test_basic_number_type():
    """Test basic number (float) type conversion."""
    schema = {"type": "object", "properties": {"score": {"type": "number"}}}
    Model = json_schema_to_base_model(schema, "TestModel")

    instance = Model(score=98.5)
    assert instance.score == 98.5


def test_basic_boolean_type():
    """Test basic boolean type conversion."""
    schema = {"type": "object", "properties": {"active": {"type": "boolean"}}}
    Model = json_schema_to_base_model(schema, "TestModel")

    instance = Model(active=True)
    assert instance.active is True


def test_multiple_basic_types():
    """Test schema with multiple basic types."""
    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "age": {"type": "integer"},
            "score": {"type": "number"},
            "active": {"type": "boolean"},
        },
    }
    Model = json_schema_to_base_model(schema, "TestModel")

    instance = Model(name="Alice", age=30, score=95.5, active=True)
    assert instance.name == "Alice"
    assert instance.age == 30
    assert instance.score == 95.5
    assert instance.active is True


def test_required_fields():
    """Test that required fields are enforced."""
    schema = {
        "type": "object",
        "properties": {"name": {"type": "string"}, "age": {"type": "integer"}},
        "required": ["name"],
    }
    Model = json_schema_to_base_model(schema, "TestModel")

    # Should work with required field
    instance = Model(name="Bob")
    assert instance.name == "Bob"

    # Should fail without required field
    with pytest.raises(ValidationError):
        Model()


def test_optional_fields():
    """Test that optional fields work correctly."""
    schema = {
        "type": "object",
        "properties": {"name": {"type": "string"}, "nickname": {"type": "string"}},
        "required": ["name"],
    }
    Model = json_schema_to_base_model(schema, "TestModel")

    # Should work without optional field
    instance = Model(name="Bob")
    assert instance.name == "Bob"
    assert instance.nickname is None

    # Should work with optional field
    instance2 = Model(name="Bob", nickname="Bobby")
    assert instance2.nickname == "Bobby"


def test_default_values():
    """Test that default values are used."""
    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "role": {"type": "string", "default": "user"},
        },
        "required": ["name"],
    }
    Model = json_schema_to_base_model(schema, "TestModel")

    instance = Model(name="Alice")
    assert instance.role == "user"

    instance2 = Model(name="Bob", role="admin")
    assert instance2.role == "admin"


def test_array_type():
    """Test array/list type conversion."""
    schema = {
        "type": "object",
        "properties": {"tags": {"type": "array", "items": {"type": "string"}}},
    }
    Model = json_schema_to_base_model(schema, "TestModel")

    instance = Model(tags=["python", "testing"])
    assert instance.tags == ["python", "testing"]


def test_array_of_integers():
    """Test array of integers."""
    schema = {
        "type": "object",
        "properties": {"scores": {"type": "array", "items": {"type": "integer"}}},
    }
    Model = json_schema_to_base_model(schema, "TestModel")

    instance = Model(scores=[1, 2, 3, 4, 5])
    assert instance.scores == [1, 2, 3, 4, 5]


def test_nested_object():
    """Test nested object type conversion."""
    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "address": {
                "type": "object",
                "properties": {
                    "street": {"type": "string"},
                    "city": {"type": "string"},
                },
            },
        },
    }
    Model = json_schema_to_base_model(schema, "TestModel")

    instance = Model(name="Alice", address={"street": "123 Main St", "city": "NYC"})
    assert instance.name == "Alice"
    assert instance.address.street == "123 Main St"
    assert instance.address.city == "NYC"


def test_deeply_nested_object():
    """Test deeply nested object structures."""
    schema = {
        "type": "object",
        "properties": {
            "user": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "contact": {
                        "type": "object",
                        "properties": {
                            "email": {"type": "string"},
                            "phone": {"type": "string"},
                        },
                    },
                },
            }
        },
    }
    Model = json_schema_to_base_model(schema, "TestModel")

    instance = Model(
        user={
            "name": "Bob",
            "contact": {"email": "bob@example.com", "phone": "555-1234"},
        }
    )
    assert instance.user.name == "Bob"
    assert instance.user.contact.email == "bob@example.com"


def test_array_of_objects():
    """Test array containing nested objects."""
    schema = {
        "type": "object",
        "properties": {
            "users": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "age": {"type": "integer"},
                    },
                },
            }
        },
    }
    Model = json_schema_to_base_model(schema, "TestModel")

    instance = Model(users=[{"name": "Alice", "age": 30}, {"name": "Bob", "age": 25}])
    assert len(instance.users) == 2
    assert instance.users[0].name == "Alice"
    assert instance.users[1].age == 25


def test_enum_values():
    """Test enum type conversion using Literal."""
    schema = {
        "type": "object",
        "properties": {"status": {"type": "string", "enum": ["active", "inactive"]}},
    }
    Model = json_schema_to_base_model(schema, "TestModel")

    instance = Model(status="active")
    assert instance.status == "active"

    # Invalid enum value should fail validation
    with pytest.raises(ValidationError):
        Model(status="unknown")


def test_enum_with_integers():
    """Test enum with integer values."""
    schema = {
        "type": "object",
        "properties": {"priority": {"type": "integer", "enum": [1, 2, 3]}},
    }
    Model = json_schema_to_base_model(schema, "TestModel")

    instance = Model(priority=2)
    assert instance.priority == 2

    with pytest.raises(ValidationError):
        Model(priority=5)


def test_anyof_union_types():
    """Test anyOf for union types."""
    schema = {
        "type": "object",
        "properties": {"value": {"anyOf": [{"type": "string"}, {"type": "integer"}]}},
    }
    Model = json_schema_to_base_model(schema, "TestModel")

    instance1 = Model(value="text")
    assert instance1.value == "text"

    instance2 = Model(value=42)
    assert instance2.value == 42


def test_anyof_with_null():
    """Test anyOf including null type."""
    schema = {
        "type": "object",
        "properties": {
            "optional_value": {"anyOf": [{"type": "string"}, {"type": "null"}]}
        },
    }
    Model = json_schema_to_base_model(schema, "TestModel")

    instance1 = Model(optional_value="test")
    assert instance1.optional_value == "test"

    instance2 = Model(optional_value=None)
    assert instance2.optional_value is None


def test_anyof_complex_types():
    """Test anyOf with complex types like objects."""
    schema = {
        "type": "object",
        "properties": {
            "data": {
                "anyOf": [
                    {"type": "string"},
                    {
                        "type": "object",
                        "properties": {"value": {"type": "integer"}},
                    },
                ]
            }
        },
    }
    Model = json_schema_to_base_model(schema, "TestModel")

    instance1 = Model(data="simple string")
    assert instance1.data == "simple string"

    instance2 = Model(data={"value": 100})
    assert instance2.data.value == 100


def test_field_descriptions():
    """Test that field descriptions are preserved."""
    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "The user's full name"}
        },
    }
    Model = json_schema_to_base_model(schema, "TestModel")

    # Check that the field has a description in the model schema
    model_schema = Model.model_json_schema()
    assert "description" in model_schema["properties"]["name"]
    assert model_schema["properties"]["name"]["description"] == "The user's full name"


def test_field_constraints():
    """Test that field constraints are applied."""
    schema = {
        "type": "object",
        "properties": {
            "age": {"type": "integer", "minimum": 0, "maximum": 150},
            "username": {"type": "string", "minLength": 3, "maxLength": 20},
        },
    }
    Model = json_schema_to_base_model(schema, "TestModel")

    # Valid values should work
    instance = Model(age=25, username="alice")
    assert instance.age == 25

    # Values outside constraints should fail
    with pytest.raises(ValidationError):
        Model(age=-1, username="al")


def test_jsonschema_object_input():
    """Test using JSONSchema object as input."""
    # JSONSchema needs dict of JSONSchema objects for properties
    schema_dict = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "age": {"type": "integer"},
        },
        "required": ["name"],
    }
    # Convert to JSONSchema object
    schema = JSONSchema(**schema_dict)
    Model = json_schema_to_base_model(schema, "TestModel")

    instance = Model(name="Alice", age=30)
    assert instance.name == "Alice"
    assert instance.age == 30


def test_empty_schema():
    """Test schema with no properties."""
    schema = {"type": "object", "properties": {}}
    Model = json_schema_to_base_model(schema, "TestModel")

    instance = Model()
    assert isinstance(instance, BaseModel)


def test_schema_without_properties():
    """Test schema without properties field."""
    schema = {"type": "object"}
    Model = json_schema_to_base_model(schema, "TestModel")

    instance = Model()
    assert isinstance(instance, BaseModel)


def test_error_invalid_schema_type():
    """Test error handling for invalid schema type."""
    with pytest.raises(ValueError, match="Schema must be a dict"):
        json_schema_to_base_model("invalid", "TestModel")


def test_error_invalid_properties_type():
    """Test error handling for invalid properties type."""
    schema = {"type": "object", "properties": "invalid"}
    with pytest.raises(ValueError, match="'properties' must be a dict"):
        json_schema_to_base_model(schema, "TestModel")


def test_error_invalid_required_type():
    """Test error handling for invalid required field type."""
    schema = {"type": "object", "properties": {}, "required": "invalid"}
    with pytest.raises(ValueError, match="'required' must be a list"):
        json_schema_to_base_model(schema, "TestModel")


def test_error_invalid_anyof_type():
    """Test error handling for invalid anyOf type."""
    schema = {
        "type": "object",
        "properties": {"field": {"anyOf": "invalid"}},
    }
    with pytest.raises(ValueError, match="'anyOf' must be a list"):
        json_schema_to_base_model(schema, "TestModel")


def test_error_empty_anyof():
    """Test error handling for empty anyOf."""
    schema = {
        "type": "object",
        "properties": {"field": {"anyOf": []}},
    }
    with pytest.raises(ValueError, match="'anyOf' cannot be empty"):
        json_schema_to_base_model(schema, "TestModel")


def test_nested_model_naming():
    """Test that nested models have descriptive names."""
    schema = {
        "type": "object",
        "properties": {
            "billing_address": {
                "type": "object",
                "properties": {"street": {"type": "string"}},
            },
            "shipping_address": {
                "type": "object",
                "properties": {"street": {"type": "string"}},
            },
        },
    }
    Model = json_schema_to_base_model(schema, "OrderModel")

    instance = Model(
        billing_address={"street": "123 Bill St"},
        shipping_address={"street": "456 Ship Ave"},
    )
    assert instance.billing_address.street == "123 Bill St"
    assert instance.shipping_address.street == "456 Ship Ave"

    # Check that nested models have different names based on the field
    assert (
        type(instance.billing_address).__name__
        != type(instance.shipping_address).__name__
    )


def test_complex_real_world_schema():
    """Test a complex real-world-like schema."""
    schema = {
        "type": "object",
        "properties": {
            "id": {"type": "integer"},
            "username": {"type": "string", "minLength": 3},
            "email": {"type": "string"},
            "profile": {
                "type": "object",
                "properties": {
                    "first_name": {"type": "string"},
                    "last_name": {"type": "string"},
                    "age": {"type": "integer", "minimum": 0},
                    "bio": {"type": "string"},
                },
                "required": ["first_name", "last_name"],
            },
            "roles": {"type": "array", "items": {"type": "string"}},
            "status": {"type": "string", "enum": ["active", "inactive", "pending"]},
            "metadata": {
                "anyOf": [
                    {"type": "object"},
                    {"type": "null"},
                ]
            },
        },
        "required": ["id", "username", "email", "profile"],
    }
    Model = json_schema_to_base_model(schema, "UserModel")

    instance = Model(
        id=1,
        username="alice",
        email="alice@example.com",
        profile={"first_name": "Alice", "last_name": "Smith", "age": 30},
        roles=["admin", "user"],
        status="active",
        metadata={"key": "value"},
    )

    assert instance.id == 1
    assert instance.username == "alice"
    assert instance.profile.first_name == "Alice"
    assert instance.profile.age == 30
    assert instance.roles == ["admin", "user"]
    assert instance.status == "active"


def test_dict_type_without_properties():
    """Test object type without properties becomes Dict[str, Any]."""
    schema = {
        "type": "object",
        "properties": {"config": {"type": "object"}},
    }
    Model = json_schema_to_base_model(schema, "TestModel")

    instance = Model(config={"key1": "value1", "key2": 42})
    assert instance.config["key1"] == "value1"
    assert instance.config["key2"] == 42
