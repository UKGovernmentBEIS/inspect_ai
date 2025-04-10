

If you want a more strongly typed interface to sample metadata, you can define a [Pydantic model](https://docs.pydantic.dev/latest/concepts/models/) and use it to both validate and read metadata.

For validation, pass a `BaseModel` derived class in the `FieldSpec`. The interface to metadata is read-only so you must also specify `frozen=True`. For example:

```python
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

To read metadata in a typesafe fashion, use the `metadata_as()` method on `Sample` or `TaskState`:

```python
metadata = state.metadata_as(PopularityMetadata)
```

Note again that the intended semantics of `metadata` are read-only, so attempting to write into the returned metadata will raise a Pydantic `FrozenInstanceError`. 

If you need per-sample mutable data, use the [sample store](agent-custom.qmd#sample-store), which also supports [typing](agent-custom.qmd#store-typing) using Pydantic models. 

