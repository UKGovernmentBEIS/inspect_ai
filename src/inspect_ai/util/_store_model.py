from typing import Any, Type, TypeVar

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, TypeAdapter

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

    _strict_coercion: bool = PrivateAttr(default=False)
    """Raise on reads of stored values that fail field validation.

    Set per instance by `store_as(strict=True)` (via
    `_activate_strict_coercion()`), never directly. See `store_as()` for
    the user-facing semantics.
    """

    def model_post_init(self, __context: Any) -> None:
        for name in self.__class__.model_fields.keys():
            if name == "store":
                continue
            # if its in the store, then have our dict reflect that
            ns_name = self._ns_name(name)
            if ns_name in self.store:
                self._get_and_coerce_field(name)
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
        elif name in self.__class__.model_fields and name not in [
            "store",
            "instance",
        ]:
            store_key = self._ns_name(name)
            if store_key in self.store:
                return self._get_and_coerce_field(name)
            else:
                return object.__getattribute__(self, name)
        # default to super
        else:
            return super().__getattribute__(name)

    def __setattr__(self, name: str, value: Any) -> None:
        self._validate_value(name, value)
        if name in self.__class__.model_fields:
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
        for field_name in self.__class__.model_fields.keys():
            if field_name == "store":
                continue
            # in strict mode, a field with no stored value (e.g. deleted from
            # the store) has nothing to validate -- skip it rather than raising
            # about the None that Store.get returns for a missing key
            if self._strict_coercion and self._ns_name(field_name) not in self.store:
                continue
            self._get_and_coerce_field(field_name)

    def _activate_strict_coercion(self) -> None:
        """Make reads through this instance strict (see `store_as()`).

        Sets the flag consulted by `_coerce_value`, then re-reads every field
        currently present in the store so that invalid stored values raise at
        the `store_as(strict=True)` call site rather than on first field access.
        """
        self._strict_coercion = True
        for field_name in self.__class__.model_fields.keys():
            if field_name == "store":
                continue
            if self._ns_name(field_name) in self.store:
                self._get_and_coerce_field(field_name)

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

    def _get_and_coerce_field(self, field_name: str) -> Any:
        """Get a field value from the store, coerce it to the proper type, and update if needed.

        This method:
        1. Gets the raw value from the store
        2. Coerces it to the proper type if needed
        3. Updates both the store and __dict__ if coercion occurred
        4. Returns the coerced value
        """
        ns_name = self._ns_name(field_name)
        raw_value = self.store.get(ns_name)
        coerced_value = self._coerce_value(field_name, raw_value)

        # If we coerced the value (created a new object), update the store
        # so future reads are fast and mutations to mutable objects persist
        if coerced_value is not raw_value:
            self.store.set(ns_name, coerced_value)

        # Always update __dict__ to keep it in sync
        self.__dict__[field_name] = coerced_value

        return coerced_value

    def _coerce_value(self, field_name: str, value: Any) -> Any:
        """Coerce a raw value from the store to the proper field type.

        This handles nested Pydantic models, lists of models, dicts of models,
        TypedDicts, dataclasses, tuples, and other complex types.
        """
        if field_name not in self.__class__.model_fields:
            return value

        # Skip coercion for None and scalar values (they don't need it). In
        # strict mode they are validated like everything else, so that e.g. a
        # stored str where a model is declared raises rather than passing through.
        if not self._strict_coercion and self._is_scalar(value):
            return value

        field_info = self.__class__.model_fields[field_name]  # pylint: disable=unsubscriptable-object
        field_type = field_info.annotation

        # Attempt coercion with TypeAdapter. This handles BaseModels, TypedDicts,
        # dataclasses, tuples, lists, dicts, etc. Coerced non-scalar values are
        # cached back into the Store; validation itself reruns on each read
        try:
            adapter: TypeAdapter[Any] = TypeAdapter(field_type)
        except Exception:
            # pydantic cannot build a validator for this field type (e.g. an
            # arbitrary type permitted by arbitrary_types_allowed) so no
            # coercion is possible -- return the stored value as-is
            return value

        try:
            return adapter.validate_python(value)
        except Exception as ex:
            if self._strict_coercion:
                raise ValueError(
                    f"Stored value for key '{self._ns_name(field_name)}' does not "
                    f"validate against the declared type {field_type!r} of field "
                    f"'{field_name}' on {self.__class__.__name__} (stored value has "
                    f"type {type(value).__name__}): {ex}"
                ) from ex
            # If coercion fails, return the raw value
            return value

    def _is_scalar(self, value: Any) -> bool:
        """Check if a value is a scalar type that doesn't need coercion.

        Scalars include: str, int, float, bool, None, bytes
        Everything else (lists, dicts, tuples, objects) might need coercion.
        """
        return isinstance(value, str | int | float | bool | type(None) | bytes)

    model_config = ConfigDict(arbitrary_types_allowed=True)


SMT = TypeVar("SMT", bound=StoreModel)


def store_as(
    model_cls: Type[SMT], instance: str | None = None, strict: bool = False
) -> SMT:
    """Get a Pydantic model interface to the store.

    Args:
      model_cls: Pydantic model type (must derive from StoreModel)
      instance: Optional instance name for store (enables multiple instances
        of a given StoreModel type within a single sample)
      strict: When `True`, reads through the returned instance raise
        `ValueError` (naming the store key, the declared field type, and the
        actual value's type) if a stored value fails validation against the
        declared field type, rather than returning the raw value as-is.
        Values already in the store are validated before this function
        returns. Strictness is a property of the returned instance only —
        other `store_as()` calls for the same model and store are
        unaffected. Validation uses pydantic's default (lax) mode,
        so stored values pydantic can coerce to the declared type (e.g.
        `"5"` for an `int` field) are converted and cached back to the
        store, not rejected; fields whose declared types pydantic cannot
        build a validator for (e.g. arbitrary types) are always returned
        as-is, as no validation is possible for them.

    Returns:
      StoreModel: model_cls bound to current Store.
    """
    model = model_cls(store=store(), instance=instance)
    if strict:
        model._activate_strict_coercion()
    return model
