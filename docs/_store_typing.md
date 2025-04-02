
If you prefer a typesafe interface to the sample store, you can define a [Pydantic model](https://docs.pydantic.dev/latest/concepts/models/) which reads and writes values into the store. There are several benefits to using Pydantic models for store access:

1. You can provide type annotations and validation rules for all fields.
2. Default values for all fields are declared using standard Pydantic syntax.
3. Store names are automatically namespaced (to prevent conflicts between multiple store accessors).

#### Definition

First, derive a class from `StoreModel` (which in turn derives from Pydantic `BaseModel`):

```python
from pydantic import Field
from inspect_ai.util import StoreModel

class Activity(StoreModel):
    active: bool = Field(default=False)
    tries: int = Field(default=0)
    actions: list[str] = Field(default_factory=list)
```

Note that we define defaults for all fields. This is generally required so that you can initialise your Pydantic model from an empty store. For collections (`list` and `dict`) you should use `default_factory` so that each instance gets its own default.

There are two special field names that you cannot use in your `StoreModel`: the `store` field is used as a reference to the underlying `Store` and the optional `instance` field is used to provide a scope for use of multiple instances of a store model within a sample.

#### Usage

Use the `store_as()` function to get a typesafe interface to the store based on your model:

```python
# typed interface to store from state
activity = state.store_as(Activity)
activity.active = True
activity.tries += 1

# global store_as() function (e.g. for use from tools)
from inspect_ai.util import store_as
activity = store_as(Activity)
```

Note that all instances of `Activity` created within a running sample share the same sample `Store` so can see each other's changes. For example, you can call `state.store_as()` in multiple solvers and/or scorers and it will resolve to the same sample-scoped instance. 

The names used in the underlying `Store` are namespaced to prevent collisions with other `Store` accessors. For example, the `active` field in the `Activity` class is written to the store with the name `Activity:active`.

#### Namespaces

If you need to create multiple instances of a `StoreModel` within a sample, you can use the `instance` parameter to deliniate multiple named instances. For example:

```python
red_activity = state.store_as(Activity, instance="red_team")
blue_activity = state.store_as(Activity, instance="blue_team")
```


#### Explicit Store

The `store_as()` function automatically binds to the current sample `Store`. You can alternatively create an explicit `Store` and pass it directly to the model (e.g. for testing purposes):

```python
from inspect_ai.util import Store
store = Store()
activity = Activity(store=store)
```

