# AI Answers Plugin for SearXNG  
**Single file install**  
**Does not block result loading time**  

A SearXNG plugin that generates AI answers using search results as RAG context. Supports 8+ LLM providers.

Features:
- token-by-token UI streaming
- clickable inline citations
- interactive mode to continue summary, ask follow ups, copy, or regenerate
- simple response mode with no extras
- internally called low-latency RAG for follow ups (bypasses http loopback)
- native network integration via `searx.network` (respects proxy/SSL settings)
- stateless conversation persistence/sharability via URL
- provider detection based on URL


## Installation

Place `ai_answers.py` into the `searx/plugins` directory of your instance (or mount it in a container) and enable it in `settings.yml`:

```yaml
plugins:
  searx.plugins.ai_answers.SXNGPlugin:  
    active: true
```

## Configuration

Configure via the environment variables:

### Required

- `LLM_PROVIDER`: openrouter, openai, ollama, localai, lmstudio, gemini, azure, or huggingface
- `LLM_KEY`: Provider API key (optional for local providers: ollama, localai, lmstudio)

### Optional

- `LLM_MODEL`: Model identifier. Defaults vary. Recommended: 10-30B dense or 5-15B MoE activated.
- `LLM_URL`: Overrides endpoint URL for any provider preset.
- `LLM_MAX_TOKENS`: Default `500`.
- `LLM_TEMPERATURE`: Default `0.2`.
- `LLM_CONTEXT_DEEP_COUNT`: results as context with full snippets. Default `5`.
- `LLM_CONTEXT_SHALLOW_COUNT`: Results with headlines only (additional breadth). Default `15`.
- `LLM_TABS`: Tab whitelist, comma delimiter. Default `general,science,it,news`.
- `LLM_INTERACTIVE`: UI mode. Default is `true` (interactive: copy, regenerate, follow up). Set to `false` for simple response only mode.

## How It Works
1 user initial search 
2 results return server side 
3 `post_search` plugin hook entry
4 token optimized context extracted 
5 inject the ui/logic "shell" into standard results answer object 
6 client side script calls custom endpoint with signed token
7 LLM response streams back token by token

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
pip install flask flask-babel
python tests/demo.py   # Interactive demo at localhost:5000
python tests/test.py   # One-shot test suite
```
