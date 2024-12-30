import pytest
from pydantic import Field, ValidationError

from inspect_ai import Task, eval
from inspect_ai.solver._solver import Solver, solver
from inspect_ai.util import Store, StoreModel, store, store_as


# A subclass of StoreModel demonstrating typical usage
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

    assert eval(Task(solver=model_basic()))[0].status == "success"


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

    assert eval(Task(solver=model_assignment()))[0].status == "success"


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
