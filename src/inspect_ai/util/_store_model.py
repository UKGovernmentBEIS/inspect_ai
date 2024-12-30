import inspect
from typing import Any

from pydantic import BaseModel, Field, PydanticUserError

from ._store import Store


class StoreModel(BaseModel):
    _store: Store = Field(exclude=True)

    def __init__(self, store: Store):
        super().__init__()

        # keep reference to store
        object.__setattr__(self, "_store", store)

        # validate that all fields have default or default_factory
        for field_name, field in self.model_fields.items():
            if (
                field_name != "_store"
                and field.default is None
                and field.default_factory is None
            ):
                raise PydanticUserError(
                    f"Field '{field_name}' in {self.__class__.__name__} must have either default or default_factory",
                    code="model-field-missing-annotation",
                )

    def __getattr__(self, name: str) -> Any:
        # for model fields, read the data directly from the store
        if name in self.model_fields:
            field = self.model_fields[name]
            if name not in self._store:
                # use default/default_factory if there is no value in the store
                if field.default_factory is not None:
                    params = inspect.signature(field.default_factory).parameters
                    if len(params) == 0:
                        self._store.set(name, field.default_factory())  # type: ignore[call-arg]
                    else:
                        self._store.set(name, field.default_factory({}))  # type: ignore[call-arg]
                else:
                    return field.default
            return self._store.get(name)
        # normal processing for other attributes
        else:
            return super().__getattr__(name)  # type: ignore[misc]

    def __setattr__(self, name: str, value: Any) -> None:
        # for model fields, set the data directly on the store
        if name in self.model_fields:
            self._store.set(name, value)
        else:
            super().__setattr__(name, value)

    class Config:
        arbitrary_types_allowed = True
