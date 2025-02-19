
|  |  |
|------------------------------------|------------------------------------|
| Lab APIs | [OpenAI](providers.qmd#openai), [Anthropic](providers.qmd#anthropic), [Google](providers.qmd#google), [Grok](providers.qmd#grok), [Mistral](providers.qmd#mistral) |
| Cloud APIs | [AWS Bedrock](providers.qmd#aws-bedrock), [Azure AI](providers.qmd#azure-ai), [Vertex AI](providers.qmd#vertex-ai) |
| Open (Hosted) | [Groq](providers.qmd#groq), [Together AI](providers.qmd#together-ai), [Cloudflare](providers.qmd#cloudflare), [Goodfire](providers.qmd#goodfire) |
| Open (Local) | [Hugging Face](providers.qmd#hugging-face), [vLLM](providers.qmd#vllm), [Ollama](providers.qmd#ollama), [Lllama-cpp-python](providers.qmd#llama-cpp-python) |

<br/>

If the provider you are using is not listed above, you may still be able to use it if:

1. It is available via OpenRouter (see the docs on using [OpenRouter](providers.qmd#openrouter) with Inspect).

2. It provides an OpenAI compatible API endpoint. In this scenario, use the Inspect [OpenAI](providers.qmd#openai) interface and set the `OPENAI_BASE_URL` environment variable to the apprpriate value for your provider.

You can also create [Model API Extensions](extensions.qmd#model-apis) to add model providers using their native interface.


