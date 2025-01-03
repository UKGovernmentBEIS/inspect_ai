# Typing


## Overview

The Inspect codebase is written using strict
[MyPy](https://mypy-lang.org/) type-checking—if you enable the same for
your project along with installing the [MyPy VS Code
Extension](https://marketplace.visualstudio.com/items?itemName=ms-python.mypy-type-checker)
you’ll benefit from all of these type definitions.

The sample store and sample metadata interfaces are weakly typed to
accommodate arbitrary user data structures. Below, we describe how to
implement a [typed store](#typed-store) and [typed
metadata](#typed-metadata) using Pydantic models.

## Typed Store

If you prefer a typesafe interface to the sample store, you can define a
[Pydantic model](https://docs.pydantic.dev/latest/concepts/models/)
which reads and writes values into the store. There are several benefits
to using Pydantic models for store access:

1.  You can provide type annotations and validation rules for all
    fields.
2.  Default values for all fields are declared using standard Pydantic
    syntax.
3.  Store names are automatically namespaced (to prevent conflicts
    between multiple store accessors).

#### Definition

First, derive a class from `StoreModel` (which in turn derives from
Pydantic `BaseModel`):

``` python
from pydantic import Field
from inspect_ai.util import StoreModel

class Activity(StoreModel):
    active: bool = Field(default=False)
    tries: int = Field(default=0)
    actions: list[str] = Field(default_factory=list)
```

Note that we define defaults for all fields. This is generally required
so that you can initialise your Pydantic model from an empty store. For
collections (`list` and `dict`) you should use `default_factory` so that
each instance gets its own default.

#### Usage

Use the `store_as()` function to get a typesafe interface to the store
based on your model:

``` python
# typed interface to store from state
activity = state.store_as(Activity)
activity.active = True
activity.tries += 1

# global store_as() function (e.g. for use from tools)
from inspect_ai.util import store_as
activity = store_as(Activity)
```

Note that all instances of `Activity` created within a running sample
share the same sample `Store` so can see each other’s changes. For
example, you can call `state.store_as()` in multiple solvers and/or
scorers and it will resolve to the same sample-scoped instance.

The names used in the underlying `Store` are namespaced to prevent
collisions with other `Store` accessors. For example, the `active` field
in the `Activity` class is written to the store with the name
`Activity:active`.

#### Explicit Store

The `store_as()` function automatically binds to the current sample
`Store`. You can alternatively create an explicit `Store` and pass it
directly to the model (e.g. for testing purposes):

``` python
from inspect_ai.util import Store
store = Store()
activity = Activity(store=store)
```

## Typed Metadata

If you want a more strongly typed interface to sample metadata, you can
define a [Pydantic
model](https://docs.pydantic.dev/latest/concepts/models/) and use it to
both validate and read metadata.

For validation, pass a `BaseModel` derived class in the `FieldSpec`. The
interface to metadata is read-only so you must also specify
`frozen=True`. For example:

``` python
from pydantic import BaseModel

class PopularityMetadata(BaseModel, frozen=True):
    category: str
    label_confidence: float

dataset = json_dataset(
    "popularity.jsonl",
    FieldSpec(
        input="question",
        target="answer_matching_behavior",
        id="question_id",
        metadata=PopularityMetadata,
    ),
)
```

To read metadata in a typesafe fashion, us the `metadata_as()` method on
`Sample` or `TaskState`:

``` python
metadata = state.metadata_as(PopularityMetadata)
```

Note again that the intended semantics of `metadata` are read-only, so
attempting to write into the returned metadata will raise a Pydantic
`FrozenInstanceError`.

If you need per-sample mutable data, use the [sample
store](agents-api.qmd#sample-store), which also supports
[typing](agents-api.qmd#store-typing) using Pydantic models.
