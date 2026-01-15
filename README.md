# AI Answers for SearXNG

**Does not block result loading time.**

A SearXNG plugin that generates an AI answer using search results as RAG grounding context. Supports Google Gemini and OpenAI-compatible providers (OpenRouter, Ollama, etc.).
Features token by token UI updates as response is recieved.
## Installation

Place `ai_answers.py` into the `searx/plugins` directory of your instance (or mount it in a container) and enable it in `settings.yml`:

```yaml
plugins:
  searx.plugins.ai_answers.SXNGPlugin:  
    active: true
```

## Configuration

Set the following environment variables:

### General

- `LLM_PROVIDER`: `openrouter` (default) or `gemini`.
- `GEMINI_MAX_TOKENS`: Defaults to `500`.
- `GEMINI_TEMPERATURE`: Defaults to `0.2`.

### OpenRouter / OpenAI / Ollama

- `OPENROUTER_API_KEY`: Your API key.
- `OPENROUTER_MODEL`: Defaults to `google/gemma-3-27b-it:free`.
- `OPENROUTER_BASE_URL`: Defaults to `openrouter.ai`. (Change to `localhost:11434` for Ollama).

### Google Gemini

- `GEMINI_API_KEY`: Your Google AI API key.
- `GEMINI_MODEL`: Defaults to `gemma-3-27b-it`.

## How It Works

After search completes, the plugin extracts 6 top results as context. A client-side script calls the stream endpoint with a signed token. The LLM response streams back to update UI dynamically.

## Ollama (Local)

```
LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=ollama
OPENROUTER_MODEL=gemma3:27b
OPENROUTER_BASE_URL=localhost:11434
```
