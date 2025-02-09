# inspect_ai.model


## Generation

### get_model

Get an instance of a model.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/cfbd741f07dd94c2e95cb4016f009a47dbbda652/src/inspect_ai/model/_model.py#L595)

``` python
def get_model(
    model: str | Model | None = None,
    config: GenerateConfig = GenerateConfig(),
    base_url: str | None = None,
    api_key: str | None = None,
    **model_args: Any,
) -> Model
```

`model` str \| [Model](inspect_ai.model.qmd#model) \| None  
Model specification. If `Model` is passed it is returned unmodified, if
`None` is passed then the model currently being evaluated is returned
(or if there is no evaluation then the model referred to by
`INSPECT_EVAL_MODEL`).

`config` [GenerateConfig](inspect_ai.model.qmd#generateconfig)  
Configuration for model.

`base_url` str \| None  
Optional. Alternate base URL for model.

`api_key` str \| None  
Optional. API key for model.

`**model_args` Any  
Additional args to pass to model constructor.

### Model

Model interface.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/cfbd741f07dd94c2e95cb4016f009a47dbbda652/src/inspect_ai/model/_model.py#L180)

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

#### Methods

\_\_init\_\_  
Create a model.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/cfbd741f07dd94c2e95cb4016f009a47dbbda652/src/inspect_ai/model/_model.py#L189)

``` python
def __init__(self, api: ModelAPI, config: GenerateConfig) -> None
```

`api` [ModelAPI](inspect_ai.model.qmd#modelapi)  
Model API provider.

`config` [GenerateConfig](inspect_ai.model.qmd#generateconfig)  
Model configuration.

generate  
Generate output from the model.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/cfbd741f07dd94c2e95cb4016f009a47dbbda652/src/inspect_ai/model/_model.py#L211)

``` python
async def generate(
    self,
    input: str | list[ChatMessage],
    tools: list[Tool]
    | list[ToolDef]
    | list[ToolInfo]
    | list[Tool | ToolDef | ToolInfo] = [],
    tool_choice: ToolChoice | None = None,
    config: GenerateConfig = GenerateConfig(),
    cache: bool | CachePolicy = False,
) -> ModelOutput
```

`input` str \| list\[[ChatMessage](inspect_ai.model.qmd#chatmessage)\]  
Chat message input (if a `str` is passed it is converted to a
`ChatMessageUser`).

`tools` list\[[Tool](inspect_ai.tool.qmd#tool)\] \| list\[[ToolDef](inspect_ai.tool.qmd#tooldef)\] \| list\[[ToolInfo](inspect_ai.tool.qmd#toolinfo)\] \| list\[[Tool](inspect_ai.tool.qmd#tool) \| [ToolDef](inspect_ai.tool.qmd#tooldef) \| [ToolInfo](inspect_ai.tool.qmd#toolinfo)\]  
Tools available for the model to call.

`tool_choice` [ToolChoice](inspect_ai.tool.qmd#toolchoice) \| None  
Directives to the model as to which tools to prefer.

`config` [GenerateConfig](inspect_ai.model.qmd#generateconfig)  
Model configuration.

`cache` bool \| [CachePolicy](inspect_ai.model.qmd#cachepolicy)  
Caching behavior for generate responses (defaults to no caching).

### GenerateConfig

Model generation options.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/cfbd741f07dd94c2e95cb4016f009a47dbbda652/src/inspect_ai/model/_generate_config.py#L82)

``` python
class GenerateConfig(BaseModel)
```

#### Attributes

`max_retries` int \| None  
Maximum number of times to retry request (defaults to 5).

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
(e.g. “42=10,43=-10”). OpenAI, Grok, and Grok only.

`seed` int \| None  
Random seed. OpenAI, Google, Mistral, Groq, HuggingFace, and vLLM only.

`top_k` int \| None  
Randomly sample the next word from the top_k most likely next words.
Anthropic, Google, HuggingFace, and vLLM only.

`num_choices` int \| None  
How many chat completion choices to generate for each input message.
OpenAI, Grok, Google, TogetherAI, and vLLM only.

`logprobs` bool \| None  
Return log probabilities of the output tokens. OpenAI, Grok, TogetherAI,
Huggingface, llama-cpp-python, and vLLM only.

`top_logprobs` int \| None  
Number of most likely tokens (0-20) to return at each token position,
each with an associated log probability. OpenAI, Grok, Huggingface, and
vLLM only.

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
Constrains effort on reasoning for reasoning models. Open AI o1 models
only.

`reasoning_history` bool \| None  
Include reasoning in chat message history sent to generate.

#### Methods

merge  
Merge another model configuration into this one.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/cfbd741f07dd94c2e95cb4016f009a47dbbda652/src/inspect_ai/model/_generate_config.py#L154)

``` python
def merge(
    self, other: Union["GenerateConfig", GenerateConfigArgs]
) -> "GenerateConfig"
```

`other` Union\[[GenerateConfig](inspect_ai.model.qmd#generateconfig), [GenerateConfigArgs](inspect_ai.model.qmd#generateconfigargs)\]  
Configuration to merge.

### GenerateConfigArgs

Type for kwargs that selectively override GenerateConfig.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/cfbd741f07dd94c2e95cb4016f009a47dbbda652/src/inspect_ai/model/_generate_config.py#L9)

``` python
class GenerateConfigArgs(TypedDict, total=False)
```

#### Attributes

`max_retries` int \| None  
Maximum number of times to retry request (defaults to 5).

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
Constrains effort on reasoning for reasoning models. Open AI o1 models
only.

`reasoning_history` bool \| None  
Include reasoning in chat message history sent to generate.

### ModelOutput

Output from model generation.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/cfbd741f07dd94c2e95cb4016f009a47dbbda652/src/inspect_ai/model/_model_output.py#L102)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/cfbd741f07dd94c2e95cb4016f009a47dbbda652/src/inspect_ai/model/_model_output.py#L157)

``` python
@staticmethod
def from_content(
    model: str,
    content: str,
    stop_reason: StopReason = "stop",
    error: str | None = None,
) -> "ModelOutput"
```

`model` str  
Model name.

`content` str  
Text content from generation.

`stop_reason` [StopReason](inspect_ai.model.qmd#stopreason)  
Stop reason for generation.

`error` str \| None  
Error message.

for_tool_call  
Returns a ModelOutput for requesting a tool call.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/cfbd741f07dd94c2e95cb4016f009a47dbbda652/src/inspect_ai/model/_model_output.py#L183)

``` python
@staticmethod
def for_tool_call(
    model: str,
    tool_name: str,
    tool_arguments: dict[str, Any],
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

`tool_call_id` str \| None  
Optional ID for the tool call. Defaults to a random UUID.

`content` str \| None  
Optional content to include in the message. Defaults to “tool call for
tool {tool_name}”.

### ModelUsage

Token usage for completion.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/cfbd741f07dd94c2e95cb4016f009a47dbbda652/src/inspect_ai/model/_model_output.py#L11)

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

### StopReason

Reason that the model stopped or failed to generate.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/cfbd741f07dd94c2e95cb4016f009a47dbbda652/src/inspect_ai/model/_model_output.py#L30)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/cfbd741f07dd94c2e95cb4016f009a47dbbda652/src/inspect_ai/model/_model_output.py#L77)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/cfbd741f07dd94c2e95cb4016f009a47dbbda652/src/inspect_ai/model/_chat_message.py#L162)

``` python
ChatMessage = Union[
    ChatMessageSystem, ChatMessageUser, ChatMessageAssistant, ChatMessageTool
]
```

### ChatMessageBase

Base class for chat messages.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/cfbd741f07dd94c2e95cb4016f009a47dbbda652/src/inspect_ai/model/_chat_message.py#L15)

``` python
class ChatMessageBase(BaseModel)
```

#### Attributes

`role` Literal\['system', 'user', 'assistant', 'tool'\]  
Conversation role

`content` str \| list\[[Content](inspect_ai.model.qmd#content)\]  
Content (simple string or list of content objects)

`source` Literal\['input', 'generate'\] \| None  
Source of message.

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/cfbd741f07dd94c2e95cb4016f009a47dbbda652/src/inspect_ai/model/_chat_message.py#L70)

``` python
class ChatMessageSystem(ChatMessageBase)
```

#### Attributes

`role` Literal\['system'\]  
Conversation role.

### ChatMessageUser

User chat message.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/cfbd741f07dd94c2e95cb4016f009a47dbbda652/src/inspect_ai/model/_chat_message.py#L77)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/cfbd741f07dd94c2e95cb4016f009a47dbbda652/src/inspect_ai/model/_chat_message.py#L87)

``` python
class ChatMessageAssistant(ChatMessageBase)
```

#### Attributes

`role` Literal\['assistant'\]  
Conversation role.

`tool_calls` list\[ToolCall\] \| None  
Tool calls made by the model.

`reasoning` str \| None  
Reasoning content.

### ChatMessageTool

Tool chat message.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/cfbd741f07dd94c2e95cb4016f009a47dbbda652/src/inspect_ai/model/_chat_message.py#L122)

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

## Content

### Content

Content sent to or received from a model.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/cfbd741f07dd94c2e95cb4016f009a47dbbda652/src/inspect_ai/_util/content.py#L58)

``` python
Content = Union[ContentText, ContentImage, ContentAudio, ContentVideo]
```

### ContentText

Text content.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/cfbd741f07dd94c2e95cb4016f009a47dbbda652/src/inspect_ai/_util/content.py#L6)

``` python
class ContentText(BaseModel)
```

#### Attributes

`type` Literal\['text'\]  
Type.

`text` str  
Text content.

### ContentImage

Image content.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/cfbd741f07dd94c2e95cb4016f009a47dbbda652/src/inspect_ai/_util/content.py#L16)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/cfbd741f07dd94c2e95cb4016f009a47dbbda652/src/inspect_ai/_util/content.py#L32)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/cfbd741f07dd94c2e95cb4016f009a47dbbda652/src/inspect_ai/_util/content.py#L45)

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

## Logprobs

### Logprob

Log probability for a token.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/cfbd741f07dd94c2e95cb4016f009a47dbbda652/src/inspect_ai/model/_model_output.py#L54)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/cfbd741f07dd94c2e95cb4016f009a47dbbda652/src/inspect_ai/model/_model_output.py#L70)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/cfbd741f07dd94c2e95cb4016f009a47dbbda652/src/inspect_ai/model/_model_output.py#L41)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/cfbd741f07dd94c2e95cb4016f009a47dbbda652/src/inspect_ai/model/_cache.py#L58)

``` python
class CachePolicy
```

#### Methods

\_\_init\_\_  
Create a CachePolicy.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/cfbd741f07dd94c2e95cb4016f009a47dbbda652/src/inspect_ai/model/_cache.py#L80)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/cfbd741f07dd94c2e95cb4016f009a47dbbda652/src/inspect_ai/model/_cache.py#L332)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/cfbd741f07dd94c2e95cb4016f009a47dbbda652/src/inspect_ai/model/_cache.py#L247)

``` python
def cache_clear(model: str = "") -> bool
```

`model` str  
Model to clear cache for.

### cache_list_expired

Returns a list of all the cached files that have passed their expiry
time.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/cfbd741f07dd94c2e95cb4016f009a47dbbda652/src/inspect_ai/model/_cache.py#L361)

``` python
def cache_list_expired(filter_by: list[str] = []) -> list[Path]
```

`filter_by` list\[str\]  
Default \[\]. List of model names to filter by. If an empty list, this
will search the entire cache.

### cache_prune

Delete all expired cache entries.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/cfbd741f07dd94c2e95cb4016f009a47dbbda652/src/inspect_ai/model/_cache.py#L401)

``` python
def cache_prune(files: list[Path] = []) -> None
```

`files` list\[Path\]  
List of files to prune. If empty, this will search the entire cache.

### cache_path

Path to cache directory.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/cfbd741f07dd94c2e95cb4016f009a47dbbda652/src/inspect_ai/model/_cache.py#L267)

``` python
def cache_path(model: str = "") -> Path
```

`model` str  
Path to cache directory for specific model.

## Provider

### modelapi

Decorator for registering model APIs.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/cfbd741f07dd94c2e95cb4016f009a47dbbda652/src/inspect_ai/model/_registry.py#L30)

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
https://inspect.ai-safety-institute.org.uk/models.html#model-args)

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/cfbd741f07dd94c2e95cb4016f009a47dbbda652/src/inspect_ai/model/_model.py#L58)

``` python
class ModelAPI(abc.ABC)
```

#### Methods

\_\_init\_\_  
Create a model API provider.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/cfbd741f07dd94c2e95cb4016f009a47dbbda652/src/inspect_ai/model/_model.py#L70)

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

generate  
Generate output from the model.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/cfbd741f07dd94c2e95cb4016f009a47dbbda652/src/inspect_ai/model/_model.py#L112)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/cfbd741f07dd94c2e95cb4016f009a47dbbda652/src/inspect_ai/model/_model.py#L139)

``` python
def max_tokens(self) -> int | None
```

max_connections  
Default max_connections.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/cfbd741f07dd94c2e95cb4016f009a47dbbda652/src/inspect_ai/model/_model.py#L143)

``` python
def max_connections(self) -> int
```

connection_key  
Scope for enforcement of max_connections.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/cfbd741f07dd94c2e95cb4016f009a47dbbda652/src/inspect_ai/model/_model.py#L147)

``` python
def connection_key(self) -> str
```

is_rate_limit  
Is this exception a rate limit error.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/cfbd741f07dd94c2e95cb4016f009a47dbbda652/src/inspect_ai/model/_model.py#L151)

``` python
def is_rate_limit(self, ex: BaseException) -> bool
```

`ex` BaseException  
Exception to check for rate limit.

collapse_user_messages  
Collapse consecutive user messages into a single message.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/cfbd741f07dd94c2e95cb4016f009a47dbbda652/src/inspect_ai/model/_model.py#L159)

``` python
def collapse_user_messages(self) -> bool
```

collapse_assistant_messages  
Collapse consecutive assistant messages into a single message.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/cfbd741f07dd94c2e95cb4016f009a47dbbda652/src/inspect_ai/model/_model.py#L163)

``` python
def collapse_assistant_messages(self) -> bool
```

tools_required  
Any tool use in a message stream means that tools must be passed.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/cfbd741f07dd94c2e95cb4016f009a47dbbda652/src/inspect_ai/model/_model.py#L167)

``` python
def tools_required(self) -> bool
```

tool_result_images  
Tool results can contain images

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/cfbd741f07dd94c2e95cb4016f009a47dbbda652/src/inspect_ai/model/_model.py#L171)

``` python
def tool_result_images(self) -> bool
```

has_reasoning_history  
Chat message assistant messages can include reasoning.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/cfbd741f07dd94c2e95cb4016f009a47dbbda652/src/inspect_ai/model/_model.py#L175)

``` python
def has_reasoning_history(self) -> bool
```
