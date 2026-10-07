from typing import Any, Iterator

import pytest
from pydantic import (
    AliasChoices,
    AliasGenerator,
    AliasPath,
    BaseModel,
    ConfigDict,
    Field,
    ModelWrapValidatorHandler,
    ValidationError,
    ValidationInfo,
    ValidatorFunctionWrapHandler,
    field_validator,
    model_validator,
)

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
    model.model_dump()
    model.model_dump_json()

    assert ambient_store._data == {}
    assert own_store.get("AliasedModel:m1:x") == 10

    with pytest.raises(ValidationError):
        setattr(model, "x", "invalid")
    assert own_store.get("AliasedModel:m1:x") == 10


@pytest.mark.parametrize(
    "validation_alias",
    [
        lambda name: AliasPath("payload", name),
        lambda name: AliasChoices(AliasPath("payload", name), name.upper()),
    ],
)
def test_store_model_validation_with_path_aliases(
    ambient_store: Store, validation_alias: Any
) -> None:
    class PathAliasedModel(StoreModel):
        model_config = ConfigDict(
            alias_generator=AliasGenerator(validation_alias=validation_alias)
        )
        x: int = 5

    own_store = Store()
    model = PathAliasedModel.model_validate(
        {"payload": {"store": own_store, "instance": "m1"}}
    )
    assert model.store is own_store

    model.x = 10
    model.model_dump()
    model.model_dump_json()

    assert ambient_store._data == {}
    assert own_store.get("PathAliasedModel:m1:x") == 10


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


def _limit() -> int:
    return store().get("limit", 0)


class LimitedNested(BaseModel):
    value: int = 0
    limit: int = Field(default_factory=_limit)

    @field_validator("value")
    @classmethod
    def check_value(cls, value: int) -> int:
        if value > store().get("limit", 0):
            raise ValueError("value over limit")
        return value


class LimitedModel(StoreModel):
    x: int = 0
    nested: LimitedNested = Field(default_factory=LimitedNested)

    @field_validator("x")
    @classmethod
    def check_x(cls, x: int) -> int:
        if x > store().get("limit", 0):
            raise ValueError("x over limit")
        return x

    @model_validator(mode="after")
    def check_nested(self) -> "LimitedModel":
        if self.nested.limit != store().get("limit", 0):
            raise ValueError("nested limit differs from store")
        return self


@pytest.mark.parametrize("own_store", [True, False])
def test_store_model_validators_see_sample_store(
    ambient_store: Store, own_store: bool
) -> None:
    ambient_store.set("limit", 100)
    model = LimitedModel(store=Store() if own_store else ambient_store)

    model.x = 10
    model.nested = LimitedNested(value=10)
    model.model_dump()
    model.model_dump_json()
    assert model.x == 10

    with pytest.raises(ValidationError):
        model.x = 1000
    assert model.x == 10


class NamedLimit(StoreModel):
    x: int = 1

    @model_validator(mode="after")
    def check_m1_limit(self) -> "NamedLimit":
        if self.instance == "m1" and self.x > 5:
            raise ValueError("m1 is limited to 5")
        return self


@pytest.mark.parametrize("own_store", [True, False])
def test_store_model_validators_see_instance(
    ambient_store: Store, own_store: bool
) -> None:
    backing = Store() if own_store else ambient_store
    model = NamedLimit(store=backing, instance="m1")

    with pytest.raises(ValidationError):
        model.x = 10
    assert backing.get("NamedLimit:m1:x") == 1

    NamedLimit(store=backing).x = 10
    assert backing.get("NamedLimit:x") == 10


def _check_m1_limit(instance: Any, x: Any) -> None:
    if instance == "m1" and int(x) > 5:
        raise ValueError("m1 is limited to 5")


class AfterFieldLimit(StoreModel):
    x: int = 1

    @field_validator("x", mode="after")
    @classmethod
    def check_x(cls, x: int, info: ValidationInfo) -> int:
        _check_m1_limit(info.data.get("instance"), x)
        return x


class BeforeFieldLimit(StoreModel):
    x: int = 1

    @field_validator("x", mode="before")
    @classmethod
    def check_x(cls, x: Any, info: ValidationInfo) -> Any:
        _check_m1_limit(info.data.get("instance"), x)
        return x


class PlainFieldLimit(StoreModel):
    x: int = 1

    @field_validator("x", mode="plain")
    @classmethod
    def check_x(cls, x: Any, info: ValidationInfo) -> int:
        _check_m1_limit(info.data.get("instance"), x)
        return int(x)


class WrapFieldLimit(StoreModel):
    x: int = 1

    @field_validator("x", mode="wrap")
    @classmethod
    def check_x(
        cls, x: Any, handler: ValidatorFunctionWrapHandler, info: ValidationInfo
    ) -> Any:
        _check_m1_limit(info.data.get("instance"), x)
        return handler(x)


class BeforeModelLimit(StoreModel):
    x: int = 1

    @model_validator(mode="before")
    @classmethod
    def check_m1(cls, data: Any) -> Any:
        _check_m1_limit(data.get("instance"), data.get("x", 1))
        return data


class WrapModelLimit(StoreModel):
    x: int = 1

    @model_validator(mode="wrap")
    @classmethod
    def check_m1(cls, data: Any, handler: ModelWrapValidatorHandler[Any]) -> Any:
        _check_m1_limit(data.get("instance"), data.get("x", 1))
        return handler(data)


@pytest.mark.parametrize(
    "model_cls",
    [
        AfterFieldLimit,
        BeforeFieldLimit,
        PlainFieldLimit,
        WrapFieldLimit,
        BeforeModelLimit,
        WrapModelLimit,
    ],
)
def test_store_model_early_validators_see_instance(
    model_cls: type[StoreModel],
) -> None:
    backing = Store()
    model = model_cls(store=backing, instance="m1")

    with pytest.raises(ValidationError):
        setattr(model, "x", 10)
    assert backing.get(f"{model_cls.__name__}:m1:x") == 1


def test_store_model_reserved_field_assignment_validated() -> None:
    backing = Store()
    model = MyModel(store=backing, instance="m1")
    before = dict(backing._data)

    with pytest.raises(ValidationError):
        setattr(model, "store", 17)
    with pytest.raises(ValidationError):
        setattr(model, "instance", 17)

    assert model.store is backing
    assert model.instance == "m1"
    assert backing._data == before
