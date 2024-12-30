import pytest
from pydantic import Field, ValidationError

from inspect_ai.util._store import Store
from inspect_ai.util._store_model import StoreModel


# A subclass of StoreModel demonstrating typical usage
class MyModel(StoreModel):
    x: int = Field(default=5)
    y: str = Field(default="default_y")
    z: float = Field(default=1.23)


def test_store_model_basic():
    store = Store()
    model = MyModel(store=store)
    assert model.y == "default_y"
    assert model.z == 1.23


def test_store_model_assignment():
    store = Store()
    model = MyModel(store=store)

    model.x = 42
    model.y = "new_value"
    model.z = 9.99

    assert store.get("x") == 42
    assert store.get("y") == "new_value"
    assert store.get("z") == 9.99

    # Also check the model itself
    assert model.x == 42
    assert model.y == "new_value"
    assert model.z == 9.99


def test_store_model_validation_error():
    store = Store()
    model = MyModel(store=store)

    with pytest.raises(ValidationError):
        model.x = "not an integer"


def test_behind_the_scenes_update():
    store = Store()
    model = MyModel(store=store)

    # Initially set:
    model.x = 1

    # Behind the scenes update:
    store.set("x", 999)

    assert model.x == 999


def test_model_dump():
    store = Store()
    model = MyModel(store=store)
    model.x = 123
    model.y = "hello"

    dumped = model.model_dump()

    assert dumped["x"] == 123
    assert dumped["y"] == "hello"
    assert dumped["z"] == 1.23  # default


def test_namespacing_example():
    store = Store()
    _model = MyModel(store=store)
    assert "MyModel:x" in store
