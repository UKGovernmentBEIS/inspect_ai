from __future__ import annotations

import copy as _copy
import types
import typing
from datetime import date as _D
from datetime import datetime as _DT
from datetime import time as _T
from functools import lru_cache
from typing import (
    Annotated,
    Any,
    Callable,
    Dict,
    Literal,
    Mapping,
    MutableMapping,
    Type,
    TypeVar,
    Union,
    get_args,
    get_origin,
)

from pydantic import BaseModel
from pydantic_core import PydanticUndefined

T = TypeVar("T", bound=BaseModel)


def fast_model(
    *,
    defaults: bool = True,
    post_init: bool = True,
    keep_extras: bool = True,
    copy_mutable_defaults: bool = False,  # set True to shallow-copy list/dict/set defaults
    coerce_datetime: bool = True,  # parse ISO strings to datetime/date/time
) -> Callable[[Type[T]], Type[T]]:
    """
    Decorator that adds `fast_construct(data: dict)` to a Pydantic v2 model class.

    - Recursively builds nested models with *no validation* (fast).
    - Applies field defaults/default_factory for missing fields when `defaults=True`.
    - Calls `model_post_init(None)` when `post_init=True`.
    - Preserves extras in `__pydantic_extra__` when model_config.extra == 'allow' and `keep_extras=True`.
    - Coerces ISO strings to datetime/date/time when `coerce_datetime=True`.
    """

    def decorator(cls: type[T]) -> type[T]:
        # ---------- one-time per-class build plan ----------
        model_fields = cls.model_fields
        field_names = tuple(model_fields.keys())

        # Lazy initialization cache for type hints and derived data
        _init_cache: dict[str, Any] = {}

        def _get_lazy_init() -> tuple[
            dict[str, Any],
            dict[str, str],
            set[str],
            set[str],
            dict[str, tuple[Any, Any]],
            dict[str, typing.Callable[[Any], Any]]
        ]:
            """Lazily initialize type hints and derived data structures."""
            if "initialized" not in _init_cache:
                # Get type hints (this may trigger imports)
                type_hints = typing.get_type_hints(cls, include_extras=True)

                # Alias mapping (supports simple string alias and AliasChoices-like objects)
                def _alias_keys(field: Any) -> set[str]:
                    alias = getattr(field, "alias", None)
                    if not alias:
                        return set()
                    if isinstance(alias, str):
                        return {alias}
                    # best-effort for objects that expose .choices (e.g., AliasChoices)
                    if hasattr(alias, "choices"):
                        return {c for c in getattr(alias, "choices") if isinstance(c, str)}
                    return set()

                aliases_for: dict[str, set[str]] = {
                    name: _alias_keys(f) for name, f in model_fields.items()
                }
                all_alias_keys = {ak for v in aliases_for.values() for ak in v}

                # Reverse mapping for O(1) alias lookups
                alias_to_field: dict[str, str] = {}
                for name, aliases in aliases_for.items():
                    for alias in aliases:
                        alias_to_field[alias] = name

                # Precompute set for extras detection
                declared_and_alias_keys = set(field_names) | all_alias_keys

                # Defaults per field
                defaults_info: dict[str, tuple[Any, Any]] = {
                    name: (f.default, f.default_factory) for name, f in model_fields.items()
                }

                # Converter per field (precompiled, cached)
                converters: dict[str, typing.Callable[[Any], Any]] = {
                    name: _make_converter(
                        type_hints.get(name, f.annotation), coerce_datetime=coerce_datetime
                    )
                    for name, f in model_fields.items()
                }

                _init_cache["type_hints"] = type_hints
                _init_cache["alias_to_field"] = alias_to_field
                _init_cache["declared_and_alias_keys"] = declared_and_alias_keys
                _init_cache["defaults_info"] = defaults_info
                _init_cache["converters"] = converters
                _init_cache["initialized"] = True

            return (
                _init_cache["type_hints"],
                _init_cache["alias_to_field"],
                _init_cache["declared_and_alias_keys"],
                _init_cache["declared_and_alias_keys"],
                _init_cache["defaults_info"],
                _init_cache["converters"]
            )

        extra_mode = (getattr(cls, "model_config", {}) or {}).get("extra", None)
        allow_extras = keep_extras and (extra_mode == "allow")

        def _maybe_copy_default(v: Any) -> Any:
            if not copy_mutable_defaults:
                return v
            if isinstance(v, dict | list | set):
                return _copy.copy(v)
            return v

        def fast_construct(data: Dict[str, Any]) -> T:
            """Unchecked, recursive constructor compiled for `cls`.

            - Fills defaults if enabled.
            - Calls model_post_init(None) if enabled.
            - Attaches extras if enabled and allowed by config.
            """
            if not isinstance(data, dict):
                return data

            # Get lazily initialized data
            (
                type_hints,
                alias_to_field,
                declared_and_alias_keys,
                _,
                defaults_info,
                converters
            ) = _get_lazy_init()

            out: Dict[str, Any] = {}
            fields_set = set()  # only user-provided fields (by name or alias)

            # Consume inputs by field name or alias (optimized with reverse mapping)
            for key, value in data.items():
                if key in field_names:
                    # Direct field name match
                    out[key] = converters[key](value)
                    fields_set.add(key)
                elif key in alias_to_field:
                    # Alias match - O(1) lookup
                    field_name = alias_to_field[key]
                    if field_name not in out:  # Don't overwrite if field already set
                        out[field_name] = converters[field_name](value)
                        fields_set.add(field_name)

            # Apply defaults for any fields still missing (don't add to fields_set)
            if defaults:
                for name in field_names:
                    if name in out:
                        continue
                    dflt, factory = defaults_info[name]
                    if dflt is not PydanticUndefined:
                        out[name] = _maybe_copy_default(dflt)
                    elif factory is not None:
                        out[name] = factory()  # type: ignore[call-arg]

            inst = cls.model_construct(_fields_set=fields_set, **out)

            # Attach extras for extra='allow' (using precomputed set)
            if allow_extras:
                extras = {
                    k: v for k, v in data.items() if k not in declared_and_alias_keys
                }
                if extras:
                    object.__setattr__(inst, "__pydantic_extra__", extras)

            # Optional model_post_init(None)
            if post_init:
                mpi = getattr(inst, "model_post_init", None)
                if callable(mpi):
                    mpi(None)

            return inst

        setattr(cls, "fast_construct", fast_construct)
        return cls

    return decorator


# ---------- converter compiler (cached across classes/types) ----------


def _is_model(tp: Any) -> bool:
    try:
        return isinstance(tp, type) and issubclass(tp, BaseModel)
    except (TypeError, AttributeError):
        return False


def _strip_annotated(tp: Any) -> Any:
    return get_args(tp)[0] if get_origin(tp) is Annotated else tp


def _find_discriminator_field(model_branches: list[Any]) -> str | None:
    """Find a common discriminator field among model branches.

    A discriminator field is one that has a Literal type with a single value
    that differs across branches.
    """
    if not model_branches:
        return None

    # Get all field names from first branch
    first_branch = model_branches[0]
    if not hasattr(first_branch, "model_fields"):
        return None

    candidate_fields = set(first_branch.model_fields.keys())

    # Check each field to see if it could be a discriminator
    for field_name in candidate_fields:
        is_discriminator = True
        seen_values: set[Any] = set()

        for branch in model_branches:
            if not hasattr(branch, "model_fields"):
                is_discriminator = False
                break

            if field_name not in branch.model_fields:
                is_discriminator = False
                break

            field = branch.model_fields[field_name]
            # Check if it's a Literal type
            field_type = field.annotation

            # Handle Union[Literal[...], None] or Optional[Literal[...]]
            if get_origin(field_type) is Union:
                union_args = get_args(field_type)
                # Find the Literal type in the union
                literal_types = [
                    arg for arg in union_args if get_origin(arg) is Literal
                ]
                if literal_types:
                    field_type = literal_types[0]

            if get_origin(field_type) is Literal:
                literal_values = get_args(field_type)
                if len(literal_values) == 1:
                    value = literal_values[0]
                    if value in seen_values:
                        # Duplicate value, not a good discriminator
                        is_discriminator = False
                        break
                    seen_values.add(value)
                else:
                    # Multiple literal values, not a discriminator
                    is_discriminator = False
                    break
            else:
                # Not a literal type
                is_discriminator = False
                break

        if is_discriminator and len(seen_values) == len(model_branches):
            return str(field_name)

    return None


def _get_discriminator_value(model_cls: Any, field_name: str) -> Any:
    """Get the discriminator value for a model class."""
    if not hasattr(model_cls, "model_fields"):
        return None

    if field_name not in model_cls.model_fields:
        return None

    field = model_cls.model_fields[field_name]
    field_type = field.annotation

    # Handle Union[Literal[...], None] or Optional[Literal[...]]
    if get_origin(field_type) is Union:
        union_args = get_args(field_type)
        # Find the Literal type in the union
        literal_types = [arg for arg in union_args if get_origin(arg) is Literal]
        if literal_types:
            field_type = literal_types[0]

    if get_origin(field_type) is Literal:
        literal_values = get_args(field_type)
        if len(literal_values) == 1:
            return literal_values[0]

    # Check if there's a default value
    if field.default is not PydanticUndefined:
        return field.default

    return None


@lru_cache(maxsize=None)
def _make_converter(tp: Any, *, coerce_datetime: bool) -> Callable[[Any], Any]:
    """Returns a function v -> converted_v that:

    - Recursively fast-constructs BaseModel-typed values
    - Handles list/set/tuple/dict/mappings
    - Prefers model branches inside Unions/Optionals
    - Optionally coerces ISO strings to datetime/date/time (cheap)
    """
    tp = _strip_annotated(tp)
    origin = get_origin(tp)
    args = get_args(tp)

    # ---- scalar coercions for JSON round-trip ----
    if coerce_datetime:
        if tp is _DT:

            def conv_dt(v: Any) -> Any:
                if v is None or isinstance(v, _DT):
                    return v
                if isinstance(v, str):
                    s = v[:-1] + "+00:00" if v.endswith("Z") else v
                    try:
                        return _DT.fromisoformat(s)
                    except (ValueError, AttributeError):
                        return v  # stay unchecked
                return v

            return conv_dt
        if tp is _D:

            def conv_date(v: Any) -> Any:
                if isinstance(v, str):
                    try:
                        return _D.fromisoformat(v)
                    except (ValueError, AttributeError):
                        return v
                return v

            return conv_date
        if tp is _T:

            def conv_time(v: Any) -> Any:
                if isinstance(v, str):
                    try:
                        return _T.fromisoformat(v)
                    except (ValueError, AttributeError):
                        return v
                return v

            return conv_time

    # ---- nested BaseModel ----
    if _is_model(tp):

        def conv_model(v: Any) -> Any:
            if isinstance(v, dict):
                # Use fast_construct if available, else fallback unchecked build
                fc = getattr(tp, "fast_construct", None)
                if callable(fc):
                    return fc(v)
                return _unchecked_build(
                    tp,
                    v,
                    defaults=False,
                    post_init=False,
                    keep_extras=False,
                    coerce_datetime=coerce_datetime,
                )
            return v

        return conv_model

    # ---- Unions / Optionals ----
    if origin is Union or origin is types.UnionType:
        # Prefer model branches if input is a dict
        model_branches = [a for a in args if _is_model(_strip_annotated(a))]
        if model_branches:
            # Check for discriminated union by looking for a common discriminator field
            discriminator_field = _find_discriminator_field(model_branches)

            if discriminator_field:
                # Build a mapping from discriminator value to converter
                discriminator_map = {}
                for branch in model_branches:
                    disc_value = _get_discriminator_value(branch, discriminator_field)
                    if disc_value is not None:
                        discriminator_map[disc_value] = _make_converter(
                            branch, coerce_datetime=coerce_datetime
                        )

                def conv_discriminated_union(v: Any) -> Any:
                    if isinstance(v, dict) and discriminator_field in v:
                        disc_value = v[discriminator_field]
                        if disc_value in discriminator_map:
                            return discriminator_map[disc_value](v)
                    # Fallback to trying each branch
                    for branch in model_branches:
                        try:
                            converter = _make_converter(
                                branch, coerce_datetime=coerce_datetime
                            )
                            return converter(v)
                        except (TypeError, ValueError, KeyError, AttributeError):
                            continue
                    return v

                return conv_discriminated_union
            else:
                # No discriminator, try each branch in order
                branch_convs = [
                    _make_converter(a, coerce_datetime=coerce_datetime)
                    for a in model_branches
                ]

                def conv_union_model(v: Any) -> Any:
                    if isinstance(v, dict):
                        for f in branch_convs:
                            try:
                                return f(v)
                            except (TypeError, ValueError, KeyError, AttributeError):
                                # These are expected errors during union resolution
                                continue
                    return v

                return conv_union_model
        # Handle other Union types (including None)
        # Filter out None type
        non_none_args = [a for a in args if a is not type(None)]

        if len(non_none_args) == 1:
            # Optional type - just use the converter for the non-None type
            converter = _make_converter(
                non_none_args[0], coerce_datetime=coerce_datetime
            )
            return lambda v: converter(v) if v is not None else None
        elif len(non_none_args) > 1:
            # Multiple non-None types, try each converter
            converters = [
                _make_converter(arg, coerce_datetime=coerce_datetime)
                for arg in non_none_args
            ]

            def conv_union(v: Any) -> Any:
                if v is None:
                    return None
                # Try each converter
                for conv in converters:
                    try:
                        return conv(v)
                    except (TypeError, ValueError, KeyError, AttributeError):
                        continue
                return v

            return conv_union
        else:
            # Only None type or empty
            return lambda v: v

    # ---- containers ----
    if origin is list:
        item = (
            _make_converter(args[0], coerce_datetime=coerce_datetime)
            if args
            else (lambda x: x)
        )
        return lambda v: [item(x) for x in v]
    if origin is set:
        item = (
            _make_converter(args[0], coerce_datetime=coerce_datetime)
            if args
            else (lambda x: x)
        )
        return lambda v: {item(x) for x in v}
    if origin is tuple:
        if args and args[-1] is not Ellipsis:
            convs = [_make_converter(a, coerce_datetime=coerce_datetime) for a in args]
            return lambda v: tuple(f(x) for f, x in zip(convs, v))
        item = (
            _make_converter(args[0], coerce_datetime=coerce_datetime)
            if args
            else (lambda x: x)
        )
        return lambda v: tuple(item(x) for x in v)
    if origin in (dict, Mapping, MutableMapping):
        kf = (
            _make_converter(args[0], coerce_datetime=coerce_datetime)
            if args
            else (lambda x: x)
        )
        vf = (
            _make_converter(args[1], coerce_datetime=coerce_datetime)
            if len(args) > 1
            else (lambda x: x)
        )
        return lambda v: {kf(k): vf(val) for k, val in v.items()}

    # ---- primitives / Any / unknown ----
    return lambda v: v


# ---------- fallback for undecorated nested models ----------


def _unchecked_build(
    tp: type[BaseModel],
    data: Dict[str, Any],
    *,
    defaults: bool,
    post_init: bool,
    keep_extras: bool,
    coerce_datetime: bool,
) -> BaseModel:
    """
    Minimal unchecked constructor for nested models that weren't decorated with @fast_model.

    Applies the same scalar coercions; defaults/post_init optional.
    """
    if not isinstance(data, dict):
        return data  # type: ignore[return-value]
    hints = typing.get_type_hints(tp, include_extras=True)
    out: Dict[str, Any] = {}
    fields_set = set()

    # Build by declared names only (no alias choices here for simplicity)
    for name, f in tp.model_fields.items():
        if name in data:
            out[name] = _make_converter(
                hints.get(name, f.annotation), coerce_datetime=coerce_datetime
            )(data[name])
            fields_set.add(name)

    if defaults:
        for name, f in tp.model_fields.items():
            if name in out:
                continue
            dflt, factory = f.default, f.default_factory
            if dflt is not PydanticUndefined:
                out[name] = dflt
            elif factory is not None:
                out[name] = factory()  # type: ignore[call-arg]

    inst = tp.model_construct(_fields_set=fields_set, **out)

    if keep_extras and (getattr(tp, "model_config", {}) or {}).get("extra") == "allow":
        declared = set(tp.model_fields.keys())
        extras = {k: v for k, v in data.items() if k not in declared}
        if extras:
            object.__setattr__(inst, "__pydantic_extra__", extras)

    if post_init:
        mpi = getattr(inst, "model_post_init", None)
        if callable(mpi):
            mpi(None)

    return inst
