# AI Answers for SearXNG

A SearXNG plugin that streams AI responses using search results as grounding context. Supports Google Gemini and OpenAI-compatible providers (OpenRouter, Ollama, etc.).

## Installation

Place `ai_answers.py` into the `searx/plugins` directory of your instance (or mount it in a container) and enable it in `settings.yml`:

```yaml
plugins:
  - name: ai_answers
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

After search completes, the plugin extracts the top 6 results as context. A client-side script calls the stream endpoint with a signed token. The LLM response streams back. Token by token rendering is soon.

## Ollama (Local)

```
LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=ollama
OPENROUTER_MODEL=gemma3:27b
OPENROUTER_BASE_URL=localhost:11434
```
