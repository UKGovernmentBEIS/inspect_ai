import inspect
from typing import Any, Type, TypeVar

from pydantic import BaseModel, Field

from ._store import Store, store

STORE = "_store"


class StoreModel(BaseModel):
    """Store backed Pydandic BaseModel.

    The model is initialised from a Store, so that Store should
    either already satisfy the validation constraints of the model
    OR you should provide Field(default=) annotations for all of
    your model fields (the latter approach is recommended).
    """

    _store: Store = Field(exclude=True)

    def __init__(self, store: Store):
        super().__init__()

        # keep reference to store (object.__setattr__ bypasses our override)
        object.__setattr__(self, STORE, store)

        # populate defaults
        for name, field in self.model_fields.items():
            if name == STORE:
                continue
            # apply namespace to name
            ns_name = self._ns_name(name)
            if ns_name not in self._store:
                if field.default_factory is not None:
                    params = inspect.signature(field.default_factory).parameters
                    if len(params) == 0:
                        self._store.set(ns_name, field.default_factory())  # type: ignore[call-arg]
                    else:
                        self._store.set(ns_name, field.default_factory({}))  # type: ignore[call-arg]
                elif hasattr(field, "default"):
                    self._store.set(ns_name, field.default)

        # validate and sync model
        self._sync_model()

    def __getattr__(self, name: str) -> Any:
        if name in self.model_fields and name != STORE:
            return self._store.get(self._ns_name(name))
        else:
            return super().__getattr__(name)  # type: ignore[misc]

    def __setattr__(self, name: str, value: Any) -> None:
        if name in self.model_fields and name != STORE:
            # validate with the new value (can throw ValidationError)
            temp_data = self._store._data.copy()
            temp_data[name] = value
            self._validate_store(temp_data)

            # update the store and sync the underlying __dict__
            self._store.set(self._ns_name(name), value)
            self.__dict__[name] = value
        else:
            super().__setattr__(name, value)

    def model_dump(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self._sync_model()  # in case store was updated behind our back
        return super().model_dump(*args, **kwargs)

    def model_dump_json(self, *args: Any, **kwargs: Any) -> str:
        self._sync_model()  # in case store was updated behind our back
        return super().model_dump_json(*args, **kwargs)

    def _sync_model(self) -> None:
        self._validate_store()
        for field_name in self.model_fields.keys():
            if field_name == STORE:
                continue
            store_value = self._store.get(self._ns_name(field_name))
            self.__dict__[field_name] = store_value

    def _validate_store(self, data: dict[str, Any] | None = None) -> None:
        # validate store or custom dict
        data = data if data is not None else self._store._data

        # pick out keys to validate
        validate: dict[str, Any] = {}
        for k, v in data.items():
            if k.startswith(f"{self.__class__.__name__}:"):
                unprefixed = self._un_ns_name(k)
                validate[unprefixed] = v

        # perform validation
        type(self).model_validate(validate)

    def _ns_name(self, name: str) -> str:
        return f"{self.__class__.__name__}:{name}"

    def _un_ns_name(self, name: str) -> str:
        return name.replace(f"{self.__class__.__name__}:", "", 1)

    class Config:
        arbitrary_types_allowed = True


SMT = TypeVar("SMT", bound=StoreModel)


def store_as(model_cls: Type[SMT]) -> SMT:
    """Get a Pydantic model interface to the currently active `Store`.

    Args:
       model_cls: Pydantic model type (must derive from StoreModel)

    Returns:
       Instance of model_cls bound to current Store.
    """
    return model_cls(store())
