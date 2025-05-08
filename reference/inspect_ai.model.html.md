# inspect_ai.model


## Generation

### get_model

Get an instance of a model.

Calls to get_model() are memoized (i.e. a call with the same arguments
will return an existing instance of the model rather than creating a new
one). You can disable this with `memoize=False`.

If you prefer to immediately close models after use (as well as prevent
caching) you can employ the async context manager built in to the
`Model` class. For example:

``` python
async with get_model("openai/gpt-4o") as model:
    response = await model.generate("Say hello")
```

In this case, the model client will be closed at the end of the context
manager and will not be available in the get_model() cache.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/5044b7730b357516973690a752dfbc3d8b575b8f/src/inspect_ai/model/_model.py#L873)

``` python
def get_model(
    model: str | Model | None = None,
    *,
    role: str | None = None,
    default: str | Model | None = None,
    config: GenerateConfig = GenerateConfig(),
    base_url: str | None = None,
    api_key: str | None = None,
    memoize: bool = True,
    **model_args: Any,
) -> Model
```

`model` str \| [Model](inspect_ai.model.qmd#model) \| None  
Model specification. If `Model` is passed it is returned unmodified, if
`None` is passed then the model currently being evaluated is returned
(or if there is no evaluation then the model referred to by
`INSPECT_EVAL_MODEL`).

`role` str \| None  
Optional named role for model (e.g. for roles specified at the task or
eval level). Provide a `default` as a fallback in the case where the
`role` hasn’t been externally specified.

`default` str \| [Model](inspect_ai.model.qmd#model) \| None  
Optional. Fallback model in case the specified `model` or `role` is not
found.

`config` [GenerateConfig](inspect_ai.model.qmd#generateconfig)  
Configuration for model.

`base_url` str \| None  
Optional. Alternate base URL for model.

`api_key` str \| None  
Optional. API key for model.

`memoize` bool  
Use/store a cached version of the model based on the parameters to
`get_model()`

`**model_args` Any  
Additional args to pass to model constructor.

### Model

Model interface.

Use `get_model()` to get an instance of a model. Model provides an async
context manager for closing the connection to it after use. For example:

``` python
async with get_model("openai/gpt-4o") as model:
    response = await model.generate("Say hello")
```

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/5044b7730b357516973690a752dfbc3d8b575b8f/src/inspect_ai/model/_model.py#L258)

``` python
class Model
```

#### Attributes

`api` [ModelAPI](inspect_ai.model.qmd#modelapi)  
Model API.

`config` [GenerateConfig](inspect_ai.model.qmd#generateconfig)  
Generation config.

`name` str  
Model name.

`role` str \| None  
Model role.

#### Methods

\_\_init\_\_  
Create a model.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/5044b7730b357516973690a752dfbc3d8b575b8f/src/inspect_ai/model/_model.py#L277)

``` python
def __init__(
    self, api: ModelAPI, config: GenerateConfig, model_args: dict[str, Any] = {}
) -> None
```

`api` [ModelAPI](inspect_ai.model.qmd#modelapi)  
Model API provider.

`config` [GenerateConfig](inspect_ai.model.qmd#generateconfig)  
Model configuration.

`model_args` dict\[str, Any\]  
Optional model args

generate  
Generate output from the model.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/5044b7730b357516973690a752dfbc3d8b575b8f/src/inspect_ai/model/_model.py#L343)

``` python
async def generate(
    self,
    input: str | list[ChatMessage],
    tools: Sequence[Tool | ToolDef | ToolInfo | ToolSource] | ToolSource = [],
    tool_choice: ToolChoice | None = None,
    config: GenerateConfig = GenerateConfig(),
    cache: bool | CachePolicy = False,
) -> ModelOutput
```

`input` str \| list\[[ChatMessage](inspect_ai.model.qmd#chatmessage)\]  
Chat message input (if a `str` is passed it is converted to a
`ChatMessageUser`).

`tools` Sequence\[[Tool](inspect_ai.tool.qmd#tool) \| [ToolDef](inspect_ai.tool.qmd#tooldef) \| [ToolInfo](inspect_ai.tool.qmd#toolinfo) \| [ToolSource](inspect_ai.tool.qmd#toolsource)\] \| [ToolSource](inspect_ai.tool.qmd#toolsource)  
Tools available for the model to call.

`tool_choice` [ToolChoice](inspect_ai.tool.qmd#toolchoice) \| None  
Directives to the model as to which tools to prefer.

`config` [GenerateConfig](inspect_ai.model.qmd#generateconfig)  
Model configuration.

`cache` bool \| [CachePolicy](inspect_ai.model.qmd#cachepolicy)  
Caching behavior for generate responses (defaults to no caching).

generate_loop  
Generate output from the model, looping as long as the model calls
tools.

Similar to `generate()`, but runs in a loop resolving model tool calls.
The loop terminates when the model stops calling tools. The final
`ModelOutput` as well the message list for the conversation are returned
as a tuple.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/5044b7730b357516973690a752dfbc3d8b575b8f/src/inspect_ai/model/_model.py#L436)

``` python
async def generate_loop(
    self,
    input: str | list[ChatMessage],
    tools: Sequence[Tool | ToolDef | ToolSource] | ToolSource = [],
    config: GenerateConfig = GenerateConfig(),
    cache: bool | CachePolicy = False,
) -> tuple[list[ChatMessage], ModelOutput]
```

`input` str \| list\[[ChatMessage](inspect_ai.model.qmd#chatmessage)\]  
Chat message input (if a `str` is passed it is converted to a
`ChatMessageUser`).

`tools` Sequence\[[Tool](inspect_ai.tool.qmd#tool) \| [ToolDef](inspect_ai.tool.qmd#tooldef) \| [ToolSource](inspect_ai.tool.qmd#toolsource)\] \| [ToolSource](inspect_ai.tool.qmd#toolsource)  
Tools available for the model to call.

`config` [GenerateConfig](inspect_ai.model.qmd#generateconfig)  
Model configuration.

`cache` bool \| [CachePolicy](inspect_ai.model.qmd#cachepolicy)  
Caching behavior for generate responses (defaults to no caching).

### GenerateConfig

Model generation options.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/5044b7730b357516973690a752dfbc3d8b575b8f/src/inspect_ai/model/_generate_config.py#L113)

``` python
class GenerateConfig(BaseModel)
```

#### Attributes

`max_retries` int \| None  
Maximum number of times to retry request (defaults to unlimited).

`timeout` int \| None  
Request timeout (in seconds).

`max_connections` int \| None  
Maximum number of concurrent connections to Model API (default is model
specific).

`system_message` str \| None  
Override the default system message.

`max_tokens` int \| None  
The maximum number of tokens that can be generated in the completion
(default is model specific).

`top_p` float \| None  
An alternative to sampling with temperature, called nucleus sampling,
where the model considers the results of the tokens with top_p
probability mass.

`temperature` float \| None  
What sampling temperature to use, between 0 and 2. Higher values like
0.8 will make the output more random, while lower values like 0.2 will
make it more focused and deterministic.

`stop_seqs` list\[str\] \| None  
Sequences where the API will stop generating further tokens. The
returned text will not contain the stop sequence.

`best_of` int \| None  
Generates best_of completions server-side and returns the ‘best’ (the
one with the highest log probability per token). vLLM only.

`frequency_penalty` float \| None  
Number between -2.0 and 2.0. Positive values penalize new tokens based
on their existing frequency in the text so far, decreasing the model’s
likelihood to repeat the same line verbatim. OpenAI, Google, Grok, Groq,
vLLM, and SGLang only.

`presence_penalty` float \| None  
Number between -2.0 and 2.0. Positive values penalize new tokens based
on whether they appear in the text so far, increasing the model’s
likelihood to talk about new topics. OpenAI, Google, Grok, Groq, vLLM,
and SGLang only.

`logit_bias` dict\[int, float\] \| None  
Map token Ids to an associated bias value from -100 to 100
(e.g. “42=10,43=-10”). OpenAI, Grok, Grok, and vLLM only.

`seed` int \| None  
Random seed. OpenAI, Google, Mistral, Groq, HuggingFace, and vLLM only.

`top_k` int \| None  
Randomly sample the next word from the top_k most likely next words.
Anthropic, Google, HuggingFace, vLLM, and SGLang only.

`num_choices` int \| None  
How many chat completion choices to generate for each input message.
OpenAI, Grok, Google, TogetherAI, vLLM, and SGLang only.

`logprobs` bool \| None  
Return log probabilities of the output tokens. OpenAI, Grok, TogetherAI,
Huggingface, llama-cpp-python, vLLM, and SGLang only.

`top_logprobs` int \| None  
Number of most likely tokens (0-20) to return at each token position,
each with an associated log probability. OpenAI, Grok, Huggingface,
vLLM, and SGLang only.

`parallel_tool_calls` bool \| None  
Whether to enable parallel function calling during tool use (defaults to
True). OpenAI and Groq only.

`internal_tools` bool \| None  
Whether to automatically map tools to model internal implementations
(e.g. ‘computer’ for anthropic).

`max_tool_output` int \| None  
Maximum tool output (in bytes). Defaults to 16 \* 1024.

`cache_prompt` Literal\['auto'\] \| bool \| None  
Whether to cache the prompt prefix. Defaults to “auto”, which will
enable caching for requests with tools. Anthropic only.

`reasoning_effort` Literal\['low', 'medium', 'high'\] \| None  
Constrains effort on reasoning for reasoning models (defaults to
`medium`). Open AI o1 models only.

`reasoning_tokens` int \| None  
Maximum number of tokens to use for reasoning. Anthropic Claude models
only.

`reasoning_summary` Literal\['concise', 'detailed', 'auto'\] \| None  
Provide summary of reasoning steps (defaults to no summary). Use ‘auto’
to access the most detailed summarizer available for the current model.
OpenAI reasoning models only.

`reasoning_history` Literal\['none', 'all', 'last', 'auto'\] \| None  
Include reasoning in chat message history sent to generate.

`response_schema` [ResponseSchema](inspect_ai.model.qmd#responseschema) \| None  
Request a response format as JSONSchema (output should still be
validated). OpenAI, Google, Mistral, vLLM, and SGLang only.

`extra_body` dict\[str, Any\] \| None  
Extra body to be sent with requests to OpenAI compatible servers.
OpenAI, vLLM, and SGLang only.

#### Methods

merge  
Merge another model configuration into this one.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/5044b7730b357516973690a752dfbc3d8b575b8f/src/inspect_ai/model/_generate_config.py#L214)

``` python
def merge(
    self, other: Union["GenerateConfig", GenerateConfigArgs]
) -> "GenerateConfig"
```

`other` Union\[[GenerateConfig](inspect_ai.model.qmd#generateconfig), [GenerateConfigArgs](inspect_ai.model.qmd#generateconfigargs)\]  
Configuration to merge.

### GenerateConfigArgs

Type for kwargs that selectively override GenerateConfig.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/5044b7730b357516973690a752dfbc3d8b575b8f/src/inspect_ai/model/_generate_config.py#L28)

``` python
class GenerateConfigArgs(TypedDict, total=False)
```

#### Attributes

`max_retries` int \| None  
Maximum number of times to retry request (defaults to unlimited).

`timeout` int \| None  
Request timeout (in seconds).

`max_connections` int \| None  
Maximum number of concurrent connections to Model API (default is model
specific).

`system_message` str \| None  
Override the default system message.

`max_tokens` int \| None  
The maximum number of tokens that can be generated in the completion
(default is model specific).

`top_p` float \| None  
An alternative to sampling with temperature, called nucleus sampling,
where the model considers the results of the tokens with top_p
probability mass.

`temperature` float \| None  
What sampling temperature to use, between 0 and 2. Higher values like
0.8 will make the output more random, while lower values like 0.2 will
make it more focused and deterministic.

`stop_seqs` list\[str\] \| None  
Sequences where the API will stop generating further tokens. The
returned text will not contain the stop sequence.

`best_of` int \| None  
Generates best_of completions server-side and returns the ‘best’ (the
one with the highest log probability per token). vLLM only.

`frequency_penalty` float \| None  
Number between -2.0 and 2.0. Positive values penalize new tokens based
on their existing frequency in the text so far, decreasing the model’s
likelihood to repeat the same line verbatim. OpenAI, Google, Grok, Groq,
and vLLM only.

`presence_penalty` float \| None  
Number between -2.0 and 2.0. Positive values penalize new tokens based
on whether they appear in the text so far, increasing the model’s
likelihood to talk about new topics. OpenAI, Google, Grok, Groq, and
vLLM only.

`logit_bias` dict\[int, float\] \| None  
Map token Ids to an associated bias value from -100 to 100
(e.g. “42=10,43=-10”). OpenAI and Grok only.

`seed` int \| None  
Random seed. OpenAI, Google, Mistral, Groq, HuggingFace, and vLLM only.

`top_k` int \| None  
Randomly sample the next word from the top_k most likely next words.
Anthropic, Google, and HuggingFace only.

`num_choices` int \| None  
How many chat completion choices to generate for each input message.
OpenAI, Grok, Google, and TogetherAI only.

`logprobs` bool \| None  
Return log probabilities of the output tokens. OpenAI, Grok, TogetherAI,
Huggingface, llama-cpp-python, and vLLM only.

`top_logprobs` int \| None  
Number of most likely tokens (0-20) to return at each token position,
each with an associated log probability. OpenAI, Grok, and Huggingface
only.

`parallel_tool_calls` bool \| None  
Whether to enable parallel function calling during tool use (defaults to
True). OpenAI and Groq only.

`internal_tools` bool \| None  
Whether to automatically map tools to model internal implementations
(e.g. ‘computer’ for anthropic).

`max_tool_output` int \| None  
Maximum tool output (in bytes). Defaults to 16 \* 1024.

`cache_prompt` Literal\['auto'\] \| bool \| None  
Whether to cache the prompt prefix. Defaults to “auto”, which will
enable caching for requests with tools. Anthropic only.

`reasoning_effort` Literal\['low', 'medium', 'high'\] \| None  
Constrains effort on reasoning for reasoning models (defaults to
`medium`). Open AI o1 models only.

`reasoning_tokens` int \| None  
Maximum number of tokens to use for reasoning. Anthropic Claude models
only.

`reasoning_summary` Literal\['concise', 'detailed', 'auto'\] \| None  
Provide summary of reasoning steps (defaults to no summary). Use ‘auto’
to access the most detailed summarizer available for the current model.
OpenAI reasoning models only.

`reasoning_history` Literal\['none', 'all', 'last', 'auto'\] \| None  
Include reasoning in chat message history sent to generate.

`response_schema` [ResponseSchema](inspect_ai.model.qmd#responseschema) \| None  
Request a response format as JSONSchema (output should still be
validated). OpenAI, Google, and Mistral only.

`extra_body` dict\[str, Any\] \| None  
Extra body to be sent with requests to OpenAI compatible servers.
OpenAI, vLLM, and SGLang only.

### ResponseSchema

Schema for model response when using Structured Output.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/5044b7730b357516973690a752dfbc3d8b575b8f/src/inspect_ai/model/_generate_config.py#L11)

``` python
class ResponseSchema(BaseModel)
```

#### Attributes

`name` str  
The name of the response schema. Must be a-z, A-Z, 0-9, or contain
underscores and dashes, with a maximum length of 64.

`json_schema` [JSONSchema](inspect_ai.util.qmd#jsonschema)  
The schema for the response format, described as a JSON Schema object.

`description` str \| None  
A description of what the response format is for, used by the model to
determine how to respond in the format.

`strict` bool \| None  
Whether to enable strict schema adherence when generating the output. If
set to true, the model will always follow the exact schema defined in
the schema field. OpenAI and Mistral only.

### ModelOutput

Output from model generation.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/5044b7730b357516973690a752dfbc3d8b575b8f/src/inspect_ai/model/_model_output.py#L131)

``` python
class ModelOutput(BaseModel)
```

#### Attributes

`model` str  
Model used for generation.

`choices` list\[[ChatCompletionChoice](inspect_ai.model.qmd#chatcompletionchoice)\]  
Completion choices.

`usage` [ModelUsage](inspect_ai.model.qmd#modelusage) \| None  
Model token usage

`time` float \| None  
Time elapsed (in seconds) for call to generate.

`metadata` dict\[str, Any\] \| None  
Additional metadata associated with model output.

`error` str \| None  
Error message in the case of content moderation refusals.

`stop_reason` [StopReason](inspect_ai.model.qmd#stopreason)  
First message stop reason.

`message` [ChatMessageAssistant](inspect_ai.model.qmd#chatmessageassistant)  
First message choice.

`completion` str  
Text of first message choice text.

#### Methods

from_content  
Create ModelOutput from simple text content.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/5044b7730b357516973690a752dfbc3d8b575b8f/src/inspect_ai/model/_model_output.py#L191)

``` python
@staticmethod
def from_content(
    model: str,
    content: str | list[Content],
    stop_reason: StopReason = "stop",
    error: str | None = None,
) -> "ModelOutput"
```

`model` str  
Model name.

`content` str \| list\[[Content](inspect_ai.model.qmd#content)\]  
Text content from generation.

`stop_reason` [StopReason](inspect_ai.model.qmd#stopreason)  
Stop reason for generation.

`error` str \| None  
Error message.

for_tool_call  
Returns a ModelOutput for requesting a tool call.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/5044b7730b357516973690a752dfbc3d8b575b8f/src/inspect_ai/model/_model_output.py#L219)

``` python
@staticmethod
def for_tool_call(
    model: str,
    tool_name: str,
    tool_arguments: dict[str, Any],
    internal: JsonValue | None = None,
    tool_call_id: str | None = None,
    content: str | None = None,
) -> "ModelOutput"
```

`model` str  
model name

`tool_name` str  
The name of the tool.

`tool_arguments` dict\[str, Any\]  
The arguments passed to the tool.

`internal` JsonValue \| None  
The model’s internal info for the tool (if any).

`tool_call_id` str \| None  
Optional ID for the tool call. Defaults to a random UUID.

`content` str \| None  
Optional content to include in the message. Defaults to “tool call for
tool {tool_name}”.

### ModelCall

Model call (raw request/response data).

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/5044b7730b357516973690a752dfbc3d8b575b8f/src/inspect_ai/model/_model_call.py#L16)

``` python
class ModelCall(BaseModel)
```

#### Attributes

`request` dict\[str, JsonValue\]  
Raw data posted to model.

`response` dict\[str, JsonValue\]  
Raw response data from model.

`time` float \| None  
Time taken for underlying model call.

#### Methods

create  
Create a ModelCall object.

Create a ModelCall from arbitrary request and response objects (they
might be dataclasses, Pydandic objects, dicts, etc.). Converts all
values to JSON serialiable (exluding those that can’t be)

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/5044b7730b357516973690a752dfbc3d8b575b8f/src/inspect_ai/model/_model_call.py#L28)

``` python
@staticmethod
def create(
    request: Any,
    response: Any,
    filter: ModelCallFilter | None = None,
    time: float | None = None,
) -> "ModelCall"
```

`request` Any  
Request object (dict, dataclass, BaseModel, etc.)

`response` Any  
Response object (dict, dataclass, BaseModel, etc.)

`filter` ModelCallFilter \| None  
Function for filtering model call data.

`time` float \| None  
Time taken for underlying ModelCall

### ModelConversation

Model conversation.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/5044b7730b357516973690a752dfbc3d8b575b8f/src/inspect_ai/model/_conversation.py#L7)

``` python
class ModelConversation(Protocol)
```

#### Attributes

`messages` list\[[ChatMessage](inspect_ai.model.qmd#chatmessage)\]  
Conversation history.

`output` [ModelOutput](inspect_ai.model.qmd#modeloutput)  
Model output.

### ModelUsage

Token usage for completion.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/5044b7730b357516973690a752dfbc3d8b575b8f/src/inspect_ai/model/_model_output.py#L12)

``` python
class ModelUsage(BaseModel)
```

#### Attributes

`input_tokens` int  
Total input tokens used.

`output_tokens` int  
Total output tokens used.

`total_tokens` int  
Total tokens used.

`input_tokens_cache_write` int \| None  
Number of tokens written to the cache.

`input_tokens_cache_read` int \| None  
Number of tokens retrieved from the cache.

`reasoning_tokens` int \| None  
Number of tokens used for reasoning.

### StopReason

Reason that the model stopped or failed to generate.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/5044b7730b357516973690a752dfbc3d8b575b8f/src/inspect_ai/model/_model_output.py#L59)

``` python
StopReason = Literal[
    "stop",
    "max_tokens",
    "model_length",
    "tool_calls",
    "content_filter",
    "unknown",
]
```

### ChatCompletionChoice

Choice generated for completion.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/5044b7730b357516973690a752dfbc3d8b575b8f/src/inspect_ai/model/_model_output.py#L106)

``` python
class ChatCompletionChoice(BaseModel)
```

#### Attributes

`message` [ChatMessageAssistant](inspect_ai.model.qmd#chatmessageassistant)  
Assistant message.

`stop_reason` [StopReason](inspect_ai.model.qmd#stopreason)  
Reason that the model stopped generating.

`logprobs` [Logprobs](inspect_ai.model.qmd#logprobs) \| None  
Logprobs.

## Messages

### ChatMessage

Message in a chat conversation

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/5044b7730b357516973690a752dfbc3d8b575b8f/src/inspect_ai/model/_chat_message.py#L195)

``` python
ChatMessage = Union[
    ChatMessageSystem, ChatMessageUser, ChatMessageAssistant, ChatMessageTool
]
```

### ChatMessageBase

Base class for chat messages.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/5044b7730b357516973690a752dfbc3d8b575b8f/src/inspect_ai/model/_chat_message.py#L17)

``` python
class ChatMessageBase(BaseModel)
```

#### Attributes

`id` str \| None  
Unique identifer for message.

`content` str \| list\[[Content](inspect_ai.model.qmd#content)\]  
Content (simple string or list of content objects)

`source` Literal\['input', 'generate'\] \| None  
Source of message.

`internal` JsonValue \| None  
Model provider specific payload - typically used to aid transformation
back to model types.

`text` str  
Get the text content of this message.

ChatMessage content is very general and can contain either a simple text
value or a list of content parts (each of which can either be text or an
image). Solvers (e.g. for prompt engineering) often need to interact
with chat messages with the assumption that they are a simple string.
The text property returns either the plain str content, or if the
content is a list of text and images, the text items concatenated
together (separated by newline)

### ChatMessageSystem

System chat message.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/5044b7730b357516973690a752dfbc3d8b575b8f/src/inspect_ai/model/_chat_message.py#L85)

``` python
class ChatMessageSystem(ChatMessageBase)
```

#### Attributes

`role` Literal\['system'\]  
Conversation role.

### ChatMessageUser

User chat message.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/5044b7730b357516973690a752dfbc3d8b575b8f/src/inspect_ai/model/_chat_message.py#L92)

``` python
class ChatMessageUser(ChatMessageBase)
```

#### Attributes

`role` Literal\['user'\]  
Conversation role.

`tool_call_id` list\[str\] \| None  
ID(s) of tool call(s) this message has the content payload for.

### ChatMessageAssistant

Assistant chat message.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/5044b7730b357516973690a752dfbc3d8b575b8f/src/inspect_ai/model/_chat_message.py#L102)

``` python
class ChatMessageAssistant(ChatMessageBase)
```

#### Attributes

`role` Literal\['assistant'\]  
Conversation role.

`tool_calls` list\[ToolCall\] \| None  
Tool calls made by the model.

`model` str \| None  
Model used to generate assistant message.

### ChatMessageTool

Tool chat message.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/5044b7730b357516973690a752dfbc3d8b575b8f/src/inspect_ai/model/_chat_message.py#L155)

``` python
class ChatMessageTool(ChatMessageBase)
```

#### Attributes

`role` Literal\['tool'\]  
Conversation role.

`tool_call_id` str \| None  
ID of tool call.

`function` str \| None  
Name of function called.

`error` [ToolCallError](inspect_ai.tool.qmd#toolcallerror) \| None  
Error which occurred during tool call.

### trim_messages

Trim message list to fit within model context.

Trim the list of messages by: - Retaining all system messages. -
Retaining the ‘input’ messages from the sample. - Preserving a
proportion of the remaining messages (`preserve=0.7` by default). -
Ensuring that all assistant tool calls have corresponding tool messages.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/5044b7730b357516973690a752dfbc3d8b575b8f/src/inspect_ai/model/_trim.py#L6)

``` python
def trim_messages(
    messages: list[ChatMessage], preserve: float = 0.7
) -> list[ChatMessage]
```

`messages` list\[[ChatMessage](inspect_ai.model.qmd#chatmessage)\]  
List of messages to trim.

`preserve` float  
Ratio of converation messages to preserve (defaults to 0.7)

## Content

### Content

Content sent to or received from a model.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/5044b7730b357516973690a752dfbc3d8b575b8f/src/inspect_ai/_util/content.py#L80)

``` python
Content = Union[ContentText, ContentReasoning, ContentImage, ContentAudio, ContentVideo]
```

### ContentText

Text content.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/5044b7730b357516973690a752dfbc3d8b575b8f/src/inspect_ai/_util/content.py#L6)

``` python
class ContentText(BaseModel)
```

#### Attributes

`type` Literal\['text'\]  
Type.

`text` str  
Text content.

`refusal` bool \| None  
Was this a refusal message?

### ContentReasoning

Reasoning content.

See the specification for [thinking
blocks](https://docs.anthropic.com/en/docs/build-with-claude/extended-thinking#understanding-thinking-blocks)
for Claude models.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/5044b7730b357516973690a752dfbc3d8b575b8f/src/inspect_ai/_util/content.py#L19)

``` python
class ContentReasoning(BaseModel)
```

#### Attributes

`type` Literal\['reasoning'\]  
Type.

`reasoning` str  
Reasoning content.

`signature` str \| None  
Signature for reasoning content (used by some models to ensure that
reasoning content is not modified for replay)

`redacted` bool  
Indicates that the explicit content of this reasoning block has been
redacted.

### ContentImage

Image content.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/5044b7730b357516973690a752dfbc3d8b575b8f/src/inspect_ai/_util/content.py#L38)

``` python
class ContentImage(BaseModel)
```

#### Attributes

`type` Literal\['image'\]  
Type.

`image` str  
Either a URL of the image or the base64 encoded image data.

`detail` Literal\['auto', 'low', 'high'\]  
Specifies the detail level of the image.

Currently only supported for OpenAI. Learn more in the [Vision
guide](https://platform.openai.com/docs/guides/vision/low-or-high-fidelity-image-understanding).

### ContentAudio

Audio content.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/5044b7730b357516973690a752dfbc3d8b575b8f/src/inspect_ai/_util/content.py#L54)

``` python
class ContentAudio(BaseModel)
```

#### Attributes

`type` Literal\['audio'\]  
Type.

`audio` str  
Audio file path or base64 encoded data URL.

`format` Literal\['wav', 'mp3'\]  
Format of audio data (‘mp3’ or ‘wav’)

### ContentVideo

Video content.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/5044b7730b357516973690a752dfbc3d8b575b8f/src/inspect_ai/_util/content.py#L67)

``` python
class ContentVideo(BaseModel)
```

#### Attributes

`type` Literal\['video'\]  
Type.

`video` str  
Audio file path or base64 encoded data URL.

`format` Literal\['mp4', 'mpeg', 'mov'\]  
Format of video data (‘mp4’, ‘mpeg’, or ‘mov’)

## Tools

### execute_tools

Perform tool calls in the last assistant message.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/5044b7730b357516973690a752dfbc3d8b575b8f/src/inspect_ai/model/_call_tools.py#L94)

``` python
async def execute_tools(
    messages: list[ChatMessage],
    tools: Sequence[Tool | ToolDef | ToolSource] | ToolSource,
    max_output: int | None = None,
) -> ExecuteToolsResult
```

`messages` list\[[ChatMessage](inspect_ai.model.qmd#chatmessage)\]  
Current message list

`tools` Sequence\[[Tool](inspect_ai.tool.qmd#tool) \| [ToolDef](inspect_ai.tool.qmd#tooldef) \| [ToolSource](inspect_ai.tool.qmd#toolsource)\] \| [ToolSource](inspect_ai.tool.qmd#toolsource)  
Available tools

`max_output` int \| None  
Maximum output length (in bytes). Defaults to max_tool_output from
active GenerateConfig (16 \* 1024 by default).

### ExecuteToolsResult

Result from executing tools in the last assistant message.

In conventional tool calling scenarios there will be only a list of
`ChatMessageTool` appended and no-output. However, if there are
`handoff()` tools (used in multi-agent systems) then other messages may
be appended and an `output` may be available as well.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/5044b7730b357516973690a752dfbc3d8b575b8f/src/inspect_ai/model/_call_tools.py#L78)

``` python
class ExecuteToolsResult(NamedTuple)
```

#### Attributes

`messages` list\[[ChatMessage](inspect_ai.model.qmd#chatmessage)\]  
Messages added to conversation.

`output` [ModelOutput](inspect_ai.model.qmd#modeloutput) \| None  
Model output if a generation occurred within the conversation.

## Logprobs

### Logprob

Log probability for a token.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/5044b7730b357516973690a752dfbc3d8b575b8f/src/inspect_ai/model/_model_output.py#L83)

``` python
class Logprob(BaseModel)
```

#### Attributes

`token` str  
The predicted token represented as a string.

`logprob` float  
The log probability value of the model for the predicted token.

`bytes` list\[int\] \| None  
The predicted token represented as a byte array (a list of integers).

`top_logprobs` list\[[TopLogprob](inspect_ai.model.qmd#toplogprob)\] \| None  
If the `top_logprobs` argument is greater than 0, this will contain an
ordered list of the top K most likely tokens and their log
probabilities.

### Logprobs

Log probability information for a completion choice.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/5044b7730b357516973690a752dfbc3d8b575b8f/src/inspect_ai/model/_model_output.py#L99)

``` python
class Logprobs(BaseModel)
```

#### Attributes

`content` list\[[Logprob](inspect_ai.model.qmd#logprob)\]  
a (num_generated_tokens,) length list containing the individual log
probabilities for each generated token.

### TopLogprob

List of the most likely tokens and their log probability, at this token
position.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/5044b7730b357516973690a752dfbc3d8b575b8f/src/inspect_ai/model/_model_output.py#L70)

``` python
class TopLogprob(BaseModel)
```

#### Attributes

`token` str  
The top-kth token represented as a string.

`logprob` float  
The log probability value of the model for the top-kth token.

`bytes` list\[int\] \| None  
The top-kth token represented as a byte array (a list of integers).

## Caching

### CachePolicy

The `CachePolicy` is used to define various criteria that impact how
model calls are cached.

`expiry`: Default “24h”. The expiry time for the cache entry. This is a
string of the format “12h” for 12 hours or “1W” for a week, etc. This is
how long we will keep the cache entry, if we access it after this point
we’ll clear it. Setting to `None` will cache indefinitely.

`per_epoch`: Default True. By default we cache responses separately for
different epochs. The general use case is that if there are multiple
epochs, we should cache each response separately because scorers will
aggregate across epochs. However, sometimes a response can be cached
regardless of epoch if the call being made isn’t under test as part of
the evaluation. If False, this option allows you to bypass that and
cache independently of the epoch.

`scopes`: A dictionary of additional metadata that should be included in
the cache key. This allows for more fine-grained control over the cache
key generation.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/5044b7730b357516973690a752dfbc3d8b575b8f/src/inspect_ai/model/_cache.py#L58)

``` python
class CachePolicy
```

#### Methods

\_\_init\_\_  
Create a CachePolicy.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/5044b7730b357516973690a752dfbc3d8b575b8f/src/inspect_ai/model/_cache.py#L80)

``` python
def __init__(
    self,
    expiry: str | None = "1W",
    per_epoch: bool = True,
    scopes: dict[str, str] = {},
) -> None
```

`expiry` str \| None  
Expiry.

`per_epoch` bool  
Per epoch

`scopes` dict\[str, str\]  
Scopes

### cache_size

Calculate the size of various cached directories and files

If neither `subdirs` nor `files` are provided, the entire cache
directory will be calculated.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/5044b7730b357516973690a752dfbc3d8b575b8f/src/inspect_ai/model/_cache.py#L334)

``` python
def cache_size(
    subdirs: list[str] = [], files: list[Path] = []
) -> list[tuple[str, int]]
```

`subdirs` list\[str\]  
List of folders to filter by, which are generally model names. Empty
directories will be ignored.

`files` list\[Path\]  
List of files to filter by explicitly. Note that return value group
these up by their parent directory

### cache_clear

Clear the cache directory.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/5044b7730b357516973690a752dfbc3d8b575b8f/src/inspect_ai/model/_cache.py#L249)

``` python
def cache_clear(model: str = "") -> bool
```

`model` str  
Model to clear cache for.

### cache_list_expired

Returns a list of all the cached files that have passed their expiry
time.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/5044b7730b357516973690a752dfbc3d8b575b8f/src/inspect_ai/model/_cache.py#L363)

``` python
def cache_list_expired(filter_by: list[str] = []) -> list[Path]
```

`filter_by` list\[str\]  
Default \[\]. List of model names to filter by. If an empty list, this
will search the entire cache.

### cache_prune

Delete all expired cache entries.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/5044b7730b357516973690a752dfbc3d8b575b8f/src/inspect_ai/model/_cache.py#L403)

``` python
def cache_prune(files: list[Path] = []) -> None
```

`files` list\[Path\]  
List of files to prune. If empty, this will search the entire cache.

### cache_path

Path to cache directory.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/5044b7730b357516973690a752dfbc3d8b575b8f/src/inspect_ai/model/_cache.py#L269)

``` python
def cache_path(model: str = "") -> Path
```

`model` str  
Path to cache directory for specific model.

## Provider

### modelapi

Decorator for registering model APIs.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/5044b7730b357516973690a752dfbc3d8b575b8f/src/inspect_ai/model/_registry.py#L30)

``` python
def modelapi(name: str) -> Callable[..., type[ModelAPI]]
```

`name` str  
Name of API

### ModelAPI

Model API provider.

If you are implementing a custom ModelAPI provider your `__init__()`
method will also receive a `**model_args` parameter that will carry any
custom `model_args` (or `-M` arguments from the CLI) specified by the
user. You can then pass these on to the approriate place in your model
initialisation code (for example, here is what many of the built-in
providers do with the `model_args` passed to them:
<https://inspect.aisi.org.uk/models.html#model-args>)

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/5044b7730b357516973690a752dfbc3d8b575b8f/src/inspect_ai/model/_model.py#L98)

``` python
class ModelAPI(abc.ABC)
```

#### Methods

\_\_init\_\_  
Create a model API provider.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/5044b7730b357516973690a752dfbc3d8b575b8f/src/inspect_ai/model/_model.py#L110)

``` python
def __init__(
    self,
    model_name: str,
    base_url: str | None = None,
    api_key: str | None = None,
    api_key_vars: list[str] = [],
    config: GenerateConfig = GenerateConfig(),
) -> None
```

`model_name` str  
Model name.

`base_url` str \| None  
Alternate base URL for model.

`api_key` str \| None  
API key for model.

`api_key_vars` list\[str\]  
Environment variables that may contain keys for this provider (used for
override)

`config` [GenerateConfig](inspect_ai.model.qmd#generateconfig)  
Model configuration.

aclose  
Async close method for closing any client allocated for the model.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/5044b7730b357516973690a752dfbc3d8b575b8f/src/inspect_ai/model/_model.py#L152)

``` python
async def aclose(self) -> None
```

close  
Sync close method for closing any client allocated for the model.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/5044b7730b357516973690a752dfbc3d8b575b8f/src/inspect_ai/model/_model.py#L156)

``` python
def close(self) -> None
```

generate  
Generate output from the model.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/5044b7730b357516973690a752dfbc3d8b575b8f/src/inspect_ai/model/_model.py#L167)

``` python
@abc.abstractmethod
async def generate(
    self,
    input: list[ChatMessage],
    tools: list[ToolInfo],
    tool_choice: ToolChoice,
    config: GenerateConfig,
) -> ModelOutput | tuple[ModelOutput | Exception, ModelCall]
```

`input` list\[[ChatMessage](inspect_ai.model.qmd#chatmessage)\]  
Chat message input (if a `str` is passed it is converted to a
`ChatUserMessage`).

`tools` list\[[ToolInfo](inspect_ai.tool.qmd#toolinfo)\]  
Tools available for the model to call.

`tool_choice` [ToolChoice](inspect_ai.tool.qmd#toolchoice)  
Directives to the model as to which tools to prefer.

`config` [GenerateConfig](inspect_ai.model.qmd#generateconfig)  
Model configuration.

max_tokens  
Default max_tokens.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/5044b7730b357516973690a752dfbc3d8b575b8f/src/inspect_ai/model/_model.py#L194)

``` python
def max_tokens(self) -> int | None
```

max_tokens_for_config  
Default max_tokens for a given config.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/5044b7730b357516973690a752dfbc3d8b575b8f/src/inspect_ai/model/_model.py#L198)

``` python
def max_tokens_for_config(self, config: GenerateConfig) -> int | None
```

`config` [GenerateConfig](inspect_ai.model.qmd#generateconfig)  
Generation config.

max_connections  
Default max_connections.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/5044b7730b357516973690a752dfbc3d8b575b8f/src/inspect_ai/model/_model.py#L209)

``` python
def max_connections(self) -> int
```

connection_key  
Scope for enforcement of max_connections.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/5044b7730b357516973690a752dfbc3d8b575b8f/src/inspect_ai/model/_model.py#L213)

``` python
def connection_key(self) -> str
```

should_retry  
Should this exception be retried?

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/5044b7730b357516973690a752dfbc3d8b575b8f/src/inspect_ai/model/_model.py#L217)

``` python
def should_retry(self, ex: Exception) -> bool
```

`ex` Exception  
Exception to check for retry

collapse_user_messages  
Collapse consecutive user messages into a single message.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/5044b7730b357516973690a752dfbc3d8b575b8f/src/inspect_ai/model/_model.py#L225)

``` python
def collapse_user_messages(self) -> bool
```

collapse_assistant_messages  
Collapse consecutive assistant messages into a single message.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/5044b7730b357516973690a752dfbc3d8b575b8f/src/inspect_ai/model/_model.py#L229)

``` python
def collapse_assistant_messages(self) -> bool
```

tools_required  
Any tool use in a message stream means that tools must be passed.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/5044b7730b357516973690a752dfbc3d8b575b8f/src/inspect_ai/model/_model.py#L233)

``` python
def tools_required(self) -> bool
```

tool_result_images  
Tool results can contain images

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/5044b7730b357516973690a752dfbc3d8b575b8f/src/inspect_ai/model/_model.py#L237)

``` python
def tool_result_images(self) -> bool
```

disable_computer_screenshot_truncation  
Some models do not support truncation of computer screenshots.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/5044b7730b357516973690a752dfbc3d8b575b8f/src/inspect_ai/model/_model.py#L241)

``` python
def disable_computer_screenshot_truncation(self) -> bool
```

emulate_reasoning_history  
Chat message assistant messages with reasoning should playback reasoning
with emulation (.e.g. tags)

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/5044b7730b357516973690a752dfbc3d8b575b8f/src/inspect_ai/model/_model.py#L245)

``` python
def emulate_reasoning_history(self) -> bool
```

force_reasoning_history  
Force a specific reasoning history behavior for this provider.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/5044b7730b357516973690a752dfbc3d8b575b8f/src/inspect_ai/model/_model.py#L249)

``` python
def force_reasoning_history(self) -> Literal["none", "all", "last"] | None
```

auto_reasoning_history  
Behavior to use for reasoning_history=‘auto’

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/5044b7730b357516973690a752dfbc3d8b575b8f/src/inspect_ai/model/_model.py#L253)

``` python
def auto_reasoning_history(self) -> Literal["none", "all", "last"]
```
