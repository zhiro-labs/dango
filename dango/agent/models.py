"""
Model construction for every supported provider.

Google (Gemini / Gemma) gets a dedicated subclass with Gemini-specific
parameters; every other provider is resolved through Agno's
"provider:model_id" string format.
"""

import os

from agno.exceptions import ModelProviderError
from agno.models.google import Gemini

from ..utils.config_utils import env_bool
from .settings import ModelSpec

# ── Provider → API key env var ────────────────────────────────────────────────
# Complete list sourced from Agno model source code.
# google is included so GOOGLE_API_KEY is set for model-as-string and other callers.
# Complex cloud providers (aws-bedrock, azure-*, vertexai-*, ibm) need their own
# multi-var auth setup and are intentionally omitted.
PROVIDER_KEY_MAP: dict[str, str] = {
    "google":           "GOOGLE_API_KEY",
    "aimlapi":          "AIMLAPI_API_KEY",
    "anthropic":        "ANTHROPIC_API_KEY",
    "cerebras":         "CEREBRAS_API_KEY",
    "cerebras-openai":  "CEREBRAS_API_KEY",
    "cohere":           "CO_API_KEY",
    "cometapi":         "COMETAPI_KEY",
    "dashscope":        "DASHSCOPE_API_KEY",
    "deepinfra":        "DEEPINFRA_API_KEY",
    "deepseek":         "DEEPSEEK_API_KEY",
    "fireworks":        "FIREWORKS_API_KEY",
    "groq":             "GROQ_API_KEY",
    "huggingface":      "HF_TOKEN",
    "internlm":         "INTERNLM_API_KEY",
    "langdb":           "LANGDB_API_KEY",
    "litellm":          "LITELLM_API_KEY",
    "litellm-openai":   "LITELLM_API_KEY",
    "meta":             "LLAMA_API_KEY",
    "llama-openai":     "LLAMA_API_KEY",
    "mistral":          "MISTRAL_API_KEY",
    "moonshot":         "MOONSHOT_API_KEY",
    "n1n":              "N1N_API_KEY",
    "nebius":           "NEBIUS_API_KEY",
    "neosantara":       "NEOSANTARA_API_KEY",
    "nvidia":           "NVIDIA_API_KEY",
    "ollama":           "OLLAMA_API_KEY",
    "openai":           "OPENAI_API_KEY",
    "openai-chat":      "OPENAI_API_KEY",
    "openai-responses": "OPENAI_API_KEY",
    "openrouter":       "OPENROUTER_API_KEY",
    "perplexity":       "PERPLEXITY_API_KEY",
    "portkey":          "PORTKEY_API_KEY",
    "requesty":         "REQUESTY_API_KEY",
    "sambanova":        "SAMBANOVA_API_KEY",
    "siliconflow":      "SILICONFLOW_API_KEY",
    "together":         "TOGETHER_API_KEY",
    "vllm":             "VLLM_API_KEY",
    # llama-cpp and lmstudio use OpenAILike with api_key="not-provided" default,
    # no standard env var — FAST/DEEP_API_KEY is passed directly if set.
    "xai":              "XAI_API_KEY",
}


def inject_provider_key(spec: ModelSpec) -> None:
    """Map FAST/DEEP_API_KEY to the env var the provider's SDK reads.

    Uses setdefault so a pre-existing env var (e.g. set by the user directly)
    is never overwritten.
    """
    if not spec.api_key or not spec.name:
        return
    env_var = PROVIDER_KEY_MAP.get(spec.provider)
    if env_var:
        os.environ.setdefault(env_var, spec.api_key)


# ── Gemini subclass ───────────────────────────────────────────────────────────
class DangoGemini(Gemini):
    """Gemini with corrected error messages.

    Agno bug: ainvoke overwrites the useful str(e) error message with
    e.response.text (an aiohttp bound method, not the actual response body).
    We recover the original error string from __cause__ before it propagates.
    """

    async def ainvoke(self, messages, assistant_message, **kwargs):
        try:
            return await super().ainvoke(messages, assistant_message, **kwargs)
        except ModelProviderError as e:
            cause = e.__cause__
            if cause is not None and str(e).startswith("<"):
                raise ModelProviderError(
                    message=str(cause),
                    status_code=e.status_code,
                    model_name=e.model_name,
                    model_id=e.model_id,
                ) from cause
            raise


def _make_gemini(spec: ModelSpec) -> DangoGemini:
    """Create a DangoGemini reading params from {prefix}_* with GEMINI_* as fallback."""
    prefix = spec.env_prefix

    def f(key: str) -> float | None:
        v = os.getenv(f"{prefix}_{key}") or os.getenv(f"GEMINI_{key}")
        return float(v) if v else None

    def i(key: str) -> int | None:
        v = os.getenv(f"{prefix}_{key}") or os.getenv(f"GEMINI_{key}")
        return int(v) if v else None

    def b(key: str, default: str = "false") -> bool:
        v = os.getenv(f"{prefix}_{key}") or os.getenv(f"GEMINI_{key}", default)
        return env_bool(v)

    retries = i("RETRIES")
    if retries is None:
        retries = 2  # default: retry 503/5xx twice before giving up

    model_id = spec.model_id
    return DangoGemini(
        id=model_id,
        api_key=spec.api_key,
        search=b("SEARCH", "true"),
        grounding_dynamic_threshold=f("GROUNDING_THRESHOLD"),
        url_context=False if model_id.startswith("gemma-") else b("URL_CONTEXT", "false"),
        thinking_budget=i("THINKING_BUDGET"),
        thinking_level=os.getenv(f"{prefix}_THINKING_LEVEL") or os.getenv("GEMINI_THINKING_LEVEL") or None,
        retries=retries,
        delay_between_retries=i("RETRY_DELAY") or 1,
        exponential_backoff=True,
    )


def make_model(spec: ModelSpec) -> DangoGemini | object | str:
    """Return a model instance, or a string for Agno's model-as-string resolution.

    - google: → DangoGemini (with Gemini-specific params)
    - others without base_url → model string (Agno resolves at runtime)
    - others with base_url → Agno instantiates the class, then base_url/host is patched
    """
    if spec.provider == "google":
        return _make_gemini(spec)

    if spec.base_url:
        from agno.models.utils import get_model as _agno_get_model
        instance = _agno_get_model(spec.name)
        if hasattr(instance, "host"):           # Ollama uses 'host'
            instance.host = spec.base_url
        elif hasattr(instance, "base_url"):     # most OpenAI-like providers
            instance.base_url = spec.base_url
        else:
            # Provider has no native base_url/host param — force-set as attribute.
            # The setting is NOT ignored; whether the provider honours it depends on
            # its internal client construction. A warning is printed to aid debugging.
            print(
                f"⚠️  [{spec.env_prefix}_BASE_URL] provider '{spec.provider}' has no native base_url/host param — "
                f"force-setting attribute '{spec.base_url}'. Behaviour depends on provider implementation."
            )
            instance.base_url = spec.base_url
        if spec.api_key and hasattr(instance, "api_key"):
            instance.api_key = spec.api_key
        return instance

    return spec.name
