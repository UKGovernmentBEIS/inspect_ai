from typing import Any, Iterator

import pytest
from pydantic import AliasGenerator, BaseModel, ConfigDict, Field, ValidationError

from inspect_ai import Task, eval
from inspect_ai.solver._solver import Solver, solver
from inspect_ai.util import Store, StoreModel, store, store_as
from inspect_ai.util._store import _subtask_store


class MyModel(StoreModel):
    x: int = Field(default=5)
    y: str = Field(default="default_y")
    z: float = Field(default=1.23)


def check_solver(solver: Solver):
    log = eval(Task(solver=solver))[0]
    assert log.status == "success"


def test_store_model_basic():
    @solver
    def model_basic():
        async def solve(state, generate):
            model = MyModel()
            assert model.y == "default_y"
            assert model.z == 1.23
            return state

        return solve

    log = eval(Task(solver=model_basic()), model="mockllm/model")[0]
    assert log.status == "success"


def test_store_model_log() -> None:
    class Step(BaseModel):
        response: dict[str, Any]
        results: list[dict[str, Any]]

    class Trajectory(StoreModel):
        x: int = Field(default=5)
        y: str = Field(default="default_y")
        z: float = Field(default=1.23)
        steps: list[Step] = Field(default_factory=list)

    @solver
    def model_log():
        async def solve(state, generate):
            model = Trajectory()
            model.x = 1
            model.y = "a"
            model.steps.append(Step(response={"foo": "bar"}, results=[{"foo": "bar"}]))
            return state

        return solve

    log = eval(Task(solver=model_log()), model="mockllm/model")[0]
    assert log.samples

    # reconstruct the store from the sample
    store = Store(log.samples[0].store)
    assert store.get("Trajectory:x") == 1
    assert store.get("Trajectory:y") == "a"

    # reconstruct the store model from the sample
    my_model = Trajectory(store=store)
    assert my_model.x == 1
    assert my_model.y == "a"

    # access the store model via store_as
    my_model = log.samples[0].store_as(Trajectory)
    assert my_model.x == 1
    assert my_model.y == "a"
    assert isinstance(my_model.steps[0], Step)


def test_store_model_assignment():
    def check_values(s, m: MyModel):
        assert s.get("MyModel:x") == 42
        assert s.get("MyModel:y") == "new_value"
        assert s.get("MyModel:z") == 9.99

        # Also check the model itself
        assert m.x == 42
        assert m.y == "new_value"
        assert m.z == 9.99

    @solver
    def model_assignment():
        async def solve(state, generate):
            # test w/ explicit store
            s = Store()
            model = MyModel(store=s)
            model.x = 42
            model.y = "new_value"
            model.z = 9.99
            check_values(s, model)

            # test w/ default store
            model = store_as(MyModel)
            model.x = 42
            model.y = "new_value"
            model.z = 9.99
            check_values(store(), model)

            return state

        return solve

    assert (
        eval(Task(solver=model_assignment()), model="mockllm/model")[0].status
        == "success"
    )


def test_store_model_validation_error():
    store = Store()
    model = MyModel(store=store)

    with pytest.raises(ValidationError):
        model.x = "not an integer"


def test_store_model_behind_the_scenes_update():
    store = Store()
    model = MyModel(store=store)

    # Initially set:
    model.x = 1

    # Behind the scenes update:
    store.set("MyModel:x", 999)

    assert model.x == 999


def test_store_model_init_from_store():
    store = Store()
    store.set("MyModel:x", 999)
    model = MyModel(store=store)
    assert model.x == 999


def test_store_model_dump():
    store = Store()
    model = MyModel(store=store)
    model.x = 123
    model.y = "hello"

    dumped = model.model_dump()

    assert dumped["x"] == 123
    assert dumped["y"] == "hello"
    assert dumped["z"] == 1.23  # default

    store.set("MyModel:x", 10)
    dumped = model.model_dump()
    assert dumped["x"] == 10


def test_store_model_multiple_instances_same_store():
    store = Store()
    model1 = MyModel(store=store)
    model2 = MyModel(store=store)

    model1.x = 42
    assert model2.x == 42

    model2.y = "shared"
    assert model1.y == "shared"


def test_store_multiple_model_instances_context():
    store = Store()
    model1 = MyModel(store=store, instance="m1")
    model2 = MyModel(store=store, instance="m2")

    model1.x = 42
    assert model2.x != 42

    model2.y = "shared"
    assert model1.y != "shared"


def test_store_model_deletion():
    store = Store()
    model = MyModel(store=store)

    # Delete from store
    store.delete("MyModel:x")
    assert model.x == 5  # Should return to default value

    # Verify store state
    assert "MyModel:x" not in store


class NestedModel(BaseModel):
    name: str
    value: int


class ComplexModel(StoreModel):
    nested: NestedModel = Field(default=NestedModel(name="default", value=0))
    items: list[str] = Field(default_factory=list)


def test_store_model_complex_model_handling():
    store = Store()
    model = ComplexModel(store=store)

    # Test nested model assignment
    new_nested = NestedModel(name="test", value=42)
    model.nested = new_nested
    assert store.get("ComplexModel:nested").model_dump() == new_nested.model_dump()

    # Test list handling
    model.items = ["a", "b", "c"]
    assert store.get("ComplexModel:items") == ["a", "b", "c"]


def test_store_model_validation_on_update():
    store = Store()
    model = MyModel(store=store)

    # Test direct store update with invalid value
    with pytest.raises(ValidationError):
        store.set("MyModel:x", "invalid")
        model._sync_model()  # Should trigger validation

    # Test multiple field validation
    with pytest.raises(ValidationError):
        store.set("MyModel:x", "invalid")
        store.set("MyModel:z", "also invalid")
        model._sync_model()


def test_store_model_dump_options():
    model = MyModel()
    model.x = 42

    # Test exclude
    dumped = model.model_dump(exclude={"y"})
    assert "y" not in dumped
    assert dumped["x"] == 42

    # Test include
    dumped = model.model_dump(include={"x"})
    assert len(dumped) == 1
    assert dumped["x"] == 42

    # Test json dump
    json_dumped = model.model_dump_json()
    assert '"x":42' in json_dumped


class DerivedModel(MyModel):
    additional: str = Field(default="extra")


def test_store_model_inheritance():
    store = Store()
    derived = DerivedModel(store=store)

    # Test that base class fields work
    derived.x = 42
    assert store.get("DerivedModel:x") == 42

    # Test that new fields work
    derived.additional = "modified"
    assert store.get("DerivedModel:additional") == "modified"

    # Test that namespacing is correct
    base = MyModel(store=store)
    base.x = 100
    assert derived.x == 42  # Should not be affected by base model


class IllegalModel(StoreModel):
    my_model: MyModel = Field(default_factory=MyModel)


class IllegalModel2(StoreModel):
    my_model: MyModel | None = None


def test_error_on_embed_store_model():
    with pytest.raises(TypeError):
        IllegalModel()

    illegal = IllegalModel2()
    with pytest.raises(TypeError):
        illegal.my_model = MyModel()


@pytest.fixture
def ambient_store() -> Iterator[Store]:
    ambient = Store()
    token = _subtask_store.set(ambient)
    try:
        yield ambient
    finally:
        _subtask_store.reset(token)


def test_store_model_validation_does_not_write_ambient_store(ambient_store: Store):
    own_store = Store()
    model = MyModel(store=own_store)

    model.x = 10
    model.model_dump()

    assert ambient_store._data == {}
    assert own_store.get("MyModel:x") == 10


def test_store_model_instance_validation_does_not_write_ambient_store(
    ambient_store: Store,
):
    own_store = Store()
    model = MyModel(store=own_store, instance="m1")
    MyModel(store=own_store)

    model.x = 10
    model.model_dump()

    assert ambient_store._data == {}
    assert own_store.get("MyModel:m1:x") == 10
    assert own_store.get("MyModel:x") == 5


def test_store_model_instance_validation_uses_own_namespace():
    store = Store()
    model = MyModel(store=store, instance="m1")
    MyModel(store=store)

    with pytest.raises(ValidationError):
        model.x = "invalid"
    assert store.get("MyModel:m1:x") == 5


@pytest.mark.parametrize(
    "alias_generator", [str.upper, AliasGenerator(validation_alias=str.upper)]
)
def test_store_model_validation_with_aliases(
    ambient_store: Store, alias_generator: Any
) -> None:
    class AliasedModel(StoreModel):
        model_config = ConfigDict(alias_generator=alias_generator)
        x: int = 5

    own_store = Store()
    model = AliasedModel.model_validate({"STORE": own_store, "INSTANCE": "m1"})

    model.x = 10
    model.model_dump_json()

    assert ambient_store._data == {}
    assert own_store.get("AliasedModel:m1:x") == 10

    with pytest.raises(ValidationError):
        setattr(model, "x", "invalid")
    assert own_store.get("AliasedModel:m1:x") == 10


class AliasedNested(BaseModel):
    value: int = Field(default=0, alias="v")


class AliasedNestedModel(StoreModel):
    nested: AliasedNested = Field(default_factory=AliasedNested)


def test_store_model_nested_aliases_still_validate() -> None:
    store = Store()
    model = AliasedNestedModel(store=store)

    setattr(model, "nested", {"v": 42})
    assert model.nested.value == 42
    model.model_dump()

    store.set("AliasedNestedModel:nested", {"v": 7})
    assert model.model_dump()["nested"] == {"value": 7}

    with pytest.raises(ValidationError):
        setattr(model, "nested", {"v": "invalid"})
    assert model.nested.value == 7


class RequiredAliasedNested(BaseModel):
    value: int = Field(alias="v")


class RequiredAliasedNestedModel(StoreModel):
    nested: RequiredAliasedNested = Field(
        default_factory=lambda: RequiredAliasedNested(v=0)
    )


def test_store_model_nested_aliases_reject_field_names() -> None:
    store = Store()
    model = RequiredAliasedNestedModel(store=store)

    with pytest.raises(ValidationError):
        setattr(model, "nested", {"value": 42})
    assert model.nested.value == 0
    assert store.get("RequiredAliasedNestedModel:nested") == RequiredAliasedNested(v=0)
