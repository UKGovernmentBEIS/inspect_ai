from typing import Any, Type, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from ._store import Store, store


class StoreModel(BaseModel):
    """Store backed Pydandic BaseModel.

    The model is initialised from a Store, so that Store should
    either already satisfy the validation constraints of the model
    OR you should provide Field(default=) annotations for all of
    your model fields (the latter approach is recommended).
    """

    store: Store = Field(exclude=True, default_factory=store)
    instance: str | None = Field(exclude=True, default=None)

    def model_post_init(self, __context: Any) -> None:
        for name in self.model_fields.keys():
            if name == "store":
                continue
            # if its in the store, then have our dict reflect that
            ns_name = self._ns_name(name)
            if ns_name in self.store:
                self.__dict__[name] = self.store.get(ns_name)
            # if its not in the store, then reflect dict into store
            elif name in self.__dict__.keys():
                self.store.set(ns_name, self.__dict__[name])

            # validate that we aren't using a nested StoreModel
            self._validate_value(name, self.__dict__[name])

    def __getattribute__(self, name: str) -> Any:
        # sidestep dunders and pydantic fields
        if name.startswith("__") or name.startswith("model_"):
            return object.__getattribute__(self, name)
        # handle model_fields (except 'store' and 'namespace') by reading the store
        elif name in object.__getattribute__(self, "model_fields") and name not in [
            "store",
            "instance",
        ]:
            store_key = self._ns_name(name)
            if store_key in self.store:
                return self.store.get(store_key)
            else:
                return object.__getattribute__(self, name)
        # default to super
        else:
            return super().__getattribute__(name)

    def __setattr__(self, name: str, value: Any) -> None:
        self._validate_value(name, value)
        if name in self.model_fields:
            # validate with the new value (can throw ValidationError)
            temp_data = self.store._data.copy()
            temp_data[self._ns_name(name)] = value
            self._validate_store(temp_data)

            # update the store and sync the underlying __dict__
            self.store.set(self._ns_name(name), value)
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
            if field_name == "store":
                continue
            store_value = self.store.get(self._ns_name(field_name))
            self.__dict__[field_name] = store_value

    def _validate_store(self, data: dict[str, Any] | None = None) -> None:
        # validate store or custom dict
        data = data if data is not None else self.store._data

        # pick out keys to validate
        validate: dict[str, Any] = {}
        for k, v in data.items():
            if k.startswith(f"{self.__class__.__name__}:"):
                unprefixed = self._un_ns_name(k)
                validate[unprefixed] = v

        # perform validation
        self.__class__.model_validate(validate)

    def _validate_value(self, name: str, value: Any) -> None:
        # validate that we aren't using a nested StoreModel
        if isinstance(value, StoreModel):
            raise TypeError(
                f"{name} is a StoreModel and you may not embed a StoreModel "
                "inside another StoreModel (derive from BaseModel for fields in a StoreModel)."
            )

    def _ns_name(self, name: str) -> str:
        namespace = f"{self.instance}:" if self.instance is not None else ""
        return f"{self.__class__.__name__}:{namespace}{name}"

    def _un_ns_name(self, name: str) -> str:
        name = name.replace(f"{self.__class__.__name__}:", "", 1)
        if self.instance:
            name = name.replace(f"{self.instance}:", "", 1)
        return name

    model_config = ConfigDict(arbitrary_types_allowed=True)


SMT = TypeVar("SMT", bound=StoreModel)


def store_as(model_cls: Type[SMT], instance: str | None = None) -> SMT:
    """Get a Pydantic model interface to the store.

    Args:
      model_cls: Pydantic model type (must derive from StoreModel)
      instance: Optional instance name for store (enables multiple instances
        of a given StoreModel type within a single sample)


    Returns:
      StoreModel: model_cls bound to current Store.
    """
    return model_cls(store=store(), instance=instance)
