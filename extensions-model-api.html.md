# Model APIs – Inspect

You can add a model provider by deriving a new class from [ModelAPI](./reference/inspect_ai.model.html.md#modelapi) and then creating a function decorated by `@modelapi` that returns the class. These are typically implemented in separate files (for reasons described below):

    custom.py

``` python
class CustomModelAPI(ModelAPI):
    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        api_key_vars: list[str] = [],
        config: GenerateConfig = GenerateConfig(),
        **model_args: Any
    ) -> None:
        super().__init__(model_name, base_url, api_key, api_key_vars, config)

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput:
        ...
```

    providers.py

``` python
@modelapi(name="custom")
def custom():
    from .custom import CustomModelAPI

    return CustomModelAPI
```

The layer of indirection (creating a function that returns a ModelAPI class) is done so that you can separate the registration of models from the importing of libraries they require (important for limiting dependencies). You can see this used within Inspect to make all model package dependencies optional [here](https://github.com/UKGovernmentBEIS/inspect_ai/blob/main/src/inspect_ai/model/_providers/providers.py). With this scheme, packages required to interact with models (e.g. `openai`, `anthropic`, `vllm`, etc.) are only imported when their model API type is actually used.

The `__init__()` method *must* call the `super().__init__()` method, and typically instantiates the model client library.

The `__init__()` method receive a `**model_args` parameter that will carry any custom `model_args` (or `-M` and `--model-config` arguments from the CLI) specified by the user. You can then pass these on to the appropriate place in your model initialisation code (for example, here is what many of the built-in providers do with `model_args` passed to them: <https://inspect.aisi.org.uk/models.html#model-args>).

The [generate()](./reference/inspect_ai.solver.html.md#generate) method handles interacting with the model, converting inspect messages, tools, and config into model native data structures. It may optionally return a `tuple[ModelOutput, ModelCall]` to record the raw request and response in the sample transcript—see [Recording Model Calls](#sec-recording-model-calls) below.

In addition, there are a number of optional properties and methods you can override to adapt Inspect’s behaviour to your provider (default max tokens and connections, identifying rate limit errors, whether to collapse consecutive messages, etc.)—see [Provider Options](#sec-provider-options) below.

See the implementation of the [built-in model providers](https://github.com/UKGovernmentBEIS/inspect_ai/tree/main/src/inspect_ai/model/_providers) for additional insight on building a custom provider.

## Recording Model Calls

By default, [generate()](./reference/inspect_ai.solver.html.md#generate) returns a [ModelOutput](./reference/inspect_ai.model.html.md#modeloutput). You can optionally return a `tuple[ModelOutput, ModelCall]` instead, where the [ModelCall](./reference/inspect_ai.model.html.md#modelcall) captures the raw request sent to the model and the raw response received from it. This data is stored in the sample transcript (as part of the [ModelEvent](./reference/inspect_ai.event.html.md#modelevent)) and is invaluable for debugging your provider integration.

Create a [ModelCall](./reference/inspect_ai.model.html.md#modelcall) with the `ModelCall.create()` factory, which converts arbitrary request and response objects (dicts, dataclasses, Pydantic models, etc.) into JSON-serialisable data:

    custom.py

``` python
from inspect_ai.model import ModelCall

async def generate(
    self,
    input: list[ChatMessage],
    tools: list[ToolInfo],
    tool_choice: ToolChoice,
    config: GenerateConfig,
) -> tuple[ModelOutput, ModelCall]:
    # build the native request and call the model client
    request = self.build_request(input, tools, tool_choice, config)
    response = await self.client.create(**request)

    # record the raw request/response in the transcript
    model_call = ModelCall.create(request=request, response=response)

    return self.model_output(response), model_call
```

If the model has not yet responded (for example because an error occurred), pass `response=None`.

### Filtering Model Call Data

Requests often contain data you don’t want recorded verbatim—most commonly base64-encoded images, which would bloat the transcript. Pass a `filter` function to `ModelCall.create()` to transform or redact values before they are stored. The filter receives the dictionary key (or `None` for non-dict values) and the value, and returns a (possibly modified) value:

``` python
from inspect_ai.model import ModelCall

def model_call_filter(key: str | None, value: object) -> object:
    # redact base64 encoded image data
    if key == "data" and isinstance(value, str) and value.startswith("data:image"):
        return "<image data>"
    return value

model_call = ModelCall.create(
    request=request, response=response, filter=model_call_filter
)
```

## Provider Options

The [ModelAPI](./reference/inspect_ai.model.html.md#modelapi) base class defines a number of properties and methods you can override to adapt Inspect’s behaviour to your provider’s requirements. All have sensible defaults, so you only need to override the ones relevant to your provider. The most frequently used are:

| Method | Default | Purpose |
|----|----|----|
| `connection_key()` | `"default"` | Scope for enforcing `max_connections` (e.g. return the API key or account so that concurrency limits apply per-account). |
| `max_connections()` | (built-in) | Default maximum number of concurrent connections to the model API. |
| `max_tokens()` | `None` | Default `max_tokens` for generation when the user doesn’t specify one. |
| `should_retry(ex)` | `False` | Whether a given exception (e.g. a rate limit or transient server error) should trigger a retry. |
| `is_auth_failure(ex)` | `False` | Whether an exception indicates an authentication failure (used to trigger an API key refresh). |
| `collapse_user_messages()` | `False` | Collapse consecutive user messages into a single message (required by some providers). |
| `collapse_assistant_messages()` | `False` | Collapse consecutive assistant messages into a single message. |
| `tools_required()` | `False` | Whether tool definitions must be passed whenever the message stream contains tool use. |
| `tool_result_images()` | `False` | Whether tool results may contain images. |

For example, scoping connections per API key and retrying on rate limits:

``` python
from tenacity import RetryCallState

class CustomModelAPI(ModelAPI):
    ...

    def connection_key(self) -> str:
        return self.api_key or "default"

    def should_retry(self, ex: Exception) -> bool:
        return isinstance(ex, RateLimitError)
```

Beyond these, there are further options for token counting (`count_text_tokens()`, `count_media_tokens()`, `tokenize()`), reasoning history (`force_reasoning_history()`, `auto_reasoning_history()`), and provider-native context compaction (`compact()`). See the [ModelAPI](https://github.com/UKGovernmentBEIS/inspect_ai/blob/main/src/inspect_ai/model/_model.py) source code for the complete set and full documentation.

## Model Registration

If you are publishing a custom model API within a Python package, you should register an `inspect_ai` [setuptools entry point](https://setuptools.pypa.io/en/latest/userguide/entry_point.html). This will ensure that inspect loads your extension before it attempts to resolve a model name that uses your provider.

For example, if your package was named `evaltools` and your model provider was exported from a source file named `_registry.py` at the root of your package, you would register it like this in `pyproject.toml`:

``` toml
[project.entry-points.inspect_ai]
evaltools = "evaltools._registry"
```

``` toml
[project.entry-points.inspect_ai]
evaltools = "evaltools._registry"
```

``` toml
[tool.poetry.plugins.inspect_ai]
evaltools = "evaltools._registry"
```

## Model Usage

Once you’ve created the class, decorated it with `@modelapi` as shown above, and registered it, then you can use it as follows:

``` bash
inspect eval ctf.py --model custom/my-model
```

Where `my-model` is the name of some model supported by your provider (this will be passed to `__init()__` in the `model_name` argument).

You can also reference it from within Python calls to [get_model()](./reference/inspect_ai.model.html.md#get_model) or [eval()](./reference/inspect_ai.html.md#eval):

``` python
# get a model instance
model = get_model("custom/my-model")

# run an eval with the model
eval(math, model = "custom/my-model")
```
