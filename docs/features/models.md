---
summary: "`provider:model_id` format, supported providers, dual-model AUTO_ROUTE, error fallback, local models, context token budget."
description: "Connect Dango to any AI provider — Gemini, GPT-4o, Claude, Llama, Groq, Ollama, and more. Supports dual-model routing, automatic provider detection, and local model servers."
tags:
  - Models
  - Gemini
  - GPT-4o
  - Claude
  - Ollama
---

# Model Providers & Routing

## Provider Format

Models are specified as `provider:model_id`. The bot automatically maps `FAST_API_KEY` / `DEEP_API_KEY` to the correct provider SDK env var at startup — you do not need to set `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, etc. yourself.

| Provider prefix | Example | API key source |
|---|---|---|
| `google:` | `google:gemini-2.5-flash` | [Google AI Studio](https://aistudio.google.com/apikey) |
| `openai:` | `openai:gpt-4o` | [OpenAI Platform](https://platform.openai.com/api-keys) |
| `anthropic:` | `anthropic:claude-sonnet-4-20250514` | [Anthropic Console](https://console.anthropic.com/) |
| `groq:` | `groq:llama-3.3-70b-versatile` | [Groq Console](https://console.groq.com/) |
| `openrouter:` | `openrouter:meta-llama/llama-3.3-70b-instruct` | [OpenRouter](https://openrouter.ai/keys) |
| `mistral:` | `mistral:mistral-large-latest` | [Mistral Console](https://console.mistral.ai/) |
| `xai:` | `xai:grok-3` | [xAI Console](https://console.x.ai/) |
| `deepseek:` | `deepseek:deepseek-chat` | [DeepSeek Platform](https://platform.deepseek.com/) |
| `ollama:` | `ollama:llama3.2` | Local (no key needed) |
| `lmstudio:` | `lmstudio:my-model` | Local (no key needed) |
| `vllm:` | `vllm:my-model` | Local (no key needed) |
| `openai-chat:` | `openai-chat:my-model` | Any OpenAI-compatible API |

For the complete provider list, see the [Agno model index](https://docs.agno.com/models/providers/model-index).

## Google Gemini / Gemma extras

`google:` models get additional features not available for other providers:

- **Search grounding** — automatically searches Google when the model needs current information (`GEMINI_SEARCH=true` by default)
- **URL context** — the model fetches and reads URLs mentioned in the conversation (`GEMINI_URL_CONTEXT=false` by default; not supported by `gemma-*` models)
- **Thinking budget** — control reasoning token usage (`GEMINI_THINKING_BUDGET`, Gemini 2.5+ and Gemma 4)

## Dual-model routing

Set `DEEP_MODEL` to enable a second model for complex messages:

```env
FAST_MODEL=google:gemma-4-26b-a4b-it   # everyday questions
FAST_API_KEY=your_key

DEEP_MODEL=google:gemini-2.5-pro        # complex analysis
DEEP_API_KEY=your_key                   # can be same key if same provider
```

### AUTO_ROUTE

With `AUTO_ROUTE=on`, the bot scores each message for complexity before routing:

- **Simple** → fast model (acknowledgments, translations, short questions)
- **Complex** → deep model (code, math, multi-part questions, reasoning)

The classifier (`complexity_router.py`) is multilingual — it handles EN, ZH, JA, KO, ES, FR, DE, RU, PT, VI, TH, and AR.

### /deep command

Force the deep model for a single message regardless of AUTO_ROUTE:

```
/deep <your message>
```

Requires `DEEP_MODEL` to be set.

### Auto-route on URL (Gemini-specific)

If the fast model is a Gemini without `url_context` enabled, but the deep model has it enabled, any message containing a URL is automatically routed to the deep model — so that the model with URL-reading capability handles it.

## Error fallback

With `FALLBACK_ON_ERROR=on`, if one model returns an error, the bot retries with the other:

- `fast → deep`: fast model fails → retry with deep model
- `deep → fast`: deep model fails → retry with fast model

A `[dango-sysinfo]` note appears in the channel when fallback fires — the message format is:

```
> [dango-sysinfo] ⚡ google:gemini-2.0-flash failed — response served by google:gemini-2.5-pro.
```

Works best when fast and deep use **different providers** — same-provider fallback cannot protect against provider-wide outages. If both models share a provider, this warning is printed at startup:

```
⚠️  [config] FAST_MODEL and DEEP_MODEL share provider 'google' — FALLBACK_ON_ERROR won't protect against provider-wide outages.
```

Non-Gemini providers retry 2× before triggering fallback, except for errors a retry cannot fix — a rejected API key, an unknown model name, a conversation longer than the context window, or another rejected request — which go straight to fallback (or to the [error reply](../troubleshooting.md#the-bot-replies-with-a-model-error)). Gemini handles its own retries internally.

## Local models

Point `FAST_BASE_URL` at a local inference server:

```env
FAST_MODEL=ollama:llama3.2
FAST_API_KEY=local           # most local servers accept any non-empty string
FAST_BASE_URL=http://localhost:11434
```

If the bot runs in Docker and the model server runs on the host:

```env
FAST_BASE_URL=http://host.docker.internal:11434
```

## Context token budget

`CONTEXT_TOKEN_BUDGET` caps the total input tokens per request. When history exceeds the limit, the oldest messages are dropped first to stay within budget.

```env
CONTEXT_TOKEN_BUDGET=8192   # 0 = no limit (default)
```

Use `FAST_CONTEXT_TOKEN_BUDGET` / `DEEP_CONTEXT_TOKEN_BUDGET` to set different limits per model.
