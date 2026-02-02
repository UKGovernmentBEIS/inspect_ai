
|  |  |
|------------------------------------|------------------------------------|
| Lab APIs | [OpenAI](providers.qmd#openai), [Anthropic](providers.qmd#anthropic), [Google](providers.qmd#google), [Grok](providers.qmd#grok), [Mistral](providers.qmd#mistral), [DeepSeek](providers.qmd#deepseek), [Perplexity](providers.qmd#perplexity) |
| Cloud APIs | [AWS Bedrock](providers.qmd#aws-bedrock) and [Azure AI](providers.qmd#azure-ai) |
| Open (Hosted) | [Groq](providers.qmd#groq), [Together AI](providers.qmd#together-ai), [Fireworks AI](providers.qmd#fireworks-ai), [Cloudflare](providers.qmd#cloudflare), [HF Inference Providers](providers.qmd#hf-inference-providers), [SambaNova](providers.qmd#sambanova) |
| Open (Local) | [Hugging Face](providers.qmd#hugging-face), [vLLM](providers.qmd#vllm), [Ollama](providers.qmd#ollama), [Lllama-cpp-python](providers.qmd#llama-cpp-python), [SGLang](providers.qmd#sglang), [TransformerLens](providers.qmd#transformer-lens), [nnterp](providers.qmd#nnterp) |

<br/>

If the provider you are using is not listed above, you may still be able to use it if:

1. It provides an OpenAI compatible API endpoint. In this scenario, use the Inspect [OpenAI Compatible API](providers.qmd#openai-api) interface.

2. It is available via OpenRouter (see the docs on using [OpenRouter](providers.qmd#openrouter) with Inspect).


You can also create [Model API Extensions](extensions.qmd#model-apis) to add model providers using their native interface.
