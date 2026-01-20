# AI Answers for SearXNG

**Does not block result loading time.**

A SearXNG plugin that generates AI answers using search results as RAG context. Supports 8 LLM providers.

Features token-by-token streaming and clickable inline citations.

## Installation

Place `ai_answers.py` into the `searx/plugins` directory of your instance (or mount it in a container) and enable it in `settings.yml`:

```yaml
plugins:
  searx.plugins.ai_answers.SXNGPlugin:  
    active: true
```

## Configuration

Set the following environment variables:

### Required

- `LLM_PROVIDER`: openrouter, openai, ollama, localai, lmstudio, gemini, azure, or huggingface
- `LLM_KEY`: Your API key

### Optional

- `LLM_MODEL`: Model identifier. Defaults vary by provider.
- `LLM_URL`: Custom endpoint URL. Overrides provider preset.
- `LLM_MAX_TOKENS`: Defaults to `500`.
- `LLM_TEMPERATURE`: Defaults to `0.2`.
- `LLM_CONTEXT_COUNT`: Search results to include. Defaults to `5`.
- `LLM_TABS`: Comma-separated tab whitelist. Defaults to general,science,it,news.
- `LLM_STYLE`: UI mode. Set to "simple" for no interactive controls (copy, regenerate, follow up, continue). Defaults to simple.

## How It Works

After search completes, the plugin extracts top search results as context. A client-side script calls the stream endpoint with a signed token. The LLM response streams back token by token.

## Examples

### OpenRouter
```
LLM_PROVIDER=openrouter
LLM_KEY=sk-or-xxx
LLM_MODEL=google/gemma-3-27b-it:free
```

### Ollama (Local)
```
LLM_PROVIDER=ollama
LLM_KEY=ollama
LLM_MODEL=llama3.2
```

### LocalAI
```
LLM_PROVIDER=localai
LLM_KEY=your-key
LLM_MODEL=gpt-4
LLM_URL=http://localai.lan:8080/v1/chat/completions
```

### Gemini
```
LLM_PROVIDER=gemini
LLM_KEY=AIzaSy...
LLM_MODEL=gemma-3-27b-it
```

### Azure
```
LLM_PROVIDER=azure
LLM_KEY=your-api-key
LLM_URL=https://your-resource.openai.azure.com/openai/deployments/your-deployment/chat/completions?api-version=2024-02-01
```

### Hugging Face
```
LLM_PROVIDER=huggingface
LLM_KEY=hf_xxx
LLM_MODEL=meta-llama/Meta-Llama-3-8B-Instruct
```

## Development

```bash
pip install flask flask-babel python-dotenv
python demo.py   # Interactive test server on localhost:5000
python test.py   # One-shot test suite
```
