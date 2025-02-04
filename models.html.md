# Using Models


## Overview

Inspect has support for a wide variety of language model APIs and can be
extended to support arbitrary additional ones. Support for the following
providers is built in to Inspect:

|  |  |
|----|----|
| Lab APIs | [OpenAI](providers.qmd#openai), [Anthropic](providers.qmd#anthropic), [Google](providers.qmd#google), [Grok](providers.qmd#grok), [Mistral](providers.qmd#mistral) |
| Cloud APIs | [AWS Bedrock](providers.qmd#aws-bedrock), [Azure AI](providers.qmd#azure-ai), [Vertex AI](providers.qmd#vertex-ai) |
| Open (Hosted) | [Groq](providers.qmd#groq), [Together AI](providers.qmd#together-ai), [Cloudflare](providers.qmd#cloudflare), [Goodfire](providers.qmd#goodfire) |
| Open (Local) | [Hugging Face](providers.qmd#hugging-face), [vLLM](providers.qmd#vllm), [Ollama](providers.qmd#ollama), [Lllama-cpp-python](providers.qmd#llama-cpp-python) |

<br/>

If the provider you are using is not listed above, you may still be able
to use it if:

1.  It is available via OpenRouter (see the docs on using
    [OpenRouter](providers.qmd#openrouter) with Inspect).

2.  It provides an OpenAI compatible API endpoint. In this scenario, use
    the Inspect [OpenAI](providers.qmd#openai) interface and set the
    `OPENAI_BASE_URL` environment variable to the apprpriate value for
    your provider.

You can also create [Model API Extensions](extensions.qmd#model-apis) to
add model providers using their native interface.

Below we’ll describe various ways to specify and provide options to
models in Inspect evaluations. Review this first, then see the
provider-specific sections for additional usage details and available
options.

## Selecting a Model

To select a model for an evaluation, pass it’s name on the command line
or use the `model` argument of the `eval()` function:

``` bash
inspect eval arc.py --model openai/gpt-4o-mini
inspect eval arc.py --model anthropic/claude-3-5-sonnet-latest
```

Or:

``` python
eval("arc.py", model="openai/gpt-4o-mini")
eval("arc.py", model="anthropic/claude-3-5-sonnet-latest")
```

Alternatively, you can set the `INSPECT_EVAL_MODEL` environment variable
(either in the shell or a `.env` file) to select a model externally:

``` bash
INSPECT_EVAL_MODEL=google/gemini-1.5-pro
```

## Generation Config

There are a variety of configuration options that affect the behaviour
of model generation. There are options which affect the generated tokens
(`temperature`, `top_p`, etc.) as well as the connection to model
providers (`timeout`, `max_retries`, etc.)

You can specify generation options either on the command line or in
direct calls to `eval()`. For example:

``` bash
inspect eval arc.py --model openai/gpt-4 --temperature 0.9
inspect eval arc.py --model google/gemini-1.0-pro --max-connections 20
```

Or:

``` python
eval("arc.py", model="openai/gpt-4", temperature=0.9)
eval("arc.py", model="google/gemini-1.0-pro", max_connections=20)
```

Use `inspect eval --help` to learn about all of the available generation
config options.

## Model Args

If there is an additional aspect of a model you want to tweak that isn’t
covered by the `GenerateConfig`, you can use model args to pass
additional arguments to model clients. For example, here we specify the
`transport` option for a Google Gemini model:

``` bash
inspect eval arc.py --model google/gemini-1.0-pro -M transport:grpc
```

See the documentation for the requisite model provider for information
on how model args are passed through to model clients.

## Max Connections

Inspect uses an asynchronous architecture to run task samples in
parallel. If your model provider can handle 100 concurrent connections,
then Inspect can utilise all of those connections to get the highest
possible throughput. The limiting factor on parallelism is therefore not
typically local parallelism (e.g. number of cores) but rather what the
underlying rate limit is for your interface to the provider.

By default, Inspect uses a `max_connections` value of 10. You can
increase this consistent with your account limits. If you are
experiencing rate-limit errors you will need to experiment with the
`max_connections` option to find the optimal value that keeps you under
the rate limit (the section on [Parallelism](parallelism.qmd) includes
additional documentation on how to do this).

## Learning More

- [Providers](providers.qmd) covers usage details and available options
  for the various supported providers.

- [Caching](caching.qmd) explains how to cache model output to reduce
  the number of API calls made.

- [Multimodal](multimodal.qmd) describes the APIs available for creating
  multimodal evaluations (including images, audio, and video).

- [Reasoning](reasoning.qmd) documents the additional options and data
  available for reasoning models.
